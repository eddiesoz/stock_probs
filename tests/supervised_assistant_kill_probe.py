"""Exercise the assistant kill switch during a native search approval on one candidate.

This opt-in probe attaches only to the exact disposable R-ASTRA-120 candidate accepted by
``supervised_assistant_probe``. It starts no containers, sends synthetic session material only
through stdin and HTTP headers, and never writes a receipt containing conversation content.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import selectors
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from tests import native_assistant_probe
from tests import supervised_assistant_probe as supervised

ROOT = Path(__file__).resolve().parents[1]
NATIVE_DRIVER = ROOT / "tests" / "native_assistant_probe.py"
PYTHON = ROOT / ".dev-venv" / "bin" / "python"
PUBLIC_ORIGIN = "https://ledger-r120.test"
PUBLIC_HOST = "ledger-r120.test"
CONTAINER_PREFIX = supervised.CONTAINER_PREFIX
VOLUME_PREFIX = supervised.VOLUME_PREFIX
PROCESS_LIMIT = supervised.PROCESS_LIMIT
MEMORY_LIMIT_BYTES = supervised.MEMORY_LIMIT_BYTES
NATIVE_TIMEOUT_SECONDS = supervised.NATIVE_TIMEOUT_SECONDS
OUTPUT_LIMIT = 128 * 1024
LINE_LIMIT = 16 * 1024
TERMINAL_POLL_SECONDS = 12.0
KILL_TIMEOUT_SECONDS = 35.0
SAFE_TERMINAL_ERRORS = supervised._NATIVE_SAFE_TURN_ERROR_CODES
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_CONVERSATION_ID = re.compile(r"^[0-9a-f-]{36}$")
_PREVIEW_ID = re.compile(r"^[0-9a-f-]{36}$")


ProbeError = supervised.ProbeError


def _candidate_base_is_scoped(candidate: supervised.Candidate) -> bool:
    """Check fixed container, volume, image, and loopback identity fields."""

    if not isinstance(candidate.container, str) or not isinstance(candidate.data_volume, str):
        return False
    container_match = re.fullmatch(r"assistant-r120-candidate-([0-9a-f]{12})", candidate.container)
    volume_match = re.fullmatch(r"stock-probs-assistant-r120-([0-9a-f]{12})", candidate.data_volume)
    return bool(
        container_match
        and volume_match
        and container_match.group(1) == volume_match.group(1)
        and isinstance(candidate.container_id, str)
        and _CONTAINER_ID.fullmatch(candidate.container_id)
        and isinstance(candidate.image_id, str)
        and supervised._SHA256_IMAGE.fullmatch(candidate.image_id)
        and type(candidate.host_port) is int
        and 1 <= candidate.host_port <= 65_535
        and candidate.base_url == f"http://127.0.0.1:{candidate.host_port}"
        and type(candidate.host_pid) is int
        and candidate.host_pid > 1
    )


def _candidate_network_is_scoped(candidate: supervised.Candidate) -> bool:
    """Require the exact user-defined network identity returned by candidate inspection."""

    expected_name = f"{candidate.data_volume}-candidate-network"
    return bool(
        candidate.network_name == expected_name
        and isinstance(candidate.network_id, str)
        and _HEX64.fullmatch(candidate.network_id)
    )


def _candidate_is_scoped(candidate: supervised.Candidate) -> bool:
    """Require both the fixed candidate identity and its exact private network binding."""

    return _candidate_base_is_scoped(candidate) and _candidate_network_is_scoped(candidate)


def _require_scoped_candidate(candidate: supervised.Candidate) -> None:
    if not _candidate_base_is_scoped(candidate):
        raise ProbeError("candidate identity did not match the fixed disposable scope")
    if not _candidate_network_is_scoped(candidate):
        raise ProbeError(
            "candidate exact network identity is required for the fixed disposable scope"
        )


def _expected_search_query_sha256() -> str:
    """Derive the fixture query identity from the maintained native-driver contract."""

    return hashlib.sha256(native_assistant_probe._ATTACH_SEARCH_QUERY.encode("utf-8")).hexdigest()


def _validate_active_search_checkpoint(value: object) -> dict[str, object]:
    """Accept only the driver's closed receipt for a running turn awaiting exact search approval."""

    expected_keys = {
        "mode",
        "phase",
        "origin",
        "owner_index",
        "turn_status",
        "search_preview_pending",
        "workspace_summary_digest_matches",
        "search_query_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("mode") != "attach-existing-app"
        or value.get("phase") != "active_search_wait"
        or value.get("origin") != PUBLIC_ORIGIN
        or value.get("owner_index") != 1
        or value.get("turn_status") != "running"
        or value.get("search_preview_pending") is not True
        or value.get("workspace_summary_digest_matches") is not True
        or value.get("search_query_sha256") != _expected_search_query_sha256()
    ):
        raise ProbeError("native driver did not reach the exact pending-search checkpoint")
    return {
        "phase": "active_search_wait",
        "owner_index": 1,
        "turn_status": "running",
        "search_preview_pending": True,
        "workspace_summary_digest_matches": True,
        "search_query_sha256": value["search_query_sha256"],
    }


def _driver_failure_projection(value: object) -> dict[str, object]:
    """Require EOF at the paused checkpoint and project only closed terminal facts."""

    if (
        not isinstance(value, dict)
        or value.get("mode") != "attach-existing-app"
        or value.get("phase") != "final"
        or value.get("attached_candidate_acceptance") is not False
        or value.get("safe_error_code") != "active_scan_ack_invalid"
        or value.get("failure_stage") != "turn_poll_and_search_confirmation"
        or value.get("active_search_scan_acknowledged") is not False
        or value.get("search_approved") is not False
        or value.get("search_approval_count") != 0
    ):
        raise ProbeError("native driver did not close without approving the pending search")
    return {
        "phase": "final",
        "active_search_scan_acknowledged": False,
        "search_approved": False,
        "search_approval_count": 0,
        "safe_error_code": "active_scan_ack_invalid",
    }


