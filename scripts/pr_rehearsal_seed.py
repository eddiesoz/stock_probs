"""Create bounded synthetic auth and write fixtures inside the disposable candidate only."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx

from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.backup import BackupManager, _check_deadline, _run_with_deadline
from stock_probs.config import Settings
from stock_probs.repository import Repository
from stock_probs.totp import encrypt_secret, generate_secret

OWNER_GITHUB_ID = 9_820_000_001
MEMBER_GITHUB_ID = 9_820_000_002
RESTORE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.spbackup$")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_pristine(repository: Repository) -> None:
    with repository.connect() as connection:
        actual = {
            "users": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "sessions": connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            "totp_factors": connection.execute("SELECT COUNT(*) FROM totp_factors").fetchone()[0],
            "portfolio": connection.execute(
                "SELECT COUNT(*) FROM user_instrument_list_items"
            ).fetchone()[0],
            "conversations": connection.execute(
                "SELECT COUNT(*) FROM assistant_conversations"
            ).fetchone()[0],
        }
        if actual != {
            "users": 1,
            "sessions": 0,
            "totp_factors": 0,
            "portfolio": 0,
            "conversations": 0,
        }:
            raise RuntimeError("synthetic volume is not pristine")
        legacy = connection.execute(
            "SELECT login, legacy_owner_claimed_at FROM users WHERE id=1"
        ).fetchone()
        if legacy is None or legacy[0] != "legacy-owner" or legacy[1] is not None:
            raise RuntimeError("synthetic volume legacy owner is not pristine")
    if any(repository.representative_counts().values()):
        raise RuntimeError("synthetic research history is not empty")


def _seed(repository: Repository, settings: Settings) -> dict[str, object]:
    _require_pristine(repository)
    now = datetime.now(UTC).replace(microsecond=0)
    expires = now + timedelta(hours=12)
    result_users: list[dict[str, str]] = []
    user_ids: list[int] = []
    for index, (github_id, role, count) in enumerate(
        ((OWNER_GITHUB_ID, "admin", 1), (MEMBER_GITHUB_ID, "member", 2))
    ):
        suffix = secrets.token_hex(4)
        user = repository.auth_create_user(
            {
                "github_id": github_id,
                "github_login": f"r120-rehearsal-{suffix}",
                "display_name": f"Synthetic rehearsal owner {index + 1}",
                "role": role,
                "status": "active",
                "created_at": now,
            }
        )
        user_id = int(user["id"])
        user_ids.append(user_id)
        totp_secret = generate_secret() if index == 0 else None
        encrypted_factor = (
            encrypt_secret(totp_secret, settings.auth_session_secret, user_id=user_id)
            if totp_secret is not None
            else "synthetic-member-factor-material"
        )
        with repository.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO totp_factors "
                "(user_id, secret_ciphertext, created_at, confirmed_at, "
                "last_accepted_step, updated_at) VALUES (?, ?, ?, ?, -1, ?)",
                (user_id, encrypted_factor, now.isoformat(), now.isoformat(), now.isoformat()),
            )
            factor_id = int(cursor.lastrowid)
            connection.commit()
        session_cookie = secrets.token_urlsafe(32)
        csrf_cookie = secrets.token_urlsafe(32)
        with repository.connect() as connection:
            connection.execute(
                """INSERT INTO sessions
                (user_id, session_id, token_hash, csrf_token_hash, issued_at, last_seen_at,
                 idle_expires_at, absolute_expires_at, auth_method, mfa_method,
                 mfa_verified_at, mfa_factor_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'github', 'totp', ?, ?)""",
                (
                    user_id,
                    secrets.token_hex(16),
                    hashlib.sha256(session_cookie.encode()).hexdigest(),
                    hashlib.sha256(csrf_cookie.encode()).hexdigest(),
                    now.isoformat(),
                    now.isoformat(),
                    expires.isoformat(),
                    expires.isoformat(),
                    now.isoformat(),
                    factor_id,
                ),
            )
            connection.commit()
        if repository.auth_get_session(hashlib.sha256(session_cookie.encode()).hexdigest()) is None:
            raise RuntimeError("synthetic auth session did not verify")
        for offset in range(count):
            symbol = f"R120{'A' if index == 0 else 'B'}{offset + 1}"
            repository.add_instrument_list_item(
                "portfolio",
                owner_user_id=user_id,
                provider="Synthetic Test",
                canonical_symbol=symbol,
                asset_type="stock",
                exchange="TEST",
                display_name=f"Synthetic rehearsal holding {symbol}",
                added_at=now,
                quantity=1.0,
            )
        expected = {"saved_searches": 0, "watchlist_items": 0, "portfolio_items": count}
        fixture = {
            "session_cookie": session_cookie,
            "csrf_cookie": csrf_cookie,
            "expected_tool_result_sha256": _digest(expected),
        }
        if totp_secret is not None:
            fixture["totp_secret"] = totp_secret
        result_users.append(fixture)
    return {"users": result_users, "synthetic_user_ids": user_ids}


def _write_marker(repository: Repository, user_id: int, revision: str) -> str:
    now = datetime.now(UTC)
    request_id = f"pr1-{revision}-post-migration"
    repository.record_failure(
        owner_user_id=user_id,
        request_id=request_id,
        submitted_symbol="PRREH",
        normalized_symbol="PRREH",
        asset_type="stock",
        error_code="synthetic_rehearsal_marker",
        error_message="synthetic schema-13 post-migration write",
        submitted_at=now,
        completed_at=now,
    )
    return request_id


def _snapshot(repository: Repository, request_id: str) -> dict[str, object]:
    with repository.connect() as connection:
        rows: dict[str, list[tuple[object, ...]]] = {}
        for table, query in {
            "users": "SELECT id, github_user_id, role, status FROM users ORDER BY id",
            "sessions": "SELECT user_id, auth_method, mfa_method FROM sessions ORDER BY user_id",
            "factors": "SELECT user_id, confirmed_at FROM totp_factors ORDER BY user_id",
            "portfolio": (
                "SELECT owner_user_id, canonical_symbol, quantity "
                "FROM user_instrument_list_items ORDER BY owner_user_id, canonical_symbol"
            ),
            "marker": (
                "SELECT event.id, owner.owner_user_id, event.request_id, event.error_code "
                "FROM search_events AS event JOIN search_event_owners AS owner "
                "ON owner.event_id = event.id WHERE event.request_id = ? ORDER BY event.id"
            ),
        }.items():
            if table == "marker":
                selected = connection.execute(query, (request_id,))
            else:
                selected = connection.execute(query)
            rows[table] = [tuple(row) for row in selected.fetchall()]
    if len(rows["marker"]) != 1:
        raise RuntimeError("post-migration write marker is missing")
    from stock_probs.api import _restore_security_digest

    return {
        "sha256": _digest(rows),
        "security_state_sha256": _restore_security_digest(repository.database_path),
        "marker_present": True,
        "marker_rows": len(rows["marker"]),
    }


@contextmanager
def _stale_synthetic_step_up(repository: Repository, users: list[dict[str, str]]) -> Iterator[None]:
    """Temporarily age verified synthetic sessions for the restore-denial probe."""

    expected_identities = (
        (OWNER_GITHUB_ID, "admin"),
        (MEMBER_GITHUB_ID, "member"),
    )
    now = datetime.now(UTC)
    stale_at = (now - timedelta(minutes=10)).isoformat()
    sessions: list[tuple[int, int, str, str]] = []
    token_hashes: set[str] = set()
    for user, (github_id, role) in zip(users, expected_identities, strict=True):
        session_cookie = user["session_cookie"]
        csrf_cookie = user["csrf_cookie"]
        token_hash = hashlib.sha256(session_cookie.encode()).hexdigest()
        csrf_hash = hashlib.sha256(csrf_cookie.encode()).hexdigest()
        if token_hash in token_hashes:
            raise RuntimeError("restore-guard synthetic sessions are not distinct")
        token_hashes.add(token_hash)
        with repository.connect() as connection:
            rows = connection.execute(
                """SELECT session.id AS session_id, session.user_id,
                session.csrf_token_hash, session.mfa_method, session.mfa_verified_at,
                session.mfa_factor_id, session.revoked_at, user.github_user_id,
                user.login, user.role, user.status
                FROM sessions AS session
                JOIN users AS user ON user.id = session.user_id
                WHERE session.token_hash = ?""",
                (token_hash,),
            ).fetchall()
        if len(rows) != 1:
            raise RuntimeError("restore-guard synthetic session is invalid")
        row = rows[0]
        verified_text = row["mfa_verified_at"]
        try:
            verified_at = datetime.fromisoformat(verified_text)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("restore-guard synthetic step-up is invalid") from exc
        if verified_at.tzinfo is None:
            raise RuntimeError("restore-guard synthetic step-up is invalid")
        if (
            type(row["github_user_id"]) is not int
            or row["github_user_id"] != github_id
            or not isinstance(row["login"], str)
            or re.fullmatch(r"r120-rehearsal-[a-f0-9]{8}", row["login"]) is None
            or row["role"] != role
            or row["status"] != "active"
            or row["csrf_token_hash"] != csrf_hash
            or row["mfa_method"] != "totp"
            or type(row["mfa_factor_id"]) is not int
            or row["revoked_at"] is not None
            or repository.auth_get_session(token_hash) is None
        ):
            raise RuntimeError("restore-guard synthetic identity is invalid")
        sessions.append((int(row["session_id"]), int(row["user_id"]), token_hash, verified_text))

    with repository.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for session_id, user_id, token_hash, verified_text in sessions:
                cursor = connection.execute(
                    """UPDATE sessions SET mfa_verified_at = ?
                    WHERE id = ? AND user_id = ? AND token_hash = ?
                      AND mfa_verified_at = ? AND mfa_method = 'totp'
                      AND revoked_at IS NULL""",
                    (stale_at, session_id, user_id, token_hash, verified_text),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("restore-guard synthetic session changed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    try:
        yield
    finally:
        with repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for session_id, user_id, token_hash, verified_text in sessions:
                    cursor = connection.execute(
                        """UPDATE sessions SET mfa_verified_at = ?
                        WHERE id = ? AND user_id = ? AND token_hash = ?
                          AND mfa_verified_at = ? AND mfa_method = 'totp'
                          AND revoked_at IS NULL""",
                        (verified_text, session_id, user_id, token_hash, stale_at),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            "restore-guard could not restore synthetic step-up state"
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def _restore_guard(
    request: object,
    repository: Repository,
    *,
    post_request: Callable[..., httpx.Response] | None = None,
) -> dict[str, object]:
    if (
        not isinstance(request, dict)
        or set(request) != {"users", "backup_name"}
        or not isinstance(request.get("users"), list)
        or len(request["users"]) != 2
        or not isinstance(request.get("backup_name"), str)
        or RESTORE_NAME.fullmatch(request["backup_name"]) is None
    ):
        raise RuntimeError("restore-guard fixture is invalid")
    user_fields = (
        {
            "session_cookie",
            "csrf_cookie",
            "expected_tool_result_sha256",
            "totp_secret",
        },
        {"session_cookie", "csrf_cookie", "expected_tool_result_sha256"},
    )
    fixture_users: list[dict[str, str]] = []
    for index, user in enumerate(request["users"]):
        if not isinstance(user, dict) or set(user) != user_fields[index]:
            raise RuntimeError("restore-guard identity is invalid")
        if (
            not isinstance(user["session_cookie"], str)
            or re.fullmatch(r"[A-Za-z0-9_-]{16,256}", user["session_cookie"]) is None
            or not isinstance(user["csrf_cookie"], str)
            or re.fullmatch(r"[A-Za-z0-9_-]{16,256}", user["csrf_cookie"]) is None
            or not isinstance(user["expected_tool_result_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", user["expected_tool_result_sha256"]) is None
            or (
                index == 0
                and (
                    not isinstance(user["totp_secret"], str)
                    or not 16 <= len(user["totp_secret"]) <= 128
                )
            )
        ):
            raise RuntimeError("restore-guard identity is invalid")
        fixture_users.append(
            {
                "session_cookie": user["session_cookie"],
                "csrf_cookie": user["csrf_cookie"],
            }
        )

    statuses: list[int] = []
    with _stale_synthetic_step_up(repository, fixture_users):
        for user in fixture_users:
            headers = {
                "host": "ledger-r120.test",
                "origin": "https://ledger-r120.test",
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={user['session_cookie']}; "
                    f"{CSRF_COOKIE_NAME}={user['csrf_cookie']}"
                ),
                "x-csrf-token": user["csrf_cookie"],
                "accept": "application/json",
            }
            if post_request is None:
                with httpx.Client(
                    base_url="http://127.0.0.1:8000", timeout=3.0, trust_env=False
                ) as client:
                    response = client.post(
                        "/api/v1/operations/restores",
                        headers=headers,
                        json={"name": request["backup_name"], "promote": True},
                    )
            else:
                response = post_request(
                    "/api/v1/operations/restores",
                    headers=headers,
                    json={"name": request["backup_name"], "promote": True},
                )
            statuses.append(response.status_code)
    if statuses != [403, 403]:
        raise RuntimeError("restore-security boundary did not refuse both synthetic owners")
    return {"restore_guard_denied_without_fresh_step_up": True}


def _verify_historical_backup(
    repository: Repository, settings: Settings, backup_name: str
) -> dict[str, object]:
    if RESTORE_NAME.fullmatch(backup_name) is None:
        raise RuntimeError("historical backup identity is invalid")
    manager = BackupManager(repository, settings.backup_dir)

    def inspect():
        with repository.exclusive():
            result = manager._verify_unlocked(backup_name, require_active_schema=False)
            try:
                _check_deadline()
            except Exception:
                result[2].cleanup()
                raise
            return result

    manifest, _database, staging = _run_with_deadline(inspect)
    try:
        if manifest.get("schema_version") != 12:
            raise RuntimeError("historical backup schema mismatch")
        return {
            "verified": True,
            "schema_version": 12,
            "integrity_verified": True,
        }
    finally:
        staging.cleanup()


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "seed",
        "marker",
        "snapshot",
        "restore-guard",
        "verify-backup",
    }:
        return 2
    settings = Settings.from_env()
    repository = Repository(settings.database_path)
    operation = sys.argv[1]
    if operation == "seed":
        value: object = _seed(repository, settings)
    elif operation == "marker":
        request = json.load(sys.stdin)
        if (
            not isinstance(request, dict)
            or set(request) != {"user_id", "revision"}
            or type(request["user_id"]) is not int
            or request["user_id"] < 1
            or not isinstance(request["revision"], str)
            or len(request["revision"]) != 40
        ):
            return 2
        value = {"request_id": _write_marker(repository, request["user_id"], request["revision"])}
    elif operation == "snapshot":
        request = json.load(sys.stdin)
        if (
            not isinstance(request, dict)
            or set(request) != {"request_id"}
            or not isinstance(request["request_id"], str)
            or len(request["request_id"]) > 96
        ):
            return 2
        value = _snapshot(repository, request["request_id"])
    elif operation == "verify-backup":
        request = json.load(sys.stdin)
        if (
            not isinstance(request, dict)
            or set(request) != {"backup_name"}
            or not isinstance(request["backup_name"], str)
        ):
            return 2
        value = _verify_historical_backup(repository, settings, request["backup_name"])
    else:
        value = _restore_guard(json.load(sys.stdin), repository)
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
