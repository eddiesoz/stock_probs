"""Typed, peer-checked client for the fixed in-container supervisor socket."""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import stat
import struct
from collections.abc import Awaitable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TypeVar, cast
from urllib.parse import urlsplit

from stock_probs.assistant.native_provider_adapters import (
    NativeProviderDescriptorError,
    resolve_native_adapter,
)

CONTROL_SOCKET = Path("/run/assistant/control.sock")
SOCKET_DIRECTORY = CONTROL_SOCKET.parent
SOCKET_OWNER_UID = 0
SOCKET_GROUP_GID = 10001
WORKER_API_URL = "http://127.0.0.1:4097"
PROXY_PREFIX = "/api/v1/assistant/internal/provider/"
MCP_PREFIX = "/api/v1/assistant/internal/mcp/"
REQUEST_LIMIT = 16 * 1024
RESPONSE_LIMIT = 32 * 1024
IO_TIMEOUT_SECONDS = 3.0
PURGE_POLL_SECONDS = 0.1
PURGE_WAIT_SECONDS = 20.0

_EXECUTION_ID = re.compile(r"^[0-9a-f]{32}$")
_PURGE_ID = re.compile(r"^[0-9a-f]{32}$")
_PROVIDER_ID = re.compile(
    r"^(?:opencode-zen|opencode-console|openai|openai-chatgpt|anthropic|google|custom)$"
)
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_CAPABILITY = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_ERROR_CODES = frozenset(
    {
        "request_invalid",
        "request_rejected",
        "operation_disabled",
        "location_limit",
        "location_conflict",
        "location_unavailable",
        "worker_unavailable",
        "purge_id_unknown",
        "home_purge_depth_exceeded",
        "home_purge_entry_limit",
        "home_purge_mount_boundary",
        "native_adapter_unsupported",
        "native_provider_mismatch",
        "worker_home_identity_invalid",
        "worker_tmp_identity_invalid",
        "worker_start_timeout",
    }
)
_DISABLE_REASONS = frozenset(
    {"operator", "kill_switch", "security_failure", "shutdown", "restart_budget_exhausted"}
)
_T = TypeVar("_T")


class SupervisorClientError(RuntimeError):
    """A bounded protocol failure without echoing request contents or capabilities."""

    def __init__(self, code: str):
        super().__init__(f"Assistant supervisor is unavailable ({code}).")
        self.code = code


def _valid_local_url(value: str, *, prefix: str, execution_id: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and port == 8000
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.path == f"{prefix}{execution_id}"
    )


def _validate_prepare_request(
    *,
    execution_id: str,
    provider_id: str,
    adapter_id: str,
    native_provider_id: str,
    model_id: str,
    model_alias: str,
    proxy_base_url: str,
    proxy_capability: str,
    mcp_url: str,
    mcp_capability: str,
) -> None:
    if not _EXECUTION_ID.fullmatch(execution_id):
        raise SupervisorClientError("execution_id_invalid")
    if not _PROVIDER_ID.fullmatch(provider_id):
        raise SupervisorClientError("provider_invalid")
    try:
        resolve_native_adapter(adapter_id, native_provider_id)
    except NativeProviderDescriptorError as exc:
        raise SupervisorClientError(exc.code) from None
    if not _MODEL_ID.fullmatch(model_id) or model_alias != "assistant-selected":
        raise SupervisorClientError("model_invalid")
    if not _CAPABILITY.fullmatch(proxy_capability) or not _CAPABILITY.fullmatch(mcp_capability):
        raise SupervisorClientError("capability_invalid")
    if not _valid_local_url(
        proxy_base_url, prefix=PROXY_PREFIX, execution_id=execution_id
    ) or not _valid_local_url(mcp_url, prefix=MCP_PREFIX, execution_id=execution_id):
        raise SupervisorClientError("endpoint_invalid")


def _validate_socket_path() -> None:
    """Reject a replaced socket or writable parent before opening a local connection."""

    try:
        parent = os.lstat(SOCKET_DIRECTORY)
        endpoint = os.lstat(CONTROL_SOCKET)
    except OSError as exc:
        raise SupervisorClientError("socket_unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != SOCKET_OWNER_UID
        or parent.st_mode & 0o022
        or not stat.S_ISSOCK(endpoint.st_mode)
        or endpoint.st_uid != SOCKET_OWNER_UID
        or endpoint.st_gid != SOCKET_GROUP_GID
        or stat.S_IMODE(endpoint.st_mode) != 0o660
    ):
        raise SupervisorClientError("socket_identity_invalid")


