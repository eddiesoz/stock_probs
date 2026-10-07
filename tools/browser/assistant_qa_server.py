"""Loopback-only FastAPI fixture for assistant route and persistence browser checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

from stock_probs.api import create_app
from stock_probs.assistant.schemas import AssistantModelPolicy, AssistantTurnResult
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "stock_probs"
    / "assistant"
    / "assistant_catalog.json"
)
_CATALOG = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
_ZEN = _CATALOG["zen"]
_ELIGIBLE_ZEN_MODELS = sorted(
    (
        (model_id, model)
        for model_id, model in _ZEN["reviewed_models"].items()
        if model.get("available") is True
        and model.get("free") is True
        and model.get("training") is False
        and model.get("data_collection_allowed") is False
        and model.get("data_collection_default") is False
        and model.get("route") == "openai-compatible"
    ),
    key=lambda item: item[0],
)
if not _ELIGIBLE_ZEN_MODELS:
    raise RuntimeError("The maintained catalog has no eligible synthetic browser model.")
_ZEN_MODEL_KEY, _ZEN_MODEL = _ELIGIBLE_ZEN_MODELS[0]
_MODEL_ID = f"{_ZEN['provider_id']}/{_ZEN_MODEL_KEY}"
_MODEL_POLICY_VERSION = str(_ZEN["policy_version"])
_BILLING_POLICY_VERSION = str(
    _ZEN_MODEL.get("billing_policy_version", _ZEN["billing_policy_version"])
)
_MODEL = AssistantModelPolicy(
    model_id=_MODEL_ID,
    provider_id=str(_ZEN["provider_id"]),
    display_name=f"Synthetic QA / {_ZEN_MODEL['display_name']}",
    available=bool(_ZEN_MODEL["available"]),
    free=bool(_ZEN_MODEL["free"]),
    training=bool(_ZEN_MODEL["training"]),
    terms_url=str(_ZEN["terms_url"]),
    terms_reviewed_at=str(_ZEN["terms_reviewed_at"]),
    policy_version=_MODEL_POLICY_VERSION,
    disclosure="Synthetic browser QA output. No external model is called.",
    data_collection_allowed=bool(_ZEN_MODEL["data_collection_allowed"]),
    data_collection_default=bool(_ZEN_MODEL["data_collection_default"]),
)

# Fixed, non-secret values exist only in this disposable test server process and database.
_SESSION = "browser-assistant-fixture-session-not-a-production-credential"
_CSRF = "browser-assistant-fixture-csrf-token-not-a-production-credential"
_GITHUB_ID = 120120120
_EVENT_STREAM_PATH = re.compile(
    r"^/api/v1/assistant/conversations/[^/]+/turns/[^/]+/events$"
)


class _AssistantStreamAudit:
    """Capture bounded synthetic-fixture SSE completion facts without body content."""

    def __init__(self, application, records):
        self.application = application
        self.records = records

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "GET"
            or not _EVENT_STREAM_PATH.fullmatch(scope.get("path", ""))
        ):
            await self.application(scope, receive, send)
            return

        response_status = None
        body_bytes = 0
        complete_event_seen = False
        body_tail = b""
        body_ended = False

        async def capture(message):
            nonlocal response_status, body_bytes, complete_event_seen, body_tail, body_ended
            if message.get("type") == "http.response.start":
                response_status = message.get("status")
            elif message.get("type") == "http.response.body":
                body = message.get("body", b"")
                body_bytes += len(body)
                body_tail = body_tail + body
                complete_event_seen = complete_event_seen or b"event: complete" in body_tail
                body_tail = body_tail[-32:]
                body_ended = not message.get("more_body", False)
            await send(message)

        error_class = None
        try:
            await self.application(scope, receive, capture)
        except Exception as error:
            error_class = type(error).__name__
            raise
        finally:
            self.records.append({
                "path": scope.get("path", ""),
                "status": response_status,
                "body_bytes": body_bytes,
                "complete_event": complete_event_seen,
                "body_end": body_ended,
                "error": error_class,
            })
            del self.records[:-10]


class _Catalog:
    def list_models(self):
        return [_MODEL]


class _Providers:
    def model_policy_state(self, model_id: str, *, owner_id: int | None = None):
        del owner_id
        if model_id != _MODEL.model_id:
            return None
        return {
            "enabled": True,
            "usable": True,
            "native_provider_id": "assistant-proxy",
            "privacy_policy_version": _MODEL_POLICY_VERSION,
            "acknowledged_privacy_policy_version": _MODEL_POLICY_VERSION,
            "billing_class": "free",
            "billing_policy_version": _BILLING_POLICY_VERSION,
            "acknowledged_billing_policy_version": _BILLING_POLICY_VERSION,
            "policy_version": _MODEL.policy_version,
            "revision": 1,
            "availability_reason": None,
        }

    async def proxy_chat_completion(self, provider_id, model_id, body):
        del provider_id, model_id, body
        yield b"data: [DONE]\n\n"


class _Runtime:
    def __init__(self, origin: str):
        self.origin = origin

    async def start(self):
        return None

    def status(self):
        return {"status": "ready", "message": None}

    async def close(self):
        return None

    async def run_turn(self, *, context, prompt, emit):
        if prompt.strip() in {
            "fixture webfetch approval",
            "fixture webfetch decline",
            "fixture webfetch cancellation",
            "fixture webfetch stale context",
            "fixture webfetch stale route context",
            "fixture webfetch stale decline",
        }:
            # Exercise the real FastAPI confirmation waiter without making an external request.
            exact_url = "https://example.com/research?fixture=browser-qa&view=research%2Fsummary"
            await emit({
                "type": "meta",
                "data": {
                    "model_id": context.model_id,
                    "policy_version": _MODEL.policy_version,
                    "context_version": context.context_version,
                },
            })
            approved_url = await self.assistant.await_webfetch_approval(context, exact_url, emit)
            if approved_url == exact_url:
                text = (
                    "Synthetic web page request was approved exactly once; "
                    "no external request was made."
                )
            else:
                text = "Synthetic web page request was declined; no external request was made."
            await emit({"type": "token", "data": {"text": text}})
            return AssistantTurnResult(status="completed")

        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            response = await client.post(
                f"{self.origin}/api/v1/assistant/internal/mcp/{context.execution_id}",
                headers={
                    "authorization": f"Bearer {context.capability}",
                    "content-type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "browser-fixture-tool-call",
                    "method": "tools/call",
                    "params": {"name": "workspace.summary", "arguments": {}},
                },
            )
        if not response.is_success:
            try:
                error_code = response.json().get("error", {}).get("code", "unknown")
            except (ValueError, AttributeError):
                error_code = "unknown"
            raise RuntimeError(
                f"synthetic browser MCP call returned HTTP {response.status_code} ({error_code})"
            )
        await emit({
            "type": "meta",
            "data": {
                "model_id": context.model_id,
                "policy_version": _MODEL.policy_version,
                "context_version": context.context_version,
            },
        })
        await emit({
            "type": "token",
            "data": {"text": "Synthetic research response from the local browser fixture."},
        })
        await emit({
            "type": "proposed_action",
            "data": {"action_type": "theme.set", "payload": {"theme": "dark"}},
        })
        return AssistantTurnResult(status="completed")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_session(application, now: datetime) -> int:
    repository = application.state.repository
    user = repository.auth_create_user({
        "github_id": _GITHUB_ID,
        "github_login": "browser-fixture-admin",
        "display_name": "Browser fixture admin",
        "role": "admin",
        "status": "active",
        "created_at": now,
    })
    user_id = int(user["id"])
    with repository.connect() as connection:
        cursor = connection.execute(
            """INSERT INTO totp_factors
            (user_id, secret_ciphertext, created_at, confirmed_at,
             last_accepted_step, updated_at)
            VALUES (?, ?, ?, ?, -1, ?)""",
            (user_id, "browser-fixture-only", now.isoformat(), now.isoformat(), now.isoformat()),
        )
        factor_id = int(cursor.lastrowid)
        expires = now + timedelta(hours=12)
        connection.execute(
            """INSERT INTO sessions
            (user_id, session_id, token_hash, csrf_token_hash, issued_at, last_seen_at,
             idle_expires_at, absolute_expires_at, auth_method, mfa_method,
             mfa_verified_at, mfa_factor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'github', 'totp', ?, ?)""",
            (
                user_id,
                "browser-assistant-fixture-session-id",
                _digest(_SESSION),
                _digest(_CSRF),
                now.isoformat(),
                now.isoformat(),
                expires.isoformat(),
                expires.isoformat(),
                now.isoformat(),
                factor_id,
            ),
        )
        connection.commit()
    return user_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if not 1 <= args.port <= 65_535:
        raise SystemExit("--port must be a valid TCP port")
    origin = f"http://127.0.0.1:{args.port}"
    base = Settings.from_env()
    settings = replace(
        base,
        host="127.0.0.1",
        port=args.port,
        environment="test",
        auth_mode="github",
        auth_session_secret="browser-fixture-only-session-secret-never-for-production",  # noqa: S106
        auth_public_origin=origin,
        auth_cookie_secure=False,
        github_client_id="browser-fixture-only",
        github_client_secret="browser-fixture-only",  # noqa: S106
        github_redirect_uri=f"{origin}/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
    )
    runtime = _Runtime(origin)
    application = create_app(
        settings,
        FixtureProvider(),
        assistant_runtime=runtime,
        assistant_catalog=_Catalog(),
        assistant_providers=_Providers(),
    )
    runtime.assistant = application.state.assistant
    stream_audits = []

    async def assistant_stream_audit():
        return {"items": list(stream_audits)}

    application.add_api_route(
        "/__qa/assistant-stream-audit",
        assistant_stream_audit,
        methods=["GET"],
        include_in_schema=False,
    )
    # Keep assistant lease/session timestamps aligned while the forecast fixture retains its
    # fixed historical clock for deterministic saved-event context.
    assistant_now = datetime.now(UTC).replace(microsecond=0)
    application.state.assistant.clock = lambda: assistant_now
    settings.ensure_local_dirs()
    application.state.repository.migrate()
    user_id = _seed_session(application, assistant_now)
    application.state.service.search("ACDC", "stock", owner_user_id=user_id)
    uvicorn.run(
        _AssistantStreamAudit(application, stream_audits),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