def _safe_environment() -> dict[str, str]:
    """Keep the local driver independent of inherited credentials and application settings."""

    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _start_native_driver(
    candidate: supervised.Candidate, users: list[dict[str, str]]
) -> tuple[subprocess.Popen[bytes], dict[str, object], bytes]:
    """Start the fixed native driver and wait for its first exact active-search checkpoint."""

    _require_scoped_candidate(candidate)
    driver_input = json.dumps(
        {"base_url": candidate.base_url, "origin": PUBLIC_ORIGIN, "users": users},
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    try:
        child = subprocess.Popen(  # noqa: S603 - fixed interpreter and fixed probe script.
            [str(PYTHON), str(NATIVE_DRIVER), "--attach-existing-app"],
            cwd=ROOT,
            env=_safe_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ProbeError("fixed native driver could not start") from exc
    if child.stdin is None or child.stdout is None:
        _stop_child(child)
        raise ProbeError("fixed native driver pipes were unavailable")
    try:
        child.stdin.write(driver_input + b"\n")
        child.stdin.flush()
    except OSError as exc:
        _stop_child(child)
        raise ProbeError("private native-driver input pipe failed") from exc
    finally:
        del driver_input

    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    captured = bytearray()
    pending = bytearray()
    deadline = time.monotonic() + NATIVE_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            _sample_resource_state(candidate)
            if child.poll() is not None:
                raise ProbeError("native driver exited before its active-search checkpoint")
            ready = selector.select(timeout=0.2)
            if not ready:
                continue
            try:
                chunk = os.read(child.stdout.fileno(), 4096)
            except OSError as exc:
                raise ProbeError("native driver output pipe failed") from exc
            if not chunk:
                raise ProbeError("native driver ended before its active-search checkpoint")
            captured.extend(chunk)
            pending.extend(chunk)
            if len(captured) > OUTPUT_LIMIT or len(pending) > LINE_LIMIT:
                raise ProbeError("native driver exceeded its bounded checkpoint output")
            if b"\n" not in pending:
                continue
            line, remainder = pending.split(b"\n", 1)
            if remainder:
                raise ProbeError("native driver emitted more than one checkpoint before kill")
            try:
                checkpoint_value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProbeError("native driver checkpoint was malformed") from exc
            checkpoint = _validate_active_search_checkpoint(checkpoint_value)
            if any(
                user[field].encode("utf-8") in captured
                for user in users
                for field in ("session_cookie", "csrf_cookie", "totp_secret")
                if field in user
            ):
                raise ProbeError("native driver checkpoint exposed synthetic session material")
            return child, checkpoint, bytes(captured)
        raise ProbeError("native driver did not reach a pending search within its deadline")
    except BaseException:
        _stop_child(child)
        raise
    finally:
        selector.close()


def _stop_child(child: subprocess.Popen[bytes]) -> None:
    """Bound child cleanup even if the native driver or its output protocol is broken."""

    try:
        if child.poll() is not None:
            try:
                child.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2.0)
            return
        child.terminate()
        try:
            child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2.0)
    finally:
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None and not stream.closed:
                with contextlib.suppress(OSError):
                    stream.close()


