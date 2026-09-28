"""Persistence tests for account state and explicit owner isolation."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib.resources import files

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


def _origin_session(repository: Repository, user_id: int, label: str, at: datetime = NOW) -> str:
    """Create one live provisional session for generation-bound MFA operations."""

    token_hash = _digest(f"{label}-token")
    repository.auth_create_session(
        {
            "session_id": f"{label}-session-0001",
            "user_id": user_id,
            "token_hash": token_hash,
            "csrf_token_hash": _digest(f"{label}-csrf"),
            "auth_method": "github",
            "created_at": at.isoformat(),
            "last_seen_at": at.isoformat(),
            "idle_expires_at": (at + timedelta(hours=1)).isoformat(),
            "expires_at": (at + timedelta(days=1)).isoformat(),
        }
    )
    return token_hash


def _enroll_factor(
    repository: Repository,
    user_id: int,
    label: str,
    recovery_hashes: list[str],
    at: datetime = NOW,
) -> tuple[dict[str, object], str]:
    """Install one factor through the same generation/origin-bound repository path as auth."""

    origin = _origin_session(repository, user_id, f"{label}-origin", at)
    secret = f"enc:v1:{label}:" + "x" * 32
    pending = repository.auth_begin_totp_enrollment(
        user_id,
        secret,
        at.isoformat(),
        (at + timedelta(minutes=5)).isoformat(),
        None,
        origin,
    )
    assert pending is not None
    factor = repository.auth_confirm_totp_enrollment(
        user_id,
        (at + timedelta(seconds=1)).isoformat(),
        secret,
        1,
        recovery_hashes,
        (at + timedelta(seconds=1)).isoformat(),
        None,
        origin,
    )
    assert factor is not None
    return factor, origin


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
            "totp_factors",
            "totp_enrollments",
            "recovery_codes",
            "totp_attempt_throttles",
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


def test_v8_to_v9_preserves_legacy_owner_audit_rows_and_passkeys(tmp_path):
    """The additive MFA migration preserves existing owner mappings and credentials."""

    database_path = tmp_path / "v8.sqlite3"
    migration_names = (
        "001_initial.sql",
        "002_historical_analysis.sql",
        "003_restore_and_immutability_guards.sql",
        "004_history_facets.sql",
        "005_instrument_lists.sql",
        "006_rolling_forecast_horizons.sql",
        "007_auth_ownership_sidecars.sql",
        "008_foreign_reconstruction_audits.sql",
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version, migration_name in enumerate(migration_names, start=1):
            connection.executescript(
                files("stock_probs.migrations").joinpath(migration_name).read_text()
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, NOW.isoformat()),
            )

    legacy = Repository(database_path)
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)
    event_id, run_id, _, _ = legacy.record_success(
        owner_user_id=1,
        request_id="legacy-v8-event",
        submitted_symbol="ACDC",
        asset_type="stock",
        input_snapshot=snapshot,
        results=results,
        submitted_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    credential_id = "legacy-credential-1"
    legacy.register_passkey(
        user_id=1,
        credential_id=credential_id,
        public_key="legacy-public-key-1",
        sign_count=4,
        transports=None,
        created_at=NOW,
    )
    with legacy.connect() as connection:
        before = {
            "event": tuple(
                connection.execute(
                    "SELECT id, request_id, run_id FROM search_events WHERE id = ?", (event_id,)
                ).fetchone()
            ),
            "run": tuple(
                connection.execute(
                    "SELECT id, symbol FROM forecast_runs WHERE id = ?", (run_id,)
                ).fetchone()
            ),
            "event_owner": tuple(
                connection.execute(
                    "SELECT event_id, owner_user_id FROM search_event_owners WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
            ),
            "passkey": tuple(
                connection.execute(
                    "SELECT user_id, credential_id, public_key, sign_count "
                    "FROM passkeys WHERE credential_id = ?",
                    (credential_id,),
                ).fetchone()
            ),
        }

    legacy.migrate()

    with legacy.connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 9
        assert {
            "event": tuple(
                connection.execute(
                    "SELECT id, request_id, run_id FROM search_events WHERE id = ?", (event_id,)
                ).fetchone()
            ),
            "run": tuple(
                connection.execute(
                    "SELECT id, symbol FROM forecast_runs WHERE id = ?", (run_id,)
                ).fetchone()
            ),
            "event_owner": tuple(
                connection.execute(
                    "SELECT event_id, owner_user_id FROM search_event_owners WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
            ),
            "passkey": tuple(
                connection.execute(
                    "SELECT user_id, credential_id, public_key, sign_count "
                    "FROM passkeys WHERE credential_id = ?",
                    (credential_id,),
                ).fetchone()
            ),
        } == before
        assert connection.execute("SELECT COUNT(*) FROM totp_factors").fetchone()[0] == 0


def test_totp_enrollment_expiry_confirmation_and_step_isolation(tmp_path):
    """Pending factors expire, confirmation consumes them, and replay state is user-scoped."""

    repository = _repository(tmp_path)
    user1 = repository.create_user(
        github_user_id=101,
        login="totp-one",
        display_name="TOTP One",
        password_hash=None,
        created_at=NOW,
    )
    user2 = repository.create_user(
        github_user_id=102,
        login="totp-two",
        display_name="TOTP Two",
        password_hash=None,
        created_at=NOW,
    )
    origin1 = _origin_session(repository, user1["id"], "totp-one-origin")
    origin2 = _origin_session(repository, user2["id"], "totp-two-origin")

    first_secret = "enc:v1:first:" + "x" * 32
    first_expiry = NOW + timedelta(minutes=10)
    pending = repository.auth_begin_totp_enrollment(
        user1["id"],
        first_secret,
        NOW.isoformat(),
        first_expiry.isoformat(),
        None,
        origin1,
    )
    assert pending["user_id"] == user1["id"]
    assert (
        repository.auth_get_totp_enrollment(user1["id"], (NOW + timedelta(minutes=9)).isoformat())
        is not None
    )
    assert repository.auth_get_totp_enrollment(user1["id"], first_expiry.isoformat()) is None
    assert (
        repository.auth_confirm_totp_enrollment(
            user1["id"],
            first_expiry.isoformat(),
            first_secret,
            100,
            [_digest("expired-recovery")],
            first_expiry.isoformat(),
            None,
            origin1,
        )
        is None
    )

    created = NOW + timedelta(minutes=11)
    expiry = created + timedelta(minutes=5)
    stale_secret = "enc:v1:stale:" + "x" * 32
    current_secret = "enc:v1:one:" + "x" * 32
    repository.auth_begin_totp_enrollment(
        user1["id"], stale_secret, created.isoformat(), expiry.isoformat(), None, origin1
    )
    repository.auth_begin_totp_enrollment(
        user1["id"], current_secret, created.isoformat(), expiry.isoformat(), None, origin1
    )
    assert (
        repository.auth_confirm_totp_enrollment(
            user1["id"],
            (created + timedelta(seconds=1)).isoformat(),
            stale_secret,
            99,
            [_digest("stale-recovery")],
            (created + timedelta(seconds=1)).isoformat(),
            None,
            origin1,
        )
        is None
    )
    assert (
        repository.auth_get_totp_enrollment(user1["id"], created.isoformat())["secret_ciphertext"]
        == current_secret
    )
    confirmed = repository.auth_confirm_totp_enrollment(
        user1["id"],
        (created + timedelta(seconds=1)).isoformat(),
        current_secret,
        50,
        [_digest("current-recovery")],
        (created + timedelta(seconds=1)).isoformat(),
        None,
        origin1,
    )
    assert confirmed is not None
    assert confirmed["user_id"] == user1["id"]
    assert confirmed["last_accepted_step"] == 50
    assert repository.auth_get_totp_enrollment(user1["id"], expiry.isoformat()) is None
    assert repository.auth_get_totp_factor(user1["id"])["encrypted_secret"].startswith("enc:v1:one")

    user2_created = created + timedelta(seconds=1)
    user2_expiry = user2_created + timedelta(minutes=5)
    user2_secret = "enc:v1:two:" + "x" * 32
    repository.auth_begin_totp_enrollment(
        user2["id"],
        user2_secret,
        user2_created.isoformat(),
        user2_expiry.isoformat(),
        None,
        origin2,
    )
    assert (
        repository.auth_confirm_totp_enrollment(
            user2["id"],
            (user2_created + timedelta(seconds=1)).isoformat(),
            user2_secret,
            50,
            [_digest("user2-recovery")],
            (user2_created + timedelta(seconds=1)).isoformat(),
            None,
            origin2,
        )
        is not None
    )

    accepted_at = (created + timedelta(minutes=1)).isoformat()
    factor1 = repository.auth_get_totp_factor(user1["id"])["id"]
    factor2 = repository.auth_get_totp_factor(user2["id"])["id"]
    assert repository.auth_accept_totp_step(user1["id"], factor1, 100, accepted_at)
    assert repository.auth_accept_totp_step(user1["id"], factor1, 100, accepted_at) is False
    assert repository.auth_accept_totp_step(user1["id"], factor1, 99, accepted_at) is False
    assert repository.auth_accept_totp_step(user2["id"], factor2, 100, accepted_at)
    assert repository.auth_accept_totp_step(user1["id"], factor1, 101, accepted_at)
    assert repository.auth_get_totp_factor(user1["id"])["last_accepted_step"] == 101
    assert repository.auth_get_totp_factor(user2["id"])["last_accepted_step"] == 100


def test_totp_factor_replacement_rolls_back_all_security_state_on_failure(tmp_path):
    """A recovery-code conflict cannot leave a new factor or revoked session half-committed."""

    repository = _repository(tmp_path)
    user = repository.create_user(
        github_user_id=107,
        login="totp-atomic",
        display_name="TOTP Atomic",
        password_hash=None,
        created_at=NOW,
    )
    secret = "enc:v1:atomic:" + "x" * 32
    created = NOW + timedelta(minutes=1)
    origin = _origin_session(repository, user["id"], "totp-atomic-origin")
    repository.auth_begin_totp_enrollment(
        user["id"],
        secret,
        created.isoformat(),
        (created + timedelta(minutes=5)).isoformat(),
        None,
        origin,
    )
    collision = _digest("already-issued")
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO recovery_codes(user_id, code_hash, created_at) VALUES (?, ?, ?)",
            (user["id"], collision, NOW.isoformat()),
        )
        connection.commit()

    confirmed_at = (created + timedelta(seconds=1)).isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        repository.auth_confirm_totp_enrollment(
            user["id"],
            confirmed_at,
            secret,
            70,
            [collision],
            confirmed_at,
            None,
            origin,
        )

    assert repository.auth_get_totp_factor(user["id"]) is None
    assert repository.auth_get_totp_enrollment(user["id"], confirmed_at) is not None
    assert repository.auth_get_session(origin)["revoked_at"] is None
    assert repository.auth_get_recovery_code_status(user["id"])["available_count"] == 1


def test_totp_generation_fences_stale_session_and_recovery_proofs(tmp_path):
    """A replacement generation rejects every proof captured for the prior factor."""

    repository = _repository(tmp_path)
    user = repository.create_user(
        github_user_id=108,
        login="totp-generation",
        display_name="TOTP Generation",
        password_hash=None,
        created_at=NOW,
    )
    old_factor, origin = _enroll_factor(
        repository, user["id"], "generation-old", [_digest("generation-old-code")]
    )
    old_factor_id = old_factor["id"]
    replacement_secret = "enc:v1:generation-new:" + "x" * 32
    replacement_at = NOW + timedelta(minutes=1)
    pending = repository.auth_begin_totp_enrollment(
        user["id"],
        replacement_secret,
        replacement_at.isoformat(),
        (replacement_at + timedelta(minutes=5)).isoformat(),
        old_factor_id,
        origin,
    )
    assert pending is not None
    new_factor = repository.auth_confirm_totp_enrollment(
        user["id"],
        (replacement_at + timedelta(seconds=1)).isoformat(),
        replacement_secret,
        2,
        [_digest("generation-new-code")],
        (replacement_at + timedelta(seconds=1)).isoformat(),
        old_factor_id,
        origin,
    )
    assert new_factor is not None
    assert new_factor["id"] != old_factor_id

    stale_session = repository.auth_create_session(
        {
            "session_id": "stale-generation-session-0001",
            "user_id": user["id"],
            "token_hash": _digest("stale-generation-session"),
            "csrf_token_hash": _digest("stale-generation-csrf"),
            "auth_method": "github",
            "created_at": (replacement_at + timedelta(seconds=2)).isoformat(),
            "last_seen_at": (replacement_at + timedelta(seconds=2)).isoformat(),
            "idle_expires_at": (replacement_at + timedelta(hours=1)).isoformat(),
            "expires_at": (replacement_at + timedelta(days=1)).isoformat(),
            "mfa_method": "totp",
            "mfa_verified_at": (replacement_at + timedelta(seconds=2)).isoformat(),
            "expected_factor_id": old_factor_id,
            "origin_token_hash": origin,
        }
    )
    assert stale_session is None
    assert not repository.auth_accept_totp_step(
        user["id"], old_factor_id, 100, (replacement_at + timedelta(seconds=2)).isoformat()
    )
    assert not repository.auth_create_recovery_codes(
        user["id"],
        old_factor_id,
        [_digest("stale-rotation")],
        (replacement_at + timedelta(seconds=2)).isoformat(),
        origin,
    )


def test_generation_bound_repository_validation_and_clock_skew_paths(tmp_path):
    """Exercise fail-closed field validation and normal timestamp skew serialization paths."""

    repository = _repository(tmp_path)
    user = repository.create_user(
        github_user_id=110,
        login="totp-validation",
        display_name="TOTP Validation",
        password_hash=None,
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="user_id"):
        repository.auth_create_session({"user_id": "not-an-id"})
    minimal_session = {
        "user_id": user["id"],
        "created_at": NOW.isoformat(),
        "last_seen_at": NOW.isoformat(),
        "idle_expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
    }
    with pytest.raises(ValueError, match="token_hash"):
        repository.auth_create_session(
            minimal_session | {"token_hash": "bad", "csrf_token_hash": "bad"}
        )

    valid_session = {
        "session_id": "validation-session-0001",
        "user_id": user["id"],
        "token_hash": _digest("validation-token"),
        "csrf_token_hash": _digest("validation-csrf"),
        "auth_method": "github",
        "created_at": NOW.isoformat(),
        "last_seen_at": NOW.isoformat(),
        "idle_expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
    }
    with pytest.raises(ValueError, match="auth_method"):
        repository.auth_create_session(valid_session | {"auth_method": "unknown"})
    with pytest.raises(ValueError, match="auth_method"):
        repository.auth_create_session(valid_session | {"auth_method": None})
    with pytest.raises(ValueError, match="session_id length"):
        repository.auth_create_session(valid_session | {"session_id": "short"})
    generated_session = repository.auth_create_session(valid_session | {"session_id": None})
    assert generated_session is not None and len(generated_session["session_id"]) == 32

    factor, origin = _enroll_factor(
        repository, user["id"], "validation-factor", [_digest("validation-code")]
    )
    factor_id = factor["id"]
    with pytest.raises(ValueError, match="expected_factor_id"):
        repository.auth_create_session(valid_session | {"mfa_method": "totp"})
    with pytest.raises(ValueError, match="mfa_verified_at"):
        repository.auth_create_session(
            valid_session | {"mfa_method": "totp", "expected_factor_id": factor_id}
        )
    assert (
        repository.auth_create_session(
            valid_session
            | {
                "mfa_method": "totp",
                "mfa_verified_at": (NOW + timedelta(seconds=2)).isoformat(),
                "expected_factor_id": factor_id,
            }
        )
        is None
    )
    assert (
        repository.auth_create_session(
            valid_session
            | {
                "mfa_method": "totp",
                "mfa_verified_at": (NOW + timedelta(seconds=2)).isoformat(),
                "expected_factor_id": factor_id,
                "origin_token_hash": valid_session["token_hash"],
            }
        )
        is None
    )
    with pytest.raises(ValueError, match="revoke_other_sessions"):
        repository.auth_create_session(valid_session | {"revoke_other_sessions": "yes"})
    with pytest.raises(ValueError, match="mfa_method"):
        repository.auth_create_session(valid_session | {"mfa_method": "webauthn"})

    with pytest.raises(ValueError, match="originating session"):
        repository.auth_begin_totp_enrollment(
            user["id"],
            "enc:v1:missing-origin:" + "x" * 32,
            NOW.isoformat(),
            (NOW + timedelta(minutes=5)).isoformat(),
            factor_id,
            None,
        )
    with pytest.raises(ValueError, match="expire within"):
        repository.auth_begin_totp_enrollment(
            user["id"],
            "enc:v1:bad-window:" + "x" * 32,
            NOW.isoformat(),
            (NOW + timedelta(minutes=11)).isoformat(),
            factor_id,
            origin,
        )
    assert repository.auth_reserve_totp_attempt(
        user["id"], (NOW + timedelta(seconds=10)).isoformat(), factor_id
    )
    # A request timestamp captured before the write lock is clamped to the last reservation.
    assert repository.auth_reserve_totp_attempt(
        user["id"], (NOW + timedelta(seconds=5)).isoformat(), factor_id
    )
    assert not repository.auth_reserve_totp_attempt(user["id"], NOW.isoformat(), factor_id + 100)


def test_totp_throttle_is_durable_and_success_resets_failed_attempts(tmp_path):
    """Failed attempts lock one account durably, while valid verification clears the gate."""

    repository = _repository(tmp_path)
    user = repository.create_user(
        github_user_id=103,
        login="totp-throttle",
        display_name="TOTP Throttle",
        password_hash=None,
        created_at=NOW,
    )
    first = repository.auth_record_totp_attempt(
        user["id"], NOW.isoformat(), max_attempts=2, lockout_seconds=10
    )
    assert first["allowed"] is True
    assert first["attempt_count"] == 1
    locked_at = NOW + timedelta(seconds=1)
    second = repository.auth_record_totp_attempt(
        user["id"], locked_at.isoformat(), max_attempts=2, lockout_seconds=10
    )
    assert second["allowed"] is False
    assert second["attempt_count"] == 2
    assert second["locked_until"] is not None
    assert (
        repository.auth_check_totp_attempt(
            user["id"], (locked_at + timedelta(seconds=1)).isoformat()
        )["allowed"]
        is False
    )

    restarted = Repository(repository.database_path)
    assert (
        restarted.auth_check_totp_attempt(
            user["id"], (locked_at + timedelta(seconds=1)).isoformat()
        )["allowed"]
        is False
    )
    blocked = restarted.auth_record_totp_attempt(
        user["id"], (locked_at + timedelta(seconds=2)).isoformat(), max_attempts=2
    )
    assert blocked["allowed"] is False
    assert blocked["attempt_count"] == 2

    unlocked_at = locked_at + timedelta(seconds=11)
    success = restarted.auth_record_totp_attempt(
        user["id"], unlocked_at.isoformat(), max_attempts=2, successful=True
    )
    assert success["allowed"] is True
    assert success["attempt_count"] == 0
    assert success["locked_until"] is None
    after_success = restarted.auth_record_totp_attempt(
        user["id"], (unlocked_at + timedelta(seconds=1)).isoformat(), max_attempts=2
    )
    assert after_success["allowed"] is True
    assert after_success["attempt_count"] == 1


def test_totp_attempt_reservation_caps_concurrent_guesses(tmp_path):
    """The write-locked reservation admits at most five guesses before crypto runs."""

    repository = _repository(tmp_path)
    user = repository.create_user(
        github_user_id=109,
        login="totp-reservation",
        display_name="TOTP Reservation",
        password_hash=None,
        created_at=NOW,
    )
    attempted_at = NOW.isoformat()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: repository.auth_reserve_totp_attempt(user["id"], attempted_at),
                range(8),
            )
        )
    assert sum(results) == 5
    state = repository.auth_check_totp_attempt(user["id"], attempted_at)
    assert state["attempt_count"] == 5
    assert state["allowed"] is False

    # A successful verifier may clear the reservation even while the failure lock is active.
    reset = repository.auth_record_totp_attempt(
        user["id"], attempted_at, successful=True
    )
    assert reset["attempt_count"] == 0
    assert repository.auth_reserve_totp_attempt(user["id"], attempted_at)


def test_recovery_codes_are_single_use_and_rotate_atomically(tmp_path):
    """Recovery hashes are private, one-way, single-use records with bounded rotation."""

    repository = _repository(tmp_path)
    user1 = repository.create_user(
        github_user_id=104,
        login="recovery-one",
        display_name="Recovery One",
        password_hash=None,
        created_at=NOW,
    )
    user2 = repository.create_user(
        github_user_id=105,
        login="recovery-two",
        display_name="Recovery Two",
        password_hash=None,
        created_at=NOW,
    )
    first_hash = _digest("recovery-first")
    second_hash = _digest("recovery-second")
    replacement_hash = _digest("recovery-replacement")
    factor1, origin1 = _enroll_factor(
        repository, user1["id"], "recovery-one", [first_hash, second_hash]
    )
    factor2, _origin2 = _enroll_factor(
        repository, user2["id"], "recovery-two", [_digest("recovery-two-only")]
    )
    factor1_id = factor1["id"]
    factor2_id = factor2["id"]
    assert repository.auth_get_recovery_code_status(user1["id"]) == {
        "user_id": user1["id"],
        "total_count": 2,
        "available_count": 2,
        "consumed_count": 0,
        "revoked_count": 0,
    }
    assert all(
        "code_hash" not in row for row in repository.auth_list_recovery_code_status(user1["id"])
    )
    consumed_at = (NOW + timedelta(seconds=1)).isoformat()
    assert repository.auth_consume_recovery_code(
        user1["id"], factor1_id, first_hash, consumed_at
    )
    assert not repository.auth_consume_recovery_code(
        user1["id"], factor1_id, first_hash, consumed_at
    )
    assert not repository.auth_consume_recovery_code(
        user2["id"], factor2_id, second_hash, consumed_at
    )

    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="single-use"):
            connection.execute(
                "UPDATE recovery_codes SET consumed_at = NULL WHERE code_hash = ?",
                (first_hash,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            connection.execute(
                "UPDATE recovery_codes SET code_hash = ? WHERE code_hash = ?",
                (replacement_hash, second_hash),
            )

    assert repository.auth_create_recovery_codes(
        user1["id"],
        factor1_id,
        [replacement_hash],
        (NOW + timedelta(minutes=1)).isoformat(),
        origin1,
    )
    assert not repository.auth_consume_recovery_code(
        user1["id"], factor1_id, second_hash, consumed_at
    )
    assert repository.auth_consume_recovery_code(
        user1["id"], factor1_id, replacement_hash, (NOW + timedelta(minutes=2)).isoformat()
    )
    assert repository.auth_get_recovery_code_status(user1["id"]) == {
        "user_id": user1["id"],
        "total_count": 3,
        "available_count": 0,
        "consumed_count": 2,
        "revoked_count": 1,
    }
    current_codes = repository.auth_list_recovery_code_status(user1["id"])
    assert len(current_codes) == 2
    assert all(row["revoked_at"] is None for row in current_codes)


def test_session_mfa_data_is_persisted_and_revoked(tmp_path):
    """MFA proof metadata is paired, updateable only for live sessions, and retained on revoke."""

    repository = _repository(tmp_path)
    user = repository.create_user(
        github_user_id=106,
        login="session-mfa",
        display_name="Session MFA",
        password_hash=None,
        created_at=NOW,
    )
    token_hash = _digest("mfa-session")
    factor, _origin = _enroll_factor(
        repository, user["id"], "session-mfa-factor", [_digest("session-mfa-code")]
    )
    factor_id = factor["id"]
    repository.auth_create_session(
        {
            "session_id": "mfa-session-0001",
            "user_id": user["id"],
            "token_hash": token_hash,
            "csrf_token_hash": _digest("mfa-csrf"),
            "auth_method": "github",
            "created_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "idle_expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
        }
    )
    assert repository.auth_set_session_mfa(
        token_hash,
        "totp",
        (NOW + timedelta(seconds=1)).isoformat(),
        factor_id,
    )
    assert repository.auth_set_session_mfa(
        token_hash, "recovery", (NOW + timedelta(minutes=1)).isoformat(), factor_id
    )
    assert repository.auth_get_session(token_hash)["mfa_method"] == "recovery"
    assert repository.auth_get_session(token_hash)["mfa_verified_at"].startswith("2025-01-10T17:04")

    second_hash = _digest("mfa-session-second")
    repository.auth_create_session(
        {
            "session_id": "mfa-session-0002",
            "user_id": user["id"],
            "token_hash": second_hash,
            "csrf_token_hash": _digest("mfa-csrf-second"),
            "auth_method": "github",
            "created_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "idle_expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
        }
    )
    assert repository.revoke_user_sessions(user["id"], revoked_at=NOW + timedelta(minutes=2)) == 3
    assert repository.auth_get_session(token_hash)["revoked_at"] is not None
    assert repository.auth_get_session(second_hash)["revoked_at"] is not None
    assert not repository.auth_set_session_mfa(
        token_hash, "totp", (NOW + timedelta(minutes=3)).isoformat(), factor_id
    )

    with repository.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE sessions SET mfa_method = 'totp', mfa_verified_at = NULL WHERE token_hash = ?",
            (token_hash,),
        )


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
    assert repository.revoke_passkey(credential_id, revoked_at=NOW + timedelta(minutes=4))
    assert repository.get_passkey(credential_id, user_id=user["id"]) is None
    assert repository.auth_get_passkeys(user["id"]) == []
    assert not repository.update_passkey_sign_count(
        credential_id, sign_count=2, used_at=NOW + timedelta(minutes=5)
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
