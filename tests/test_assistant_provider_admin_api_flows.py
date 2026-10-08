"""Public HTTP control-flow checks for assistant provider administration."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from stock_probs.api import create_app
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

_MODEL_ID = "fixture-provider/r120-admin-flow"
_UNREVIEWED_MODEL_ID = "fixture-unreviewed/r120-admin-flow"
_MODEL_REVISION = 4
_NOW = datetime.now(UTC)


def _now() -> datetime:
    """Return the same live clock used by repository auth and route checks."""

    return datetime.now(UTC)


def _auth_settings(settings: Settings) -> Settings:
    """Enable the normal authenticated assistant routes with test-only OAuth values."""

    return replace(
        settings,
        environment="test",
        auth_mode="github",
        auth_session_secret="synthetic-admin-api-session-secret-not-production-000000",  # noqa: S106
        auth_public_origin="http://testserver",
        auth_session_idle_seconds=86_400,
        github_client_id="synthetic-client-id",
        github_client_secret="synthetic-client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
    )


def _model_row(
    model_id: str = _MODEL_ID,
    *,
    provider_id: str = "fixture-provider",
    enabled: bool = True,
    usable: bool = True,
) -> dict[str, object]:
    """Return a synthetic maintained-catalog row suitable for policy routes."""

    return {
        "model_id": model_id,
        "provider_id": provider_id,
        "native_provider_id": provider_id,
        "display_name": "Synthetic admin-flow model",
        "available": True,
        "free": True,
        "training": False,
        "terms_url": "https://models.example.test/terms",
        "terms_reviewed_at": "2026-10-01",
        "policy_version": "synthetic-policy-r1",
        "disclosure": "Synthetic test model; no upstream service is used.",
        "data_collection_allowed": False,
        "data_collection_default": False,
        "privacy_policy_version": "synthetic-privacy-r1",
        "privacy_disclosure": "Synthetic privacy disclosure.",
        "billing_class": "free",
        "billing_policy_version": "synthetic-billing-r1",
        "cost_disclosure": "Synthetic fixture; no charge.",
        "acknowledged_privacy_policy_version": "synthetic-privacy-r1",
        "acknowledged_billing_policy_version": "synthetic-billing-r1",
        "enabled": enabled,
        "usable": usable,
        "revision": _MODEL_REVISION,
    }


class _Catalog:
    """Serve fixed, synthetic models without provider discovery."""

    def list_models(self) -> list[dict[str, object]]:
        return [
            _model_row(),
            _model_row(
                _UNREVIEWED_MODEL_ID,
                provider_id="fixture-unreviewed",
                enabled=False,
                usable=False,
            ),
        ]


class _Runtime:
    """Provide the app lifecycle seam without starting a worker."""

    async def start(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"status": "ready", "message": None}

    async def close(self) -> None:
        return None

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        del conversation_id
        return True


class _ProviderFailure(Exception):
    """Carry the same stable manager code that the public API maps safely."""

    def __init__(self, code: str) -> None:
        super().__init__("synthetic private provider diagnostic")
        self.code = code


class _ProviderAdminManager:
    """Capture admin writes and validation without network or vault access."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.vault_writes = 0
        self.provider_probes = 0
        self.row: dict[str, object] = {
            "provider_id": "openai",
            "display_name": "Synthetic OpenAI-compatible provider",
            "auth_methods": ["api_key"],
            "selected_model_id": None,
            "selected_base_url": "https://provider.example/v1",
            "credential_required": True,
            "credential_configured": False,
            "connection_status": "unconfigured",
            "private_credential": "synthetic-provider-response-secret",
            "native_settings": {"authorization": "synthetic-native-secret"},
        }

    def update_provider(
        self,
        provider_id: str,
        *,
        model_id: str | None = None,
        base_url: str | None = None,
        credential: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(("update", provider_id))
        if provider_id != "openai":
            raise _ProviderFailure("provider_adapter_unsupported")
        if credential is not None:
            self.vault_writes += 1
        self.row.update(
            {
                "selected_model_id": model_id or self.row["selected_model_id"],
                "selected_base_url": base_url or self.row["selected_base_url"],
                "credential_configured": credential is not None
                or self.row["credential_configured"],
            }
        )
        return {
            **self.row,
            "credential": "synthetic-provider-response-secret",
            "runtime_settings": {"credential": "synthetic-native-secret"},
        }

    def list_providers(self) -> list[dict[str, object]]:
        return [dict(self.row)]

    async def validate(
        self,
        provider_id: str,
        *,
        authorization_check: object | None = None,
    ) -> dict[str, object]:
        if callable(authorization_check) and authorization_check() is not True:
            raise _ProviderFailure("oauth_authorization_required")
        self.calls.append(("validate", provider_id))
        if provider_id != "openai":
            raise _ProviderFailure("provider_adapter_unsupported")
        self.provider_probes += 1
        started = getattr(self, "validation_started", None)
        release = getattr(self, "validation_release", None)
        if isinstance(started, threading.Event) and isinstance(release, threading.Event):
            started.set()
            if not await asyncio.to_thread(release.wait, 5):
                raise RuntimeError("held provider response timed out")
        return {
            **self.row,
            "connection_status": "ready",
            "credential": "synthetic-provider-response-secret",
        }


class _PolicyManager:
    """Model-policy fixture with revision CAS and adapter-approval behavior."""

    def __init__(self) -> None:
        self.states = {
            _MODEL_ID: _model_row(),
            _UNREVIEWED_MODEL_ID: _model_row(
                _UNREVIEWED_MODEL_ID,
                provider_id="fixture-unreviewed",
                enabled=False,
                usable=False,
            ),
        }
        self.calls: list[tuple[str, int]] = []

    def model_policy_state(
        self, model_id: str, *, owner_id: int | None = None
    ) -> dict[str, object] | None:
        del owner_id
        state = self.states.get(model_id)
        return dict(state) if state is not None else None

    def update_model_policy(
        self,
        model_id: str,
        *,
        enabled: bool,
        acknowledged_privacy_policy_version: str | None,
        acknowledged_billing_policy_version: str | None,
        expected_revision: int,
        owner_id: int,
    ) -> dict[str, object]:
        self.calls.append((model_id, expected_revision))
        current = self.states[model_id]
        if expected_revision != current["revision"]:
            raise _ProviderFailure("model_policy_conflict")
        if model_id == _UNREVIEWED_MODEL_ID and enabled:
            raise _ProviderFailure("provider_adapter_unsupported")
        current.update(
            {
                "enabled": enabled,
                "usable": enabled,
                "revision": expected_revision + 1,
                "acknowledged_privacy_policy_version": acknowledged_privacy_policy_version,
                "acknowledged_billing_policy_version": acknowledged_billing_policy_version,
            }
        )
        return {
            "model_id": model_id,
            "enabled": enabled,
            "usable": enabled,
            "revision": expected_revision + 1,
            "private_credential": "synthetic-policy-secret",
        }


class _OpenCodeReviewManager:
    """Expose owner-bound synthetic rows and CAS-clear behavior through HTTP."""

    def __init__(self) -> None:
        self.clears: list[tuple[str, int, int]] = []
        self.rows: dict[int, dict[str, object]] = {}

    def _row(self, owner_id: int) -> dict[str, object]:
        return self.rows.setdefault(
            owner_id,
            {
                "model_id": f"opencode-console/{owner_id:064x}",
                "provider_id": "opencode-console",
                "display_name": "Synthetic owner console model",
                "native_model_id": f"synthetic-model-{owner_id}",
                "adapter_id": "openai-responses",
                "protocol": "openai-responses",
                "package_id": "@opencode/ai/providers/openai",
                "endpoint": "https://api.openai.com/v1",
                "available": True,
                "enabled": False,
                "reviewed": True,
                "billing_class": "unknown",
                "training_policy": "unknown",
                "confidential_data_policy": "unknown",
                "terms_url": "https://example.org/terms",
                "privacy_disclosure": "Synthetic reviewed privacy statement.",
                "billing_disclosure": "Synthetic billing statement.",
                "privacy_policy_version": "synthetic-privacy-r1",
                "billing_policy_version": "synthetic-billing-r1",
                "revision": 1,
                "review_revision": 5,
                "usable": False,
                "availability_reason": "model_policy_review_required",
                "config_fingerprint": "a" * 64,
                "native_settings": {"headers": {"authorization": "synthetic-never-return"}},
            },
        )

    async def ensure_opencode_model_inventory(
        self, *, owner_id: int, authorization_check
    ) -> tuple[dict[str, object], ...]:
        assert authorization_check() is True
        return (dict(self._row(owner_id)),)

    async def clear_opencode_model_review(
        self,
        model_id: str,
        *,
        owner_id: int,
        expected_revision: int,
        authorization_check,
    ) -> bool:
        row = self._row(owner_id)
        self.clears.append((model_id, owner_id, expected_revision))
        assert authorization_check() is True
        if model_id != row["model_id"]:
            raise _ProviderFailure("model_unavailable")
        if expected_revision != row["review_revision"]:
            raise _ProviderFailure("model_policy_conflict")
        row.update(
            {
                "reviewed": False,
                "review_revision": expected_revision + 1,
                "terms_url": None,
                "privacy_disclosure": None,
                "billing_disclosure": None,
                "usable": False,
            }
        )
        return True


class _OAuthFailure(Exception):
    """Carry one native OAuth manager code without retaining callback details."""

    def __init__(self, code: str) -> None:
        super().__init__("synthetic OAuth manager diagnostic")
        self.code = code


class _NativeOAuthManager:
    """Keep a synthetic callback attempt bound to its creating owner and session."""

    def __init__(self) -> None:
        self.binding: tuple[int, str] | None = None
        self.attempt_id = "d" * 32
        self.status = "pending"
        self.callback_owners: list[tuple[int, str]] = []
        self.cancel_owners: list[tuple[int, str]] = []
        self.provider_egress = 0
        self.vault_writes = 0

    def _attempt(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "integration_id": "openai",
            "method_id": "chatgpt-browser",
            "status": self.status,
            "mode": "browser",
            "expires_at": datetime.now(UTC).timestamp() + 300,
            "authorization_url": None,
            "instructions": None,
            "native_attempt_id": "synthetic-native-id-must-not-escape",
            "callback_state": "synthetic-state-must-not-escape",
            "credential": {"access": "synthetic-access-must-not-escape"},
        }

    async def begin_native_oauth(
        self,
        provider_id: str,
        method_id: str,
        *,
        owner_id: int,
        session_id: str,
        session_token_hash: str,
    ) -> dict[str, object]:
        assert (provider_id, method_id) == ("openai", "chatgpt-browser")
        assert len(session_token_hash) == 64
        self.binding = (owner_id, session_id)
        self.status = "pending"
        return self._attempt()

    async def submit_native_oauth_callback(
        self, attempt_id: str, *, owner_id: int, session_id: str, callback_url: str
    ) -> dict[str, object]:
        self.callback_owners.append((owner_id, session_id))
        if attempt_id != self.attempt_id or self.binding != (owner_id, session_id):
            raise _OAuthFailure("oauth_attempt_not_found")
        assert "synthetic-code" in callback_url
        self.status = "handoff_ready"
        return self._attempt()

    async def cancel_native_oauth(
        self, attempt_id: str, *, owner_id: int, session_id: str
    ) -> dict[str, object]:
        self.cancel_owners.append((owner_id, session_id))
        if attempt_id != self.attempt_id or self.binding != (owner_id, session_id):
            raise _OAuthFailure("oauth_attempt_not_found")
        self.status = "cancelled"
        return self._attempt()


class _StreamProviders:
    """Provide an inert provider transport for repository-backed event replay."""

    async def proxy_chat_completion(
        self, *_args: object, **_kwargs: object
    ) -> AsyncIterator[bytes]:
        yield b"data: [DONE]\n\n"


def _create_app(settings: Settings, providers: object, catalog: object | None = None):
    return create_app(
        _auth_settings(settings),
        FixtureProvider(),
        _now,
        assistant_runtime=_Runtime(),
        assistant_catalog=catalog or _Catalog(),
        assistant_providers=providers,
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _add_identity(
    app: object,
    github_id: int,
    *,
    role: str = "member",
    recent_step_up: bool = True,
) -> dict[str, str | int]:
    repository = app.state.repository
    now = app.state.assistant.now().replace(microsecond=0)
    user = repository.auth_create_user(
        {
            "github_id": github_id,
            "github_login": f"synthetic-user-{github_id}",
            "display_name": f"Synthetic user {github_id}",
            "role": role,
            "status": "active",
            "created_at": now,
        }
    )
    user_id = int(user["id"])
    with repository.connect() as connection:
        factor = connection.execute(
            """INSERT INTO totp_factors
            (user_id, secret_ciphertext, created_at, confirmed_at,
             last_accepted_step, updated_at)
            VALUES (?, ?, ?, ?, -1, ?)""",
            (
                user_id,
                "synthetic-ciphertext-only-test-material",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        factor_id = int(factor.lastrowid)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        session_id = secrets.token_hex(16)
        expires = now + timedelta(hours=23)
        proof_time = now if recent_step_up else now - timedelta(minutes=15)
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
                proof_time.isoformat(),
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


def _browser(app: object, identity: dict[str, str | int]) -> TestClient:
    client = TestClient(app, client=("127.0.0.1", 52120))
    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
    return client


def _csrf(identity: dict[str, str | int]) -> dict[str, str]:
    return {"x-csrf-token": str(identity["csrf"])}


def _change_admin_authorization(app: object, identity: dict[str, str | int], change: str) -> None:
    """Revoke, demote, or expire one admin session using the disposable test repository."""

    repository = app.state.repository
    if change == "revoked":
        repository.auth_revoke_session(
            str(identity["token_hash"]), app.state.assistant.now().isoformat()
        )
    elif change == "demoted":
        repository.auth_update_user(int(identity["user_id"]), {"role": "member"})
    elif change == "step_up_expired":
        stale_proof = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
        with repository.connect() as connection:
            connection.execute(
                "UPDATE sessions SET mfa_verified_at = ? WHERE token_hash = ?",
                (stale_proof, str(identity["token_hash"])),
            )
            connection.commit()
    else:
        raise AssertionError(f"unknown authorization change: {change}")


def test_provider_write_routes_require_current_admin_and_mask_manager_secrets(settings: Settings):
    providers = _ProviderAdminManager()
    application = _create_app(settings, providers)
    with TestClient(application, client=("127.0.0.1", 52121)):
        admin = _add_identity(application, 810_101, role="admin")
        stale_admin = _add_identity(application, 810_102, role="admin", recent_step_up=False)
        demoted_admin = _add_identity(application, 810_103, role="admin")
        revoked_admin = _add_identity(application, 810_104, role="admin")
        member = _add_identity(application, 810_105)
        application.state.repository.auth_update_user(
            int(demoted_admin["user_id"]), {"role": "member"}
        )
        application.state.repository.auth_revoke_session(
            str(revoked_admin["token_hash"]), application.state.assistant.now().isoformat()
        )
        clients = [
            _browser(application, item)
            for item in (admin, stale_admin, demoted_admin, revoked_admin, member)
        ]
        fresh, stale, demoted, revoked, non_admin = clients
        settings_body = {
            "model_id": "openai/synthetic-r120-model",
            "base_url": "https://provider.example/v1",
            "credential": "synthetic-provider-request-secret",
        }
        update_path = "/api/v1/assistant/providers/openai"
        validate_path = "/api/v1/assistant/providers/openai/validate"
        try:
            assert (
                stale.put(update_path, headers=_csrf(stale_admin), json=settings_body).status_code
                == 403
            )
            assert (
                demoted.post(validate_path, headers=_csrf(demoted_admin), json={}).status_code
                == 403
            )
            assert (
                revoked.put(
                    update_path, headers=_csrf(revoked_admin), json=settings_body
                ).status_code
                == 401
            )
            assert (
                non_admin.put(update_path, headers=_csrf(member), json=settings_body).status_code
                == 403
            )
            assert fresh.put(update_path, json=settings_body).status_code == 403
            assert providers.calls == []

            unsafe_endpoint = fresh.put(
                update_path,
                headers=_csrf(admin),
                json={**settings_body, "base_url": "https://127.0.0.1/v1"},
            )
            assert unsafe_endpoint.status_code == 422
            assert providers.calls == []

            unreviewed_adapter = fresh.put(
                "/api/v1/assistant/providers/unreviewed-adapter",
                headers=_csrf(admin),
                json={"credential": "synthetic-provider-request-secret"},
            )
            assert unreviewed_adapter.status_code == 422
            assert unreviewed_adapter.json()["error"]["code"] == "provider_adapter_unsupported"
            assert "synthetic private provider diagnostic" not in unreviewed_adapter.text
            assert providers.vault_writes == 0
            assert providers.provider_probes == 0

            saved = fresh.put(update_path, headers=_csrf(admin), json=settings_body)
            assert saved.status_code == 200, saved.text
            assert saved.json()["provider"]["provider_id"] == "openai"
            assert saved.json()["provider"]["selected_model_id"] == settings_body["model_id"]
            assert saved.json()["provider"]["credential_configured"] is True
            assert "synthetic-provider-request-secret" not in saved.text
            assert "synthetic-provider-response-secret" not in saved.text
            assert "synthetic-native-secret" not in saved.text
            assert "native_settings" not in saved.text
            assert providers.vault_writes == 1

            body_rejected = fresh.post(
                validate_path,
                headers=_csrf(admin),
                json={"credential": "synthetic-provider-request-secret"},
            )
            assert body_rejected.status_code == 422
            assert providers.provider_probes == 0

            validated = fresh.post(validate_path, headers=_csrf(admin), json={})
            assert validated.status_code == 200, validated.text
            assert validated.json()["provider"]["connection_status"] == "ready"
            assert "synthetic-provider-response-secret" not in validated.text
            assert "synthetic-native-secret" not in validated.text
            assert providers.provider_probes == 1
        finally:
            for client in clients:
                client.close()


@pytest.mark.parametrize("hold", ("body", "provider_response"))
@pytest.mark.parametrize("authorization_change", ("revoked", "demoted", "step_up_expired"))
def test_provider_validation_rechecks_admin_step_up_after_awaits(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, hold: str, authorization_change: str
) -> None:
    """A stale admin cannot finish validation after body or provider-response waits."""

    providers = _ProviderAdminManager()
    application = _create_app(settings, providers)
    if hold == "body":
        client_app = application
        body_received = threading.Event()
        release_body = threading.Event()
        providers.validation_started = None
        providers.validation_release = None

        original_body = Request.body

        async def held_request_body(request: Request) -> bytes:
            if request.url.path == "/api/v1/assistant/providers/openai/validate":
                body_received.set()
                if not await asyncio.to_thread(release_body.wait, 5):
                    raise RuntimeError("held request body timed out")
            return await original_body(request)

        monkeypatch.setattr(Request, "body", held_request_body)
    else:
        client_app = application
        body_received = None
        release_body = None
        providers.validation_started = threading.Event()
        providers.validation_release = threading.Event()

    with TestClient(client_app, client=("127.0.0.1", 52123)):
        admin = _add_identity(application, 810_109, role="admin")
        client = _browser(client_app, admin)
        release = release_body or providers.validation_release
        started = body_received or providers.validation_started
        assert isinstance(release, threading.Event)
        assert isinstance(started, threading.Event)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    client.post,
                    "/api/v1/assistant/providers/openai/validate",
                    headers=_csrf(admin),
                    json={},
                )
                assert started.wait(timeout=3), "validation did not reach the held await"
                _change_admin_authorization(application, admin, authorization_change)
                release.set()
                response = pending.result(timeout=5)

            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "oauth_authorization_required"
            assert providers.provider_probes == (0 if hold == "body" else 1)
        finally:
            release.set()
            client.close()


def test_model_policy_route_uses_revision_cas_and_rejects_unreviewed_adapter_enable(
    settings: Settings,
):
    providers = _PolicyManager()
    application = _create_app(settings, providers)
    with TestClient(application, client=("127.0.0.1", 52122)):
        admin = _add_identity(application, 810_111, role="admin")
        stale_admin = _add_identity(application, 810_112, role="admin", recent_step_up=False)
        member = _add_identity(application, 810_113)
        clients = [_browser(application, item) for item in (admin, stale_admin, member)]
        fresh, stale, non_admin = clients
        path = f"/api/v1/assistant/models/{quote(_MODEL_ID, safe='')}/policy"
        expected_body = {
            "enabled": False,
            "acknowledged_privacy_policy_version": None,
            "acknowledged_billing_policy_version": None,
            "expected_revision": _MODEL_REVISION,
        }
        try:
            assert (
                stale.put(path, headers=_csrf(stale_admin), json=expected_body).status_code == 403
            )
            assert non_admin.put(path, headers=_csrf(member), json=expected_body).status_code == 403
            assert providers.calls == []

            stale_revision = fresh.put(
                path,
                headers=_csrf(admin),
                json={**expected_body, "expected_revision": _MODEL_REVISION - 1},
            )
            assert stale_revision.status_code == 409
            assert stale_revision.json()["error"]["code"] == "model_policy_conflict"
            assert providers.states[_MODEL_ID]["revision"] == _MODEL_REVISION
            assert providers.states[_MODEL_ID]["enabled"] is True

            disabled = fresh.put(path, headers=_csrf(admin), json=expected_body)
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["model"]["model_id"] == _MODEL_ID
            assert disabled.json()["model"]["enabled"] is False
            assert disabled.json()["model"]["revision"] == _MODEL_REVISION + 1
            assert "synthetic-policy-secret" not in disabled.text
            assert providers.states[_MODEL_ID]["enabled"] is False

            unreviewed_path = (
                f"/api/v1/assistant/models/{quote(_UNREVIEWED_MODEL_ID, safe='')}/policy"
            )
            unreviewed = fresh.put(
                unreviewed_path,
                headers=_csrf(admin),
                json={
                    "enabled": True,
                    "acknowledged_privacy_policy_version": "synthetic-privacy-r1",
                    "acknowledged_billing_policy_version": "synthetic-billing-r1",
                    "expected_revision": _MODEL_REVISION,
                },
            )
            assert unreviewed.status_code == 422
            assert unreviewed.json()["error"]["code"] == "provider_adapter_unsupported"
            assert providers.states[_UNREVIEWED_MODEL_ID]["enabled"] is False
            assert providers.states[_UNREVIEWED_MODEL_ID]["revision"] == _MODEL_REVISION
        finally:
            for client in clients:
                client.close()


def test_opencode_model_review_delete_is_admin_owner_and_revision_bound(settings: Settings):
    providers = _OpenCodeReviewManager()
    application = _create_app(settings, providers)
    with TestClient(application, client=("127.0.0.1", 52123)):
        admin = _add_identity(application, 810_121, role="admin")
        other_admin = _add_identity(application, 810_122, role="admin")
        member = _add_identity(application, 810_123)
        clients = [_browser(application, item) for item in (admin, other_admin, member)]
        owner, other_owner, non_admin = clients
        model_id = str(providers._row(int(admin["user_id"]))["model_id"])
        path = f"/api/v1/assistant/providers/opencode/models/{quote(model_id, safe='')}/review"
        try:
            denied_member = non_admin.delete(
                path,
                headers=_csrf(member),
                params={"expected_revision": 5},
            )
            assert denied_member.status_code == 403
            assert providers.clears == []

            missing_csrf = owner.delete(path, params={"expected_revision": 5})
            assert missing_csrf.status_code == 403
            assert providers.clears == []

            cross_owner = other_owner.delete(
                path,
                headers=_csrf(other_admin),
                params={"expected_revision": 5},
            )
            assert cross_owner.status_code == 404
            assert providers.clears == []

            stale = owner.delete(
                path,
                headers=_csrf(admin),
                params={"expected_revision": 4},
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "model_policy_conflict"
            assert providers._row(int(admin["user_id"]))["reviewed"] is True

            cleared = owner.delete(
                path,
                headers=_csrf(admin),
                params={"expected_revision": 5},
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json() == {
                "model_id": model_id,
                "reviewed": False,
                "usable": False,
            }
            assert providers._row(int(admin["user_id"]))["review_revision"] == 6
            assert "synthetic-never-return" not in cleared.text
            assert providers.clears == [
                (model_id, int(admin["user_id"]), 4),
                (model_id, int(admin["user_id"]), 5),
            ]
        finally:
            for client in clients:
                client.close()


def test_native_oauth_callback_and_cancel_are_bound_to_fresh_owner_session(settings: Settings):
    providers = _NativeOAuthManager()
    application = _create_app(settings, providers)
    with TestClient(application, client=("127.0.0.1", 52124)):
        owner = _add_identity(application, 810_131, role="admin")
        other_admin = _add_identity(application, 810_132, role="admin")
        stale_admin = _add_identity(application, 810_133, role="admin", recent_step_up=False)
        clients = [_browser(application, item) for item in (owner, other_admin, stale_admin)]
        owner_browser, other_browser, stale_browser = clients
        attempts_path = "/api/v1/assistant/providers/oauth/attempts"
        callback_url = "http://localhost:1455/auth/callback?code=synthetic-code&state=opaque-state"
        try:
            denied_begin = stale_browser.post(
                attempts_path,
                headers=_csrf(stale_admin),
                json={"provider_id": "openai", "method_id": "chatgpt-browser"},
            )
            assert denied_begin.status_code == 403
            assert providers.binding is None

            begun = owner_browser.post(
                attempts_path,
                headers=_csrf(owner),
                json={"provider_id": "openai", "method_id": "chatgpt-browser"},
            )
            assert begun.status_code == 200, begun.text
            attempt_id = begun.json()["attempt"]["attempt_id"]
            callback_path = f"{attempts_path}/{attempt_id}/callback"
            cancel_path = f"{attempts_path}/{attempt_id}"

            cross_user_callback = other_browser.post(
                callback_path,
                headers=_csrf(other_admin),
                json={"callback_url": callback_url},
            )
            assert cross_user_callback.status_code == 404
            assert providers.status == "pending"
            assert providers.vault_writes == 0
            assert providers.provider_egress == 0

            cross_user_cancel = other_browser.delete(
                cancel_path,
                headers=_csrf(other_admin),
            )
            assert cross_user_cancel.status_code == 404
            assert providers.status == "pending"
            assert providers.vault_writes == 0

            stale_callback = stale_browser.post(
                callback_path,
                headers=_csrf(stale_admin),
                json={"callback_url": callback_url},
            )
            assert stale_callback.status_code == 403
            assert providers.status == "pending"

            accepted = owner_browser.post(
                callback_path,
                headers=_csrf(owner),
                json={"callback_url": callback_url},
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["attempt"]["status"] == "handoff_ready"
            assert "synthetic-code" not in accepted.text
            assert "opaque-state" not in accepted.text
            assert "synthetic-access-must-not-escape" not in accepted.text

            cancelled = owner_browser.delete(cancel_path, headers=_csrf(owner))
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["attempt"]["status"] == "cancelled"
            assert providers.status == "cancelled"
            assert providers.vault_writes == 0
            assert providers.provider_egress == 0
            assert providers.callback_owners == [
                (int(other_admin["user_id"]), str(other_admin["session_id"])),
                (int(owner["user_id"]), str(owner["session_id"])),
            ]
            assert providers.cancel_owners == [
                (int(other_admin["user_id"]), str(other_admin["session_id"])),
                (int(owner["user_id"]), str(owner["session_id"])),
            ]
        finally:
            for client in clients:
                client.close()


def test_active_event_stream_stops_before_emitting_after_session_revocation(
    settings: Settings, monkeypatch
):
    application = _create_app(settings, _StreamProviders())
    with TestClient(application, client=("127.0.0.1", 52125)):
        owner = _add_identity(application, 810_141)
        context_browser = _browser(application, owner)
        try:
            context_response = context_browser.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            )
            assert context_response.status_code == 200, context_response.text
            context = context_response.json()["context"]
            assistant = application.state.assistant
            now = assistant.now()
            conversation = assistant.storage.create_conversation(
                int(owner["user_id"]),
                title="Synthetic stream revocation",
                context=context,
                context_version=str(context["context_version"]),
                created_at=now,
            )
            policy = assistant.policy(_MODEL_ID)
            assistant.storage.create_consent(
                int(owner["user_id"]),
                model_id=_MODEL_ID,
                policy_version=policy.policy_version,
                accepted_terms=True,
                data_collection_opt_in=False,
                recorded_at=now,
            )
            capability = secrets.token_urlsafe(32)
            turn = assistant.storage.create_turn(
                int(owner["user_id"]),
                str(conversation["conversation"]["id"]),
                prompt="Synthetic bounded stream fixture.",
                model_id=_MODEL_ID,
                policy_version=policy.policy_version,
                context=context,
                context_version=str(context["context_version"]),
                session_id=str(owner["session_id"]),
                session_token_hash=str(owner["token_hash"]),
                capability=capability,
                now=now,
                expires_at=now + timedelta(seconds=120),
            )
            assistant.storage.set_turn_status(
                int(owner["user_id"]),
                str(conversation["conversation"]["id"]),
                str(turn["id"]),
                status="running",
                now=now,
            )
            assistant.storage.set_turn_status(
                int(owner["user_id"]),
                str(conversation["conversation"]["id"]),
                str(turn["id"]),
                status="completed",
                now=now,
            )
            assistant.storage.append_event(
                int(owner["user_id"]),
                str(conversation["conversation"]["id"]),
                str(turn["id"]),
                event_type="token",
                data={"text": "first synthetic chunk"},
                now=now,
            )
            assistant.storage.append_event(
                int(owner["user_id"]),
                str(conversation["conversation"]["id"]),
                str(turn["id"]),
                event_type="token",
                data={"text": "must not stream after revocation"},
                now=now,
            )
            events_path = (
                f"/api/v1/assistant/conversations/{conversation['conversation']['id']}"
                f"/turns/{turn['id']}/events"
            )
            timeline: list[str] = []
            projected_events: list[tuple[int, dict[str, object]]] = []
            original_project = assistant.project_event_for_browser

            def revoke_after_first_projection(auth, event):
                projected = original_project(auth, event)
                sequence = int(event["sequence"])
                projected_events.append((sequence, dict(projected["data"])))
                timeline.append(f"project:{sequence}")
                if sequence == 1:
                    application.state.repository.auth_revoke_session(
                        str(owner["token_hash"]), assistant.now().isoformat()
                    )
                    session = application.state.repository.auth_get_session(
                        str(owner["token_hash"])
                    )
                    timeline.append(
                        "repository-revoke:committed"
                        if session is not None and session.get("revoked_at") is not None
                        else "repository-revoke:missing"
                    )
                return projected

            browser = _browser(application, owner)
            try:
                with monkeypatch.context() as scoped:
                    scoped.setattr(
                        assistant,
                        "project_event_for_browser",
                        revoke_after_first_projection,
                    )
                    response = browser.get(events_path, params={"after": 0})
                assert response.status_code == 200, response.text
                assert response.content == (
                    b'id: 1\nevent: token\ndata: {"text":"first synthetic chunk"}\n\n'
                )
                assert projected_events == [(1, {"text": "first synthetic chunk"})]
                assert timeline == ["project:1", "repository-revoke:committed"]
                session_record = application.state.repository.auth_get_session(
                    str(owner["token_hash"])
                )
                assert session_record is not None
                assert session_record["revoked_at"] is not None
                denied = browser.get("/api/v1/assistant/context", params={"route": "/overview"})
                assert denied.status_code == 401
            finally:
                browser.close()
        finally:
            context_browser.close()
