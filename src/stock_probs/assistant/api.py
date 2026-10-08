"""Same-origin REST, SSE, and one leased native-MCP endpoint for the assistant."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import re
import unicodedata
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import NoReturn
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError
from starlette.types import Send

from stock_probs.assistant import net
from stock_probs.assistant.native_provider_adapters import (
    NATIVE_WEBFETCH_DESCRIPTION_SHA256,
    native_output_token_budget,
    native_webfetch_schema,
    validated_output_token_count,
)
from stock_probs.assistant.oauth_transport import OAuthTransport, OAuthTransportError
from stock_probs.assistant.providers import _native_zen_upstream_headers
from stock_probs.assistant.schemas import (
    AssistantActionConfirmationRequest,
    AssistantConsentRequest,
    AssistantContextQuery,
    AssistantConversationCreateRequest,
    AssistantConversationDeleteRequest,
    AssistantConversationUpdateRequest,
    AssistantCustomProviderEndpointRequest,
    AssistantModelAdminPolicyRequest,
    AssistantOAuthAttemptCallbackRequest,
    AssistantOAuthAttemptCompleteRequest,
    AssistantOAuthAttemptCreateRequest,
    AssistantOpenCodeModelReviewRequest,
    AssistantProviderUpdateRequest,
    AssistantSearchPreviewConfirmationRequest,
    AssistantTurnCreateRequest,
    AssistantWebfetchPreviewConfirmationRequest,
)
from stock_probs.assistant.search import MAX_SEARCH_QUERY_BYTES, validate_webfetch_url
from stock_probs.assistant.service import (
    AssistantConsentRequired,
    AssistantService,
    AssistantUnavailable,
)
from stock_probs.assistant.storage import (
    AssistantStorageBusy,
    AssistantStorageConflict,
    AssistantStorageError,
    AssistantStorageNotFound,
    AssistantStorageQuotaExceeded,
)
from stock_probs.auth import SESSION_COOKIE_NAME, AuthContext, AuthManager
from stock_probs.config import Settings

_EXECUTION_ID = re.compile(r"^[0-9a-f]{32}$")
_OAUTH_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_OAUTH_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_OAUTH_STATUSES = frozenset(
    {"pending", "handoff_ready", "connected", "denied", "expired", "cancelled"}
)
_OAUTH_MODES = frozenset({"device", "code", "browser"})
_OAUTH_AUTHORIZATION_HOSTS = {
    "openai": frozenset({"auth.openai.com"}),
    "opencode": frozenset({"opencode.ai"}),
}
_OAUTH_METHODS = frozenset(
    {
        ("openai", "chatgpt-browser"),
        ("openai", "chatgpt-headless"),
        ("opencode", "device"),
    }
)
_PROXY_MAX_OUTPUT_BYTES = 1024 * 1024
_PROXY_MAX_MESSAGES = 32
_PROXY_MAX_MESSAGE_BYTES = 64 * 1024
_PROXY_MAX_TOOL_CALLS = 8
_PROXY_MAX_TOOL_ARGUMENT_BYTES = 16 * 1024
_PROXY_MAX_NATIVE_JSON_BYTES = 256 * 1024
_PROXY_CALL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_NATIVE_SESSION_ID = re.compile(r"^ses[\x21-\x7e]{0,61}$")
_OPENCODE_MODEL_ID = re.compile(r"^opencode-console/[0-9a-f]{64}$")
_PROXY_NEXT_CHUNK_CANCEL_SECONDS = 0.2
_PROXY_CLOSE_SECONDS = 1.0
_PROXY_STREAM_TIMEOUT_SECONDS = 120.0
_PROVIDER_STREAM_FAILURE_MARKER = "ASSISTANT_PROVIDER_STREAM_FAILURE_V1 "
_PROVIDER_STREAM_FAILURE_STAGES = frozenset(
    {"upstream_stream", "proxy_validation", "proxy_deadline", "proxy_guard"}
)
_PROVIDER_TRANSPORT_ERROR_CODES = frozenset(
    {
        "dns_unavailable",
        "header_invalid",
        "private_destination_rejected",
        "provider_authorization_required",
        "provider_authorization_timeout",
        "provider_connect_failed",
        "provider_deadline_exceeded",
        "provider_headers_too_large",
        "provider_redirect_rejected",
        "provider_response_invalid",
        "provider_response_too_large",
        "provider_upstream_unavailable",
        "request_invalid",
        "url_invalid",
        "upstream_error_unknown",
    }
)
_PROVIDER_PROXY_ERROR_CODES = frozenset(
    {
        "chunk_invalid",
        "chunk_too_large",
        "proxy_error_unknown",
        "request_superseded",
        "stream_deadline_exceeded",
        "stream_output_limit_exceeded",
    }
)
_PROVIDER_STREAM_FAILURE_ERROR_CODES = _PROVIDER_TRANSPORT_ERROR_CODES | _PROVIDER_PROXY_ERROR_CODES
_PROVIDER_403_CONTENT_TYPE_CLASSES = frozenset(
    {"json", "html", "event_stream", "other", "missing", "invalid"}
)
_PROVIDER_403_CF_MITIGATED_CLASSES = frozenset({"challenge", "absent", "other"})
_PROVIDER_403_ERROR_TYPE_CLASSES = frozenset(
    {"region_error", "data_policy_error", "free_usage_limit_error", "other", "malformed", "unknown"}
)
_SAFE_PROVIDER_FIELDS = frozenset(
    {
        "provider_id",
        "display_name",
        "auth_methods",
        "selected_model_id",
        "selected_base_url",
        "credential_required",
        "credential_configured",
        "oauth_connected",
        "connection_status",
        "terms_url",
        "selected_terms_url",
        "selected_privacy_disclosure",
        "selected_billing_disclosure",
        "selected_billing_class",
        "native_provider_id",
        "adapter_id",
        "protocol",
        "endpoint_editable",
        "credential_supported",
        "validation_requires_credential",
        "unsupported_reason",
        "selected_endpoint_policy_reviewed",
    }
)
_SAFE_PROVIDER_TEXT_FIELDS = frozenset(
    {
        "provider_id",
        "display_name",
        "selected_model_id",
        "selected_base_url",
        "connection_status",
        "terms_url",
        "selected_terms_url",
        "selected_privacy_disclosure",
        "selected_billing_disclosure",
        "selected_billing_class",
        "native_provider_id",
        "adapter_id",
        "protocol",
        "unsupported_reason",
    }
)
_SAFE_PROVIDER_BOOL_FIELDS = frozenset(
    {
        "credential_required",
        "credential_configured",
        "oauth_connected",
        "endpoint_editable",
        "credential_supported",
        "validation_requires_credential",
        "selected_endpoint_policy_reviewed",
    }
)
_SAFE_MODEL_POLICY_FIELDS = frozenset(
    {
        "model_id",
        "provider_id",
        "native_provider_id",
        "display_name",
        "available",
        "enabled",
        "free",
        "training_uses_data",
        "privacy_policy_version",
        "privacy_disclosure",
        "billing_class",
        "billing_policy_version",
        "cost_disclosure",
        "revision",
        "usable",
        "availability_reason",
        "id",
        "provider",
        "name",
        "availability",
        "training",
        "terms_url",
        "terms_reviewed_at",
        "policy_version",
        "disclosure",
        "consent",
    }
)
_SAFE_MODEL_TEXT_FIELDS = frozenset(
    {
        "model_id",
        "provider_id",
        "native_provider_id",
        "display_name",
        "privacy_policy_version",
        "privacy_disclosure",
        "billing_policy_version",
        "cost_disclosure",
        "availability_reason",
        "id",
        "provider",
        "name",
        "availability",
        "training",
        "terms_url",
        "terms_reviewed_at",
        "policy_version",
        "disclosure",
    }
)
_SAFE_MODEL_BOOL_FIELDS = frozenset(
    {"available", "enabled", "free", "training_uses_data", "usable"}
)


def _native_websearch_declaration() -> dict[str, object]:
    """Return the exact builtin descriptor observed from the pinned OpenCode V2 runtime."""

    return {
        "type": "function",
        "function": {
            "name": "websearch",
            "description": (
                "Search the web using the user's selected search integration. Use this for "
                "current information beyond knowledge cutoff.\n\n"
                f"The current year is {datetime.now(UTC).year}. Use this year when searching "
                "for recent information or current events."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Websearch query"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": False,
        },
    }


def _native_webfetch_declaration_matches(value: object) -> bool:
    """Match the pinned native function text by hash and its exact closed schema."""

    if not isinstance(value, Mapping) or set(value) != {"type", "function"}:
        return False
    if value.get("type") != "function":
        return False
    function = value.get("function")
    if (
        not isinstance(function, Mapping)
        or set(function) != {"name", "description", "parameters", "strict"}
        or function.get("name") != "webfetch"
        or function.get("strict") is not False
    ):
        return False
    description = function.get("description")
    parameters = function.get("parameters")
    if not isinstance(description, str):
        return False
    try:
        description_sha256 = hashlib.sha256(description.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return False
    return (
        description_sha256 == NATIVE_WEBFETCH_DESCRIPTION_SHA256
        and isinstance(parameters, Mapping)
        and dict(parameters) == native_webfetch_schema("openai-compatible-chat")
    )


def _native_webfetch_arguments_valid(value: Mapping[str, object]) -> bool:
    """Keep native fetch arguments within the same exact public-HTTPS contract."""

    if set(value) - {"url", "format", "timeout"} or "url" not in value:
        return False
    url = value.get("url")
    if not isinstance(url, str):
        return False
    try:
        if validate_webfetch_url(url) != url:
            return False
    except UnicodeError:
        return False
    output_format = value.get("format")
    if "format" in value and (
        not isinstance(output_format, str) or output_format not in {"text", "markdown", "html"}
    ):
        return False
    if "timeout" not in value:
        return True
    timeout = value["timeout"]
    if type(timeout) is int:
        return 0 < timeout <= 120
    return type(timeout) is float and math.isfinite(timeout) and 0 < timeout <= 120


def _utf8_length(value: str) -> int | None:
    """Return a bounded-input text length, rejecting lone UTF-16 surrogates."""

    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys so exact native tool arguments have one interpretation."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _error(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message}}


def _consume_task_result(task: asyncio.Task[object]) -> None:
    """Retrieve a background task exception so bounded cleanup never leaks warnings."""

    if task.cancelled():
        return
    with suppress(asyncio.CancelledError, Exception):
        task.exception()


async def _close_provider_iterator(upstream: object) -> None:
    """Close an async provider iterator with a fixed deadline and consume its failure."""

    close = getattr(upstream, "aclose", None)
    if not callable(close):
        return
    try:
        closing = asyncio.create_task(close())
    except Exception:
        return
    done, pending = await asyncio.wait({closing}, timeout=_PROXY_CLOSE_SECONDS)
    if pending:
        closing.cancel()
        closing.add_done_callback(_consume_task_result)
    elif done:
        _consume_task_result(closing)


def _defer_provider_close(task: asyncio.Task[bytes], upstream: object) -> None:
    """Close only after a cancellation-resistant __anext__ has actually returned."""

    _consume_task_result(task)
    loop = task.get_loop()
    if loop.is_closed():
        return
    try:
        loop.create_task(_close_provider_iterator(upstream))
    except RuntimeError:
        # The loop is already closing. Do not race aclose against the active __anext__.
        return


async def _provider_proxy_chunks(
    upstream: AsyncIterator[bytes],
    is_current: Callable[[], bool],
) -> AsyncIterator[bytes]:
    """Bridge one bounded provider stream and preserve failures as an interrupted stream."""

    total = 0
    deadline = asyncio.get_running_loop().time() + _PROXY_STREAM_TIMEOUT_SECONDS
    next_chunk: asyncio.Task[bytes] | None = None
    try:
        while True:
            if not is_current():
                raise _ProviderProxyProtocolError(
                    stage="proxy_guard", error_code="request_superseded"
                )
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise _ProviderProxyTimeout()
            next_chunk = asyncio.create_task(upstream.__anext__())
            done, pending = await asyncio.wait({next_chunk}, timeout=remaining)
            if pending:
                raise _ProviderProxyTimeout()
            try:
                chunk = next_chunk.result()
            except StopAsyncIteration:
                return
            except asyncio.CancelledError:
                raise
            except net.PublicHTTPError as exc:
                error_code = (
                    exc.code
                    if type(exc) is net.PublicHTTPError
                    and type(exc.code) is str
                    and exc.code in _PROVIDER_TRANSPORT_ERROR_CODES
                    else "upstream_error_unknown"
                )
                status_code = (
                    exc.status_code
                    if type(exc) is net.PublicHTTPError
                    and type(exc.status_code) is int
                    and 100 <= exc.status_code <= 599
                    else None
                )
                content_type_class = (
                    exc.content_type_class
                    if type(exc) is net.PublicHTTPError
                    and error_code == "provider_upstream_unavailable"
                    and status_code == 403
                    and type(exc.content_type_class) is str
                    and exc.content_type_class in _PROVIDER_403_CONTENT_TYPE_CLASSES
                    else None
                )
                cf_mitigated_class = (
                    exc.cf_mitigated_class
                    if type(exc) is net.PublicHTTPError
                    and error_code == "provider_upstream_unavailable"
                    and status_code == 403
                    and type(exc.cf_mitigated_class) is str
                    and exc.cf_mitigated_class in _PROVIDER_403_CF_MITIGATED_CLASSES
                    else None
                )
                provider_error_type_class = (
                    exc.provider_error_type_class
                    if type(exc) is net.PublicHTTPError
                    and error_code == "provider_upstream_unavailable"
                    and status_code == 403
                    and type(exc.provider_error_type_class) is str
                    and exc.provider_error_type_class in _PROVIDER_403_ERROR_TYPE_CLASSES
                    else None
                )
                raise _ProviderProxyProtocolError(
                    stage="upstream_stream",
                    error_code=error_code,
                    status_code=status_code,
                    content_type_class=content_type_class,
                    cf_mitigated_class=cf_mitigated_class,
                    provider_error_type_class=provider_error_type_class,
                ) from None
            except Exception:
                # Do not turn an upstream exception into clean EOF; native clients must see
                # an interrupted response and reject any partial completion.
                raise _ProviderProxyProtocolError(
                    stage="upstream_stream", error_code="upstream_error_unknown"
                ) from None
            next_chunk = None
            if not isinstance(chunk, bytes):
                raise _ProviderProxyProtocolError(
                    stage="proxy_validation", error_code="chunk_invalid"
                )
            if len(chunk) > 32 * 1024:
                raise _ProviderProxyProtocolError(
                    stage="proxy_validation", error_code="chunk_too_large"
                )
            if not is_current():
                raise _ProviderProxyProtocolError(
                    stage="proxy_guard", error_code="request_superseded"
                )
            total += len(chunk)
            if total > _PROXY_MAX_OUTPUT_BYTES:
                raise _ProviderProxyProtocolError(
                    stage="proxy_validation", error_code="stream_output_limit_exceeded"
                )
            yield chunk
    except asyncio.CancelledError:
        raise
    except (_ProviderProxyTimeout, _ProviderProxyProtocolError):
        raise
    except Exception:
        # Keep adapter details, URLs, and provider messages out of the private stream.
        raise _ProviderProxyProtocolError(
            stage="proxy_guard", error_code="proxy_error_unknown"
        ) from None
    finally:
        pending_next = next_chunk
        if pending_next is not None and not pending_next.done():
            # Register result consumption and deferred close before an await that a
            # disconnected client can cancel a second time.
            pending_next.add_done_callback(lambda task: _defer_provider_close(task, upstream))
            defer_close = True
            pending_next.cancel()
            try:
                await asyncio.wait({pending_next}, timeout=_PROXY_NEXT_CHUNK_CANCEL_SECONDS)
            except asyncio.CancelledError:
                # The callback owns cleanup if cancellation interrupted this bounded wait.
                raise
        else:
            defer_close = False
        if pending_next is not None and pending_next.done() and not defer_close:
            # Recheck after cancellation/wait: StopAsyncIteration can win the race with
            # request cancellation and must still be retrieved before this frame exits.
            _consume_task_result(pending_next)
        if not defer_close:
            await _close_provider_iterator(upstream)


class _ProviderProxyTimeout(AssistantUnavailable):
    """Identify only the app proxy's own bounded stream deadline to private telemetry."""

    def __init__(self) -> None:
        super().__init__("provider_unavailable", 503)
        self.stage = "proxy_deadline"
        self.error_code = "stream_deadline_exceeded"
        self.status_code: int | None = None