def _peer_uid(peer: object) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise SupervisorClientError("peer_credentials_unavailable")
    get_socket_option = getattr(peer, "getsockopt", None)
    if not callable(get_socket_option):
        raise SupervisorClientError("peer_credentials_unavailable")
    try:
        credentials = get_socket_option(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        )
    except OSError as exc:
        raise SupervisorClientError("peer_credentials_unavailable") from exc
    _, uid, _ = struct.unpack("3i", credentials)
    return uid


class SupervisorClient:
    """Use only the fixed local control API; never pass through caller paths or commands."""

    async def _request(self, payload: Mapping[str, object]) -> dict[str, object]:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if len(encoded) > REQUEST_LIMIT:
            raise SupervisorClientError("request_too_large")
        _validate_socket_path()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + IO_TIMEOUT_SECONDS

        async def within_deadline(awaitable: Awaitable[_T]) -> _T:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(awaitable, timeout=remaining)

        try:
            reader, writer = await within_deadline(
                asyncio.open_unix_connection(str(CONTROL_SOCKET), limit=RESPONSE_LIMIT + 1)
            )
        except (TimeoutError, OSError) as exc:
            raise SupervisorClientError("socket_unavailable") from exc
        cancelled = False

        def abort_writer() -> None:
            with suppress(Exception):
                writer.transport.abort()
            with suppress(Exception):
                writer.close()

        try:
            peer = writer.get_extra_info("socket")
            if _peer_uid(peer) != SOCKET_OWNER_UID:
                raise SupervisorClientError("peer_identity_invalid")
            writer.write(encoded + b"\n")
            await within_deadline(writer.drain())
            writer.write_eof()
            try:
                raw = await within_deadline(reader.readuntil(b"\n"))
            except asyncio.LimitOverrunError as exc:
                raise SupervisorClientError("response_invalid") from exc
            except asyncio.IncompleteReadError as exc:
                raise SupervisorClientError("response_invalid") from exc
            if not raw.endswith(b"\n") or len(raw) - 1 > RESPONSE_LIMIT:
                raise SupervisorClientError("response_invalid")
            if await within_deadline(reader.read(1)):
                raise SupervisorClientError("response_invalid")
            try:
                response = json.loads(raw[:-1])
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SupervisorClientError("response_invalid") from exc
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise SupervisorClientError("response_invalid")
            if response["ok"] is not True:
                code = response.get("error")
                safe_code = (
                    code if isinstance(code, str) and code in _ERROR_CODES else "request_rejected"
                )
                raise SupervisorClientError(safe_code)
            return cast(dict[str, object], response)
        except asyncio.CancelledError:
            cancelled = True
            # An outer caller may have a tighter deadline than this socket client's timeout.
            abort_writer()
            raise
        except TimeoutError as exc:
            raise SupervisorClientError("request_timeout") from exc
        finally:
            if not cancelled:
                writer.close()
                remaining = deadline - loop.time()
                if remaining > 0:
                    try:
                        await asyncio.wait_for(writer.wait_closed(), timeout=remaining)
                    except asyncio.CancelledError:
                        abort_writer()
                        raise
                    except (TimeoutError, OSError):
                        pass

    async def status(self) -> Mapping[str, object]:
        response = await self._request({"version": 1, "op": "status"})
        status = response.get("status")
        password = response.get("api_password")
        observation_uncertain = response.get("observation_uncertain")
        if (
            status not in {"ready", "starting", "disabled", "unavailable", "stopped"}
            or response.get("api_url") != WORKER_API_URL
            or not isinstance(password, str)
            or not 32 <= len(password) <= 128
            or not _CAPABILITY.fullmatch(password)
            or type(observation_uncertain) is not bool
        ):
            raise SupervisorClientError("status_invalid")
        return {
            "ok": True,
            "status": status,
            "api_url": WORKER_API_URL,
            "api_password": password,
            # Older or malformed status projections cannot authorize native WebFetch.
            "webfetch_guard_ready": response.get("webfetch_guard_ready") is True,
            "observation_uncertain": observation_uncertain,
        }

    async def prepare_location(
        self,
        *,
        execution_id: str,
        provider_id: str,
        adapter_id: str,
        native_provider_id: str,
        model_id: str,
        model_alias: str,
        proxy_base_url: str,
        proxy_capability: str,
        mcp_url: str,
        mcp_capability: str,
    ) -> Mapping[str, object]:
        _validate_prepare_request(
            execution_id=execution_id,
            provider_id=provider_id,
            adapter_id=adapter_id,
            native_provider_id=native_provider_id,
            model_id=model_id,
            model_alias=model_alias,
            proxy_base_url=proxy_base_url,
            proxy_capability=proxy_capability,
            mcp_url=mcp_url,
            mcp_capability=mcp_capability,
        )
        response = await self._request(
            {
                "version": 1,
                "op": "prepare_location",
                "execution_id": execution_id,
                "provider_id": provider_id,
                "adapter_id": adapter_id,
                "native_provider_id": native_provider_id,
                "model_id": model_id,
                "model_alias": model_alias,
                "proxy_base_url": proxy_base_url,
                "proxy_capability": proxy_capability,
                "mcp_url": mcp_url,
                "mcp_capability": mcp_capability,
            }
        )
        expected = f"/run/assistant/worker-locations/{execution_id}"
        if response.get("directory") != expected:
            raise SupervisorClientError("location_invalid")
        return {"ok": True, "directory": expected}

    async def remove_location(self, execution_id: str) -> str | None:
        if not _EXECUTION_ID.fullmatch(execution_id):
            raise SupervisorClientError("execution_id_invalid")
        response = await self._request(
            {"version": 1, "op": "remove_location", "execution_id": execution_id}
        )
        purge_id = response.get("purge_id")
        if purge_id is None:
            return None
        if not isinstance(purge_id, str) or not _PURGE_ID.fullmatch(purge_id):
            raise SupervisorClientError("purge_response_invalid")
        return purge_id

    async def hold_worker(self, lease_id: str) -> None:
        """Keep HOME intact for one bounded native OAuth attempt."""

        if not isinstance(lease_id, str) or not _PURGE_ID.fullmatch(lease_id):
            raise SupervisorClientError("worker_hold_id_invalid")
        response = await self._request({"version": 1, "op": "hold_worker", "lease_id": lease_id})
        if set(response) != {"ok"}:
            raise SupervisorClientError("worker_hold_response_invalid")

    async def release_worker(self, lease_id: str) -> str | None:
        """Release one OAuth hold and return a purge generation when it becomes idle."""

        if not isinstance(lease_id, str) or not _PURGE_ID.fullmatch(lease_id):
            raise SupervisorClientError("worker_hold_id_invalid")
        response = await self._request({"version": 1, "op": "release_worker", "lease_id": lease_id})
        purge_id = response.get("purge_id")
        if purge_id is None:
            if set(response) != {"ok"}:
                raise SupervisorClientError("worker_hold_response_invalid")
            return None
        if (
            set(response) != {"ok", "purge_id"}
            or not isinstance(purge_id, str)
            or not _PURGE_ID.fullmatch(purge_id)
        ):
            raise SupervisorClientError("worker_hold_response_invalid")
        return purge_id

    @staticmethod
    def _read_purge_response(
        response: Mapping[str, object], expected_id: str | None = None
    ) -> tuple[str, str]:
        purge_id = response.get("purge_id")
        status = response.get("status")
        if (
            not isinstance(purge_id, str)
            or not _PURGE_ID.fullmatch(purge_id)
            or (expected_id is not None and purge_id != expected_id)
            or not isinstance(status, str)
            or status not in {"pending", "cleared", "failed"}
        ):
            raise SupervisorClientError("purge_response_invalid")
        return purge_id, cast(str, status)

    async def request_home_purge(self) -> str:
        response = await self._request({"version": 1, "op": "purge_worker_home"})
        purge_id, _ = self._read_purge_response(response)
        return purge_id

    async def home_purge_status(self, purge_id: str) -> str:
        if not _PURGE_ID.fullmatch(purge_id):
            raise SupervisorClientError("purge_id_invalid")
        response = await self._request({"version": 1, "op": "purge_status", "purge_id": purge_id})
        _, status = self._read_purge_response(response, purge_id)
        return status

    async def wait_for_home_purge(
        self, purge_id: str, *, timeout: float = PURGE_WAIT_SECONDS
    ) -> bool:
        if not _PURGE_ID.fullmatch(purge_id):
            raise SupervisorClientError("purge_id_invalid")
        if not 0 < timeout <= PURGE_WAIT_SECONDS:
            raise SupervisorClientError("purge_timeout_invalid")
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            try:
                status = await asyncio.wait_for(self.home_purge_status(purge_id), timeout=remaining)
            except TimeoutError:
                return False
            except SupervisorClientError as exc:
                if exc.code not in {"socket_unavailable", "request_timeout"}:
                    raise
                # The fixed supervisor may be recycling the worker before it can answer again.
                status = "pending"
            if status == "cleared":
                return True
            if status == "failed":
                return False
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(PURGE_POLL_SECONDS, remaining))

    async def disable(self, reason: str) -> str:
        if reason not in _DISABLE_REASONS:
            raise SupervisorClientError("disable_reason_invalid")
        response = await self._request({"version": 1, "op": "disable", "reason": reason})
        purge_id = response.get("purge_id")
        if not isinstance(purge_id, str) or not _PURGE_ID.fullmatch(purge_id):
            raise SupervisorClientError("response_invalid")
        return purge_id
