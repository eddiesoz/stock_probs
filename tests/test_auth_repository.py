"""Persistence tests for account state and explicit owner isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from stock_probs import repository as repository_module
from stock_probs.domain import calculate_forecasts
from stock_probs.provider import FixtureProvider
from stock_probs.repository import SCHEMA_VERSION, Repository, RepositoryError

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


def _repository(tmp_path) -> Repository:
    """Create a migrated repository for one isolated test."""

    repository = Repository(tmp_path / "stock_probs.sqlite3")
    repository.migrate()
    return repository


def _digest(value: str) -> str:
    """Return the digest shape expected by the opaque-token repository contract."""

    return sha256(value.encode()).hexdigest()


def test_oauth_state_storage_prunes_and_caps_anonymous_starts(tmp_path, monkeypatch):
    """Expired/used states do not fill the durable sign-in transaction budget."""

    repository = _repository(tmp_path)
    monkeypatch.setattr(repository_module, "MAX_PENDING_OAUTH_STATES", 3)

    def store(index: int, at: datetime) -> None:
        repository.auth_store_oauth_state(
            {
                "state_hash": _digest(f"bounded-state-{index}"),
                "code_verifier": "v" * 43,
                "redirect_uri": "https://ledger.example.test/auth/callback",
                "created_at": at.isoformat(),
                "expires_at": (at + timedelta(minutes=5)).isoformat(),
            }
        )

    for index in range(3):
        store(index, NOW)
    with pytest.raises(RepositoryError, match="capacity"):
        store(3, NOW)
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 3

    repository.auth_consume_oauth_state(_digest("bounded-state-0"), NOW.isoformat())
    store(3, NOW + timedelta(seconds=1))
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 3

    store(4, NOW + timedelta(minutes=6))
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 1


def test_migration_creates_auth_tables_and_designated_legacy_owner(tmp_path):
    """Clean creation records schema 7 and a non-credential legacy import target."""

    repository = _repository(tmp_path)

    with repository.connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == (
            SCHEMA_VERSION
        )
        assert tuple(
            connection.execute(
                "SELECT login, role, status, password_hash FROM users WHERE id = 1"
            ).fetchone()
        ) == ("legacy-owner", "admin", "active", None)
        for table in (
            "invitations",
            "sessions",
            "oauth_states",
            "passkeys",
            "forecast_run_owners",
            "forecast_result_owners",
            "search_event_owners",
            "outcome_owners",
            "user_instrument_list_items",
            "history_exports",
        ):
            assert (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
                ).fetchone()
                is not None
            )

    assert repository.legacy_owner_id() == 1


def test_auth_rows_are_single_use_bound_and_revocable(tmp_path):
    """Invitation, session, and passkey methods enforce their one-way security transitions."""

    repository = _repository(tmp_path)
    user = repository.create_user(
        github_user_id=42,
        login="alice",
        display_name="Alice",
        password_hash=None,
        created_at=NOW,
    )
    invitation_hash = _digest("invite")
    repository.create_invitation(
        github_user_id=43,
        github_login="member",
        token_hash=invitation_hash,
        invited_by_user_id=user["id"],
        expires_at=NOW + timedelta(days=1),
        created_at=NOW,
    )
    assert (
        repository.consume_invitation(token_hash=invitation_hash, now=NOW)["github_user_id"] == 43
    )
    assert repository.consume_invitation(token_hash=invitation_hash, now=NOW) is None

    session_hash = _digest("session")
    csrf_hash = _digest("csrf")
    repository.create_session(
        user_id=user["id"],
        token_hash=session_hash,
        csrf_token_hash=csrf_hash,
        issued_at=NOW,
        last_seen_at=NOW,
        idle_expires_at=NOW + timedelta(hours=1),
        absolute_expires_at=NOW + timedelta(days=1),
    )
    assert repository.get_session(session_hash, now=NOW)["login"] == "alice"
    assert repository.revoke_session(
        session_hash, revoked_at=NOW + timedelta(minutes=1), reason="logout"
    )
    assert repository.get_session(session_hash, now=NOW + timedelta(minutes=2)) is None

    credential_id = "c" * 16
    repository.register_passkey(
        user_id=user["id"],
        credential_id=credential_id,
        public_key="k" * 16,
        sign_count=0,
        transports=None,
        created_at=NOW,
    )
    assert repository.get_passkey(credential_id, user_id=user["id"])["user_id"] == user["id"]
    assert repository.get_passkey(credential_id, user_id=1) is None
    assert repository.update_passkey_sign_count(
        credential_id, sign_count=1, used_at=NOW + timedelta(minutes=2)
    )
    assert not repository.update_passkey_sign_count(
        credential_id, sign_count=0, used_at=NOW + timedelta(minutes=3)
    )

    state_hash = _digest("oauth-state")
    repository.auth_store_oauth_state(
        {
            "state_hash": state_hash,
            "code_verifier": "v" * 43,
            "redirect_uri": "https://ledger.example.test/auth/callback",
            "created_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        }
    )
    state = repository.auth_consume_oauth_state(
        state_hash, (NOW + timedelta(seconds=1)).isoformat()
    )
    assert state is not None and state["code_verifier"] == "v" * 43
    assert (
        repository.auth_consume_oauth_state(state_hash, (NOW + timedelta(seconds=2)).isoformat())
        is None
    )

    session_hash = _digest("adapter-session")
    csrf_hash = _digest("adapter-csrf")
    created = repository.auth_create_session(
        {
            "session_id": "s" * 16,
            "user_id": user["id"],
            "token_hash": session_hash,
            "csrf_token_hash": csrf_hash,
            "auth_method": "local",
            "created_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "idle_expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
        }
    )
    assert created["session_id"] == "s" * 16
    assert repository.auth_get_session(session_hash)["expires_at"].startswith("2025-01-11")
    repository.auth_touch_session(
        {
            "token_hash": session_hash,
            "last_seen_at": (NOW + timedelta(minutes=1)).isoformat(),
            "idle_expires_at": (NOW + timedelta(hours=2)).isoformat(),
        }
    )
    assert repository.auth_get_session(session_hash)["last_seen_at"].startswith("2025-01-10T17:04")


def test_legacy_owner_claim_is_one_time_and_preserves_sidecars(tmp_path):
    """Claiming id 1 changes account identity without reassigning immutable ownership rows."""

    repository = _repository(tmp_path)
    local_hash = "scrypt$15$8$1$development-only"
    with repository.connect() as connection:
        before = {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]  # noqa: S608
            for table in (
                "forecast_run_owners",
                "forecast_result_owners",
                "search_event_owners",
                "outcome_owners",
            )
        }
    claimed = repository.claim_legacy_owner(
        login="owner",
        display_name="Research owner",
        password_hash=local_hash,
        claimed_at=NOW,
    )
    assert claimed["id"] == 1
    assert claimed["login"] == "owner"
    assert repository.legacy_owner_id() == 1
    with repository.connect() as connection:
        after = {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]  # noqa: S608
            for table in before
        }
        assert (
            connection.execute("SELECT legacy_owner_claimed_at FROM users WHERE id = 1").fetchone()[
                0
            ]
            == NOW.isoformat()
        )
    assert after == before
    with pytest.raises(ValueError, match="already claimed"):
        repository.claim_legacy_owner(
            login="owner-again",
            display_name="Another owner",
            password_hash=local_hash,
            claimed_at=NOW + timedelta(seconds=1),
        )


def test_legacy_owner_claim_rejects_duplicate_github_identity(tmp_path):
    """A GitHub owner claim cannot steal an identity already bound to another account."""

    repository = _repository(tmp_path)
    repository.create_user(
        github_user_id=42,
        login="existing",
        display_name="Existing",
        password_hash=None,
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="already assigned"):
        repository.claim_legacy_owner(
            login="owner",
            display_name="Research owner",
            github_user_id=42,
            claimed_at=NOW,
        )
    assert repository.legacy_owner_id() == 1


def test_owner_filtering_keeps_events_and_outcomes_private(tmp_path):
    """Two principals may reuse immutable content while retaining separate event/outcome views."""

    repository = _repository(tmp_path)
    member = repository.create_user(
        github_user_id=42,
        login="member",
        display_name="Member",
        password_hash=None,
        created_at=NOW,
    )
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)
    legacy_event, run_id, _, _ = repository.record_success(
        owner_user_id=1,
        request_id="legacy-event",
        submitted_symbol="ACDC",
        asset_type="stock",
        input_snapshot=snapshot,
        results=results,
        submitted_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    member_event, member_run_id, _, _ = repository.record_success(
        owner_user_id=member["id"],
        request_id="member-event",
        submitted_symbol="ACDC",
        asset_type="stock",
        input_snapshot=snapshot,
        results=results,
        submitted_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    assert member_run_id == run_id
    assert repository.history(owner_user_id=1)["total"] == 1
    assert repository.history(owner_user_id=member["id"])["total"] == 1
    assert repository.reconstruction(member["id"], legacy_event) is None

    result_id = repository.reconstruction(member["id"], member_event)["results"][0]["id"]
    repository.append_outcome(
        member["id"],
        result_id,
        25.0,
        0.01,
        NOW + timedelta(days=1),
        "observed",
        "member-only outcome",
        "close comparison",
        NOW + timedelta(days=1),
    )
    assert repository.reconstruction(1, legacy_event)["results"][0]["outcomes"] == []
    assert len(repository.reconstruction(member["id"], member_event)["results"][0]["outcomes"]) == 1


def test_failed_foreign_history_source_is_audited_without_an_owner_fk(tmp_path):
    """An inaccessible source remains request context, never a cross-owner relationship."""

    repository = _repository(tmp_path)
    member = repository.create_user(
        github_user_id=43,
        login="member",
        display_name="Member",
        password_hash=None,
        created_at=NOW,
    )
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)
    admin_event, _, _, _ = repository.record_success(
        owner_user_id=1,
        request_id="admin-source",
        submitted_symbol="ACDC",
        asset_type="stock",
        input_snapshot=snapshot,
        results=results,
        submitted_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )

    owner_failure = repository.record_failure(
        owner_user_id=member["id"],
        request_id="member-foreign-source-failure",
        submitted_symbol=f"<history event {admin_event}>",
        normalized_symbol=None,
        asset_type="invalid",
        error_code="historical_source_unavailable",
        error_message="Fresh analysis requires a saved successful forecast event.",
        submitted_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        analysis_kind="fresh_historical_reconstruction",
        source_event_id=admin_event,
        requested_cutoff=NOW,
    )
    member_event = repository.reconstruction(member["id"], owner_failure)["event"]
    assert member_event["source_event_id"] is None
    assert member_event["requested_source_event_id"] == admin_event


def test_owner_is_required_for_research_reads(tmp_path):
    """Repository APIs do not silently fall back to the legacy account."""

    repository = _repository(tmp_path)
    with pytest.raises(TypeError):
        repository.history()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="owner_user_id is required"):
        repository.history(owner_user_id=None)