class _ProviderProxyProtocolError(AssistantUnavailable):
    """Identify a safe proxy guard failure without retaining upstream exception details."""

    def __init__(
        self,
        *,
        stage: str = "proxy_guard",
        error_code: str = "proxy_error_unknown",
        status_code: int | None = None,
        content_type_class: str | None = None,
        cf_mitigated_class: str | None = None,
        provider_error_type_class: str | None = None,
    ) -> None:
        super().__init__("provider_unavailable", 503)
        self.stage = (
            stage
            if type(stage) is str and stage in _PROVIDER_STREAM_FAILURE_STAGES
            else "proxy_guard"
        )
        self.error_code = (
            error_code
            if type(error_code) is str and error_code in _PROVIDER_STREAM_FAILURE_ERROR_CODES
            else "proxy_error_unknown"
        )
        self.status_code = (
            status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        )
        classes_are_valid = (
            self.stage == "upstream_stream"
            and self.error_code == "provider_upstream_unavailable"
            and self.status_code == 403
            and type(content_type_class) is str
            and content_type_class in _PROVIDER_403_CONTENT_TYPE_CLASSES
            and type(cf_mitigated_class) is str
            and cf_mitigated_class in _PROVIDER_403_CF_MITIGATED_CLASSES
        )
        self.content_type_class = content_type_class if classes_are_valid else None
        self.cf_mitigated_class = cf_mitigated_class if classes_are_valid else None
        error_type_is_valid = (
            self.stage == "upstream_stream"
            and self.error_code == "provider_upstream_unavailable"
            and self.status_code == 403
            and type(provider_error_type_class) is str
            and provider_error_type_class in _PROVIDER_403_ERROR_TYPE_CLASSES
        )
        self.provider_error_type_class = provider_error_type_class if error_type_is_valid else None


class _ProviderProxyStreamingResponse(StreamingResponse):
    """Check initial upstream status in the stream task before sending response headers."""

    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        authorization_check: Callable[[], bool],
        denied: Response,
        media_type: str,
        headers: dict[str, str],
    ) -> None:
        super().__init__(content, media_type=media_type, headers=headers)
        self._authorization_check = authorization_check
        self._denied = denied

    async def stream_response(self, send: Send) -> None:
        iterator = self.body_iterator
        try:
            initial_error: Exception | None = None
            first_chunk: bytes | None = None
            try:
                first_chunk = await iterator.__anext__()
            except StopAsyncIteration:
                pass
            except Exception as exc:
                initial_error = exc

            try:
                still_authorized = self._authorization_check()
            except Exception:
                still_authorized = False
            if not still_authorized:
                await send(
                    {
                        "type": "http.response.start",
                        "status": self._denied.status_code,
                        "headers": self._denied.raw_headers,
                    }
                )
                await send({"type": "http.response.body", "body": self._denied.body})
                return

            if _is_initial_provider_auth_failure(initial_error):
                assert type(initial_error) is _ProviderProxyProtocolError
                status_code = initial_error.status_code
                assert type(status_code) is int
                failure_response = JSONResponse(
                    status_code=status_code,
                    content=_error(
                        "provider_unavailable", "The selected model provider is unavailable."
                    ),
                    headers={"Cache-Control": "no-store"},
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": failure_response.status_code,
                        "headers": failure_response.raw_headers,
                    }
                )
                await send({"type": "http.response.body", "body": failure_response.body})
                return

            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            if initial_error is not None:
                raise initial_error
            if first_chunk is not None:
                await send({"type": "http.response.body", "body": first_chunk, "more_body": True})
            async for chunk in iterator:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await _close_provider_iterator(iterator)


def _is_initial_provider_auth_failure(
    failure: object,
) -> bool:
    return (
        type(failure) is _ProviderProxyProtocolError
        and failure.stage == "upstream_stream"
        and failure.error_code == "provider_upstream_unavailable"
        and type(failure.status_code) is int
        and failure.status_code in {401, 403}
    )


