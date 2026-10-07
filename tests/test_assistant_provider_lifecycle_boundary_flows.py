"""Exercise provider configuration and OAuth lifecycle failures through HTTP."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.assistant.model_catalog import AssistantModelCatalog
from stock_probs.assistant.providers import AssistantProviderManager
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider


def _auth_settings(settings: Settings, data_dir: Path) -> Settings:
    """Use an isolated local database and synthetic OAuth configuration."""

    return replace(
        settings,
        data_dir=data_dir,
        environment="test",
        auth_mode="github",
        auth_session_secret="synthetic-provider-lifecycle-session-secret-not-production-0000",  # noqa: S106
        auth_public_origin="http://testserver",
        auth_session_idle_seconds=86_400,
        github_client_id="synthetic-client-id",
        github_client_secret="synthetic-client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
    )


def _sha(value: str) -> str:
    """Return the digest stored for a synthetic app session."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _add_admin(application: Any, github_id: int) -> dict[str, str | int]:
    """Create one synthetic admin with a recent MFA session for provider writes."""

    repository = application.state.repository
    now = application.state.assistant.now().replace(microsecond=0)
    user = repository.auth_create_user(
        {
            "github_id": github_id,
            "github_login": f"synthetic-{github_id}",
            "display_name": f"Synthetic provider admin {github_id}",
            "role": "admin",
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


def _browser_client(application: Any, identity: dict[str, str | int]) -> TestClient:
    """Return a local browser client carrying the synthetic session and CSRF cookies."""

    authenticated = application.state.auth.authenticate(
        str(identity["token"]), application.state.assistant.now()
    )
    assert authenticated.user.id == identity["user_id"]
    client = TestClient(application, client=("127.0.0.1", 51231))
    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
    return client


class _ProviderRuntime:
    """Capture safe provider syncs and allow one synthetic runtime failure."""

    def __init__(self) -> None:
        self.fail_next_sync = False
        self.syncs: list[tuple[str, dict[str, object]]] = []

    async def start(self) -> None:
        """Keep the test runtime in-process."""

    def status(self) -> dict[str, object]:
        """Report a healthy synthetic runtime to app lifecycle checks."""

        return {"status": "ready", "message": None}

    async def close(self) -> None:
        """Release no external resources."""

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        """Satisfy the assistant runtime protocol without retaining conversation state."""

        del conversation_id
        return True

    def sync_provider_configuration(
        self,
        provider_id: str,
        definition: dict[str, object],
        state: dict[str, object],
    ) -> None:
        """Fail before publishing state when the lifecycle test injects a sync error."""

        del definition
        if self.fail_next_sync:
            self.fail_next_sync = False
            raise RuntimeError("synthetic private runtime diagnostic")
        self.syncs.append((provider_id, dict(state)))


class _RevokingOAuthRuntime(_ProviderRuntime):
    """Supply synthetic native OAuth data and revoke its app session during handoff."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts: set[str] = set()
        self.cancelled: list[str] = []
        self.revoke_session: Any | None = None

    async def list_native_integrations(self) -> list[dict[str, object]]:
        """Advertise only the reviewed synthetic OpenAI OAuth method."""

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
        """Return the method's validated authorization shape without network access."""

        assert (integration_id, method_id) == ("openai", "chatgpt-headless")
        assert owner_id > 0 and len(session_id) == 32 and len(capability) == 32
        self.attempts.add(attempt_id)
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
        """Signal that the native side has one synthetic handoff ready."""

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
        """Return synthetic credentials, revoking the browser session before commit."""

        assert integration_id == "openai" and attempt_id in self.attempts
        assert owner_id > 0 and len(session_id) == 32
        assert self.revoke_session is not None
        self.revoke_session()
        return {
            "type": "oauth",
            "methodID": "chatgpt-headless",
            "access": "synthetic-access-token-lifecycle-r120",
            "refresh": "synthetic-refresh-token-lifecycle-r120",
            "expires": int((time.time() + 3600) * 1000),
            "metadata": {"accountID": "synthetic-account-lifecycle-r120"},
        }

    async def cancel_native_oauth(
        self,
        integration_id: str,
        attempt_id: str,
        *,
        owner_id: int,
        session_id: str,
    ) -> None:
        """Record release of the synthetic native attempt."""

        assert integration_id == "openai"
        assert owner_id > 0 and len(session_id) == 32
        self.cancelled.append(attempt_id)


def test_provider_http_rollback_survives_manager_recreation_and_removal(
    settings: Settings, tmp_path: Path
) -> None:
    """Keep the last committed provider credential when runtime sync rejects an update."""

    config = _auth_settings(settings, tmp_path)
    catalog = AssistantModelCatalog(config)
    vault_dir = tmp_path / "assistant-vault"
    manager = AssistantProviderManager(config, catalog, vault_dir=vault_dir)
    runtime = _ProviderRuntime()
    application = create_app(
        config,
        FixtureProvider(),
        lambda: datetime.now(UTC),
        assistant_runtime=runtime,
        assistant_catalog=catalog,
        assistant_providers=manager,
    )

    with TestClient(application, client=("127.0.0.1", 51232)):
        admin = _add_admin(application, 512_301)
        browser = _browser_client(application, admin)
        previous_secret = "synthetic-provider-key-before-r120"  # noqa: S105
        rejected_secret = "synthetic-provider-key-rejected-r120"  # noqa: S105
        try:
            saved = browser.put(
                "/api/v1/assistant/providers/openai",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={"credential": previous_secret},
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["provider"]["credential_configured"] is True
            assert previous_secret not in saved.text
            assert manager.credential_for_runtime("openai") == previous_secret
            assert runtime.syncs == [("openai", {})]

            runtime.fail_next_sync = True
            rejected = browser.put(
                "/api/v1/assistant/providers/openai",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={"credential": rejected_secret},
            )
            assert rejected.status_code == 422
            assert rejected.json()["error"]["code"] == "runtime_configuration_sync_failed"
            assert "synthetic private runtime diagnostic" not in rejected.text
            assert previous_secret not in rejected.text
            assert rejected_secret not in rejected.text
            assert manager.credential_for_runtime("openai") == previous_secret
            assert runtime.syncs == [("openai", {})]

            adopted_manager = AssistantProviderManager(config, catalog, vault_dir=vault_dir)
            adopted_manager.attach_runtime(runtime)
            application.state.assistant.providers = adopted_manager
            adopted = browser.get("/api/v1/assistant/providers")
            assert adopted.status_code == 200, adopted.text
            openai = next(
                row for row in adopted.json()["providers"] if row["provider_id"] == "openai"
            )
            assert openai["credential_configured"] is True
            assert adopted_manager.credential_for_runtime("openai") == previous_secret
            assert previous_secret not in adopted.text

            cleared = browser.delete(
                "/api/v1/assistant/providers/openai",
                headers={"x-csrf-token": str(admin["csrf"])},
            )
            assert cleared.status_code == 200, cleared.text
            cleared_openai = next(
                row for row in cleared.json()["providers"] if row["provider_id"] == "openai"
            )
            assert cleared_openai["credential_configured"] is False
            assert adopted_manager.credential_for_runtime("openai") is None
            assert runtime.syncs[-1] == ("openai", {})
            assert previous_secret not in cleared.text
            assert rejected_secret not in cleared.text
        finally:
            browser.close()


def test_custom_provider_http_endpoint_change_drops_endpoint_scoped_credential(
    settings: Settings, tmp_path: Path
) -> None:
    """Persist a reviewed custom endpoint and remove its key when the endpoint changes."""

    config = _auth_settings(settings, tmp_path)
    catalog = AssistantModelCatalog(config)
    manager = AssistantProviderManager(
        config,
        catalog,
        vault_dir=tmp_path / "assistant-vault",
    )
    runtime = _ProviderRuntime()
    application = create_app(
        config,
        FixtureProvider(),
        lambda: datetime.now(UTC),
        assistant_runtime=runtime,
        assistant_catalog=catalog,
        assistant_providers=manager,
    )

    with TestClient(application, client=("127.0.0.1", 51234)):
        admin = _add_admin(application, 512_303)
        browser = _browser_client(application, admin)
        secret = "synthetic-custom-endpoint-key-r120"  # noqa: S105
        first_endpoint = "https://first-model.example.test/v1"
        second_endpoint = "https://second-model.example.test/v1"
        policy = {
            "terms_url": "https://terms.example.test/policy",
            "privacy_disclosure": "Administrator review; privacy claims remain unverified.",
            "billing_disclosure": "Administrator review; pricing claims remain unverified.",
            "billing_class": "paid",
            "endpoint_policy_reviewed": True,
        }
        try:
            configured = browser.put(
                "/api/v1/assistant/providers/custom",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={**policy, "base_url": first_endpoint, "credential": secret},
            )
            assert configured.status_code == 200, configured.text
            first = configured.json()["provider"]
            assert first["selected_base_url"] == first_endpoint
            assert first["selected_terms_url"] == policy["terms_url"]
            assert first["selected_endpoint_policy_reviewed"] is True
            assert first["credential_configured"] is True
            assert secret not in configured.text
            assert secret not in manager._config_path.read_text(encoding="utf-8")
            assert manager.credential_for_runtime("custom") == secret
            first_runtime_state = runtime.syncs[-1][1]
            assert runtime.syncs[-1][0] == "custom"
            assert first_runtime_state["base_url"] == first_endpoint
            assert first_runtime_state["terms_url"] == policy["terms_url"]
            assert first_runtime_state["endpoint_policy_reviewed"] is True
            assert secret not in str(first_runtime_state)

            changed = browser.put(
                "/api/v1/assistant/providers/custom",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={**policy, "base_url": second_endpoint},
            )
            assert changed.status_code == 200, changed.text
            second = changed.json()["provider"]
            assert second["selected_base_url"] == second_endpoint
            assert second["selected_endpoint_policy_reviewed"] is True
            assert second["credential_configured"] is False
            assert manager.credential_for_runtime("custom") is None
            assert secret not in changed.text
            assert secret not in manager._config_path.read_text(encoding="utf-8")
            changed_runtime_state = runtime.syncs[-1][1]
            assert runtime.syncs[-1][0] == "custom"
            assert changed_runtime_state["base_url"] == second_endpoint
            assert changed_runtime_state["terms_url"] == policy["terms_url"]
            assert changed_runtime_state["endpoint_policy_reviewed"] is True
            assert "credential" not in changed_runtime_state
            assert secret not in str(changed_runtime_state)
        finally:
            browser.close()


def test_oauth_http_revocation_during_handoff_cancels_and_discards_credentials(
    settings: Settings, tmp_path: Path
) -> None:
    """A revoked admin session cannot persist credentials returned by native handoff."""

    config = _auth_settings(settings, tmp_path)
    catalog = AssistantModelCatalog(config)
    runtime = _RevokingOAuthRuntime()
    manager = AssistantProviderManager(
        config,
        catalog,
        vault_dir=tmp_path / "assistant-vault",
    )
    application = create_app(
        config,
        FixtureProvider(),
        lambda: datetime.now(UTC),
        assistant_runtime=runtime,
        assistant_catalog=catalog,
        assistant_providers=manager,
    )

    with TestClient(application, client=("127.0.0.1", 51233)):
        admin = _add_admin(application, 512_302)
        browser = _browser_client(application, admin)
        runtime.revoke_session = lambda: application.state.repository.auth_revoke_session(
            str(admin["token_hash"]),
            application.state.assistant.now().replace(microsecond=0).isoformat(),
        )
        credential_path = manager._oauth_credential_path(
            "openai", int(admin["user_id"]), "chatgpt-headless"
        )
        try:
            started = browser.post(
                "/api/v1/assistant/providers/oauth/attempts",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={"provider_id": "openai", "method_id": "chatgpt-headless"},
            )
            assert started.status_code == 200, started.text
            attempt_id = str(started.json()["attempt"]["attempt_id"])

            completed = browser.post(
                f"/api/v1/assistant/providers/oauth/attempts/{attempt_id}/complete",
                headers={"x-csrf-token": str(admin["csrf"])},
                json={},
            )
            assert completed.status_code == 403
            assert completed.json()["error"]["code"] == "oauth_authorization_required"
            assert "synthetic-access-token-lifecycle-r120" not in completed.text
            assert "synthetic-refresh-token-lifecycle-r120" not in completed.text
            assert "synthetic-account-lifecycle-r120" not in completed.text
            assert not credential_path.exists()
            assert manager._oauth_attempts[attempt_id].status == "cancelled"
            assert manager._oauth_attempts[attempt_id].transport_capability is None
            assert attempt_id in runtime.cancelled
            assert asyncio.run(
                manager.list_native_oauth_connections(owner_id=int(admin["user_id"]))
            ) == ()
        finally:
            browser.close()
