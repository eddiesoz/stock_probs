"""Focused regression coverage for the schema-13 synthetic restore guard."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "pr_rehearsal_seed.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))
SPEC = importlib.util.spec_from_file_location("r120_pr_rehearsal_seed", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
seed_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = seed_script
SPEC.loader.exec_module(seed_script)


def _fixture(tmp_path: Path) -> tuple[Settings, Repository, dict[str, object]]:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="synthetic-seed-repair-test-secret-not-production-000000",  # noqa: S106
        auth_public_origin="https://ledger-r120.test",
    )
    repository = Repository(settings.database_path)
    repository.migrate()
    seeded = seed_script._seed(repository, settings)
    return settings, repository, seeded


def _step_up_timestamps(repository: Repository, users: list[dict[str, str]]) -> list[str]:
    timestamps = []
    for user in users:
        token_hash = hashlib.sha256(user["session_cookie"].encode()).hexdigest()
        session = repository.auth_get_session(token_hash)
        assert session is not None
        verified_at = session["mfa_verified_at"]
        assert isinstance(verified_at, str)
        timestamps.append(verified_at)
    return timestamps


def test_restore_guard_projects_seeded_users_and_checks_real_api_step_up_denial(
    tmp_path: Path,
) -> None:
    settings, repository, seeded = _fixture(tmp_path)
    users = cast(list[dict[str, str]], seeded["users"])
    before = _step_up_timestamps(repository, users)
    now = datetime.now(UTC)
    assert all(
        timedelta(0) <= now - datetime.fromisoformat(timestamp) <= timedelta(minutes=5)
        for timestamp in before
    )
    application = create_app(settings, FixtureProvider())
    responses: list[httpx.Response] = []

    with TestClient(application, base_url="https://ledger-r120.test") as client:
        result = seed_script._restore_guard(
            {"users": users, "backup_name": "synthetic-target.spbackup"},
            repository,
            post_request=lambda *args, **kwargs: _record_response(
                responses, client.post(*args, **kwargs)
            ),
        )

    assert result == {"restore_guard_denied_without_fresh_step_up": True}
    assert [response.status_code for response in responses] == [403, 403]
    assert responses[0].json()["error"]["code"] == "authorization_denied"
    assert "fresh authenticator code" in responses[0].json()["error"]["message"]
    assert _step_up_timestamps(repository, users) == before


def test_restore_guard_handles_seed_sessions_that_aged_during_native_turns(
    tmp_path: Path,
) -> None:
    _settings, repository, seeded = _fixture(tmp_path)
    users = cast(list[dict[str, str]], seeded["users"])
    aged_at = (datetime.now(UTC) - timedelta(minutes=15)).isoformat()
    for user in users:
        token_hash = hashlib.sha256(user["session_cookie"].encode()).hexdigest()
        session = repository.auth_get_session(token_hash)
        assert session is not None
        with repository.connect() as connection:
            connection.execute(
                "UPDATE sessions SET mfa_verified_at = ? WHERE token_hash = ? AND user_id = ?",
                (aged_at, token_hash, session["user_id"]),
            )
            connection.commit()
    before = _step_up_timestamps(repository, users)
    responses: list[httpx.Response] = []

    def reject_restore(*_args: object, **_kwargs: object) -> httpx.Response:
        now = datetime.now(UTC)
        for timestamp in _step_up_timestamps(repository, users):
            assert now - datetime.fromisoformat(timestamp) > timedelta(minutes=5)
        response = httpx.Response(403)
        responses.append(response)
        return response

    result = seed_script._restore_guard(
        {"users": users, "backup_name": "synthetic-target.spbackup"},
        repository,
        post_request=reject_restore,
    )

    assert result == {"restore_guard_denied_without_fresh_step_up": True}
    assert [response.status_code for response in responses] == [403, 403]
    assert _step_up_timestamps(repository, users) == before


def _record_response(responses: list[httpx.Response], response: httpx.Response) -> httpx.Response:
    responses.append(response)
    return response


def test_restore_guard_rejects_non_synthetic_session_without_http_or_timestamp_change(
    tmp_path: Path,
) -> None:
    _settings, repository, seeded = _fixture(tmp_path)
    users = cast(list[dict[str, str]], seeded["users"])
    before = _step_up_timestamps(repository, users)
    owner_cookie = users[0]["session_cookie"]
    owner_hash = hashlib.sha256(owner_cookie.encode()).hexdigest()
    with repository.connect() as connection:
        connection.execute(
            "UPDATE users SET github_user_id = ? WHERE id = ("
            "SELECT user_id FROM sessions WHERE token_hash = ?) ",
            (seed_script.OWNER_GITHUB_ID + 100, owner_hash),
        )
        connection.commit()
    requests: list[object] = []

    with pytest.raises(RuntimeError, match="synthetic identity is invalid"):
        seed_script._restore_guard(
            {"users": users, "backup_name": "synthetic-target.spbackup"},
            repository,
            post_request=lambda *args, **kwargs: requests.append((args, kwargs)),
        )

    assert requests == []
    assert _step_up_timestamps(repository, users) == before


def test_restore_guard_restores_fresh_step_up_when_request_transport_raises(
    tmp_path: Path,
) -> None:
    _settings, repository, seeded = _fixture(tmp_path)
    users = cast(list[dict[str, str]], seeded["users"])
    before = _step_up_timestamps(repository, users)

    def fail_request(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic transport failure")

    with pytest.raises(RuntimeError, match="synthetic transport failure"):
        seed_script._restore_guard(
            {"users": users, "backup_name": "synthetic-target.spbackup"},
            repository,
            post_request=fail_request,
        )

    assert _step_up_timestamps(repository, users) == before