async def _provider_proxy_stream_response(
    upstream: AsyncIterator[bytes],
    authorization_check: Callable[[], bool],
    *,
    runtime: object,
    execution_id: str,
    owner_id: int,
    denied: Response,
) -> Response:
    """Build a stream response that classifies initial auth status before its headers."""

    provider_stream = _provider_proxy_chunks_with_timing(
        upstream,
        authorization_check,
        runtime=runtime,
        execution_id=execution_id,
        owner_id=owner_id,
    )
    return _ProviderProxyStreamingResponse(
        provider_stream,
        authorization_check=authorization_check,
        denied=denied,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _provider_proxy_chunks_with_timing(
    upstream: AsyncIterator[bytes],
    is_current: Callable[[], bool],
    *,
    runtime: object,
    execution_id: str,
    owner_id: int,
) -> AsyncIterator[bytes]:
    """Observe only sanitized provider chunks while preserving the existing stream guard."""

    ordinal: int | None = None
    start = getattr(runtime, "_record_provider_stream_start", None)
    if callable(start):
        try:
            candidate = start(execution_id, owner_id)
            ordinal = candidate if type(candidate) is int and 1 <= candidate <= 8 else None
        except Exception:
            ordinal = None

    def record(method_name: str, *args: object) -> None:
        method = getattr(runtime, method_name, None)
        if ordinal is None or not callable(method):
            return
        try:
            method(execution_id, owner_id, ordinal, *args)
        except Exception:
            # Timing is diagnostic-only and must never change provider stream behavior.
            return

    def record_failure(
        stage: str,
        error_code: str,
        status_code: int | None = None,
        content_type_class: str | None = None,
        cf_mitigated_class: str | None = None,
        provider_error_type_class: str | None = None,
    ) -> None:
        if (
            stage == "upstream_stream"
            and error_code == "provider_upstream_unavailable"
            and status_code == 403
            and type(provider_error_type_class) is str
            and provider_error_type_class in _PROVIDER_403_ERROR_TYPE_CLASSES
        ):
            record(
                "_record_provider_stream_failure",
                stage,
                error_code,
                status_code,
                content_type_class,
                cf_mitigated_class,
                provider_error_type_class,
            )
            return
        if content_type_class is not None and cf_mitigated_class is not None:
            record(
                "_record_provider_stream_failure",
                stage,
                error_code,
                status_code,
                content_type_class,
                cf_mitigated_class,
            )
            return
        record("_record_provider_stream_failure", stage, error_code, status_code)

    proxy = _provider_proxy_chunks(upstream, is_current)
    try:
        async for chunk in proxy:
            record("_record_provider_first_sanitized_chunk")
            record("_record_provider_sanitized_yield", len(chunk))
            yield chunk
        record("_record_provider_stream_end", "ended", "clean_eof")
    except asyncio.CancelledError:
        record("_record_provider_stream_end", "cancelled", "cancelled_error")
        raise
    except GeneratorExit:
        record("_record_provider_stream_end", "cancelled", "generator_closed")
        raise
    except _ProviderProxyTimeout:
        record_failure("proxy_deadline", "stream_deadline_exceeded")
        record("_record_provider_stream_end", "failed", "proxy_timeout")
        raise
    except _ProviderProxyProtocolError as exc:
        record_failure(
            exc.stage,
            exc.error_code,
            exc.status_code,
            exc.content_type_class,
            exc.cf_mitigated_class,
            exc.provider_error_type_class,
        )
        record("_record_provider_stream_end", "failed", "safe_protocol_error")
        raise
    except Exception:
        record_failure("proxy_guard", "proxy_error_unknown")
        record("_record_provider_stream_end", "failed", "safe_protocol_error")
        raise
    finally:
        await proxy.aclose()


def _record_completed_workspace_summary_timing(
    runtime: object, execution_id: str, owner_id: int, *, tool_name: object, completed: object
) -> None:
    """Record the fixed workspace tool only after its authorized receipt completed."""

    if tool_name != "workspace.summary" or completed is not True:
        return
    record = getattr(runtime, "_record_workspace_summary_completion", None)
    if callable(record):
        try:
            record(execution_id, owner_id)
        except Exception:
            # Optional timing evidence must not affect the authorized MCP result.
            return


def _json_safe_provider(value: object) -> dict[str, object]:
    if hasattr(value, "public_dict") and callable(value.public_dict):
        value = value.public_dict()
    elif hasattr(value, "__dataclass_fields__"):
        value = {
            field: getattr(value, field)
            for field in value.__dataclass_fields__
            if field in _SAFE_PROVIDER_FIELDS
        }
    if not isinstance(value, Mapping):
        return {}
    result = {
        key: value[key][:2048]
        for key in _SAFE_PROVIDER_TEXT_FIELDS
        if key in value and isinstance(value[key], str)
    }
    result.update(
        {
            key: value[key]
            for key in _SAFE_PROVIDER_BOOL_FIELDS
            if key in value and isinstance(value[key], bool)
        }
    )
    for key in ("auth_methods", "supported_auth_methods"):
        methods = value.get(key)
        if isinstance(methods, list | tuple):
            result[key] = [item[:64] for item in methods[:8] if isinstance(item, str)]
    return result


def _provider_capability_response(value: object) -> dict[str, object]:
    """Project legacy provider settings and current capability facts into one closed row."""

    item = _json_safe_provider(value)
    methods = item.get("supported_auth_methods", item.get("auth_methods", []))
    if not isinstance(methods, list):
        methods = []
    credential_required = item.get("credential_required") is True
    capability_present = all(
        isinstance(item.get(field), str) and item[field]
        for field in ("native_provider_id", "adapter_id", "protocol")
    )
    result = {
        **item,
        "native_provider_id": item.get("native_provider_id"),
        "adapter_id": item.get("adapter_id"),
        "protocol": item.get("protocol"),
        "supported_auth_methods": methods,
        "connection_status": item.get("connection_status", "unavailable"),
        "endpoint_editable": item.get("endpoint_editable") is True,
        "credential_supported": item.get("credential_supported") is True,
        "validation_requires_credential": item.get(
            "validation_requires_credential", credential_required
        ),
        "unsupported_reason": item.get(
            "unsupported_reason", None if capability_present else "provider_capability_unavailable"
        ),
    }
    return result


def _oauth_method_response(value: object) -> dict[str, object] | None:
    """Project one manager-listed native authorization method without private fields."""

    if not isinstance(value, Mapping):
        return None
    integration_id = value.get("integration_id")
    method_id = value.get("method_id")
    label = value.get("label")
    mode = value.get("mode")
    connection_status = value.get("connection_status")
    availability_reason = value.get("availability_reason")
    if (
        not isinstance(integration_id, str)
        or _OAUTH_IDENTIFIER.fullmatch(integration_id) is None
        or not isinstance(method_id, str)
        or _OAUTH_IDENTIFIER.fullmatch(method_id) is None
        or not isinstance(label, str)
        or not 1 <= len(label.encode("utf-8")) <= 128
        or any(unicodedata.category(char).startswith("C") for char in label)
        or mode not in _OAUTH_MODES
        or not isinstance(connection_status, str)
        or re.fullmatch(r"[a-z0-9_]{1,64}", connection_status) is None
        or type(value.get("connection_supported")) is not bool
        or value.get("connection_supported") is not True
        or type(value.get("model_access_supported")) is not bool
        or (
            availability_reason is not None
            and (
                not isinstance(availability_reason, str)
                or re.fullmatch(r"[a-z0-9_]{1,64}", availability_reason) is None
            )
        )
        or (
            integration_id == "openai"
            and (
                method_id not in {"chatgpt-browser", "chatgpt-headless"}
                or value.get("model_access_supported") is not True
                or availability_reason is not None
            )
        )
        or (
            integration_id == "opencode"
            and (
                method_id != "device"
                or value.get("model_access_supported") is not False
                or availability_reason != "oauth_proxy_pending"
            )
        )
    ):
        return None
    return {
        "integration_id": integration_id,
        "method_id": method_id,
        "label": label,
        "mode": mode,
        "connection_status": connection_status,
        "connection_supported": value["connection_supported"],
        "model_access_supported": value["model_access_supported"],
        "availability_reason": availability_reason,
    }


def _oauth_connection_response(value: object) -> dict[str, object] | None:
    """Project one owner-scoped encrypted OAuth connection without vault data."""

    if not isinstance(value, Mapping):
        return None
    integration_id = value.get("integration_id")
    method_id = value.get("method_id")
    model_access_supported = value.get("model_access_supported")
    availability_reason = value.get("availability_reason")
    if (
        not isinstance(integration_id, str)
        or not isinstance(method_id, str)
        or (integration_id, method_id) not in _OAUTH_METHODS
        or value.get("status") != "connected"
        or (
            integration_id == "openai"
            and (model_access_supported is not True or availability_reason is not None)
        )
        or (
            integration_id == "opencode"
            and (
                model_access_supported is not False or availability_reason != "oauth_proxy_pending"
            )
        )
    ):
        return None
    return {
        "integration_id": integration_id,
        "method_id": method_id,
        "status": "connected",
        "model_access_supported": model_access_supported,
        "availability_reason": availability_reason,
    }


_OPENCODE_ADAPTERS = frozenset(
    {
        "openai-responses",
        "anthropic-messages",
        "google-generative-language",
        "openai-compatible-chat",
    }
)
_OPENCODE_PROTOCOLS = frozenset(
    {
        "openai-responses",
        "anthropic-messages",
        "google-generative-language",
        "openai-compatible-chat",
    }
)
_OPENCODE_PACKAGES = frozenset(
    {
        "@opencode/ai/providers/openai",
        "@opencode/ai/providers/anthropic",
        "@opencode/ai/providers/google",
        "@opencode/ai/providers/openai-compatible",
    }
)


def _opencode_public_url(value: object) -> str | None:
    """Accept a bounded public HTTPS URL from the already-filtered Console DTO."""

    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 2048:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    try:
        host_ip = ipaddress.ip_address(host) if host is not None else None
    except ValueError:
        host_ip = None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in {None, 443}
        or (host_ip is not None and not host_ip.is_global)
        or host in {"localhost", "localhost.localdomain"}
        or host.endswith((".localhost", ".local", ".test", ".example", ".invalid"))
        or "\\" in value
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        return None
    return value


def _opencode_model_review_response(value: object) -> dict[str, object] | None:
    """Project only the reviewed owner model row; never relay Console settings."""

    if not isinstance(value, Mapping):
        return None
    model_id = value.get("model_id")
    provider_id = value.get("provider_id")
    display_name = value.get("display_name")
    native_model_id = value.get("native_model_id")
    adapter_id = value.get("adapter_id")
    protocol = value.get("protocol")
    package_id = value.get("package_id")
    endpoint = _opencode_public_url(value.get("endpoint"))
    fingerprint = value.get("config_fingerprint")
    enabled = value.get("enabled")
    billing_class = value.get("billing_class")
    training_policy = value.get("training_policy")
    confidential_policy = value.get("confidential_data_policy")
    revision = value.get("revision")
    review_revision = value.get("review_revision")
    if (
        not isinstance(model_id, str)
        or _OPENCODE_MODEL_ID.fullmatch(model_id) is None
        or provider_id != "opencode-console"
        or not isinstance(display_name, str)
        or not 1 <= len(display_name.encode("utf-8")) <= 160
        or any(unicodedata.category(char).startswith("C") for char in display_name)
        or not isinstance(native_model_id, str)
        or not 1 <= len(native_model_id.encode("utf-8")) <= 160
        or any(unicodedata.category(char).startswith("C") for char in native_model_id)
        or adapter_id not in _OPENCODE_ADAPTERS
        or protocol not in _OPENCODE_PROTOCOLS
        or package_id not in _OPENCODE_PACKAGES
        or endpoint is None
        or not isinstance(fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
        or type(value.get("available")) is not bool
        or type(enabled) is not bool
        or type(value.get("reviewed")) is not bool
        or type(value.get("usable")) is not bool
        or type(revision) is not int
        or revision < 0
        or type(review_revision) is not int
        or review_revision < 0
        or billing_class not in {"unknown", "free", "paid"}
        or training_policy not in {"unknown", "no_training", "training_possible"}
        or confidential_policy not in {"unknown", "allowed", "prohibited"}
    ):
        return None
    nullable_text_fields = (
        "terms_url",
        "privacy_disclosure",
        "billing_disclosure",
        "privacy_policy_version",
        "billing_policy_version",
        "availability_reason",
    )
    projected: dict[str, object] = {
        "model_id": model_id,
        "provider_id": "opencode-console",
        "display_name": display_name,
        "native_model_id": native_model_id,
        "adapter_id": adapter_id,
        "protocol": protocol,
        "package_id": package_id,
        "endpoint": endpoint,
        "available": value["available"],
        "enabled": enabled,
        "reviewed": value["reviewed"],
        "billing_class": billing_class,
        "training_policy": training_policy,
        "confidential_data_policy": confidential_policy,
        "revision": revision,
        "review_revision": review_revision,
        "usable": value["usable"],
        "config_fingerprint": fingerprint,
    }
    for key in nullable_text_fields:
        item = value.get(key)
        if item is not None and (not isinstance(item, str) or len(item.encode("utf-8")) > 2048):
            return None
        if (
            key == "availability_reason"
            and item is not None
            and re.fullmatch(r"[a-z0-9_]{1,64}", item) is None
        ):
            return None
        if key == "terms_url" and item is not None:
            item = _opencode_public_url(item)
            if item is None:
                return None
        projected[key] = item
    return projected


def _oauth_authorization_url_allowed(
    integration_id: str, method_id: str, path: str, query: str
) -> bool:
    """Keep launch links on the exact source-reviewed method route and query vocabulary."""

    if integration_id == "openai" and method_id == "chatgpt-headless":
        return path == "/codex/device" and not query
    if integration_id == "openai" and method_id == "chatgpt-browser":
        if path != "/oauth/authorize":
            return False
        try:
            pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=10)
        except ValueError:
            return False
        fields = dict(pairs)
        expected = {
            "response_type": "code",
            "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
            "scope": "openid profile email offline_access",
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "opencode",
        }
        return (
            len(fields) == len(pairs) == 10
            and set(fields) == set(expected) | {"redirect_uri", "code_challenge", "state"}
            and all(fields[key] == item for key, item in expected.items())
            and fields["redirect_uri"] == "http://localhost:1455/auth/callback"
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", fields["code_challenge"]) is not None
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", fields["state"]) is not None
        )
    if integration_id == "opencode" and method_id == "device":
        if path != "/console/device":
            return False
        try:
            pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
        except ValueError:
            return False
        return (
            len(pairs) == 2
            and len(dict(pairs)) == len(pairs)
            and dict(pairs).get("client_id") == "opencode-cli"
            and re.fullmatch(r"[A-Za-z0-9-]{1,256}", dict(pairs).get("user_code", "")) is not None
        )
    return False


def _oauth_attempt_response(
    value: object, *, expected_attempt_id: str | None = None
) -> dict[str, object] | None:
    """Project an app-owned attempt; never serialize native IDs, errors, or credentials."""

    if not isinstance(value, Mapping):
        return None
    attempt_id = value.get("attempt_id")
    integration_id = value.get("integration_id")
    method_id = value.get("method_id")
    status = value.get("status")
    mode = value.get("mode")
    expires_at = value.get("expires_at")
    if (
        not isinstance(attempt_id, str)
        or _OAUTH_ID.fullmatch(attempt_id) is None
        or (expected_attempt_id is not None and attempt_id != expected_attempt_id)
        or not isinstance(integration_id, str)
        or _OAUTH_IDENTIFIER.fullmatch(integration_id) is None
        or not isinstance(method_id, str)
        or _OAUTH_IDENTIFIER.fullmatch(method_id) is None
        or status not in _OAUTH_STATUSES
        or mode not in _OAUTH_MODES
        or type(expires_at) not in {int, float}
        or not math.isfinite(float(expires_at))
    ):
        return None
    current = datetime.now(UTC).timestamp()
    if not current - 600 <= float(expires_at) <= current + 600:
        return None

    authorization_url = value.get("authorization_url")
    if authorization_url is not None:
        if (
            not isinstance(authorization_url, str)
            or len(authorization_url.encode("utf-8")) > 4096
            or any(unicodedata.category(char).startswith("C") for char in authorization_url)
            or "\\" in authorization_url
        ):
            return None
        try:
            parsed = urlsplit(authorization_url)
            port = parsed.port
            host = parsed.hostname
        except ValueError:
            return None
        try:
            parsed_ip = ipaddress.ip_address(host) if host is not None else None
        except ValueError:
            parsed_ip = None
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port not in {None, 443}
            or host not in _OAUTH_AUTHORIZATION_HOSTS.get(integration_id, frozenset())
            or (parsed_ip is not None and not parsed_ip.is_global)
            or host in {"localhost", "localhost.localdomain"}
            or host.endswith((".localhost", ".local", ".test", ".example", ".invalid"))
        ):
            return None
        if not _oauth_authorization_url_allowed(
            integration_id, method_id, parsed.path, parsed.query
        ):
            return None

    instructions = value.get("instructions")
    if instructions is not None and (
        not isinstance(instructions, str)
        or len(instructions.encode("utf-8")) > 2048
        or any(unicodedata.category(char).startswith("C") for char in instructions)
    ):
        return None
    return {
        "attempt_id": attempt_id,
        "integration_id": integration_id,
        "method_id": method_id,
        "status": status,
        "mode": mode,
        "expires_at": float(expires_at),
        "authorization_url": authorization_url,
        "instructions": instructions,
    }


def _json_safe_model_policy(value: Mapping[str, object]) -> dict[str, object]:
    """Return the reviewed model policy and non-sensitive provider capability projection."""

    result: dict[str, object] = {
        key: value[key][:4096]
        for key in _SAFE_MODEL_TEXT_FIELDS
        if key in value and isinstance(value[key], str)
    }
    result.update(
        {
            key: value[key]
            for key in _SAFE_MODEL_BOOL_FIELDS
            if key in value and isinstance(value[key], bool)
        }
    )
    if type(value.get("revision")) is int and value["revision"] >= 0:
        result["revision"] = value["revision"]
    billing_class = value.get("billing_class")
    if billing_class is None or (
        isinstance(billing_class, str) and billing_class in {"unknown", "free", "paid"}
    ):
        result["billing_class"] = billing_class
    consent = value.get("consent")
    if isinstance(consent, Mapping):
        accepted_at = consent.get("accepted_at")
        result["consent"] = {
            "accepted": consent.get("accepted") is True,
            "data_collection_opt_in": consent.get("data_collection_opt_in") is True,
            "accepted_at": accepted_at[:64] if isinstance(accepted_at, str) else None,
        }
    return result