def _close_paused_driver(
    child: subprocess.Popen[bytes], checkpoint_bytes: bytes, users: list[dict[str, str]]
) -> dict[str, object]:
    """Close the driver's approval gate with EOF and validate its safe final receipt."""

    if child.stdin is None or child.stdout is None:
        raise ProbeError("native driver pipes were unavailable during cleanup")
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    captured = bytearray(checkpoint_bytes)
    pending = bytearray()
    try:
        child.stdin.close()
        deadline = time.monotonic() + 8.0
        final_line: bytes | None = None
        while time.monotonic() < deadline:
            ready = selector.select(timeout=0.2)
            if not ready:
                if child.poll() is not None:
                    break
                continue
            chunk = os.read(child.stdout.fileno(), 4096)
            if not chunk:
                break
            captured.extend(chunk)
            pending.extend(chunk)
            if len(captured) > OUTPUT_LIMIT or len(pending) > LINE_LIMIT:
                raise ProbeError("native driver final output exceeded its bound")
            if b"\n" in pending:
                lines = pending.split(b"\n")
                if len(lines) != 2 or lines[1]:
                    raise ProbeError("native driver emitted an unexpected final receipt")
                final_line = lines[0]
                pending.clear()
                break
        if final_line is None:
            raise ProbeError("native driver did not close with its bounded failure receipt")
        try:
            final = json.loads(final_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProbeError("native driver final receipt was malformed") from exc
        projection = _driver_failure_projection(final)
        if any(
            user[field].encode("utf-8") in captured
            for user in users
            for field in ("session_cookie", "csrf_cookie", "totp_secret")
            if field in user
        ):
            raise ProbeError("native driver output exposed synthetic session material")
        try:
            child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _stop_child(child)
            raise ProbeError("native driver did not exit after its approval gate closed") from None
        if child.returncode != 1:
            raise ProbeError("native driver did not fail closed after its approval gate closed")
        return {
            **projection,
            "stdout_bytes": len(captured),
            "stdout_sha256": hashlib.sha256(captured).hexdigest(),
        }
    except BaseException:
        _stop_child(child)
        raise
    finally:
        selector.close()


def _run_kill(candidate: supervised.Candidate) -> dict[str, object]:
    """Invoke only the fixed no-argument kill module as the nonroot application UID."""

    _require_scoped_candidate(candidate)
    output = supervised._command(
        [
            "docker",
            "exec",
            "--user",
            "10001:10001",
            candidate.container_id,
            "python",
            "-m",
            "stock_probs.cli",
            "assistant-kill",
        ],
        timeout=KILL_TIMEOUT_SECONDS,
    )
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProbeError("fixed assistant kill command returned an invalid receipt") from exc
    if not isinstance(value, dict) or value != {"status": "assistant_disabled"}:
        raise ProbeError("fixed assistant kill command did not confirm bounded disable")
    return {"status": "assistant_disabled", "uid": 10001, "gid": 10001}


def _request(
    candidate: supervised.Candidate,
    user: dict[str, str],
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    csrf: bool = False,
) -> tuple[int, dict[str, object]]:
    """Perform one bounded same-origin request without retaining or returning raw content."""

    from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

    if (
        method not in {"GET", "POST"}
        or not (
            path.startswith("/api/v1/assistant/") or (method == "GET" and path == "/api/v1/history")
        )
        or not _candidate_is_scoped(candidate)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", user.get("session_cookie", ""))
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", user.get("csrf_cookie", ""))
    ):
        raise ProbeError("candidate API request did not match the fixed authenticated scope")
    headers = {
        "Host": PUBLIC_HOST,
        "Origin": PUBLIC_ORIGIN,
        "Accept": "application/json",
        "Cookie": (
            f"{SESSION_COOKIE_NAME}={user['session_cookie']}; "
            f"{CSRF_COOKIE_NAME}={user['csrf_cookie']}"
        ),
    }
    payload_bytes = None
    if body is not None:
        payload_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > 16 * 1024:
            raise ProbeError("candidate API request exceeded its bounded body")
        headers["Content-Type"] = "application/json"
    if csrf:
        headers["X-CSRF-Token"] = user["csrf_cookie"]
    connection = http.client.HTTPConnection("127.0.0.1", candidate.host_port, timeout=5.0)
    try:
        connection.request(method, path, body=payload_bytes, headers=headers)
        response = connection.getresponse()
        response_body = response.read(64 * 1024 + 1)
        status = response.status
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        raise ProbeError("candidate private API request failed") from exc
    finally:
        connection.close()
    if len(response_body) > 64 * 1024:
        raise ProbeError("candidate private API response exceeded its bound")
    try:
        value = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("candidate private API response was malformed") from exc
    if not isinstance(value, dict):
        raise ProbeError("candidate private API response was not an object")
    return status, value


def _error_code(payload: dict[str, object]) -> str | None:
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else None


def _maintained_model_policy(turn: dict[str, object]) -> tuple[str, str]:
    """Use the active turn's exact maintained-catalog model and policy version."""

    model_id = turn.get("model_id")
    policy_version = turn.get("policy_version")
    if (
        not isinstance(model_id, str)
        or model_id != native_assistant_probe._reviewed_free_zen_model_id()
        or not isinstance(policy_version, str)
        or not 1 <= len(policy_version) <= 200
        or any(ord(char) < 0x20 for char in policy_version)
    ):
        raise ProbeError("active turn did not retain its maintained catalog model policy")
    return model_id, policy_version


def _require_disabled_error(
    response: tuple[int, dict[str, object]], *, stage: str
) -> dict[str, object]:
    status, payload = response
    code = _error_code(payload)
    if status != 503 or code != "assistant_worker_unavailable":
        raise ProbeError(f"assistant {stage} was not denied by the kill latch")
    return {"http_status": status, "error_code": code}


_OWNER_TABLE_QUERIES = {
    "assistant_conversations": (
        "SELECT * FROM assistant_conversations WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_turns": ("SELECT * FROM assistant_turns WHERE user_id = ? ORDER BY rowid LIMIT 257"),
    "assistant_messages": (
        "SELECT * FROM assistant_messages WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_events": (
        "SELECT * FROM assistant_events WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_sources": (
        "SELECT * FROM assistant_sources WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_proposed_actions": (
        "SELECT * FROM assistant_proposed_actions WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_action_receipts": (
        "SELECT * FROM assistant_action_receipts WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_execution_leases": (
        "SELECT * FROM assistant_execution_leases WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_search_previews": (
        "SELECT * FROM assistant_search_previews WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_model_consents": (
        "SELECT * FROM assistant_model_consents WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "assistant_conversation_deletions": (
        "SELECT * FROM assistant_conversation_deletions WHERE user_id = ? ORDER BY rowid LIMIT 257"
    ),
    "user_instrument_list_items": (
        "SELECT kind, provider, canonical_symbol, asset_type, exchange, display_name, "
        "quantity, added_at FROM user_instrument_list_items WHERE owner_user_id = ? "
        "ORDER BY kind, added_at, canonical_symbol LIMIT 257"
    ),
}


def _owner_state_snapshot(
    candidate: supervised.Candidate, user: dict[str, str]
) -> dict[str, object]:
    """Read a fixed, read-only owner projection from this synthetic candidate's database."""

    _require_scoped_candidate(candidate)
    session_cookie = user.get("session_cookie")
    if not isinstance(session_cookie, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{32,128}", session_cookie
    ):
        raise ProbeError("synthetic owner session was malformed for the read-only projection")
    script = r"""import hashlib, json, sqlite3, sys
from stock_probs.config import Settings

payload = json.loads(sys.stdin.readline(4096))
if set(payload) != {"session_cookie"} or not isinstance(payload["session_cookie"], str):
    raise RuntimeError("projection input invalid")
token_hash = hashlib.sha256(payload["session_cookie"].encode("ascii")).hexdigest()
settings = Settings.from_env()
uri = settings.database_path.resolve().as_uri() + "?mode=ro"
connection = sqlite3.connect(uri, uri=True, timeout=2.0)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA query_only=ON")
connection.execute("BEGIN")
try:
    sessions = connection.execute(
        "SELECT user_id FROM sessions WHERE token_hash = ? LIMIT 2", (token_hash,)
    ).fetchall()
    if len(sessions) != 1:
        raise RuntimeError("owner session scope invalid")
    user_id = int(sessions[0]["user_id"])
    conversations = connection.execute(
        "SELECT id, context_json FROM assistant_conversations WHERE user_id = ? "
        "ORDER BY created_at, id LIMIT 2", (user_id,)
    ).fetchall()
    if len(conversations) != 1:
        raise RuntimeError("owner conversation scope invalid")
    conversation_id = str(conversations[0]["id"])
    context = json.loads(str(conversations[0]["context_json"]))
    if not isinstance(context, dict) or context.get("route") != "/overview":
        raise RuntimeError("owner context route invalid")
    turns = connection.execute(
        "SELECT id, status, error_code, model_id, policy_version, context_version "
        "FROM assistant_turns WHERE user_id = ? AND conversation_id = ? "
        "ORDER BY created_at, id LIMIT 2", (user_id, conversation_id)
    ).fetchall()
    if len(turns) != 1:
        raise RuntimeError("owner turn scope invalid")
    turn = dict(turns[0])
    previews = connection.execute(
        "SELECT id, status, query_text, context_version FROM assistant_search_previews "
        "WHERE user_id = ? AND conversation_id = ? AND turn_id = ? ORDER BY created_at, id LIMIT 2",
        (user_id, conversation_id, turn["id"]),
    ).fetchall()
    if len(previews) != 1:
        raise RuntimeError("owner preview scope invalid")
    preview = dict(previews[0])
    table_queries = (
        (
            "assistant_conversations",
            "SELECT * FROM assistant_conversations WHERE user_id = ? "
            "ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_turns",
            "SELECT * FROM assistant_turns WHERE user_id = ? ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_messages",
            "SELECT * FROM assistant_messages WHERE user_id = ? ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_events",
            "SELECT * FROM assistant_events WHERE user_id = ? ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_sources",
            "SELECT * FROM assistant_sources WHERE user_id = ? ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_proposed_actions",
            "SELECT * FROM assistant_proposed_actions WHERE user_id = ? "
            "ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_action_receipts",
            "SELECT * FROM assistant_action_receipts WHERE user_id = ? "
            "ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_execution_leases",
            "SELECT * FROM assistant_execution_leases WHERE user_id = ? "
            "ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_search_previews",
            "SELECT * FROM assistant_search_previews WHERE user_id = ? "
            "ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_model_consents",
            "SELECT * FROM assistant_model_consents WHERE user_id = ? "
            "ORDER BY rowid LIMIT 257",
        ),
        (
            "assistant_conversation_deletions",
            "SELECT * FROM assistant_conversation_deletions WHERE user_id = ? "
            "ORDER BY rowid LIMIT 257",
        ),
        (
            "user_instrument_list_items",
            "SELECT kind, provider, canonical_symbol, asset_type, exchange, display_name, "
            "quantity, added_at FROM user_instrument_list_items WHERE owner_user_id = ? "
            "ORDER BY kind, added_at, canonical_symbol LIMIT 257",
        ),
    )
    rows_by_table = {}
    row_counts = {}
    for table, query in table_queries:
        rows = connection.execute(query, (user_id,)).fetchall()
        if len(rows) > 256:
            raise RuntimeError("owner projection exceeded its row bound")
        rows_by_table[table] = [dict(row) for row in rows]
        row_counts[table] = len(rows)
    canonical = json.dumps(
        rows_by_table, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":")
    ).encode("utf-8")
    saved_rows = json.dumps(
        rows_by_table["user_instrument_list_items"], sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    if len(canonical) > 1_048_576:
        raise RuntimeError("owner projection exceeded its byte bound")
    result = {
        "conversation_id": conversation_id,
        "context_route_matches": True,
        "turn_id": str(turn["id"]),
        "turn_status": str(turn["status"]),
        "turn_error_code": turn["error_code"],
        "model_id": str(turn["model_id"]),
        "policy_version": str(turn["policy_version"]),
        "turn_context_version": str(turn["context_version"]),
        "preview_id": str(preview["id"]),
        "preview_status": str(preview["status"]),
        "preview_context_version": str(preview["context_version"]),
        "search_query_sha256": hashlib.sha256(str(preview["query_text"]).encode()).hexdigest(),
        "row_counts": row_counts,
        "saved_record_sha256": hashlib.sha256(saved_rows).hexdigest(),
        "state_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    print(json.dumps(result, separators=(",", ":")))
finally:
    connection.rollback()
    connection.close()
"""
    input_text = json.dumps({"session_cookie": session_cookie}, separators=(",", ":")) + "\n"
    value = supervised._docker_exec_json(
        candidate,
        "10001:10001",
        script,
        input_text=input_text,
        timeout=5,
    )
    expected_fields = {
        "conversation_id",
        "context_route_matches",
        "turn_id",
        "turn_status",
        "turn_error_code",
        "model_id",
        "policy_version",
        "turn_context_version",
        "preview_id",
        "preview_status",
        "preview_context_version",
        "search_query_sha256",
        "row_counts",
        "saved_record_sha256",
        "state_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise ProbeError("owner-scoped candidate database projection was malformed")
    if (
        not isinstance(value.get("conversation_id"), str)
        or _CONVERSATION_ID.fullmatch(value["conversation_id"]) is None
        or not isinstance(value.get("turn_id"), str)
        or _CONVERSATION_ID.fullmatch(value["turn_id"]) is None
        or not isinstance(value.get("preview_id"), str)
        or _PREVIEW_ID.fullmatch(value["preview_id"]) is None
        or value.get("context_route_matches") is not True
        or value.get("turn_status") not in {"running", "cancelled", "failed", "timed_out"}
        or value.get("preview_status") != "pending"
        or not isinstance(value.get("row_counts"), dict)
        or set(value["row_counts"]) != set(_OWNER_TABLE_QUERIES)
        or any(
            type(count) is not int or not 0 <= count <= 256
            for count in value["row_counts"].values()
        )
        or not isinstance(value.get("saved_record_sha256"), str)
        or _HEX64.fullmatch(value["saved_record_sha256"]) is None
        or not isinstance(value.get("state_sha256"), str)
        or _HEX64.fullmatch(value["state_sha256"]) is None
        or not isinstance(value.get("search_query_sha256"), str)
        or _HEX64.fullmatch(value["search_query_sha256"]) is None
        or not isinstance(value.get("turn_context_version"), str)
        or not isinstance(value.get("preview_context_version"), str)
        or value["turn_context_version"] != value["preview_context_version"]
    ):
        raise ProbeError("owner-scoped candidate database projection failed closed validation")
    _maintained_model_policy(
        {"model_id": value.get("model_id"), "policy_version": value.get("policy_version")}
    )
    return value


def _saved_record_projection(
    candidate: supervised.Candidate, user: dict[str, str]
) -> dict[str, object]:
    """Hash the seeded owner's instrument-list rows without returning item values."""

    _require_scoped_candidate(candidate)
    session_cookie = user.get("session_cookie")
    if not isinstance(session_cookie, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{32,128}", session_cookie
    ):
        raise ProbeError("synthetic owner session was malformed for the saved-record projection")
    script = r"""import hashlib, json, sqlite3, sys
from stock_probs.config import Settings

payload = json.loads(sys.stdin.readline(4096))
if set(payload) != {"session_cookie"} or not isinstance(payload["session_cookie"], str):
    raise RuntimeError("projection input invalid")
token_hash = hashlib.sha256(payload["session_cookie"].encode("ascii")).hexdigest()
settings = Settings.from_env()
uri = settings.database_path.resolve().as_uri() + "?mode=ro"
connection = sqlite3.connect(uri, uri=True, timeout=2.0)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA query_only=ON")
connection.execute("BEGIN")
try:
    sessions = connection.execute(
        "SELECT user_id FROM sessions WHERE token_hash = ? LIMIT 2", (token_hash,)
    ).fetchall()
    if len(sessions) != 1:
        raise RuntimeError("owner session scope invalid")
    user_id = int(sessions[0]["user_id"])
    query = (
        "SELECT kind, provider, canonical_symbol, asset_type, exchange, display_name, "
        "quantity, added_at FROM user_instrument_list_items WHERE owner_user_id = ? "
        "ORDER BY kind, added_at, canonical_symbol LIMIT 257"
    )
    rows = connection.execute(query, (user_id,)).fetchall()
    if len(rows) > 256:
        raise RuntimeError("saved-record projection exceeded its row bound")
    canonical = json.dumps(
        [dict(row) for row in rows], sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":")
    ).encode("utf-8")
    if len(canonical) > 1_048_576:
        raise RuntimeError("saved-record projection exceeded its byte bound")
    result = {
        "saved_record_count": len(rows),
        "saved_record_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    print(json.dumps(result, separators=(",", ":")))
finally:
    connection.rollback()
    connection.close()
"""
    input_text = json.dumps({"session_cookie": session_cookie}, separators=(",", ":")) + "\n"
    value = supervised._docker_exec_json(
        candidate,
        "10001:10001",
        script,
        input_text=input_text,
        timeout=5,
    )
    if (
        not isinstance(value, dict)
        or set(value) != {"saved_record_count", "saved_record_sha256"}
        or type(value.get("saved_record_count")) is not int
        or not 0 <= value["saved_record_count"] <= 256
        or not isinstance(value.get("saved_record_sha256"), str)
        or _HEX64.fullmatch(value["saved_record_sha256"]) is None
    ):
        raise ProbeError("owner-scoped saved-record projection failed closed validation")
    return value


def _approval_material(
    candidate: supervised.Candidate,
    user: dict[str, str],
    state: dict[str, object],
    expected_query_hash: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Capture exact synthetic context and approval material before the kill command."""

    context_status, context_payload = _request(
        candidate, user, "GET", "/api/v1/assistant/context?route=%2Foverview"
    )
    context = context_payload.get("context")
    if (
        context_status != 200
        or not isinstance(context, dict)
        or context.get("context_version") != state.get("turn_context_version")
    ):
        raise ProbeError("synthetic owner context could not be captured before the kill")
    preview_path = (
        f"/api/v1/assistant/conversations/{state['conversation_id']}/turns/{state['turn_id']}"
        f"/search-previews/{state['preview_id']}"
    )
    preview_status, preview_payload = _request(candidate, user, "GET", preview_path)
    preview = preview_payload
    if (
        preview_status != 200
        or not isinstance(preview, dict)
        or preview.get("id") != state.get("preview_id")
        or preview.get("status") != "pending"
        or not isinstance(preview.get("query"), str)
        or hashlib.sha256(preview["query"].encode("utf-8")).hexdigest() != expected_query_hash
        or preview.get("context_version") != state.get("turn_context_version")
        or not isinstance(preview.get("confirmation_phrase"), str)
        or not preview["confirmation_phrase"]
    ):
        raise ProbeError("native search approval was not exact and pending before the kill")
    return context, preview


def _private_history_projection(
    candidate: supervised.Candidate, user: dict[str, str]
) -> dict[str, object]:
    """Verify the authenticated app history API remains available after worker disable."""

    status, payload = _request(candidate, user, "GET", "/api/v1/history")
    items = payload.get("items")
    total = payload.get("total")
    if status != 200 or not isinstance(items, list) or type(total) is not int or total < 0:
        raise ProbeError("synthetic owner could not retrieve normal private app history")
    return {"http_status": 200, "visible_event_count": len(items), "total_event_count": total}


def _worker_home_projection(candidate: supervised.Candidate) -> dict[str, object]:
    script = r"""import json, os, stat
roots = ("/run/assistant-worker-home", "/run/assistant-worker-home/tmp")
result = {"complete": True, "regular_files": 0, "symlinks": 0, "special_files": 0,
          "unreadable_entries": 0, "directories": 0, "bytes_scanned": 0, "roots": []}
limit = 4096
for root in roots:
    try:
        info = os.lstat(root)
    except OSError:
        result["complete"] = False
        break
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 10002
        or info.st_gid != 10002
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        result["complete"] = False
        break
    result["roots"].append(
        {"uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode)}
    )
pending = [roots[0]]
while pending and result["complete"]:
    directory = pending.pop()
    try:
        entries = list(os.scandir(directory))
    except OSError:
        result["unreadable_entries"] += 1
        result["complete"] = False
        break
    for entry in entries:
        limit -= 1
        if limit < 0:
            result["complete"] = False
            break
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            result["unreadable_entries"] += 1
            result["complete"] = False
            break
        if stat.S_ISLNK(info.st_mode):
            result["symlinks"] += 1
            result["complete"] = False
        elif stat.S_ISDIR(info.st_mode):
            result["directories"] += 1
            pending.append(entry.path)
        elif stat.S_ISREG(info.st_mode):
            result["regular_files"] += 1
            result["bytes_scanned"] += info.st_size
        else:
            result["special_files"] += 1
            result["complete"] = False
print(json.dumps(result, separators=(",", ":")))
"""
    value = supervised._docker_exec_json(candidate, "10002:10002", script, timeout=8)
    if (
        not isinstance(value, dict)
        or value.get("complete") is not True
        or value.get("roots") != [{"uid": 10002, "gid": 10002, "mode": 0o700}] * 2
        or value.get("regular_files") != 0
        or value.get("symlinks") != 0
        or value.get("special_files") != 0
        or value.get("unreadable_entries") != 0
        or value.get("directories") != 1
        or value.get("bytes_scanned") != 0
    ):
        raise ProbeError("private worker HOME and TMPDIR were not empty after kill")
    return {
        "complete": True,
        "regular_files": 0,
        "symlinks": 0,
        "special_files": 0,
        "unreadable_entries": 0,
        "directories": 1,
        "bytes_scanned": 0,
        "roots": 2,
    }


def _app_process(snapshot: list[dict[str, object]]) -> dict[str, object]:
    rows = [row for row in snapshot if row.get("role") == "app_wrapper"]
    if len(rows) != 1 or type(rows[0].get("pid")) is not int or rows[0]["pid"] <= 1:
        raise ProbeError("candidate app process identity was not unique")
    return {"pid": rows[0]["pid"], "uid": rows[0].get("uid"), "gid": rows[0].get("gid")}


def _verify_surviving_app_profile(
    snapshot: list[dict[str, object]], expected_app: dict[str, object]
) -> dict[str, object]:
    """Require only the unchanged, unprivileged app and bounded supervisor after kill."""

    expected_roles = {"supervisor": 1, "app_wrapper": 1, "worker_wrapper": 0, "native_worker": 0}
    counts = {role: sum(row.get("role") == role for row in snapshot) for role in expected_roles}
    if counts != expected_roles:
        raise ProbeError("candidate process roles were invalid after assistant kill")
    by_role = {row.get("role"): row for row in snapshot}
    supervisor = by_role.get("supervisor")
    app = by_role.get("app_wrapper")
    if not isinstance(supervisor, dict) or not isinstance(app, dict):
        raise ProbeError("candidate app or supervisor profile was absent after assistant kill")
    app_identity = _app_process(snapshot)
    if (
        app_identity != expected_app
        or app.get("uid") != 10001
        or app.get("gid") != 10001
        or app.get("cap_eff") not in {"0000000000000000", "0"}
        or app.get("cap_prm") not in {"0000000000000000", "0"}
        or app.get("no_new_privileges") != "1"
        or supervisor.get("pid") != 1
        or supervisor.get("uid") != 0
        or supervisor.get("gid") != 0
        or supervisor.get("cap_eff") != "00000000000000c0"
        or supervisor.get("cap_prm") != "00000000000000c0"
        or supervisor.get("cap_bnd") != "00000000000000c0"
        or supervisor.get("no_new_privileges") != "1"
    ):
        raise ProbeError(
            "candidate surviving app or supervisor profile changed after assistant kill"
        )
    return {
        "supervisor": {
            "pid": 1,
            "uid": 0,
            "gid": 0,
            "cap_eff": supervisor["cap_eff"],
            "cap_prm": supervisor["cap_prm"],
            "cap_bnd": supervisor["cap_bnd"],
            "no_new_privileges": "1",
        },
        "app_wrapper": {
            **app_identity,
            "cap_eff": app["cap_eff"],
            "cap_prm": app["cap_prm"],
            "no_new_privileges": "1",
        },
    }


def _wait_for_worker_exit(candidate: supervised.Candidate) -> dict[str, object]:
    deadline = time.monotonic() + TERMINAL_POLL_SECONDS
    latest: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        latest = supervised._process_snapshot(candidate)
        if not any(row.get("role") in {"worker_wrapper", "native_worker"} for row in latest):
            return {
                "worker_wrapper_gone": True,
                "native_worker_gone": True,
                "processes_after_kill": len(latest),
            }
        time.sleep(0.25)
    raise ProbeError("assistant worker processes remained after the kill command")


def _wait_for_disabled_readiness(candidate: supervised.Candidate) -> dict[str, object]:
    """Wait only for the bounded app projection to reflect the completed supervisor kill."""

    deadline = time.monotonic() + TERMINAL_POLL_SECONDS
    while time.monotonic() < deadline:
        try:
            health = supervised._health(candidate)
        except ProbeError:
            time.sleep(0.25)
            continue
        assistant = health.get("assistant")
        if (
            health.get("status") == "ready"
            and health.get("schema_version") == 13
            and isinstance(assistant, dict)
            and assistant.get("enabled") is False
            and assistant.get("status") == "disabled"
        ):
            return {
                "status": "ready",
                "schema_version": 13,
                "assistant_status": "disabled",
                "assistant_enabled": False,
            }
        time.sleep(0.25)
    raise ProbeError("application readiness did not remain ready after assistant disable")


def _wait_for_terminal_state(
    candidate: supervised.Candidate, user: dict[str, str], expected_query_hash: str
) -> dict[str, object]:
    """Poll only the fixed owner-scoped SQLite projection until the active turn is terminal."""

    deadline = time.monotonic() + TERMINAL_POLL_SECONDS
    latest: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest = _owner_state_snapshot(candidate, user)
        if (
            latest.get("turn_status") in {"cancelled", "failed", "timed_out"}
            and latest.get("preview_status") == "pending"
            and latest.get("search_query_sha256") == expected_query_hash
        ):
            error_code = latest.get("turn_error_code")
            if error_code is not None and error_code not in SAFE_TERMINAL_ERRORS:
                raise ProbeError("active native turn returned an undocumented terminal error")
            return latest
        time.sleep(0.25)
    raise ProbeError("synthetic owner database did not reach a bounded fail-closed terminal state")


def _sample_resource_state(candidate: supervised.Candidate) -> dict[str, int]:
    sample = supervised._read_resources(candidate)
    if (
        sample["memory_peak"] > MEMORY_LIMIT_BYTES
        or sample["pids_current"] > PROCESS_LIMIT
        or sample["memory_events_oom"] > 0
        or sample["memory_events_oom_kill"] > 0
    ):
        raise ProbeError("candidate exceeded its verified memory or process resource limits")
    return sample


def run_probe(
    container: str,
    image_id: str,
    context_sha256: str,
    volume: str,
    candidate_revision: str | None = None,
) -> dict[str, object]:
    """Kill a verified candidate; PR identity comes from its verified build receipt.

    The explicit revision and context digest must be copied from the verified PR-candidate build
    receipt. The shared probe checks that the immutable image ID carries that exact revision label
    and linux/amd64 platform; this kill probe never builds or relabels an image.
    """

    candidate_revision = supervised._validated_candidate_revision(candidate_revision)
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if (
        supervised._SHA256_IMAGE.fullmatch(image_id) is None
        or _HEX64.fullmatch(context_sha256) is None
    ):
        raise ProbeError("candidate image and source context must use exact SHA-256 identities")
    candidate = supervised._candidate_container(
        container, image_id, context_sha256, volume, candidate_revision
    )
    _require_scoped_candidate(candidate)
    initial_candidate = {
        "container": candidate.container,
        "container_id": candidate.container_id,
        "image_id": candidate.image_id,
        "data_volume": candidate.data_volume,
        "network_name": candidate.network_name,
        "network_id": candidate.network_id,
        "source_context_sha256": context_sha256,
        "candidate_revision": candidate_revision,
        "revision_label": candidate_revision or f"local-source-{context_sha256}",
        "architecture": "linux/amd64",
    }
    baseline = _sample_resource_state(candidate)
    readiness_before = supervised._health(candidate)
    assistant_before = readiness_before.get("assistant")
    if (
        not isinstance(assistant_before, dict)
        or assistant_before.get("status") != "ready"
        or assistant_before.get("enabled") is not True
    ):
        raise ProbeError("candidate assistant was not ready before the active-turn probe")
    candidate = supervised._refresh_candidate_for_write(
        candidate, context_sha256, candidate_revision
    )
    _require_scoped_candidate(candidate)
    users = supervised._seed_users(candidate)
    if len(users) != 2:
        raise ProbeError("candidate fixture did not create exactly two synthetic owners")
    saved_records_before = _saved_record_projection(candidate, users[1])
    if saved_records_before.get("saved_record_count") != 2:
        raise ProbeError("synthetic candidate did not retain its two saved portfolio records")
    private_history_before = _private_history_projection(candidate, users[1])
    child: subprocess.Popen[bytes] | None = None
    checkpoint_bytes = b""
    try:
        child, checkpoint, checkpoint_bytes = _start_native_driver(candidate, users)
        active_health = supervised._health(candidate)
        active_assistant = active_health.get("assistant")
        if (
            not isinstance(active_assistant, dict)
            or active_assistant.get("status") != "ready"
            or active_assistant.get("enabled") is not True
        ):
            raise ProbeError(
                "candidate app or worker was not ready at the active search checkpoint"
            )
        active_state = _owner_state_snapshot(candidate, users[1])
        if (
            active_state.get("turn_status") != "running"
            or active_state.get("preview_status") != "pending"
            or active_state.get("search_query_sha256") != checkpoint["search_query_sha256"]
            or active_state.get("row_counts", {}).get("assistant_conversations") != 1
            or active_state.get("row_counts", {}).get("assistant_turns") != 1
            or active_state.get("row_counts", {}).get("assistant_search_previews") != 1
            or active_state.get("row_counts", {}).get("user_instrument_list_items") != 2
            or active_state.get("saved_record_sha256")
            != saved_records_before.get("saved_record_sha256")
        ):
            raise ProbeError(
                "owner-scoped database did not match the native pending-search checkpoint"
            )
        approval_context, approval_preview = _approval_material(
            candidate, users[1], active_state, str(checkpoint["search_query_sha256"])
        )
        process_before = supervised._process_snapshot(candidate)
        app_before = _app_process(process_before)
        role_counts = {
            role: sum(row.get("role") == role for row in process_before)
            for role in ("supervisor", "app_wrapper", "worker_wrapper", "native_worker")
        }
        if role_counts != {
            "supervisor": 1,
            "app_wrapper": 1,
            "worker_wrapper": 1,
            "native_worker": 1,
        }:
            raise ProbeError(
                "native worker process tree was absent at the pending-search checkpoint"
            )
        process_profile_before_kill = supervised._verify_worker_processes(process_before)

        candidate_pre_kill = supervised._candidate_container(
            container, image_id, context_sha256, volume, candidate_revision
        )
        if (
            candidate_pre_kill.container_id != candidate.container_id
            or candidate_pre_kill.host_pid != candidate.host_pid
            or candidate_pre_kill.image_id != candidate.image_id
            or candidate_pre_kill.data_volume != candidate.data_volume
            or candidate_pre_kill.host_port != candidate.host_port
            or candidate_pre_kill.network_name != candidate.network_name
            or candidate_pre_kill.network_id != candidate.network_id
            or candidate_pre_kill.candidate_revision != candidate.candidate_revision
        ):
            raise ProbeError("candidate container identity changed before the kill command")
        kill_receipt = _run_kill(candidate_pre_kill)
        resource_after_kill = _sample_resource_state(candidate)
        candidate_after = supervised._candidate_container(
            container, image_id, context_sha256, volume, candidate_revision
        )
        if (
            candidate_after.container_id != candidate.container_id
            or candidate_after.host_pid != candidate.host_pid
            or candidate_after.image_id != candidate.image_id
            or candidate_after.data_volume != candidate.data_volume
            or candidate_after.host_port != candidate.host_port
            or candidate_after.network_name != candidate.network_name
            or candidate_after.network_id != candidate.network_id
            or candidate_after.candidate_revision != candidate.candidate_revision
        ):
            raise ProbeError("candidate container identity changed during the kill probe")
        readiness_after_projection = _wait_for_disabled_readiness(candidate_after)

        worker_exit = _wait_for_worker_exit(candidate_after)
        process_after = supervised._process_snapshot(candidate_after)
        app_after = _app_process(process_after)
        surviving_app_profile = _verify_surviving_app_profile(process_after, app_before)
        home_purge = _worker_home_projection(candidate_after)

        terminal_state = _wait_for_terminal_state(
            candidate_after, users[1], str(checkpoint["search_query_sha256"])
        )
        if terminal_state.get("row_counts", {}).get(
            "user_instrument_list_items"
        ) != 2 or terminal_state.get("saved_record_sha256") != saved_records_before.get(
            "saved_record_sha256"
        ):
            raise ProbeError("saved portfolio records changed during assistant kill")
        conversation_id = str(terminal_state["conversation_id"])
        turn_id = str(terminal_state["turn_id"])
        preview_id = str(terminal_state["preview_id"])
        turn_status = str(terminal_state["turn_status"])
        turn_error_code = terminal_state.get("turn_error_code")
        _maintained_model_policy(
            {
                "model_id": active_state.get("model_id"),
                "policy_version": active_state.get("policy_version"),
            }
        )
        assistant_list_denial = _require_disabled_error(
            _request(candidate_after, users[1], "GET", "/api/v1/assistant/conversations"),
            stage="conversation history",
        )
        detail_path = f"/api/v1/assistant/conversations/{conversation_id}"
        assistant_detail_denial = _require_disabled_error(
            _request(candidate_after, users[1], "GET", detail_path),
            stage="conversation detail",
        )
        context_denial = _require_disabled_error(
            _request(
                candidate_after,
                users[1],
                "GET",
                "/api/v1/assistant/context?route=%2Foverview",
            ),
            stage="context preview",
        )
        preview_path = f"{detail_path}/turns/{turn_id}/search-previews/{preview_id}"
        preview_denial = _require_disabled_error(
            _request(candidate_after, users[1], "GET", preview_path),
            stage="search preview",
        )
        confirm_path = (
            f"/api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/"
            f"search-previews/{preview_id}/confirm"
        )
        approval_denial = _require_disabled_error(
            _request(
                candidate_after,
                users[1],
                "POST",
                confirm_path,
                body={
                    "context": approval_context,
                    "context_version": approval_preview["context_version"],
                    "confirmation_phrase": approval_preview["confirmation_phrase"],
                    "allow": True,
                },
                csrf=True,
            ),
            stage="pending search approval",
        )
        state_after_confirmation = _owner_state_snapshot(candidate_after, users[1])
        if (
            state_after_confirmation.get("state_sha256") != terminal_state.get("state_sha256")
            or state_after_confirmation.get("preview_status") != "pending"
            or state_after_confirmation.get("turn_status") != turn_status
            or state_after_confirmation.get("saved_record_sha256")
            != saved_records_before.get("saved_record_sha256")
        ):
            raise ProbeError("denied post-kill approval changed the owner-scoped database state")

        new_turn_denial = _require_disabled_error(
            _request(
                candidate_after,
                users[1],
                "POST",
                f"{detail_path}/turns",
                body={
                    "prompt": "Synthetic kill-switch denial probe; do not start work.",
                    "model_id": active_state["model_id"],
                    "policy_version": active_state["policy_version"],
                    "context": approval_context,
                    "context_preview_accepted": True,
                },
                csrf=True,
            ),
            stage="new turn",
        )
        state_after_new_turn = _owner_state_snapshot(candidate_after, users[1])
        if (
            state_after_new_turn.get("state_sha256") != terminal_state.get("state_sha256")
            or state_after_new_turn.get("preview_status") != "pending"
            or state_after_new_turn.get("turn_status") != turn_status
            or state_after_new_turn.get("saved_record_sha256")
            != saved_records_before.get("saved_record_sha256")
        ):
            raise ProbeError("denied post-kill turn changed the owner-scoped database state")
        private_history = _private_history_projection(candidate_after, users[1])
        state_after_history = _owner_state_snapshot(candidate_after, users[1])
        if (
            state_after_history.get("state_sha256") != terminal_state.get("state_sha256")
            or private_history != private_history_before
            or state_after_history.get("saved_record_sha256")
            != saved_records_before.get("saved_record_sha256")
        ):
            raise ProbeError("normal private history changed the owner-scoped probe projections")

        driver_receipt = _close_paused_driver(child, checkpoint_bytes, users)
        child = None
        final_resource = _sample_resource_state(candidate_after)
        app_identity = {"pid": app_after["pid"], "uid": app_after["uid"], "gid": app_after["gid"]}
        return {
            "status": "pass",
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "execution_environment": "local disposable linux/amd64 candidate; cgroup-v2 enforced",
            "candidate": initial_candidate,
            "active_checkpoint": checkpoint,
            "kill_command": kill_receipt,
            "worker_process_profile_before_kill": process_profile_before_kill,
            "surviving_app_profile_after_kill": surviving_app_profile,
            "readiness_before": {
                "status": "ready",
                "schema_version": 13,
                "assistant_status": "ready",
            },
            "readiness_after": readiness_after_projection,
            "container_and_app_identity_preserved": {
                "container_id": candidate.container_id,
                "app_process": app_identity,
            },
            "worker_processes": worker_exit,
            "worker_home": home_purge,
            "private_app_history": {
                "retrieved_after_kill": True,
                "same_projection_as_before_kill": private_history == private_history_before,
                "baseline_visible_event_count": private_history_before["visible_event_count"],
                "baseline_total_event_count": private_history_before["total_event_count"],
                **private_history,
            },
            "saved_private_records": {
                "owner_scoped_projection": True,
                "record_count": saved_records_before["saved_record_count"],
                "records_unchanged_after_kill": True,
                "records_sha256": saved_records_before["saved_record_sha256"],
            },
            "private_assistant_history": {
                "owner_scoped_read_only_projection": True,
                "conversation_count": terminal_state["row_counts"]["assistant_conversations"],
                "turn_count": terminal_state["row_counts"]["assistant_turns"],
                "active_turn_terminal_status": turn_status,
                "active_turn_error_code": turn_error_code,
                "pending_search_preview_retained": terminal_state["preview_status"] == "pending",
                "search_query_sha256": terminal_state["search_query_sha256"],
                "owner_rows_sha256": terminal_state["state_sha256"],
            },
            "post_kill_denials": {
                "conversation_list": assistant_list_denial,
                "conversation_detail": assistant_detail_denial,
                "context_preview": context_denial,
                "search_preview": preview_denial,
                "approval_confirmation": approval_denial,
                "new_turn": new_turn_denial,
                "approval_still_pending": True,
                "owner_database_unchanged": True,
                "normal_private_history_unchanged": True,
            },
            "native_driver": driver_receipt,
            "resource_limits": {
                "memory_limit_bytes": MEMORY_LIMIT_BYTES,
                "process_limit": PROCESS_LIMIT,
                "memory_peak_bytes": max(
                    baseline["memory_peak"],
                    resource_after_kill["memory_peak"],
                    final_resource["memory_peak"],
                ),
                "pids_peak_sampled": max(
                    baseline["pids_current"],
                    resource_after_kill["pids_current"],
                    final_resource["pids_current"],
                ),
                "oom_events": final_resource["memory_events_oom"],
                "oom_kill_events": final_resource["memory_events_oom_kill"],
            },
            "candidate_container_and_volume_removed": False,
        }
    finally:
        if child is not None:
            if child.stdin is not None and not child.stdin.closed:
                with contextlib.suppress(OSError):
                    child.stdin.close()
            _stop_child(child)
        for user in users:
            user.clear()


def main(argv: list[str] | None = None) -> int:
    """Run the opt-in probe only for an explicitly identified disposable candidate."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-container", required=True)
    parser.add_argument("--candidate-image-id", required=True)
    parser.add_argument("--source-context-sha256", required=True)
    parser.add_argument("--candidate-volume", required=True)
    parser.add_argument(
        "--candidate-revision",
        help="exact lowercase reviewed commit SHA from a verified PR-candidate build receipt",
    )
    args = parser.parse_args(argv)
    try:
        report = run_probe(
            args.candidate_container,
            args.candidate_image_id,
            args.source_context_sha256,
            args.candidate_volume,
            args.candidate_revision,
        )
    except ProbeError as exc:
        print(
            json.dumps({"status": "fail", "reason": str(exc), **exc.safe_details}, sort_keys=True)
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
