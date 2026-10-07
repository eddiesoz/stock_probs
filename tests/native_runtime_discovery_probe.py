"""No-prompt, closed-projection diagnostic for an attached assistant worker.

Run this file from the application container as its application UID. It uses the normal
runtime startup path and client, prepares two synthetic locations, reads location/model
metadata only, then removes those locations and awaits worker-HOME purge. It never creates
a native session, submits a prompt, calls a provider, or prints paths, identifiers, headers,
capabilities, response bodies, or exception messages.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from types import SimpleNamespace
from typing import Any

import httpx

from stock_probs.assistant.native_provider_adapters import resolve_native_adapter
from stock_probs.assistant.runtime import OpenCodeV2Runtime, _AssistantRuntimeFailure
from stock_probs.assistant.schemas import AssistantTurnContext
from stock_probs.assistant.supervisor_client import SupervisorClient

_MAX_CONTENT_BYTES = 262_144
_SAFE_RUNTIME_CODES = frozenset(
    {
        "location_discovery_mismatch",
        "model_alias_unavailable",
        "model_discovery_invalid",
        "model_discovery_unavailable",
        "model_location_mismatch",
        "model_provider_invalid",
        "model_proxy_config_invalid",
        "native_request_timeout",
        "native_response_encoding_invalid",
        "native_response_invalid",
        "native_response_too_large",
        "mcp_discovery_invalid",
        "mcp_unavailable",
    }
)
_SAFE_FAILURE_PHASES = frozenset(
    {
        "prepare_location",
        "verify_location",
        "location_discovery",
        "model_discovery",
        "mcp_discovery",
    }
)
_KNOWN_RUNTIME_FAILURE_PHASES = {
    "location_discovery_mismatch": "location_discovery",
    "model_location_mismatch": "model_discovery",
    "model_provider_invalid": "model_discovery",
    "model_proxy_config_invalid": "model_discovery",
    "mcp_discovery_invalid": "mcp_discovery",
    "mcp_unavailable": "mcp_discovery",
}
_ROUTES = {
    "/api/info": "info",
    "/api/location": "location",
    "/api/model": "model",
    "/api/mcp": "mcp",
    "/api/websearch/provider": "websearch_provider",
}


@dataclass(frozen=True, slots=True)
class _SyntheticModel:
    model_id: str
    provider_id: str
    available: bool = True


class _SyntheticCatalog:
    def __init__(self, model: _SyntheticModel) -> None:
        self._model = model

    def get_model(self, model_id: str) -> _SyntheticModel | None:
        return self._model if model_id == self._model.model_id else None


class _SyntheticProviders:
    """Provide the fixed app-proxy descriptor without any external credentials."""

    def native_execution_descriptor(self, _model_id: str):
        return resolve_native_adapter("openai-compatible-chat", "assistant-proxy")


def _reviewed_free_model() -> tuple[str, str, str]:
    """Choose an eligible model dynamically from the single maintained catalog."""

    catalog = json.loads(
        files("stock_probs.assistant")
        .joinpath("assistant_catalog.json")
        .read_text(encoding="utf-8")
    )
    zen = catalog["zen"]
    provider_id = zen["provider_id"]
    eligible = sorted(
        model_id
        for model_id, policy in zen["reviewed_models"].items()
        if policy.get("available") is True
        and policy.get("free") is True
        and policy.get("training") is False
    )
    if not eligible:
        raise RuntimeError("reviewed_model_unavailable")
    model_id = f"{provider_id}/{eligible[0]}"
    policy_version = zen["policy_version"]
    if not all(isinstance(value, str) for value in (provider_id, model_id, policy_version)):
        raise RuntimeError("reviewed_catalog_invalid")
    return provider_id, model_id, policy_version


def _encoding_class(value: str | None) -> str:
    if value is None or value.strip().casefold() in {"", "identity"}:
        return "identity_or_missing"
    return "encoded_or_unrecognized"


def _content_length_projection(value: str | None) -> tuple[str, bool]:
    if value is None:
        return "missing", True
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return "invalid", False
    if parsed < 0:
        return "invalid", False
    if parsed > _MAX_CONTENT_BYTES:
        return "over_limit", False
    return "within_limit", True


def _exception_code(exc: BaseException) -> str:
    if isinstance(exc, _AssistantRuntimeFailure) and exc.code in _SAFE_RUNTIME_CODES:
        return exc.code
    if type(exc) is RuntimeError and len(exc.args) == 1:
        code = exc.args[0]
        if type(code) is str and code in _SAFE_RUNTIME_CODES:
            return code
    return "diagnostic_unknown"


def _failure_projection(exc: BaseException, default_phase: str) -> dict[str, str]:
    code = _exception_code(exc)
    phase = getattr(exc, "phase", None)
    if type(phase) is not str or phase not in _SAFE_FAILURE_PHASES:
        phase = _KNOWN_RUNTIME_FAILURE_PHASES.get(code, default_phase)
    return {"status": "failed", "phase": phase, "code": code}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _response_hook(
    responses: list[dict[str, object]],
) -> Callable[[httpx.Response], Awaitable[None]]:
    async def observe(response: httpx.Response) -> None:
        request = response.request
        length_state, length_within_limit = _content_length_projection(
            response.headers.get("content-length")
        )
        path = request.url.path
        route = (
            "session_prompt"
            if path.startswith("/api/session/") and path.endswith("/prompt")
            else "session_api"
            if path == "/api/session" or path.startswith("/api/session/")
            else _ROUTES.get(path, "other")
        )
        responses.append(
            {
                "route": route,
                "status": response.status_code,
                "request_accept_encoding_identity": (
                    request.headers.get("accept-encoding", "").strip().casefold() == "identity"
                ),
                "response_encoding": _encoding_class(response.headers.get("content-encoding")),
                "content_length_state": length_state,
                "content_length_within_cap": length_within_limit,
                "content_type_json": response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .casefold()
                in {"application/json", "application/problem+json"},
            }
        )

    return observe


def _diagnostic_accepted(result: Mapping[str, object]) -> bool:
    """Return true only when both metadata checks and cleanup completed."""

    locations = result.get("locations")
    verify_outcomes = result.get("verify_outcomes")
    cleanup = result.get("cleanup")
    return (
        result.get("outcome") == "metadata_only_complete"
        and result.get("runtime_start_status") == "ready"
        and isinstance(locations, list)
        and len(locations) == 2
        and all(isinstance(row, dict) and row.get("prepared") is True for row in locations)
        and isinstance(verify_outcomes, list)
        and len(verify_outcomes) == 2
        and all(
            isinstance(value, Mapping)
            and value.get("status") == "verified"
            and value.get("phase") == "complete"
            and value.get("code") == "none"
            for value in verify_outcomes
        )
        and result.get("native_session_requests") == 0
        and result.get("native_prompt_requests") == 0
        and result.get("runtime_close") != "failed"
        and isinstance(cleanup, Mapping)
        and cleanup.get("locations_removed") == 2
        and cleanup.get("location_removal_failures") == 0
        and cleanup.get("purge_requested") is True
        and cleanup.get("purge_completed") is True
    )


async def _run() -> dict[str, object]:
    provider_id, model_id, policy_version = _reviewed_free_model()
    synthetic_model = _SyntheticModel(model_id=model_id, provider_id=provider_id)
    contexts = tuple(
        AssistantTurnContext(
            user_id=index + 1,
            app_id=f"synthetic-app-{index + 1}",
            conversation_id=f"synthetic-conversation-{index + 1}",
            turn_id=f"synthetic-turn-{index + 1}",
            execution_id=secrets.token_hex(16),
            capability=secrets.token_urlsafe(36),
            model_id=model_id,
            policy_version=policy_version,
            context_version=hashlib.sha256(f"synthetic-context-{index}".encode()).hexdigest(),
            page_context={"path": "/"},
            history=(),
        )
        for index in range(2)
    )
    responses: list[dict[str, object]] = []

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["event_hooks"] = {"response": [_response_hook(responses)]}
        return httpx.AsyncClient(**kwargs)

    runtime = OpenCodeV2Runtime(
        SimpleNamespace(assistant_enabled=True),
        providers=_SyntheticProviders(),
        catalog=_SyntheticCatalog(synthetic_model),
        http_client_factory=client_factory,
    )
    result: dict[str, object] = {
        "probe": "attached_runtime_no_prompt_v1",
        "started_at": _utc_now(),
        "runtime_start_status": "unknown",
        "locations": [],
        "native_responses": responses,
        "native_session_requests": 0,
        "native_prompt_requests": 0,
        "cleanup": {
            "locations_removed": 0,
            "purge_requested": False,
            "purge_completed": False,
        },
    }
    supervisor: SupervisorClient | None = None
    prepared: list[AssistantTurnContext] = []
    try:
        # Calling start() exercises the same supervisor status, auth and client construction
        # as the app. The returned API password stays inside the runtime and is never copied.
        status = await runtime.start()
        result["runtime_start_status"] = (
            status.status
            if status.status in {"ready", "unavailable", "disabled", "stopped"}
            else "unknown"
        )
        supervisor = runtime._get_supervisor()
        if status.status != "ready" or runtime._client is None:
            result["outcome"] = "runtime_start_unavailable"
            return result

        async def prepare(context: AssistantTurnContext) -> dict[str, object]:
            try:
                directory = await runtime._prepare_location(context)
            except Exception as exc:
                failure = _failure_projection(exc, "prepare_location")
                return {"prepared": False, "failure": failure}
            prepared.append(context)
            return {"prepared": directory.endswith(context.execution_id)}

        location_results = await asyncio.gather(*(prepare(context) for context in contexts))
        result["locations"] = location_results

        async def verify(context: AssistantTurnContext) -> dict[str, str]:
            try:
                expected = f"/run/assistant/worker-locations/{context.execution_id}"
                await runtime._verify_location(context, expected)
            except Exception as exc:
                return _failure_projection(exc, "verify_location")
            return {"status": "verified", "phase": "complete", "code": "none"}

        verify_outcomes = await asyncio.gather(*(verify(context) for context in prepared))
        result["verify_outcomes"] = verify_outcomes
        result["outcome"] = (
            "metadata_only_complete"
            if len(prepared) == 2 and all(row["status"] == "verified" for row in verify_outcomes)
            else "metadata_only_incomplete"
        )
        result["native_session_requests"] = sum(row["route"] == "session_api" for row in responses)
        result["native_session_requests"] += sum(
            row["route"] == "session_prompt" for row in responses
        )
        result["native_prompt_requests"] = sum(
            row["route"] == "session_prompt" for row in responses
        )
    except asyncio.CancelledError:
        result["outcome"] = "cancelled"
        raise
    except Exception as exc:
        result["outcome"] = _exception_code(exc)
    finally:
        try:
            await runtime.close()
        except Exception:
            result["runtime_close"] = "failed"
        if supervisor is None:
            try:
                supervisor = runtime._get_supervisor()
            except Exception:
                supervisor = None
        if supervisor is not None:
            purge_id: str | None = None
            removed = 0
            removal_failures = 0
            for context in contexts:
                try:
                    candidate = await supervisor.remove_location(context.execution_id)
                    removed += 1
                    if candidate is not None:
                        purge_id = candidate
                except Exception:
                    removal_failures += 1
            cleanup: dict[str, object] = {
                "locations_removed": removed,
                "location_removal_failures": removal_failures,
                "purge_requested": purge_id is not None,
                "purge_completed": False,
            }
            if purge_id is not None:
                try:
                    cleanup["purge_completed"] = await supervisor.wait_for_home_purge(
                        purge_id, timeout=20.0
                    )
                except Exception:
                    cleanup["purge_completed"] = False
            result["cleanup"] = cleanup
        result["native_responses"] = responses
        result["diagnostic_pass"] = _diagnostic_accepted(result)
        result["finished_at"] = _utc_now()
    return result


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(_run())
    except BaseException as exc:
        outcome = (
            "interrupted"
            if isinstance(exc, KeyboardInterrupt | asyncio.CancelledError)
            else "diagnostic_unknown"
        )
        result = {"outcome": outcome}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("diagnostic_pass") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