def _loopback_client(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return False


def _validated_provider_request(
    value: object, app_tools: list[dict[str, object]]
) -> dict[str, object] | None:
    """Bound the native provider protocol to messages and tools the app actually registers."""

    if not isinstance(value, Mapping):
        return None
    allowed_fields = {
        "model",
        "messages",
        "stream",
        "temperature",
        "max_tokens",
        "tools",
        "tool_choice",
        "store",
        "stream_options",
    }
    if (
        set(value) - allowed_fields
        or value.get("model") != "assistant-selected"
        or value.get("stream") is not True
        or ("store" in value and value.get("store") is not False)
    ):
        return None
    stream_options = value.get("stream_options")
    if "stream_options" in value and (
        not isinstance(stream_options, Mapping) or dict(stream_options) != {"include_usage": True}
    ):
        return None

    declarations: dict[str, tuple[dict[str, object], str]] = {}
    for tool in app_tools:
        raw_name = str(tool["name"])
        # V2 location-scoped MCP declarations use the same server prefix granted
        # in that isolated location. Keep only this exact alias; accepting an
        # underscore variant would broaden the native provider tool surface.
        for name in (raw_name, "signal-ledger_" + raw_name.replace(".", "_")):
            declarations[name] = (
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": str(tool["description"]),
                        "parameters": tool["inputSchema"],
                        "strict": False,
                    },
                },
                raw_name,
            )
    websearch = _native_websearch_declaration()
    declarations["websearch"] = (websearch, "websearch")
    declarations["webfetch"] = (None, "webfetch")

    messages = value.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= _PROXY_MAX_MESSAGES:
        return None
    text_bytes = 0
    total_tool_calls = 0
    pending_calls: dict[str, str] = {}
    called_names: set[str] = set()
    normalized_messages: list[dict[str, object]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            return None
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or role not in {"system", "user", "assistant", "tool"}:
            return None
        if role == "tool":
            call_id = message.get("tool_call_id")
            if (
                set(message) != {"role", "tool_call_id", "content"}
                or not isinstance(call_id, str)
                or _PROXY_CALL_ID.fullmatch(call_id) is None
                or call_id not in pending_calls
                or not isinstance(content, str)
                or "\x00" in content
            ):
                return None
            content_length = _utf8_length(content)
            if content_length is None:
                return None
            text_bytes += content_length
            if text_bytes > _PROXY_MAX_MESSAGE_BYTES:
                return None
            pending_calls.pop(call_id)
            normalized_messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": content}
            )
            continue

        has_calls = "tool_calls" in message
        if has_calls:
            calls = message.get("tool_calls")
            if (
                role != "assistant"
                or set(message) != {"role", "content", "tool_calls"}
                or (content is not None and not isinstance(content, str))
                or not isinstance(calls, list)
                or not 1 <= len(calls) <= _PROXY_MAX_TOOL_CALLS
            ):
                return None
        elif set(message) != {"role", "content"} or not isinstance(content, str):
            return None
        if role != "assistant" and set(message) != {"role", "content"}:
            return None
        if content is not None and (not isinstance(content, str) or "\x00" in content):
            return None
        if isinstance(content, str):
            content_length = _utf8_length(content)
            if content_length is None:
                return None
            text_bytes += content_length
            if text_bytes > _PROXY_MAX_MESSAGE_BYTES:
                return None
        if pending_calls:
            return None

        normalized_message: dict[str, object] = {"role": role, "content": content}
        if has_calls:
            normalized_calls: list[dict[str, object]] = []
            for call in calls:
                if (
                    not isinstance(call, Mapping)
                    or set(call) != {"id", "type", "function"}
                    or call.get("type") != "function"
                ):
                    return None
                call_id = call.get("id")
                function = call.get("function")
                if (
                    not isinstance(call_id, str)
                    or _PROXY_CALL_ID.fullmatch(call_id) is None
                    or call_id in pending_calls
                    or not isinstance(function, Mapping)
                    or set(function) != {"name", "arguments"}
                ):
                    return None
                name = function.get("name")
                arguments = function.get("arguments")
                if not isinstance(name, str) or name not in declarations:
                    return None
                if (
                    not isinstance(arguments, str)
                    or (argument_length := _utf8_length(arguments)) is None
                    or argument_length > _PROXY_MAX_TOOL_ARGUMENT_BYTES
                    or "\x00" in arguments
                ):
                    return None
                try:
                    arguments_value = json.loads(
                        arguments,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                        object_pairs_hook=_unique_json_object,
                    )
                    if not isinstance(arguments_value, Mapping):
                        return None
                except (json.JSONDecodeError, TypeError, ValueError):
                    return None
                if declarations[name][1] == "websearch":
                    query = arguments_value.get("query")
                    if (
                        set(arguments_value) != {"query"}
                        or not isinstance(query, str)
                        or not query.strip()
                        or query != query.strip()
                        or (query_length := _utf8_length(query)) is None
                        or query_length > MAX_SEARCH_QUERY_BYTES
                        or any(
                            ord(character) < 32 and character not in "\t\n" for character in query
                        )
                    ):
                        return None
                if declarations[name][1] == "webfetch" and not _native_webfetch_arguments_valid(
                    arguments_value
                ):
                    return None
                total_tool_calls += 1
                if total_tool_calls > _PROXY_MAX_TOOL_CALLS:
                    return None
                pending_calls[call_id] = name
                called_names.add(name)
                normalized_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                )
            normalized_message["tool_calls"] = normalized_calls
        normalized_messages.append(normalized_message)

    if pending_calls:
        return None

    normalized: dict[str, object] = {
        "model": "assistant-selected",
        "messages": normalized_messages,
        "stream": True,
        # The provider call must stay non-retained even when the native adapter omits this flag.
        "store": False,
    }
    if stream_options is not None:
        normalized["stream_options"] = {"include_usage": True}
    temperature = value.get("temperature")
    if temperature is not None:
        if type(temperature) is int:
            if not 0 <= temperature <= 2:
                return None
            normalized["temperature"] = float(temperature)
        elif type(temperature) is float and math.isfinite(temperature) and 0 <= temperature <= 2:
            normalized["temperature"] = temperature
        else:
            return None
    max_tokens = value.get("max_tokens", native_output_token_budget())
    validated_max_tokens = validated_output_token_count(max_tokens)
    if validated_max_tokens is None:
        return None
    normalized["max_tokens"] = validated_max_tokens

    tools = value.get("tools")
    declared_names: set[str] = set()
    if tools is not None:
        if not isinstance(tools, list) or len(tools) > len(app_tools) + 2:
            return None
        seen: set[str] = set()
        canonical_seen: set[str] = set()
        copied: list[dict[str, object]] = []
        for tool in tools:
            if not isinstance(tool, Mapping) or set(tool) != {"type", "function"}:
                return None
            function = tool.get("function")
            if not isinstance(function, Mapping):
                return None
            name = function.get("name")
            if not isinstance(name, str) or name in seen or name not in declarations:
                return None
            expected, canonical_name = declarations[name]
            if canonical_name in canonical_seen:
                return None
            if canonical_name == "webfetch":
                if not _native_webfetch_declaration_matches(tool):
                    return None
                function = tool["function"]
                copied_tool = {
                    "type": "function",
                    "function": {
                        "name": "webfetch",
                        "description": function["description"],
                        "parameters": native_webfetch_schema("openai-compatible-chat"),
                        "strict": False,
                    },
                }
            elif expected is None or dict(tool) != expected:
                return None
            else:
                copied_tool = expected
            seen.add(name)
            canonical_seen.add(canonical_name)
            declared_names.add(name)
            copied.append(copied_tool)
        normalized["tools"] = copied
    if not called_names <= declared_names:
        return None
    choice = value.get("tool_choice")
    if choice is not None:
        tool_names = declared_names
        if not isinstance(choice, str) or choice not in {"auto", "none", *tool_names}:
            return None
        normalized["tool_choice"] = choice
    return normalized


def _strict_json_object(raw: bytes) -> dict[str, object] | None:
    """Parse one duplicate-free JSON object without accepting non-standard constants."""

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _native_session_correlation(request: Request) -> str | None:
    """Return native session correlation without treating it as authorization."""

    values = request.headers.getlist("session-id")
    if len(values) > 1:
        return None
    if not values:
        return ""
    value = values[0]
    return value if _NATIVE_SESSION_ID.fullmatch(value) is not None else None


def _native_zen_runtime_metadata(runtime: object, execution_id: str) -> tuple[str, str] | None:
    """Read active native session/project correlation without treating it as authorization."""

    reader = getattr(runtime, "native_provider_metadata", None)
    if not callable(reader):
        return None
    try:
        metadata = reader(execution_id)
    except Exception:
        return None
    if (
        not isinstance(metadata, tuple)
        or len(metadata) != 2
        or not all(isinstance(value, str) for value in metadata)
        or _native_zen_upstream_headers(None, None, metadata[0], metadata[1], None, None) is None
    ):
        return None
    return metadata


def _native_zen_request_identity(
    request: Request,
    *,
    expected_session: str,
    expected_project: str,
) -> dict[str, str] | None:
    """Return only allowlisted native Zen fields matching the active execution metadata."""

    values: dict[str, str | None] = {}
    for name in (
        "user-agent",
        "x-opencode-client",
        "x-opencode-session",
        "x-opencode-project",
        "x-session-affinity",
        "x-session-id",
        "session-id",
    ):
        field_values = request.headers.getlist(name)
        if len(field_values) > 1:
            return None
        values[name] = field_values[0] if field_values else None
    if (
        values["x-opencode-session"] != expected_session
        or values["x-opencode-project"] != expected_project
        or any(
            values[name] is not None and values[name] != expected_session
            for name in ("x-session-affinity", "x-session-id", "session-id")
        )
    ):
        return None
    return _native_zen_upstream_headers(
        values["user-agent"],
        values["x-opencode-client"],
        values["x-opencode-session"],
        values["x-opencode-project"],
        values["x-session-affinity"],
        values["x-session-id"],
    )


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AssistantConsentRequired)
    async def consent_error(_: Request, exc: AssistantConsentRequired) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error(
                exc.code, "Review the selected model terms and privacy policy to continue."
            ),
        )

    @app.exception_handler(AssistantUnavailable)
    async def unavailable_error(_: Request, exc: AssistantUnavailable) -> JSONResponse:
        message = {
            "not_found": "The requested assistant resource was not found.",
            "assistant_worker_unavailable": "The assistant runtime is unavailable.",
            "assistant_cache_clear_pending": (
                "The temporary conversation data could not be cleared yet. Retry deletion shortly."
            ),
            "assistant_consent_required": (
                "Review the selected model terms and privacy policy to continue."
            ),
            "context_preview_required": (
                "Review the page context before sending it to the selected model."
            ),
            "sensitive_input_rejected": (
                "Remove credentials or authentication material before sending this message."
            ),
            "invalid_tool_arguments": "The tool request is outside its supported fields.",
            "tool_unavailable": "That assistant capability is unavailable.",
            "tool_result_too_large": "The bounded tool result is too large to return.",
            "totp_step_up_required": (
                "Verify your authenticator code again before changing provider settings."
            ),
            "oauth_authorization_required": (
                "Administrator authorization changed during provider authorization."
            ),
        }.get(exc.code, "The assistant request could not be completed.")
        return JSONResponse(status_code=exc.status_code, content=_error(exc.code, message))

    @app.exception_handler(AssistantStorageNotFound)
    async def storage_not_found(_: Request, exc: AssistantStorageNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_error("not_found", "The requested assistant resource was not found."),
        )

    @app.exception_handler(AssistantStorageBusy)
    async def storage_busy(_: Request, exc: AssistantStorageBusy) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=_error(
                "assistant_busy", "An assistant turn is already active; wait for it to finish."
            ),
            headers={"Retry-After": "2"},
        )

    @app.exception_handler(AssistantStorageQuotaExceeded)
    async def storage_quota(_: Request, exc: AssistantStorageQuotaExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content=_error(
                "assistant_quota_exceeded",
                "Assistant history reached its storage limit. Delete a conversation to continue.",
            ),
        )

    @app.exception_handler(AssistantStorageConflict)
    async def storage_conflict(_: Request, exc: AssistantStorageConflict) -> JSONResponse:
        code = str(exc) if str(exc).replace("_", "").isalnum() else "assistant_conflict"
        return JSONResponse(
            status_code=409,
            content=_error(
                code,
                "The assistant record changed or the request is stale. Refresh it and try again.",
            ),
        )

    @app.exception_handler(AssistantStorageError)
    async def storage_error(_: Request, exc: AssistantStorageError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=_error(
                "assistant_storage_unavailable", "Assistant history is temporarily unavailable."
            ),
        )


