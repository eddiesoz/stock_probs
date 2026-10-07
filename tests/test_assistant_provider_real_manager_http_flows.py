"""Public provider-admin flows through the real assistant provider manager."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.assistant.model_catalog import AssistantModel, AssistantModelCatalog
from stock_probs.assistant.providers import AssistantProviderManager
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider


def _now() -> datetime:
    return datetime.now(UTC)


def _auth_settings(settings: Settings, data_dir: Path) -> Settings:
    return replace(
        settings,
        data_dir=data_dir,
        environment="test",
        auth_mode="github",
        auth_session_secret="synthetic-provider-http-session-secret-not-production-000000",  # noqa: S106
        auth_public_origin="http://testserver",
        auth_session_idle_seconds=86_400,
        github_client_id="synthetic-client-id",
        github_client_secret="synthetic-client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _add_signed_in_user(application: Any, github_id: int, *, role: str) -> dict[str, str | int]:
    repository = application.state.repository
    now = application.state.assistant.now().replace(microsecond=0)
    user = repository.auth_create_user(
        {
            "github_id": github_id,
            "github_login": f"synthetic-{github_id}",
            "display_name": f"Synthetic user {github_id}",
            "role": role,
            "status": "active",
            "created_at": now,
        }
    )
    user_id = int(user["id"])
    expires = now + timedelta(hours=23)
    with repository.connect() as connection:
        factor = connection.execute(
            """INSERT INTO totp_factors
            (user_id, secret_ciphertext, created_at, confirmed_at,
             last_accepted_step, updated_at)
            VALUES (?, ?, ?, ?, -1, ?)""",
            (
                user_id,
                "synthetic-encrypted-factor-not-used-for-code-verification",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        factor_id = int(factor.lastrowid)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        session_id = secrets.token_hex(16)
        connection.execute(
            """INSERT INTO sessions
            (user_id, session_id, token_hash, csrf_token_hash, issued_at, last_seen_at,
             idle_expires_at, absolute_expires_at, auth_method, mfa_method,
             mfa_verified_at, mfa_factor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'github', 'totp', ?, ?)""",
            (
                user_id,
                session_id,
                _sha(token),
                _sha(csrf),
                now.isoformat(),
                now.isoformat(),
                expires.isoformat(),
                expires.isoformat(),
                now.isoformat(),
                factor_id,
            ),
        )
        connection.commit()
    return {
        "user_id": user_id,
        "session_id": session_id,
        "token": token,
        "token_hash": _sha(token),
        "csrf": csrf,
    }


def _mark_recent_step_up(application: Any, identity: dict[str, str | int]) -> None:
    factor = application.state.repository.auth_get_totp_factor(int(identity["user_id"]))
    assert factor is not None
    verified_at = application.state.assistant.now().replace(microsecond=0).isoformat()
    assert application.state.repository.auth_set_session_mfa(
        str(identity["token_hash"]), "totp", verified_at, int(factor["id"])
    )


def _browser_client(application: Any, identity: dict[str, str | int]) -> TestClient:
    authenticated = application.state.auth.authenticate(
        str(identity["token"]), application.state.assistant.now()
    )
    assert authenticated.user.id == identity["user_id"]
    client = TestClient(application, client=("127.0.0.1", 51120))
    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
    return client


class _Runtime:
    async def start(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"status": "ready", "message": None}

    async def close(self) -> None:
        return None

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        del conversation_id
        return True


class _NativeOAuthRuntime(_Runtime):
    def __init__(self) -> None:
        self.attempts: set[str] = set()
        self.capabilities: dict[str, str] = {}
        self.cancelled: list[str] = []

    async def list_native_integrations(self) -> list[dict[str, object]]:
        return [
            {
                "integration_id": "openai",
                "methods": [{"method_id": "chatgpt-headless", "kind": "oauth"}],
            }
        ]

    async def begin_native_oauth(
        self,
        integration_id: str,
        method_id: str,
        *,
        attempt_id: str,
        owner_id: int,
        session_id: str,
        capability: str,
    ) -> dict[str, object]:
        assert (integration_id, method_id) == ("openai", "chatgpt-headless")
        assert owner_id > 0 and len(session_id) == 32
        self.attempts.add(attempt_id)
        self.capabilities[attempt_id] = capability
        return {
            "url": "https://auth.openai.com/codex/device",
            "instructions": "Enter code: SYNTHETIC-DEVICE-CODE",
            "mode": "auto",
            "expires_at": time.time() + 300,
        }

    async def native_oauth_status(
        self,
        integration_id: str,
        attempt_id: str,
        *,
        owner_id: int,
        session_id: str,
    ) -> str:
        assert integration_id == "openai" and attempt_id in self.attempts
        assert owner_id > 0 and len(session_id) == 32
        return "handoff_ready"

    async def take_native_oauth_handoff(
        self,
        integration_id: str,
        attempt_id: str,
        *,
        owner_id: int,
        session_id: str,
    ) -> dict[str, object]:
        assert integration_id == "openai" and attempt_id in self.attempts
        assert owner_id > 0 and len(session_id) == 32
        return {
            "type": "oauth",
            "methodID": "chatgpt-headless",
            "access": "synthetic-native-access-token-r120",
            "refresh": "synthetic-native-refresh-token-r120",
            "expires": int((time.time() + 3600) * 1000),
            "metadata": {"accountID": "synthetic-native-account-r120"},
        }

    async def cancel_native_oauth(
        self,
        integration_id: str,
        attempt_id: str,
        *,
        owner_id: int,
        session_id: str,
    ) -> None:
        assert integration_id == "openai"
        assert owner_id > 0 and len(session_id) == 32
        self.cancelled.append(attempt_id)


class _ProviderConfigurationRuntime(_Runtime):
    def __init__(self) -> None:
        self.syncs: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def sync_provider_configuration(
        self,
        provider_id: str,
        definition: dict[str, object],
        state: dict[str, object],
    ) -> None:
        self.syncs.append((provider_id, dict(definition), dict(state)))


def test_real_manager_oauth_http_completion_stores_and_deletes_encrypted_connection(
    settings: Settings, tmp_path: Path
) -> None:
    config = _auth_settings(settings, tmp_path)
    catalog = AssistantModelCatalog(config)
    runtime = _NativeOAuthRuntime()
    manager = AssistantProviderManager(
        config,
        catalog,
        vault_dir=tmp_path / "assistant-vault",
    )
    application = create_app(
        config,
        FixtureProvider(),
        _now,
        assistant_runtime=runtime,
        assistant_catalog=catalog,
        assistant_providers=manager,
    )

    with TestClient(application, client=("127.0.0.1", 51121)):
        admin = _add_signed_in_user(application, 51201, role="admin")
        member = _add_signed_in_user(application, 51202, role="member")
        _mark_recent_step_up(application, admin)
        admin_browser = _browser_client(application, admin)
        member_browser = _browser_client(application, member)
        vault_path = manager._oauth_credential_path(
            "openai", int(admin["user_id"]), "chatgpt-headless"
        )
        try:
            started = admin_browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert started.status_code == 200, started.text
            attempt = started.json()["attempt"]
            attempt_id = attempt["attempt_id"]
            assert attempt["status"] == "pending"
            assert attempt["method_id"] == "chatgpt-headless"
            assert "capability" not in started.text

            completed = admin_browser.post(
                f"/api/v1/assistant/providers/oauth/attempts/{attempt_id}/complete",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={},
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["attempt"]["status"] == "connected"
            assert vault_path.is_file()
            ciphertext = vault_path.read_bytes()
            assert b"synthetic-native-access-token-r120" not in ciphertext
            assert b"synthetic-native-refresh-token-r120" not in ciphertext
            assert manager._oauth_attempts[attempt_id].transport_capability is None

            connections = admin_browser.get("/api/v1/assistant/providers/oauth/connections")
            assert connections.status_code == 200, connections.text
            assert connections.json()["connections"] == [
                {
                    "integration_id": "openai",
                    "method_id": "chatgpt-headless",
                    "status": "connected",
                    "model_access_supported": True,
                    "availability_reason": None,
                }
            ]
            transcript = started.text + completed.text + connections.text
            assert "synthetic-native-access-token-r120" not in transcript
            assert "synthetic-native-refresh-token-r120" not in transcript
            assert "synthetic-native-account-r120" not in transcript

            denied = member_browser.delete(
                "/api/v1/assistant/providers/oauth/connections/openai/chatgpt-headless",
                headers={"x-csrf-token": str(member["csrf"])},
            )
            assert denied.status_code == 403
            assert vault_path.is_file()

            removed = admin_browser.delete(
                "/api/v1/assistant/providers/oauth/connections/openai/chatgpt-headless",
                headers={"x-csrf-token": str(admin["csrf"])},
            )
            assert removed.status_code == 200, removed.text
            assert removed.json()["connection"]["status"] == "disconnected"
            assert admin_browser.get("/api/v1/assistant/providers/oauth/connections").json() == {
                "connections": []
            }
            assert not vault_path.exists()
        finally:
            admin_browser.close()
            member_browser.close()


def test_real_manager_provider_http_update_and_clear_use_private_vault_and_runtime_sync(
    settings: Settings, tmp_path: Path
) -> None:
    config = _auth_settings(settings, tmp_path)
    catalog = AssistantModelCatalog(config)
    model = AssistantModel(
        model_id="openai/synthetic-r120-admin-model",
        provider_id="openai",
        display_name="Synthetic provider-admin model",
        available=True,
        free=False,
        training=False,
        terms_url="https://models.example.test/terms",
        terms_reviewed_at="2026-10-06",
        policy_version="synthetic-r120-provider-policy",
        disclosure="Synthetic fixture; no upstream provider is contacted.",
        data_collection_allowed=False,
        data_collection_default=False,
        native_provider_id="openai",
        privacy_policy_version="synthetic-r120-privacy",
        billing_policy_version="synthetic-r120-billing",
        billing_class="paid",
        privacy_disclosure="Synthetic privacy disclosure.",
        cost_disclosure="Synthetic billing disclosure.",
    )
    manager = AssistantProviderManager(
        config,
        catalog,
        vault_dir=tmp_path / "assistant-vault",
    )
    catalog.set_native_models((model,))
    runtime = _ProviderConfigurationRuntime()
    application = create_app(
        config,
        FixtureProvider(),
        _now,
        assistant_runtime=runtime,
        assistant_catalog=catalog,
        assistant_providers=manager,
    )

    with TestClient(application, client=("127.0.0.1", 51122)):
        admin = _add_signed_in_user(application, 51203, role="admin")
        member = _add_signed_in_user(application, 51204, role="member")
        _mark_recent_step_up(application, admin)
        admin_browser = _browser_client(application, admin)
        member_browser = _browser_client(application, member)
        vault_path = manager._credential_path("openai")
        try:
            secret = "synthetic-openai-provider-key-r120"  # noqa: S105
            updated = admin_browser.put(
                "/api/v1/assistant/providers/openai",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={"model_id": model.model_id, "credential": secret},
            )
            assert updated.status_code == 200, updated.text
            provider = updated.json()["provider"]
            assert provider["provider_id"] == "openai"
            assert provider["selected_model_id"] == model.model_id
            assert provider["credential_configured"] is True
            assert secret not in updated.text
            assert vault_path.is_file()
            assert secret.encode() not in vault_path.read_bytes()
            assert len(runtime.syncs) == 1
            assert runtime.syncs[0][0] == "openai"
            assert runtime.syncs[0][2] == {"model_id": model.model_id}
            assert secret not in json.dumps(runtime.syncs[0])

            denied = member_browser.delete(
                "/api/v1/assistant/providers/openai",
                headers={"x-csrf-token": str(member["csrf"])},
            )
            assert denied.status_code == 403
            assert vault_path.is_file()
            assert len(runtime.syncs) == 1

            cleared = admin_browser.delete(
                "/api/v1/assistant/providers/openai",
                headers={"x-csrf-token": str(admin["csrf"])},
            )
            assert cleared.status_code == 200, cleared.text
            openai = next(
                row for row in cleared.json()["providers"] if row["provider_id"] == "openai"
            )
            assert "selected_model_id" not in openai
            assert openai["credential_configured"] is False
            assert openai["connection_status"] == "unconfigured"
            assert not vault_path.exists()
            assert len(runtime.syncs) == 2
            assert runtime.syncs[1][0] == "openai"
            assert runtime.syncs[1][2] == {}
            assert secret not in cleared.text
        finally:
            admin_browser.close()
            member_browser.close()