def create_assistant_router(
    assistant: AssistantService,
    auth_manager: AuthManager,
    settings: Settings,
    get_auth_context: Callable[..., AuthContext],
) -> APIRouter:
    """Build exact, same-origin assistant routes around the current auth manager."""

    # Keep assistant's request-validation errors on the application's closed error envelope.
    # Import here because api.py registers this router after its own module initialization.
    from stock_probs.api import _documented_errors

    oauth_transport = OAuthTransport()
    manager_for_oauth = assistant.providers
    attach_oauth_transport = (
        getattr(manager_for_oauth, "attach_oauth_transport", None)
        if manager_for_oauth is not None
        else None
    )
    if callable(attach_oauth_transport):
        attach_oauth_transport(oauth_transport.register, oauth_transport.revoke)

    router = APIRouter(
        prefix="/api/v1/assistant",
        tags=["assistant"],
        responses=_documented_errors(400, 403, 404, 409, 411, 413, 422, 429, 500, 502, 503),
    )

    def browser_context(request: Request) -> AuthContext:
        context = get_auth_context(request)
        assistant.require_access(context)
        return context

    def admin_context(request: Request, *, step_up: bool = False) -> AuthContext:
        context = get_auth_context(request, role="admin", step_up=step_up)
        assistant.require_admin(context, step_up=step_up)
        return context

    def live_assistant_session(
        request: Request,
        original: AuthContext,
        *,
        admin: bool = False,
        step_up: bool = False,
        check_csrf: bool = False,
    ) -> AuthContext | None:
        """Re-read the same user/session before owner-scoped model work or persistence."""

        try:
            current = auth_manager.authenticate(
                request.cookies.get(SESSION_COOKIE_NAME), datetime.now(UTC)
            )
            if check_csrf:
                auth_manager.require_csrf(current, request.headers.get("x-csrf-token"))
            if admin:
                assistant.require_admin(current, step_up=step_up)
            else:
                assistant.require_access(current)
        except Exception:
            return None
        if (
            current.user.id != original.user.id
            or current.session_id != original.session_id
            or current.token_hash != original.token_hash
        ):
            return None
        return current

    def raise_opencode_inventory_failure(exc: Exception) -> NoReturn:
        """Map owner inventory/review failures to the fixed browser error vocabulary."""

        code = getattr(exc, "code", None)
        public = {
            "oauth_connection_required": ("oauth_connection_required", 409),
            "opencode_inventory_unavailable": ("opencode_inventory_unavailable", 503),
            "model_inventory_changed": ("model_inventory_changed", 409),
            "model_policy_conflict": ("model_policy_conflict", 409),
            "custom_policy_review_required": ("custom_policy_review_required", 422),
            "model_unavailable": ("model_unavailable", 404),
            "oauth_authorization_required": ("assistant_authorization_required", 403),
        }.get(code, ("opencode_inventory_unavailable", 503))
        raise AssistantUnavailable(*public) from None

    def provider_manager() -> object:
        if not settings.assistant_enabled or assistant.providers is None:
            raise AssistantUnavailable("provider_admin_unavailable", 503)
        return assistant.providers

    def live_oauth_admin(
        request: Request,
        original: AuthContext,
        *,
        step_up: bool,
        check_csrf: bool = True,
    ) -> AuthContext | None:
        """Re-read durable session and authorization state after a long OAuth operation."""

        try:
            current = auth_manager.authenticate(
                request.cookies.get(SESSION_COOKIE_NAME), datetime.now(UTC)
            )
            if check_csrf:
                auth_manager.require_csrf(current, request.headers.get("x-csrf-token"))
            assistant.require_admin(current, step_up=step_up)
        except Exception:
            return None
        if current.user.id != original.user.id or current.session_id != original.session_id:
            return None
        return current

    async def cancel_oauth_after_rejection(
        manager: object, attempt_id: str, auth: AuthContext
    ) -> None:
        """Best-effort release of a native lease when the issuing app session goes stale."""

        cancel = getattr(manager, "cancel_native_oauth", None)
        if callable(cancel) and _OAUTH_ID.fullmatch(attempt_id) is not None:
            # The manager expires volatile attempts and drops them on worker restart too.
            with suppress(Exception):
                await cancel(
                    attempt_id,
                    owner_id=auth.user.id,
                    session_id=auth.session_id,
                )

    def raise_oauth_failure(exc: Exception) -> NoReturn:
        """Map manager failures to a small public error set without rendering their text."""

        code = getattr(exc, "code", None)
        public = {
            "oauth_attempt_not_found": ("not_found", 404),
            "oauth_attempt_conflict": ("oauth_attempt_conflict", 409),
            "oauth_method_unavailable": ("oauth_method_unavailable", 422),
            "oauth_authorization_rejected": ("oauth_authorization_required", 403),
            "oauth_authorization_required": ("oauth_authorization_required", 403),
            "oauth_attempt_expired": ("oauth_attempt_expired", 409),
            "oauth_unavailable": ("oauth_unavailable", 503),
        }.get(code, ("oauth_unavailable", 503))
        raise AssistantUnavailable(*public) from None

    def authenticated_assistant_context(context: AuthContext) -> bool:
        return bool(
            context.user.active and context.auth_method == "github" and context.mfa_method == "totp"
        )

    @router.get("/status")
    async def status(request: Request) -> dict[str, object]:
        context = get_auth_context(request)
        if not authenticated_assistant_context(context):
            raise AssistantUnavailable("not_found", 404)
        admitted = assistant.can_access(context)
        if not settings.assistant_enabled or not admitted:
            return {
                "enabled": False,
                "available": False,
                "worker": {"status": "disabled", "reason": None},
                "authorization": {"role": context.user.role, "admitted": False},
                "limits": {
                    "active_per_user": 1,
                    "active_global": 2,
                    "tools_per_turn": 8,
                    "turn_seconds": 120,
                },
                "storage": None,
            }
        await assistant.refresh_runtime_status()
        result = assistant.status(context.user.id)
        result["authorization"] = {
            "role": context.user.role,
            "admitted": True,
            "rollout_mode": settings.assistant_rollout_mode,
        }
        return result

    @router.get("/models")
    async def models(request: Request) -> dict[str, object]:
        context = browser_context(request)
        inventory = await assistant.ensure_model_inventory(
            owner_id=context.user.id,
            authorization_check=lambda: live_assistant_session(request, context) is not None,
        )
        if live_assistant_session(request, context) is None:
            raise AssistantUnavailable("assistant_authorization_required", 403)
        return assistant.model_response(context.user.id, model_inventory=inventory)

    @router.get("/providers/opencode/models")
    async def opencode_models(request: Request) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        manager = provider_manager()
        ensure = getattr(manager, "ensure_opencode_model_inventory", None)
        summary_fn = getattr(manager, "opencode_inventory_summary", None)
        if not callable(ensure) or not callable(summary_fn):
            raise AssistantUnavailable("provider_admin_unavailable", 503)

        def authorization_check() -> bool:
            return (
                live_assistant_session(request, auth, admin=True, step_up=True, check_csrf=False)
                is not None
            )

        try:
            values = await ensure(owner_id=auth.user.id, authorization_check=authorization_check)
            summary = summary_fn(owner_id=auth.user.id)
        except Exception as exc:
            raise_opencode_inventory_failure(exc)
        if (
            not isinstance(values, list | tuple)
            or not isinstance(summary, Mapping)
            or type(summary.get("unsupported_model_count")) is not int
            or not 0 <= summary["unsupported_model_count"] <= 2048
        ):
            raise AssistantUnavailable("opencode_inventory_unavailable", 503)
        rows = [_opencode_model_review_response(value) for value in values]
        if any(row is None for row in rows):
            raise AssistantUnavailable("opencode_inventory_unavailable", 503)
        if live_assistant_session(request, auth, admin=True, step_up=True) is None:
            raise AssistantUnavailable("assistant_authorization_required", 403)
        return {
            "models": rows,
            "unsupported_model_count": summary["unsupported_model_count"],
        }

    @router.put("/providers/opencode/models/{model_id:path}/review")
    async def review_opencode_model(
        model_id: str, payload: AssistantOpenCodeModelReviewRequest, request: Request
    ) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        auth_manager.require_csrf(auth, request.headers.get("x-csrf-token"))
        if _OPENCODE_MODEL_ID.fullmatch(model_id) is None:
            raise AssistantUnavailable("model_unavailable", 404)
        manager = provider_manager()
        ensure = getattr(manager, "ensure_opencode_model_inventory", None)
        review = getattr(manager, "review_opencode_model", None)
        if not callable(ensure) or not callable(review):
            raise AssistantUnavailable("provider_admin_unavailable", 503)

        def authorization_check() -> bool:
            return (
                live_assistant_session(request, auth, admin=True, step_up=True, check_csrf=True)
                is not None
            )

        try:
            rows = await ensure(owner_id=auth.user.id, authorization_check=authorization_check)
            if not any(
                isinstance(row, Mapping) and row.get("model_id") == model_id for row in rows
            ):
                raise AssistantUnavailable("model_unavailable", 404)
            updated = await review(
                model_id,
                owner_id=auth.user.id,
                terms_url=payload.terms_url,
                privacy_disclosure=payload.privacy_disclosure,
                billing_disclosure=payload.billing_disclosure,
                billing_class=payload.billing_class,
                training_policy=payload.training_policy,
                confidential_data_policy=payload.confidential_data_policy,
                endpoint_policy_reviewed=payload.endpoint_policy_reviewed,
                expected_revision=payload.expected_revision,
                expected_config_fingerprint=payload.expected_config_fingerprint,
                authorization_check=authorization_check,
            )
        except AssistantUnavailable:
            raise
        except Exception as exc:
            raise_opencode_inventory_failure(exc)
        projected = _opencode_model_review_response(updated)
        if projected is None:
            raise AssistantUnavailable("opencode_inventory_unavailable", 503)
        if live_assistant_session(request, auth, admin=True, step_up=True, check_csrf=True) is None:
            raise AssistantUnavailable("assistant_authorization_required", 403)
        return {"model": projected}

    @router.delete("/providers/opencode/models/{model_id:path}/review")
    async def clear_opencode_model_review(
        model_id: str,
        request: Request,
        expected_revision: int = Query(ge=0, le=2_147_483_647),
    ) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        auth_manager.require_csrf(auth, request.headers.get("x-csrf-token"))
        if _OPENCODE_MODEL_ID.fullmatch(model_id) is None:
            raise AssistantUnavailable("model_unavailable", 404)
        manager = provider_manager()
        ensure = getattr(manager, "ensure_opencode_model_inventory", None)
        clear = getattr(manager, "clear_opencode_model_review", None)
        if not callable(ensure) or not callable(clear):
            raise AssistantUnavailable("provider_admin_unavailable", 503)

        def authorization_check() -> bool:
            return (
                live_assistant_session(request, auth, admin=True, step_up=True, check_csrf=True)
                is not None
            )

        try:
            rows = await ensure(owner_id=auth.user.id, authorization_check=authorization_check)
            if not any(
                isinstance(row, Mapping) and row.get("model_id") == model_id for row in rows
            ):
                raise AssistantUnavailable("model_unavailable", 404)
            cleared = await clear(
                model_id,
                owner_id=auth.user.id,
                expected_revision=expected_revision,
                authorization_check=authorization_check,
            )
        except AssistantUnavailable:
            raise
        except Exception as exc:
            raise_opencode_inventory_failure(exc)
        if cleared is not True or not authorization_check():
            raise AssistantUnavailable("assistant_authorization_required", 403)
        return {"model_id": model_id, "reviewed": False, "usable": False}

    @router.put("/models/{model_id:path}/policy")
    async def update_model_policy(
        model_id: str, payload: AssistantModelAdminPolicyRequest, request: Request
    ) -> dict[str, object]:
        context = admin_context(request, step_up=True)
        auth_manager.require_csrf(context, request.headers.get("x-csrf-token"))

        def authorization_check() -> bool:
            return (
                live_assistant_session(request, context, admin=True, step_up=True, check_csrf=True)
                is not None
            )

        inventory = await assistant.ensure_model_inventory(
            owner_id=context.user.id, authorization_check=authorization_check
        )
        if not assistant.has_model_in_inventory(model_id, inventory):
            raise AssistantUnavailable("model_unavailable", 404)
        manager = provider_manager()
        updater = getattr(manager, "update_model_policy", None)
        if not callable(updater):
            raise AssistantUnavailable("model_policy_admin_unavailable", 503)
        try:
            updated = updater(
                model_id,
                enabled=payload.enabled,
                acknowledged_privacy_policy_version=payload.acknowledged_privacy_policy_version,
                acknowledged_billing_policy_version=payload.acknowledged_billing_policy_version,
                expected_revision=payload.expected_revision,
                owner_id=context.user.id,
            )
        except Exception as exc:
            code = getattr(exc, "code", "model_policy_update_failed")
            if code == "model_policy_conflict":
                raise AssistantStorageConflict("model_policy_conflict") from None
            if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
                code = "model_policy_update_failed"
            raise AssistantUnavailable(code, 422) from None

        # The provider manager returns only its closed reviewed DTO. Join it with the user's
        # current consent projection, then whitelist the exact browser-visible fields again.
        response = assistant.model_response(context.user.id, model_inventory=inventory)
        models = response.get("items", [])
        model_row = next(
            (
                dict(item)
                for item in models
                if isinstance(item, Mapping) and item.get("model_id") == model_id
            ),
            {},
        )
        if isinstance(updated, Mapping) and updated.get("model_id") == model_id:
            for key in _SAFE_MODEL_POLICY_FIELDS:
                value = updated.get(key)
                if value is not None and isinstance(value, str | bool | int):
                    model_row[key] = value
        if not model_row or model_row.get("model_id") != model_id:
            raise AssistantUnavailable("model_unavailable", 404)
        if not authorization_check():
            raise AssistantUnavailable("assistant_authorization_required", 403)
        return {"model": _json_safe_model_policy(model_row)}

    # Catalog model identifiers contain provider/model separators. The path converter keeps
    # that complete identity available after ASGI has decoded an encoded slash.
    @router.put("/models/{model_id:path}/consent")
    async def consent(
        model_id: str, payload: AssistantConsentRequest, request: Request
    ) -> dict[str, object]:
        context = browser_context(request)
        auth_manager.require_csrf(context, request.headers.get("x-csrf-token"))

        def authorization_check() -> bool:
            return live_assistant_session(request, context) is not None

        inventory = await assistant.ensure_model_inventory(
            owner_id=context.user.id, authorization_check=authorization_check
        )
        if not assistant.has_model_in_inventory(model_id, inventory):
            raise AssistantUnavailable("model_unavailable", 503)
        result = assistant.consent_response(
            context.user.id,
            model_id,
            policy_version=payload.policy_version,
            accepted_terms=payload.accepted_terms,
            data_collection_opt_in=payload.data_collection_opt_in,
            model_inventory=inventory,
        )
        if not authorization_check():
            raise AssistantUnavailable("assistant_authorization_required", 403)
        return result

    @router.get("/context")
    def context_preview(request: Request) -> dict[str, object]:
        auth = browser_context(request)
        # Parse the small query contract explicitly so unknown and duplicate keys fail closed.
        allowed = {"route", "symbol", "asset_type", "provider", "exchange", "event_id", "result_id"}
        if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
            raise AssistantUnavailable("duplicate_context_query", 422)
        params = dict(request.query_params)
        if set(params) - allowed:
            raise AssistantUnavailable("invalid_context_query", 422)
        for key in ("event_id", "result_id"):
            value = params.get(key)
            if value is not None:
                if not value.isascii() or not value.isdecimal() or len(value) > 10:
                    raise AssistantUnavailable("invalid_context_query", 422)
                params[key] = int(value)
        try:
            parsed = AssistantContextQuery.model_validate(params)
        except ValidationError:
            raise AssistantUnavailable("invalid_context_query", 422) from None
        if parsed.route == "/admin":
            assistant.require_admin(auth)
        return assistant.resolve_context(auth.user.id, parsed)

    @router.post("/conversations", status_code=201)
    def create_conversation(
        payload: AssistantConversationCreateRequest, request: Request
    ) -> dict[str, object]:
        auth = browser_context(request)
        return {
            "conversation": assistant.conversation_create(
                auth.user.id, title=payload.title, context=payload.context
            )
        }

    @router.get("/conversations")
    def conversations(
        request: Request,
        page: int = Query(1, ge=1, le=10_000),
        page_size: int = Query(20, ge=1, le=50),
    ) -> dict[str, object]:
        auth = browser_context(request)
        return assistant.storage.list_conversations(auth.user.id, page=page, page_size=page_size)

    @router.get("/conversations/{conversation_id}")
    def get_conversation(
        conversation_id: str,
        request: Request,
        message_page: int = Query(1, ge=1, le=10_000),
        message_page_size: int = Query(50, ge=1, le=100),
        event_page: int = Query(1, ge=1, le=10_000),
        event_page_size: int = Query(100, ge=1, le=200),
        action_page: int = Query(1, ge=1, le=10_000),
        action_page_size: int = Query(100, ge=1, le=200),
    ) -> dict[str, object]:
        auth = browser_context(request)
        return assistant.conversation_detail(
            auth,
            conversation_id,
            message_page=message_page,
            message_page_size=message_page_size,
            event_page=event_page,
            event_page_size=event_page_size,
            action_page=action_page,
            action_page_size=action_page_size,
        )

    @router.patch("/conversations/{conversation_id}")
    def rename_conversation(
        conversation_id: str,
        payload: AssistantConversationUpdateRequest,
        request: Request,
    ) -> dict[str, object]:
        auth = browser_context(request)
        conversation = assistant.storage.rename_conversation(
            auth.user.id,
            conversation_id,
            title=payload.title,
            expected_revision=payload.expected_revision,
            updated_at=assistant.now(),
        )
        return {"conversation": conversation["conversation"]}

    @router.delete("/conversations/{conversation_id}")
    async def delete_conversation(
        conversation_id: str,
        payload: AssistantConversationDeleteRequest,
        request: Request,
    ) -> dict[str, object]:
        auth = browser_context(request)
        return await assistant.delete_conversation(
            auth,
            conversation_id,
            expected_revision=payload.expected_revision,
            confirmation_phrase=payload.confirmation_phrase,
        )

    @router.post("/conversations/{conversation_id}/turns", status_code=202)
    async def create_turn(
        conversation_id: str,
        payload: AssistantTurnCreateRequest,
        request: Request,
    ) -> dict[str, object]:
        auth = browser_context(request)
        return await assistant.create_turn(
            auth,
            conversation_id,
            prompt=payload.prompt,
            model_id=payload.model_id,
            policy_version=payload.policy_version,
            page_context=payload.context,
            context_preview_accepted=payload.context_preview_accepted,
        )

    @router.post("/conversations/{conversation_id}/turns/{turn_id}/cancel")
    async def cancel_turn(
        conversation_id: str, turn_id: str, request: Request
    ) -> dict[str, object]:
        return await assistant.cancel_turn(browser_context(request), conversation_id, turn_id)

    @router.get("/conversations/{conversation_id}/turns/{turn_id}/events")
    async def stream_events(
        conversation_id: str,
        turn_id: str,
        request: Request,
        after: int | None = Query(default=None, ge=0),
    ) -> StreamingResponse:
        initial = browser_context(request)
        header_cursor = request.headers.get("last-event-id")
        if header_cursor is not None:
            if (
                not header_cursor.isascii()
                or not header_cursor.isdecimal()
                or len(header_cursor) > 12
            ):
                raise AssistantUnavailable("invalid_event_cursor", 422)
            parsed_header_cursor = int(header_cursor)
            if after is not None and after != parsed_header_cursor:
                raise AssistantUnavailable("conflicting_event_cursor", 422)
            after_value = parsed_header_cursor
        else:
            after_value = after or 0
        assistant.storage.get_turn(initial.user.id, conversation_id, turn_id)
        latest = assistant.storage.latest_event_sequence(initial.user.id, conversation_id, turn_id)
        if after_value > latest + 1:
            raise AssistantUnavailable("event_cursor_ahead", 409)
        cookie = request.cookies.get(SESSION_COOKIE_NAME)

        async def events():
            cursor = after_value
            while True:
                if await request.is_disconnected():
                    return
                try:
                    current = auth_manager.authenticate(cookie, datetime.now(UTC))
                    assistant.require_access(current)
                    current_turn = assistant.storage.get_turn(
                        current.user.id, conversation_id, turn_id
                    )
                    if current_turn.get("status") in {"queued", "running"}:
                        lease_ref = assistant.storage.execution_for_turn(
                            current.user.id, conversation_id, turn_id
                        )
                        lease = (
                            assistant.storage.execution_lease(str(lease_ref["execution_id"]))
                            if lease_ref
                            else None
                        )
                        if lease is None or not assistant._execution_current(
                            current.user.id,
                            str(lease["execution_id"]),
                            str(current_turn["model_id"]),
                            str(current_turn["policy_version"]),
                        ):
                            return
                    batch = assistant.storage.events_after(
                        current.user.id, conversation_id, turn_id, after=cursor, limit=100
                    )
                except Exception:
                    return
                if batch:
                    for event in batch:
                        # Revalidate on every emitted chunk; a long stream cannot rely on its
                        # initial role, current session, TOTP factor, or model-consent snapshot.
                        try:
                            current = auth_manager.authenticate(cookie, datetime.now(UTC))
                            assistant.require_access(current)
                            current_turn = assistant.storage.get_turn(
                                current.user.id, conversation_id, turn_id
                            )
                            if current_turn.get("status") in {"queued", "running"}:
                                lease_ref = assistant.storage.execution_for_turn(
                                    current.user.id, conversation_id, turn_id
                                )
                                lease = (
                                    assistant.storage.execution_lease(
                                        str(lease_ref["execution_id"])
                                    )
                                    if lease_ref
                                    else None
                                )
                                if lease is None or not assistant._execution_current(
                                    current.user.id,
                                    str(lease["execution_id"]),
                                    str(current_turn["model_id"]),
                                    str(current_turn["policy_version"]),
                                ):
                                    return
                        except Exception:
                            return
                        cursor = int(event["sequence"])
                        projected = assistant.project_event_for_browser(current, event)
                        data = json.dumps(
                            projected["data"], ensure_ascii=False, separators=(",", ":")
                        )
                        yield f"id: {cursor}\nevent: {event['type']}\ndata: {data}\n\n"
                        if event["type"] == "complete":
                            return
                    continue
                if current_turn.get("status") not in {"queued", "running"}:
                    terminal_cursor = assistant.storage.latest_event_sequence(
                        current.user.id, conversation_id, turn_id
                    )
                    has_complete = any(
                        item["type"] == "complete"
                        for item in assistant.storage.events_after(
                            current.user.id,
                            conversation_id,
                            turn_id,
                            after=max(0, terminal_cursor - 2),
                            limit=4,
                        )
                    )
                    if not has_complete and cursor <= terminal_cursor:
                        status = str(current_turn.get("status", "failed"))
                        completion = json.dumps({"status": status})
                        yield (
                            f"id: {terminal_cursor + 1}\nevent: complete\ndata: {completion}\n\n"
                        )
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @router.post("/conversations/{conversation_id}/actions/{action_id}/confirm")
    def confirm_action(
        conversation_id: str,
        action_id: str,
        payload: AssistantActionConfirmationRequest,
        request: Request,
    ) -> dict[str, object]:
        auth = browser_context(request)
        return assistant.confirm_action(
            auth,
            conversation_id,
            action_id,
            action_version=payload.action_version,
            page_context=payload.context,
            confirmation_phrase=payload.confirmation_phrase,
            allow=payload.allow,
        )

    @router.get("/conversations/{conversation_id}/turns/{turn_id}/search-previews/{preview_id}")
    def get_search_preview(
        conversation_id: str, turn_id: str, preview_id: str, request: Request
    ) -> dict[str, object]:
        auth = browser_context(request)
        return assistant.storage.get_search_preview(
            auth.user.id, conversation_id, turn_id, preview_id
        )

    @router.post(
        "/conversations/{conversation_id}/turns/{turn_id}/search-previews/{preview_id}/confirm"
    )
    def confirm_search_preview(
        conversation_id: str,
        turn_id: str,
        preview_id: str,
        payload: AssistantSearchPreviewConfirmationRequest,
        request: Request,
    ) -> dict[str, object]:
        auth = browser_context(request)
        return assistant.confirm_search_preview(
            auth,
            conversation_id,
            turn_id,
            preview_id,
            page_context=payload.context,
            context_version=payload.context_version,
            confirmation_phrase=payload.confirmation_phrase,
            allow=payload.allow,
        )

    @router.get("/conversations/{conversation_id}/turns/{turn_id}/webfetch-previews/{preview_id}")
    def get_webfetch_preview(
        conversation_id: str, turn_id: str, preview_id: str, request: Request
    ) -> dict[str, object]:
        auth = browser_context(request)
        return assistant.get_webfetch_preview(auth, conversation_id, turn_id, preview_id)

    @router.post(
        "/conversations/{conversation_id}/turns/{turn_id}/webfetch-previews/{preview_id}/confirm"
    )
    def confirm_webfetch_preview(
        conversation_id: str,
        turn_id: str,
        preview_id: str,
        payload: AssistantWebfetchPreviewConfirmationRequest,
        request: Request,
    ) -> dict[str, object]:
        auth = browser_context(request)
        return assistant.confirm_webfetch_preview(
            auth,
            conversation_id,
            turn_id,
            preview_id,
            page_context=payload.context,
            context_version=payload.context_version,
            confirmation_phrase=payload.confirmation_phrase,
            allow=payload.allow,
        )

    @router.get("/providers")
    def providers(request: Request) -> dict[str, object]:
        admin_context(request)
        manager = provider_manager()
        lister = getattr(manager, "list_providers", None)
        values = lister() if callable(lister) else ()
        if not isinstance(values, list | tuple):
            values = ()
        return {"providers": [_provider_capability_response(value) for value in values]}

    @router.get("/providers/oauth/methods")
    async def native_oauth_methods(request: Request) -> dict[str, object]:
        admin_context(request)
        manager = provider_manager()
        lister = getattr(manager, "list_native_oauth_methods", None)
        if not callable(lister):
            raise AssistantUnavailable("oauth_unavailable", 503)
        try:
            values = await lister()
        except Exception as exc:
            raise_oauth_failure(exc)
        if not isinstance(values, list | tuple):
            raise AssistantUnavailable("oauth_unavailable", 503)
        methods = [_oauth_method_response(value) for value in values]
        if any(value is None for value in methods):
            raise AssistantUnavailable("oauth_unavailable", 503)
        return {"methods": methods}

    @router.get("/providers/oauth/connections")
    async def native_oauth_connections(request: Request) -> dict[str, object]:
        auth = admin_context(request)
        manager = provider_manager()
        lister = getattr(manager, "list_native_oauth_connections", None)
        if not callable(lister):
            raise AssistantUnavailable("oauth_unavailable", 503)
        try:
            values = await lister(owner_id=auth.user.id)
        except Exception as exc:
            raise_oauth_failure(exc)
        if not isinstance(values, list | tuple):
            raise AssistantUnavailable("oauth_unavailable", 503)
        connections = [_oauth_connection_response(value) for value in values]
        if any(value is None for value in connections):
            raise AssistantUnavailable("oauth_unavailable", 503)
        if live_oauth_admin(request, auth, step_up=False, check_csrf=False) is None:
            raise AssistantUnavailable("oauth_session_expired", 403)
        return {"connections": connections}

    @router.get("/providers/oauth/attempts")
    async def native_oauth_attempts(request: Request) -> dict[str, object]:
        auth = admin_context(request)
        manager = provider_manager()
        lister = getattr(manager, "list_native_oauth_attempts", None)
        if not callable(lister):
            raise AssistantUnavailable("oauth_unavailable", 503)
        try:
            values = await lister(owner_id=auth.user.id, session_id=auth.session_id)
        except Exception as exc:
            raise_oauth_failure(exc)
        if not isinstance(values, list | tuple) or len(values) > 32:
            raise AssistantUnavailable("oauth_unavailable", 503)
        attempts = [_oauth_attempt_response(value) for value in values]
        if any(value is None for value in attempts):
            raise AssistantUnavailable("oauth_unavailable", 503)
        if live_oauth_admin(request, auth, step_up=False, check_csrf=False) is None:
            raise AssistantUnavailable("oauth_session_expired", 403)
        return {"attempts": attempts}

    @router.post("/providers/oauth/attempts")
    async def begin_native_oauth(
        payload: AssistantOAuthAttemptCreateRequest, request: Request
    ) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        manager = provider_manager()
        begin = getattr(manager, "begin_native_oauth", None)
        if not callable(begin):
            raise AssistantUnavailable("oauth_unavailable", 503)
        try:
            value = await begin(
                payload.provider_id,
                payload.method_id,
                owner_id=auth.user.id,
                session_id=auth.session_id,
                session_token_hash=auth.token_hash,
            )
        except Exception as exc:
            raise_oauth_failure(exc)
        attempt = _oauth_attempt_response(value)
        if (
            attempt is None
            or attempt["status"] != "pending"
            or attempt["integration_id"] != payload.provider_id
            or attempt["method_id"] != payload.method_id
        ):
            if isinstance(value, Mapping) and isinstance(value.get("attempt_id"), str):
                await cancel_oauth_after_rejection(manager, value["attempt_id"], auth)
            raise AssistantUnavailable("oauth_unavailable", 503)
        if live_oauth_admin(request, auth, step_up=True) is None:
            await cancel_oauth_after_rejection(manager, attempt["attempt_id"], auth)
            raise AssistantUnavailable("oauth_authorization_required", 403)
        return {"attempt": attempt}

    @router.get("/providers/oauth/attempts/{attempt_id}")
    async def native_oauth_attempt_status(attempt_id: str, request: Request) -> dict[str, object]:
        auth = admin_context(request)
        if _OAUTH_ID.fullmatch(attempt_id) is None:
            raise AssistantUnavailable("not_found", 404)
        manager = provider_manager()
        status = getattr(manager, "native_oauth_status", None)
        if not callable(status):
            raise AssistantUnavailable("oauth_unavailable", 503)
        try:
            value = await status(
                attempt_id,
                owner_id=auth.user.id,
                session_id=auth.session_id,
            )
        except Exception as exc:
            raise_oauth_failure(exc)
        attempt = _oauth_attempt_response(value, expected_attempt_id=attempt_id)
        if attempt is None:
            raise AssistantUnavailable("not_found", 404)
        if live_oauth_admin(request, auth, step_up=False, check_csrf=False) is None:
            await cancel_oauth_after_rejection(manager, attempt_id, auth)
            raise AssistantUnavailable("oauth_session_expired", 403)
        return {"attempt": attempt}

    @router.post("/providers/oauth/attempts/{attempt_id}/complete")
    async def complete_native_oauth(
        attempt_id: str, payload: AssistantOAuthAttemptCompleteRequest, request: Request
    ) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        if _OAUTH_ID.fullmatch(attempt_id) is None:
            raise AssistantUnavailable("not_found", 404)
        manager = provider_manager()
        complete = getattr(manager, "complete_native_oauth", None)
        if not callable(complete):
            raise AssistantUnavailable("oauth_unavailable", 503)

        async def authorization_check() -> bool:
            return live_oauth_admin(request, auth, step_up=True) is not None

        try:
            value = await complete(
                attempt_id,
                owner_id=auth.user.id,
                session_id=auth.session_id,
                code=payload.code,
                authorization_check=authorization_check,
            )
        except Exception as exc:
            if live_oauth_admin(request, auth, step_up=True) is None:
                await cancel_oauth_after_rejection(manager, attempt_id, auth)
                raise AssistantUnavailable("oauth_authorization_required", 403) from None
            raise_oauth_failure(exc)
        attempt = _oauth_attempt_response(value, expected_attempt_id=attempt_id)
        if attempt is None:
            await cancel_oauth_after_rejection(manager, attempt_id, auth)
            raise AssistantUnavailable("oauth_unavailable", 503)
        if live_oauth_admin(request, auth, step_up=True) is None:
            raise AssistantUnavailable("oauth_authorization_required", 403)
        return {"attempt": attempt}

    @router.post("/providers/oauth/attempts/{attempt_id}/callback")
    async def submit_native_oauth_callback(
        attempt_id: str, payload: AssistantOAuthAttemptCallbackRequest, request: Request
    ) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        if _OAUTH_ID.fullmatch(attempt_id) is None:
            raise AssistantUnavailable("not_found", 404)
        manager = provider_manager()
        callback = getattr(manager, "submit_native_oauth_callback", None)
        if not callable(callback):
            raise AssistantUnavailable("oauth_unavailable", 503)
        try:
            value = await callback(
                attempt_id,
                owner_id=auth.user.id,
                session_id=auth.session_id,
                callback_url=payload.callback_url,
            )
        except Exception as exc:
            if live_oauth_admin(request, auth, step_up=True) is None:
                await cancel_oauth_after_rejection(manager, attempt_id, auth)
                raise AssistantUnavailable("oauth_authorization_required", 403) from None
            raise_oauth_failure(exc)
        attempt = _oauth_attempt_response(value, expected_attempt_id=attempt_id)
        if attempt is None:
            await cancel_oauth_after_rejection(manager, attempt_id, auth)
            raise AssistantUnavailable("oauth_unavailable", 503)
        if live_oauth_admin(request, auth, step_up=True) is None:
            await cancel_oauth_after_rejection(manager, attempt_id, auth)
            raise AssistantUnavailable("oauth_authorization_required", 403)
        return {"attempt": attempt}

    @router.delete("/providers/oauth/attempts/{attempt_id}")
    async def cancel_native_oauth(attempt_id: str, request: Request) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        if _OAUTH_ID.fullmatch(attempt_id) is None:
            raise AssistantUnavailable("not_found", 404)
        manager = provider_manager()
        cancel = getattr(manager, "cancel_native_oauth", None)
        if not callable(cancel):
            raise AssistantUnavailable("oauth_unavailable", 503)
        try:
            value = await cancel(
                attempt_id,
                owner_id=auth.user.id,
                session_id=auth.session_id,
            )
        except Exception as exc:
            raise_oauth_failure(exc)
        attempt = _oauth_attempt_response(value, expected_attempt_id=attempt_id)
        if attempt is None or attempt["status"] != "cancelled":
            raise AssistantUnavailable("oauth_unavailable", 503)
        if live_oauth_admin(request, auth, step_up=True) is None:
            raise AssistantUnavailable("oauth_authorization_required", 403)
        return {"attempt": attempt}

    @router.delete("/providers/oauth/connections/{integration_id}/{method_id}")
    async def clear_native_oauth_connection(
        integration_id: str, method_id: str, request: Request
    ) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        if (
            _OAUTH_IDENTIFIER.fullmatch(integration_id) is None
            or _OAUTH_IDENTIFIER.fullmatch(method_id) is None
            or (integration_id, method_id) not in _OAUTH_METHODS
        ):
            raise AssistantUnavailable("not_found", 404)
        manager = provider_manager()
        clear = getattr(manager, "clear_native_oauth_connection", None)
        if not callable(clear):
            raise AssistantUnavailable("oauth_unavailable", 503)

        async def authorization_check() -> bool:
            return live_oauth_admin(request, auth, step_up=True) is not None

        try:
            cleared = await clear(
                integration_id,
                method_id,
                owner_id=auth.user.id,
                authorization_check=authorization_check,
            )
        except Exception as exc:
            if live_oauth_admin(request, auth, step_up=True) is None:
                raise AssistantUnavailable("oauth_authorization_required", 403) from None
            raise_oauth_failure(exc)
        if cleared is not True:
            raise AssistantUnavailable("oauth_unavailable", 503)
        if live_oauth_admin(request, auth, step_up=True) is None:
            raise AssistantUnavailable("oauth_authorization_required", 403)
        return {
            "connection": {
                "integration_id": integration_id,
                "method_id": method_id,
                "status": "disconnected",
                "model_access_supported": False,
                "availability_reason": "oauth_proxy_pending",
            }
        }

    @router.put("/providers/custom")
    def configure_custom_provider(
        payload: AssistantCustomProviderEndpointRequest, request: Request
    ) -> dict[str, object]:
        admin_context(request, step_up=True)
        manager = provider_manager()
        configure = getattr(manager, "configure_custom_endpoint", None)
        if not callable(configure):
            raise AssistantUnavailable("provider_admin_unavailable", 503)
        try:
            updated = configure(
                base_url=payload.base_url,
                terms_url=payload.terms_url,
                privacy_disclosure=payload.privacy_disclosure,
                billing_disclosure=payload.billing_disclosure,
                billing_class=payload.billing_class,
                endpoint_policy_reviewed=payload.endpoint_policy_reviewed,
                credential=payload.credential,
                model_id=payload.model_id,
            )
        except Exception as exc:
            code = getattr(exc, "code", "provider_unavailable")
            if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
                code = "provider_unavailable"
            raise AssistantUnavailable(code, 422) from None
        return {"provider": _provider_capability_response(updated)}

    @router.put("/providers/{provider_id}")
    def update_provider(
        provider_id: str, payload: AssistantProviderUpdateRequest, request: Request
    ) -> dict[str, object]:
        admin_context(request, step_up=True)
        manager = provider_manager()
        if provider_id == "custom":
            raise AssistantUnavailable("custom_provider_review_required", 422)
        if payload.model_id is None and payload.base_url is None and payload.credential is None:
            raise AssistantUnavailable("empty_provider_update", 422)
        updater = getattr(manager, "update_provider", None)
        if not callable(updater):
            # Never sequence independent durable writes: rejected combined settings must not
            # leave a partially changed provider record.
            raise AssistantUnavailable("provider_admin_unavailable", 503)
        try:
            updated = updater(
                provider_id,
                model_id=payload.model_id,
                base_url=payload.base_url,
                credential=payload.credential,
            )
        except Exception as exc:
            code = getattr(exc, "code", "provider_unavailable")
            if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
                code = "provider_unavailable"
            raise AssistantUnavailable(code, 422) from None
        public = _json_safe_provider(updated)
        if not public:
            public = next(
                (
                    _json_safe_provider(item)
                    for item in manager.list_providers()
                    if _json_safe_provider(item).get("provider_id") == provider_id
                ),
                {},
            )
        return {"provider": public}

    @router.delete("/providers/{provider_id}")
    def clear_provider(provider_id: str, request: Request) -> dict[str, object]:
        admin_context(request, step_up=True)
        if provider_id == "custom":
            raise AssistantUnavailable("custom_provider_review_required", 422)
        manager = provider_manager()
        manager.clear_credential(provider_id)
        return {"providers": [_json_safe_provider(item) for item in manager.list_providers()]}

    @router.post("/internal/oauth")
    async def internal_oauth_egress(request: Request) -> Response:
        """Serve fixed OAuth operations for one active admin-bound native attempt."""

        denied = JSONResponse(
            status_code=404,
            content=_error("not_found", "The requested assistant resource was not found."),
        )
        if (
            request.method != "POST"
            or request.url.query
            or not _loopback_client(request)
            or request.headers.get("origin") is not None
            or request.headers.get("referer") is not None
            or request.headers.get("cookie") is not None
            or any(name.lower().startswith("sec-fetch-") for name in request.headers)
            or request.headers.get("x-csrf-token") is not None
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            return denied
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) != 39:
            return denied
        capability = authorization[7:]
        if re.fullmatch(r"[0-9a-f]{32}", capability) is None:
            return denied
        content_length = request.headers.get("content-length")
        if content_length is not None and (
            not content_length.isascii()
            or not content_length.isdecimal()
            or int(content_length) > 16_384
        ):
            return JSONResponse(
                status_code=413,
                content=_error("invalid_oauth_request", "The OAuth request is invalid."),
            )
        raw = bytearray()
        try:
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 16_384:
                    return JSONResponse(
                        status_code=413,
                        content=_error("invalid_oauth_request", "The OAuth request is invalid."),
                    )
                raw.extend(chunk)
        except Exception:
            return JSONResponse(
                status_code=400,
                content=_error("invalid_oauth_request", "The OAuth request is invalid."),
            )
        envelope = _strict_json_object(bytes(raw))
        if (
            envelope is None
            or set(envelope) != {"attempt_id", "operation", "input"}
            or not isinstance(envelope.get("attempt_id"), str)
            or _OAUTH_ID.fullmatch(str(envelope["attempt_id"])) is None
            or not isinstance(envelope.get("operation"), str)
            or not isinstance(envelope.get("input"), Mapping)
        ):
            return JSONResponse(
                status_code=422,
                content=_error(
                    "invalid_oauth_request", "The OAuth request is outside its fixed contract."
                ),
            )
        try:
            binding = await oauth_transport.authorize(
                str(envelope["attempt_id"]), capability, str(envelope["operation"])
            )
        except OAuthTransportError:
            return denied

        def live_admin() -> bool:
            current = assistant._live_auth_context(
                user_id=binding.owner_id,
                session_id=binding.session_id,
                token_hash=binding.session_token_hash,
            )
            if current is None:
                return False
            try:
                assistant.require_admin(current, step_up=True)
            except AssistantUnavailable:
                return False
            return current.user.id == binding.owner_id and current.session_id == binding.session_id

        try:
            if not await oauth_transport.is_current(binding) or not live_admin():
                await oauth_transport.revoke(binding.attempt_id)
                return denied
            try:
                result = await oauth_transport.perform(
                    str(envelope["operation"]), envelope["input"]
                )
            except OAuthTransportError as exc:
                status_code = 422 if exc.code == "oauth_request_invalid" else 502
                error_code = (
                    "invalid_oauth_request" if status_code == 422 else "oauth_provider_unavailable"
                )
                return JSONResponse(
                    status_code=status_code,
                    content=_error(
                        error_code,
                        "The OAuth request is invalid."
                        if status_code == 422
                        else "The authorization provider is unavailable.",
                    ),
                )
            if not await oauth_transport.is_current(binding) or not live_admin():
                await oauth_transport.revoke(binding.attempt_id)
                return denied
            return JSONResponse({"result": result}, headers={"Cache-Control": "no-store"})
        finally:
            await oauth_transport.release(binding)

    @router.post("/providers/{provider_id}/validate")
    async def validate_provider(provider_id: str, request: Request) -> dict[str, object]:
        auth = admin_context(request, step_up=True)
        body = await request.body()
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                raise AssistantUnavailable("invalid_provider_request", 422) from None
            if parsed != {}:
                raise AssistantUnavailable("invalid_provider_request", 422)

        def authorization_check() -> bool:
            return live_assistant_session(request, auth, admin=True, step_up=True) is not None

        if not authorization_check():
            raise AssistantUnavailable("oauth_authorization_required", 403)
        manager = provider_manager()
        try:
            result = await manager.validate(provider_id, authorization_check=authorization_check)
        except Exception:
            if not authorization_check():
                raise AssistantUnavailable("oauth_authorization_required", 403) from None
            raise
        if not authorization_check():
            raise AssistantUnavailable("oauth_authorization_required", 403)
        return {"provider": _json_safe_provider(result)}

    async def internal_native_provider_proxy(
        execution_id: str,
        request: Request,
        *,
        expected_query: tuple[tuple[str, str], ...],
        path_model_id: str | None = None,
    ) -> Response:
        """Bridge a fixed native protocol route to the exact leased app-side provider."""

        denied = JSONResponse(
            status_code=404,
            content=_error("not_found", "The requested assistant resource was not found."),
        )
        native_session_id = _native_session_correlation(request)
        query = tuple(request.query_params.multi_items())
        if (
            _EXECUTION_ID.fullmatch(execution_id) is None
            or request.method != "POST"
            or (path_model_id is not None and path_model_id != "assistant-selected")
            or native_session_id is None
            or query != expected_query
            or not _loopback_client(request)
            or request.headers.get("origin") is not None
            or request.headers.get("referer") is not None
            or request.headers.get("cookie") is not None
            or any(name.lower().startswith("sec-fetch-") for name in request.headers)
            or request.headers.get("x-csrf-token") is not None
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            return denied
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) > 512:
            return denied
        capability = authorization[7:]
        try:
            lease = assistant.storage.validate_execution_capability(
                execution_id, capability, now=assistant.now()
            )
            user_id = int(lease["user_id"])
            turn = assistant.storage.get_turn(
                user_id, str(lease["conversation_id"]), str(lease["turn_id"])
            )
            model_id = str(turn["model_id"])
            policy_version = str(turn["policy_version"])
            policy = assistant.policy(model_id, owner_id=user_id)
        except Exception:
            return denied
        if (
            not assistant.validate_execution_session(lease)
            or not assistant._execution_current(user_id, execution_id, model_id, policy_version)
            or policy.policy_version != policy_version
            or (policy.provider_id == "openai-chatgpt" and not native_session_id)
        ):
            return denied

        def authorization_check() -> bool:
            return assistant._execution_current(user_id, execution_id, model_id, policy_version)

        content_length = request.headers.get("content-length")
        if content_length is not None:
            if not content_length.isascii() or not content_length.isdecimal():
                return JSONResponse(
                    status_code=400,
                    content=_error("invalid_provider_request", "The provider request is invalid."),
                )
            if int(content_length) > _PROXY_MAX_NATIVE_JSON_BYTES:
                return JSONResponse(
                    status_code=413,
                    content=_error(
                        "invalid_provider_request", "The provider request is too large."
                    ),
                )
        raw = bytearray()
        try:
            async for chunk in request.stream():
                if len(raw) + len(chunk) > _PROXY_MAX_NATIVE_JSON_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content=_error(
                            "invalid_provider_request", "The provider request is too large."
                        ),
                    )
                raw.extend(chunk)
        except Exception:
            return JSONResponse(
                status_code=400,
                content=_error("invalid_provider_request", "The provider request is invalid."),
            )
        body = _strict_json_object(bytes(raw))
        if body is None:
            return JSONResponse(
                status_code=422,
                content=_error(
                    "invalid_provider_request",
                    "The provider request is outside its fixed contract.",
                ),
            )
        if not authorization_check():
            return denied

        manager = assistant.providers
        proxy = getattr(manager, "proxy_native_stream", None) if manager is not None else None
        if not settings.assistant_enabled or not callable(proxy):
            return JSONResponse(
                status_code=503,
                content=_error(
                    "provider_unavailable", "The selected model provider is unavailable."
                ),
            )

        try:
            upstream = proxy(
                policy.provider_id,
                policy.model_id,
                body,
                path_model_id=path_model_id,
                query=query,
                app_tools=assistant.tool_gateway.list_tools(),
                owner_id=user_id,
                app_session_id=str(lease["session_id"]),
                native_session_id=native_session_id,
                authorization_check=authorization_check,
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            status_code = 422 if code == "provider_request_invalid" else 503
            error_code = (
                "invalid_provider_request" if status_code == 422 else "provider_unavailable"
            )
            error_message = (
                "The provider request is outside its fixed contract."
                if status_code == 422
                else "The selected model provider is unavailable."
            )
            return JSONResponse(
                status_code=status_code,
                content=_error(error_code, error_message),
            )
        if not hasattr(upstream, "__aiter__"):
            return JSONResponse(
                status_code=503,
                content=_error(
                    "provider_unavailable", "The selected model provider is unavailable."
                ),
            )
        return await _provider_proxy_stream_response(
            upstream,
            authorization_check,
            runtime=assistant.runtime,
            execution_id=execution_id,
            owner_id=user_id,
            denied=denied,
        )

    @router.post("/internal/provider/{execution_id}/v1/responses")
    async def internal_provider_responses(execution_id: str, request: Request) -> Response:
        return await internal_native_provider_proxy(execution_id, request, expected_query=())

    @router.post("/internal/provider/{execution_id}/v1/messages")
    async def internal_provider_messages(execution_id: str, request: Request) -> Response:
        return await internal_native_provider_proxy(
            execution_id, request, expected_query=(("beta", "true"),)
        )

    @router.post(
        "/internal/provider/{execution_id}/v1/models/{native_model_id}:streamGenerateContent"
    )
    async def internal_provider_google(
        execution_id: str, native_model_id: str, request: Request
    ) -> Response:
        return await internal_native_provider_proxy(
            execution_id,
            request,
            expected_query=(("alt", "sse"),),
            path_model_id=native_model_id,
        )

    @router.post("/internal/provider/{execution_id}/chat/completions")
    async def internal_provider_proxy(execution_id: str, request: Request) -> Response:
        """Proxy one exact catalog-bound provider stream for a native V2 execution."""

        denied = JSONResponse(
            status_code=404,
            content=_error("not_found", "The requested assistant resource was not found."),
        )
        native_session_id = _native_session_correlation(request)
        if (
            _EXECUTION_ID.fullmatch(execution_id) is None
            or request.method != "POST"
            or native_session_id is None
            or request.url.query
            or not _loopback_client(request)
            or request.headers.get("origin") is not None
            or request.headers.get("referer") is not None
            or request.headers.get("cookie") is not None
            or any(name.lower().startswith("sec-fetch-") for name in request.headers)
            or request.headers.get("x-csrf-token") is not None
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            return denied
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) > 512:
            return denied
        capability = authorization[7:]
        try:
            lease = assistant.storage.validate_execution_capability(
                execution_id, capability, now=assistant.now()
            )
            user_id = int(lease["user_id"])
            turn = assistant.storage.get_turn(
                user_id, str(lease["conversation_id"]), str(lease["turn_id"])
            )
            model_id = str(turn["model_id"])
            policy_version = str(turn["policy_version"])
            policy = assistant.policy(model_id, owner_id=user_id)
        except Exception:
            return denied
        if (
            not assistant.validate_execution_session(lease)
            or not assistant._execution_current(user_id, execution_id, model_id, policy_version)
            or policy.policy_version != policy_version
            or (policy.provider_id == "openai-chatgpt" and not native_session_id)
        ):
            return denied

        native_runtime_metadata = None
        if policy.provider_id == "opencode-zen":
            native_runtime_metadata = _native_zen_runtime_metadata(assistant.runtime, execution_id)
            if native_runtime_metadata is None:
                return denied

        def authorization_check() -> bool:
            if not assistant._execution_current(user_id, execution_id, model_id, policy_version):
                return False
            if policy.provider_id != "opencode-zen":
                return True
            return (
                native_runtime_metadata is not None
                and _native_zen_runtime_metadata(assistant.runtime, execution_id)
                == native_runtime_metadata
            )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=_error("invalid_provider_request", "The provider request is invalid."),
            )
        if not authorization_check():
            return denied
        bounded = _validated_provider_request(body, assistant.tool_gateway.list_tools())
        if bounded is None:
            return JSONResponse(
                status_code=422,
                content=_error(
                    "invalid_provider_request",
                    "The provider request is outside its fixed contract.",
                ),
            )
        native_identity: dict[str, str] = {}
        if policy.provider_id == "opencode-zen":
            assert native_runtime_metadata is not None
            parsed_identity = _native_zen_request_identity(
                request,
                expected_session=native_runtime_metadata[0],
                expected_project=native_runtime_metadata[1],
            )
            if parsed_identity is None:
                return JSONResponse(
                    status_code=422,
                    content=_error(
                        "invalid_provider_request",
                        "The provider request is outside its fixed contract.",
                    ),
                )
            native_identity = parsed_identity
        manager = assistant.providers
        proxy = getattr(manager, "proxy_chat_completion", None) if manager is not None else None
        if not settings.assistant_enabled or not callable(proxy):
            return JSONResponse(
                status_code=503,
                content=_error(
                    "provider_unavailable", "The selected model provider is unavailable."
                ),
            )
        # The request cannot select a URL, provider, endpoint path, or real upstream model. The
        # exact provider/model pair is read from the approved server catalog and durable turn.

        try:
            provider_context: dict[str, object] = {
                "app_tools": assistant.tool_gateway.list_tools(),
                "owner_id": user_id,
                "app_session_id": str(lease["session_id"]),
                "native_session_id": native_session_id,
                "authorization_check": authorization_check,
            }
            if "user-agent" in native_identity:
                provider_context["native_user_agent"] = native_identity["user-agent"]
            if "x-opencode-client" in native_identity:
                provider_context["native_client"] = native_identity["x-opencode-client"]
            if "x-opencode-session" in native_identity:
                provider_context["native_opencode_session"] = native_identity["x-opencode-session"]
            if "x-opencode-project" in native_identity:
                provider_context["native_opencode_project"] = native_identity["x-opencode-project"]
            if "x-session-affinity" in native_identity:
                provider_context["native_session_affinity"] = native_identity["x-session-affinity"]
            if "x-session-id" in native_identity:
                provider_context["native_session_id_alias"] = native_identity["x-session-id"]
            if not authorization_check():
                return denied
            upstream = proxy(
                policy.provider_id,
                policy.model_id,
                bounded,
                **provider_context,
            )
        except Exception:
            return JSONResponse(
                status_code=503,
                content=_error(
                    "provider_unavailable", "The selected model provider is unavailable."
                ),
            )
        if not hasattr(upstream, "__aiter__"):
            return JSONResponse(
                status_code=503,
                content=_error(
                    "provider_unavailable", "The selected model provider is unavailable."
                ),
            )

        return await _provider_proxy_stream_response(
            upstream,
            authorization_check,
            runtime=assistant.runtime,
            execution_id=execution_id,
            owner_id=user_id,
            denied=denied,
        )

    @router.post("/internal/mcp/{execution_id}")
    async def internal_mcp(execution_id: str, request: Request) -> Response:
        """Serve only the per-turn bearer-authenticated private app MCP bridge."""

        if (
            _EXECUTION_ID.fullmatch(execution_id) is None
            or request.method != "POST"
            or request.url.query
            or not _loopback_client(request)
            or request.headers.get("origin") is not None
            or request.headers.get("referer") is not None
            or request.headers.get("cookie") is not None
            or request.headers.get("sec-fetch-site") is not None
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse(
                status_code=404,
                content=_error("not_found", "The requested assistant resource was not found."),
            )
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) > 512:
            return JSONResponse(
                status_code=404,
                content=_error("not_found", "The requested assistant resource was not found."),
            )
        capability = authorization[7:]
        try:
            lease = assistant.storage.validate_execution_capability(
                execution_id, capability, now=assistant.now()
            )
        except AssistantStorageError:
            return JSONResponse(
                status_code=404,
                content=_error("not_found", "The requested assistant resource was not found."),
            )
        try:
            turn = assistant.storage.get_turn(
                int(lease["user_id"]), str(lease["conversation_id"]), str(lease["turn_id"])
            )
            if not assistant._execution_current(
                int(lease["user_id"]),
                execution_id,
                str(turn["model_id"]),
                str(turn["policy_version"]),
            ):
                return JSONResponse(
                    status_code=404,
                    content=_error("not_found", "The requested assistant resource was not found."),
                )
            message = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=_error("invalid_mcp_request", "The tool request is invalid."),
            )
        if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0":
            return JSONResponse(
                status_code=400,
                content=_error("invalid_mcp_request", "The tool request is invalid."),
            )
        method = message.get("method")
        request_id = message.get("id")
        if not isinstance(method, str) or (
            request_id is not None
            and (type(request_id) not in {str, int} or len(str(request_id)) > 80)
        ):
            return JSONResponse(
                status_code=400,
                content=_error("invalid_mcp_request", "The tool request is invalid."),
            )
        if method.startswith("notifications/") and request_id is None:
            return Response(status_code=202)
        params = message.get("params", {})
        if not isinstance(params, Mapping):
            return JSONResponse(
                status_code=400,
                content=_error("invalid_mcp_request", "The tool request is invalid."),
            )
        result: dict[str, object]
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "signal-ledger", "version": "1"},
                }
            elif method == "tools/list":
                result = {"tools": assistant.tool_gateway.list_tools()}
            elif method == "tools/call":
                name = params.get("name")
                if not isinstance(name, str):
                    raise AssistantUnavailable("invalid_tool_arguments", 422)
                lease = assistant.storage.authorize_tool_call(
                    execution_id,
                    capability,
                    now=assistant.now(),
                    marks_private_read=assistant.tool_gateway.is_private_read(name),
                )
                if not assistant.validate_execution_session(
                    lease
                ) or not assistant._execution_current(
                    int(lease["user_id"]),
                    execution_id,
                    str(turn["model_id"]),
                    str(turn["policy_version"]),
                ):
                    raise AssistantUnavailable("session_revoked", 403)
                created_at = datetime.fromisoformat(str(lease["created_at"]))
                if created_at.tzinfo is None:
                    raise AssistantUnavailable("turn_timeout", 504)
                elapsed = (assistant.now() - created_at.astimezone(UTC)).total_seconds()
                remaining = min(120.0 - elapsed, 120.0)
                if remaining <= 0:
                    raise AssistantUnavailable("turn_timeout", 504)
                try:
                    structured = await asyncio.wait_for(
                        asyncio.to_thread(
                            assistant.tool_gateway.call,
                            lease=lease,
                            name=name,
                            arguments=params.get("arguments", {}),
                        ),
                        timeout=remaining,
                    )
                except TimeoutError:
                    raise AssistantUnavailable("turn_timeout", 504) from None
                if not assistant._execution_current(
                    int(lease["user_id"]),
                    execution_id,
                    str(turn["model_id"]),
                    str(turn["policy_version"]),
                ):
                    raise AssistantUnavailable("session_revoked", 403)
                elapsed_after = (assistant.now() - created_at.astimezone(UTC)).total_seconds()
                receipt_remaining = min(120.0 - elapsed_after, 120.0)
                if receipt_remaining <= 0:
                    raise AssistantUnavailable("turn_timeout", 504)
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(assistant.persist_tool_receipt, lease, name, structured),
                        timeout=receipt_remaining,
                    )
                except TimeoutError:
                    raise AssistantUnavailable("turn_timeout", 504) from None
                if not assistant._execution_current(
                    int(lease["user_id"]),
                    execution_id,
                    str(turn["model_id"]),
                    str(turn["policy_version"]),
                ):
                    raise AssistantUnavailable("session_revoked", 403)
                text = json.dumps(
                    structured, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                )
                _record_completed_workspace_summary_timing(
                    assistant.runtime,
                    execution_id,
                    int(lease["user_id"]),
                    tool_name=name,
                    completed=True,
                )
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            else:
                return JSONResponse(
                    status_code=404,
                    content={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": "Method not found"},
                    },
                )
        except (AssistantUnavailable, AssistantStorageError) as exc:
            code = getattr(exc, "code", "tool_failed")
            result = {
                "content": [{"type": "text", "text": json.dumps({"error": code})}],
                "isError": True,
            }
        if request_id is None:
            return Response(status_code=202)
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    return router


def register_assistant_api(
    app: FastAPI,
    assistant: AssistantService,
    auth_manager: AuthManager,
    settings: Settings,
    get_auth_context: Callable[..., AuthContext],
) -> None:
    _register_error_handlers(app)
    app.include_router(create_assistant_router(assistant, auth_manager, settings, get_auth_context))


__all__ = ["create_assistant_router", "register_assistant_api"]
