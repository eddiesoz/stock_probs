"""Attach the native assistant acceptance driver to one disposable candidate container.

This is an opt-in local probe. It never builds, starts, stops, or removes a container or volume.
The caller must supply the exact image/context identity and the dedicated R-ASTRA-120 container
and volume names; cookies and CSRF values exist only in process memory and child stdin pipes.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import queue
import re
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NATIVE_DRIVER = ROOT / "tests" / "native_assistant_probe.py"
PYTHON = ROOT / ".dev-venv" / "bin" / "python"
PUBLIC_ORIGIN = "https://ledger-r120.test"
PUBLIC_HOST = "ledger-r120.test"
CONTAINER_PREFIX = "assistant-r120-candidate-"
VOLUME_PREFIX = "stock-probs-assistant-r120-"
CONTEXT_LABEL = "org.opencontainers.image.revision"
CONTROL_CANDIDATE_LABEL = "org.stock-probs.assistant-r120.candidate"
DISPOSABLE_VOLUME_LABEL = "org.stock-probs.assistant-r120.disposable"
MEMORY_LIMIT_BYTES = 768 * 1024 * 1024
CPU_LIMIT_NANOS = 1_000_000_000
PROCESS_LIMIT = 128
DOCKER_DAEMON_ENDPOINT = "unix:///var/run/docker.sock"
NATIVE_TIMEOUT_SECONDS = 180
RESOURCE_POLL_SECONDS = 0.2
OUTPUT_LIMIT = 128 * 1024
ERROR_OUTPUT_LIMIT = 32 * 1024
_NATIVE_TIMING_MARKER = "ASSISTANT_TURN_TIMING_V1 "
_NATIVE_TIMING_V2_MARKER = "ASSISTANT_TURN_TIMING_V2 "
_NATIVE_TIMING_V3_MARKER = "ASSISTANT_TURN_TIMING_V3 "
_NATIVE_TIMING_V4_MARKER = "ASSISTANT_TURN_TIMING_V4 "
_NATIVE_TIMING_V5_MARKER = "ASSISTANT_TURN_TIMING_V5 "
_NATIVE_TIMING_MARKERS = (
    _NATIVE_TIMING_MARKER,
    _NATIVE_TIMING_V2_MARKER,
    _NATIVE_TIMING_V3_MARKER,
    _NATIVE_TIMING_V4_MARKER,
    _NATIVE_TIMING_V5_MARKER,
)
_NATIVE_TIMING_MAX_LOG_BYTES = OUTPUT_LIMIT
_NATIVE_TIMING_MAX_ROWS = 2
_NATIVE_TIMING_MAX_PROVIDER_REQUESTS = 8
_NATIVE_TIMING_MAX_PROVIDER_CHUNKS = 1_048_576
_NATIVE_TIMING_MAX_PROVIDER_BYTES = 1_048_576
_NATIVE_TIMING_MAX_PROVIDER_CHUNK_BYTES = 32 * 1024
_NATIVE_TIMING_WORK_LIMIT_MS = 120_000
_NATIVE_TIMING_OBSERVATION_LIMIT_MS = 180_000
_NATIVE_TIMING_MARKER_COUNT_CAP = _NATIVE_TIMING_MAX_ROWS + 1
_NATIVE_PROVIDER_STREAM_FAILURE_PREFIX = "ASSISTANT_PROVIDER_STREAM_FAILURE_"
_NATIVE_PROVIDER_STREAM_FAILURE_MARKER = _NATIVE_PROVIDER_STREAM_FAILURE_PREFIX + "V1 "
_NATIVE_PROVIDER_STREAM_FAILURE_MAX_RECORDS = 16
_NATIVE_PROVIDER_STREAM_FAILURE_MARKER_COUNT_CAP = _NATIVE_PROVIDER_STREAM_FAILURE_MAX_RECORDS + 1
_NATIVE_PROVIDER_403_CONTENT_TYPE_CLASSES = frozenset(
    {"json", "html", "event_stream", "other", "missing", "invalid"}
)
_NATIVE_PROVIDER_403_CF_MITIGATED_CLASSES = frozenset({"challenge", "absent", "other"})
_NATIVE_PROVIDER_403_ERROR_TYPE_CLASSES = frozenset(
    {"region_error", "data_policy_error", "free_usage_limit_error", "other", "malformed", "unknown"}
)
_NATIVE_WARNING_MAX_RECORDS = 4
_NATIVE_WARNING_MARKER_COUNT_CAP = _NATIVE_WARNING_MAX_RECORDS + 1
# The collector's 256-line Docker tail is bounded even if each captured stream reaches that count.
_NATIVE_WARNING_OCCURRENCE_COUNT_MAX = 2 * 256
_NATIVE_TIMING_FAILURE_REASON_CODES = {
    "native timing diagnostic log input was malformed": "log_input_invalid",
    "native timing diagnostic marker count was malformed": "timing_marker_count_invalid",
    "native timing diagnostic payload was malformed": "timing_payload_invalid",
    "native timing diagnostic schema was malformed": "timing_schema_invalid",
    "native timing diagnostic offsets were malformed": "timing_offsets_invalid",
    "native timing diagnostic provider rows were malformed": "timing_provider_rows_invalid",
    "native timing diagnostic chunk counts were malformed": "timing_chunk_counts_invalid",
    "native timing diagnostic lifecycle was malformed": "timing_lifecycle_invalid",
    "native warning diagnostic integer was malformed": "warning_integer_invalid",
    "native warning diagnostic integer was out of bounds": "warning_integer_out_of_bounds",
    "native warning diagnostic category list was malformed": "warning_categories_invalid",
    "native warning diagnostic category list was invalid": "warning_categories_invalid",
    "native warning diagnostic timeout was malformed": "warning_timeout_invalid",
    "native warning diagnostic timeout was out of bounds": "warning_timeout_out_of_bounds",
    "native terminal warning diagnostic was malformed": "terminal_warning_invalid",
    "native terminal warning diagnostic was invalid": "terminal_warning_invalid",
    "native model discovery diagnostic was malformed": "model_discovery_payload_invalid",
    "native model discovery diagnostic outcome was invalid": "model_discovery_outcome_invalid",
    "native warning diagnostic marker was malformed": "warning_marker_invalid",
    "native warning diagnostic was malformed": "warning_payload_invalid",
    "native warning diagnostic phase was invalid": "warning_phase_invalid",
    "native warning diagnostic marker was invalid": "warning_marker_invalid",
    "native warning diagnostic record count was malformed": "warning_record_count_invalid",
    "native provider stream diagnostic marker was malformed": "provider_stream_marker_invalid",
    "native provider stream diagnostic marker was invalid": "provider_stream_marker_invalid",
    "native provider stream diagnostic payload was malformed": "provider_stream_payload_invalid",
    "native provider stream diagnostic stage was invalid": "provider_stream_stage_invalid",
    "native provider stream diagnostic error code was invalid": "provider_stream_code_invalid",
    "native provider stream diagnostic HTTP status was invalid": "provider_stream_status_invalid",
    "native provider stream diagnostic error type class was invalid": (
        "provider_stream_error_type_class_invalid"
    ),
    "native provider stream diagnostic record count was malformed": "provider_stream_count_invalid",
    "native provider stream diagnostic source was mixed": "provider_stream_source_mixed",
    "native timing diagnostic marker version was mixed": "timing_marker_version_mixed",
}
_NATIVE_TIMING_FAILURE_REASON_FALLBACK = "projection_invalid"
_NATIVE_WARNING_PHASES = frozenset(
    {
        "prepare_location",
        "verify_location",
        "location_discovery",
        "model_discovery",
        "mcp_discovery",
        "search_discovery",
        "create_session",
        "prompt",
        "wait_for_idle",
        "consume_messages",
        "unknown",
    }
)
_NATIVE_WARNING_STARTUP_STAGES = frozenset({"supervisor_status", "native_api_info"})
_NATIVE_WARNING_PRESESSION_STAGES = frozenset(
    {
        "prepare_location",
        "verify_location",
        "location_discovery",
        "model_discovery",
        "mcp_discovery",
        "search_discovery",
        "create_session",
    }
)
_NATIVE_WARNING_FAILURE_CODES = frozenset(
    {
        "diagnostic_unknown",
        "empty_response",
        "home_purge_depth_exceeded",
        "home_purge_entry_limit",
        "home_purge_mount_boundary",
        "invalid_runtime_event",
        "location_conflict",
        "location_discovery_mismatch",
        "location_limit",
        "location_unavailable",
        "mcp_discovery_invalid",
        "mcp_unavailable",
        "model_alias_unavailable",
        "model_capabilities_invalid",
        "model_discovery_invalid",
        "model_discovery_unavailable",
        "model_provider_invalid",
        "model_proxy_config_invalid",
        "native_adapter_invalid",
        "native_adapter_unavailable",
        "native_api_unavailable",
        "native_http_error",
        "native_provider_mismatch",
        "native_request_timeout",
        "native_response_encoding_invalid",
        "native_response_invalid",
        "native_response_too_large",
        "native_adapter_unsupported",
        "operation_disabled",
        "output_too_large",
        "purge_id_unknown",
        "provider_policy_changed",
        "provider_unavailable",
        "request_invalid",
        "request_rejected",
        "request_timeout",
        "runtime_restarted",
        "sensitive_output_rejected",
        "session_revoked",
        "socket_unavailable",
        "tool_failed",
        "tool_unavailable",
        "turn_cancelled",
        "turn_timeout",
        "worker_home_identity_invalid",
        "worker_not_ready",
        "worker_observation_uncertain",
        "worker_start_timeout",
        "worker_status_invalid",
        "worker_tmp_identity_invalid",
        "worker_unavailable",
    }
)
_NATIVE_TIMING_PRESESSION_PHASES = _NATIVE_WARNING_PRESESSION_STAGES | frozenset(
    {
        "input_validation",
        "startup",
        "catalog_discovery",
        "model_resolution",
        "model_policy",
        "adapter_resolution",
        "turn_admission",
    }
)
_NATIVE_TIMING_PRESESSION_FAILURE_CODES = _NATIVE_WARNING_FAILURE_CODES | frozenset(
    {
        "location_invalid",
        "model_location_mismatch",
    }
)
_NATIVE_WARNING_SESSION_OUTCOMES = frozenset(
    {"failed", "interrupted", "succeeded", "wait_failed", "unknown"}
)
_NATIVE_WARNING_FAILURE_CATEGORIES = frozenset(
    {
        "approval_missing",
        "body_limit",
        "connection",
        "dns",
        "http",
        "native_defect",
        "native_error_unknown",
        "request_invalid",
        "tls",
        "timeout",
        "unknown",
    }
)
_NATIVE_WARNING_SNAPSHOT_STATUSES = frozenset(
    {
        "invalid_response",
        "too_many_messages",
        "invalid_scope",
        "too_many_parts",
        "read",
        "http_error",
        "timeout",
        "unavailable",
        "skipped_deadline",
    }
)
_NATIVE_WARNING_ASSISTANT_FINISHES = frozenset(
    {"stop", "tool-calls", "length", "content-filter", "error", "other"}
)
_NATIVE_WARNING_WEBFETCH_STATES = frozenset({"completed", "error", "running", "unknown"})
_NATIVE_WARNING_WEBFETCH_TIMEOUT_STAGES = frozenset(
    {
        "dns_lookup_timeout",
        "fetch_deadline",
        "request_or_native_tool_timeout",
        "unknown",
        "not_timeout",
    }
)
_NATIVE_WARNING_WEBFETCH_COMPLETIONS = frozenset(
    {
        "request_invalid",
        "final_url_invalid",
        "destination_mismatch",
        "approved_destination_present",
        "approval_missing",
    }
)
_NATIVE_WARNING_SNAPSHOT_MARKER = "Assistant native terminal turn failed "
_NATIVE_WARNING_DEADLINE_MARKER = "Assistant turn deadline expired "
_NATIVE_WARNING_REQUEST_TIMEOUT_MARKER = "Assistant native request timed out "
_NATIVE_WARNING_STARTUP_MARKER = "Assistant worker startup failed "
_NATIVE_WARNING_PRESESSION_MARKER = "Assistant pre-session failure "
_NATIVE_WARNING_MODEL_DISCOVERY_MARKER = "Assistant model discovery diagnostic "
_NATIVE_WARNING_MARKERS = (
    _NATIVE_WARNING_SNAPSHOT_MARKER,
    _NATIVE_WARNING_DEADLINE_MARKER,
    _NATIVE_WARNING_REQUEST_TIMEOUT_MARKER,
    _NATIVE_WARNING_STARTUP_MARKER,
    _NATIVE_WARNING_PRESESSION_MARKER,
    _NATIVE_WARNING_MODEL_DISCOVERY_MARKER,
)
_NATIVE_MODEL_DISCOVERY_OUTCOMES = frozenset(
    {
        "alias_capabilities_invalid",
        "alias_identity_mismatch",
        "alias_missing",
        "alias_missing_after_readiness",
        "alias_proxy_config_invalid",
        "catalog_http_error",
        "catalog_invalid",
        "catalog_location_mismatch",
        "catalog_timeout",
        "catalog_timeout_after_readiness",
        "readiness_http_error",
        "readiness_invalid",
        "readiness_timeout",
    }
)
_NATIVE_PROVIDER_STREAM_FAILURE_STAGES = frozenset(
    {"upstream_stream", "proxy_validation", "proxy_deadline", "proxy_guard"}
)
_NATIVE_PROVIDER_STREAM_FAILURE_CODES = frozenset(
    {
        "chunk_invalid",
        "chunk_too_large",
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
        "proxy_error_unknown",
        "request_invalid",
        "request_superseded",
        "stream_deadline_exceeded",
        "stream_output_limit_exceeded",
        "upstream_error_unknown",
        "url_invalid",
    }
)
_NATIVE_PROVIDER_STREAM_FAILURE_PATTERN = re.compile(
    r"^stage=(?P<stage>[a-z_]+) error_code=(?P<error_code>[a-z0-9_]+)"
    r"(?: http_status=(?P<http_status>[0-9]{3}))?$"
)
_NATIVE_WARNING_COUNT_MAX = 4096
_NATIVE_WARNING_ELAPSED_MAX_MS = 180_000
_NATIVE_WARNING_PROVIDER_TIMEOUT_MAX_SECONDS = 120.0
_NATIVE_WARNING_TOOL_ELAPSED_MAX_MS = 120_000
_NATIVE_WARNING_TOOL_ERROR_MAX = 8
_NATIVE_WARNING_INT = re.compile(r"^(?:0|[1-9][0-9]{0,8})$")
_NATIVE_WARNING_SECONDS = re.compile(
    r"^(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,17})?(?:e[+-]?[0-9]{1,3})?$"
)
_NATIVE_WARNING_CATEGORY_LIST = re.compile(r"^[a-z][a-z0-9_-]*(?:,[a-z][a-z0-9_-]*)*$")
_NATIVE_WARNING_TERMINAL_PATTERN = re.compile(
    r"^\(session_outcome=(?P<session_outcome>[a-z_]+), "
    r"snapshot=(?P<snapshot>[a-z_]+), "
    r"assistant_finish=(?P<assistant_finish>[a-z,-]+), "
    r"assistant_failure=(?P<assistant_failure>[a-z0-9_,-]+), "
    r"assistant_error_count=(?P<assistant_error_count>[0-9]+), "
    r"webfetch_state=(?P<webfetch_state>[a-z,-]+), "
    r"webfetch_failure=(?P<webfetch_failure>[a-z0-9_,-]+), "
    r"webfetch_timeout_stage=(?P<webfetch_timeout_stage>[a-z0-9_,-]+), "
    r"webfetch_timeout_seconds_max=(?P<webfetch_timeout_seconds_max>[^,]+), "
    r"webfetch_tool_elapsed_ms_max=(?P<webfetch_tool_elapsed_ms_max>[^,]+), "
    r"webfetch_completion=(?P<webfetch_completion>[a-z0-9_,-]+), "
    r"native_failure=(?P<native_failure>[a-z0-9_,-]+), "
    r"native_tool_error_count=(?P<native_tool_error_count>[0-9]+)\)\."
)
_NATIVE_WARNING_DEADLINE_PATTERN = re.compile(
    r"^\(phase=(?P<phase>[a-z_]+), elapsed_ms=(?P<elapsed_ms>[0-9]+)\)\."
)
_NATIVE_WARNING_REQUEST_TIMEOUT_PATTERN = re.compile(
    r"^\(phase=(?P<phase>[a-z_]+), error_code=request_timeout, "
    r"elapsed_ms=(?P<elapsed_ms>[0-9]+)\)\."
)
_NATIVE_WARNING_STARTUP_PATTERN = re.compile(
    r"^\(startup_stage=(?P<stage>[a-z_]+), failure_code=(?P<failure_code>[a-z0-9_]+)\)\."
)
_NATIVE_WARNING_PRESESSION_PATTERN = re.compile(
    r"^\(stage=(?P<stage>[a-z_]+), failure_code=(?P<failure_code>[a-z0-9_]+)\)\."
)
_NATIVE_WARNING_MODEL_DISCOVERY_PATTERN = re.compile(
    r"^\(phase=model_discovery, outcome=(?P<outcome>[a-z_]+), "
    r"readiness_attempts=(?P<readiness_attempts>[0-9]+), "
    r"readiness_timeouts=(?P<readiness_timeouts>[0-9]+), "
    r"catalog_attempts=(?P<catalog_attempts>[0-9]+), "
    r"catalog_timeouts=(?P<catalog_timeouts>[0-9]+), "
    r"empty_catalog_responses=(?P<empty_catalog_responses>[0-9]+), "
    r"missing_alias_responses=(?P<missing_alias_responses>[0-9]+), "
    r"post_readiness_catalog_responses=(?P<post_readiness_catalog_responses>[0-9]+), "
    r"post_readiness_missing_alias_responses=(?P<post_readiness_missing_alias_responses>[0-9]+), "
    r"elapsed_ms=(?P<elapsed_ms>[0-9]+)\)\."
)

_SHA256_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_WEBFETCH_TARGET_SHA256 = hashlib.sha256(b"https://www.iana.org/domains/reserved").hexdigest()
_NATIVE_FAILURE_STAGES = frozenset(
    {
        "input_validation",
        "model_inventory",
        "admin_step_up",
        "admin_model_policy",
        "user_consent_and_conversation_setup",
        "concurrent_turn_create",
        "turn_poll_and_search_confirmation",
        "owner_evidence_and_isolation",
        "conversation_delete_and_health",
        "acceptance_validation",
    }
)
_NATIVE_ACCEPTANCE_FAILURES = frozenset(
    {
        "turn_requests_not_concurrent",
        "search_not_approved",
        "active_search_checkpoint_missing",
        "native_search_sources_missing",
        "webfetch_not_approved",
        "webfetch_approval_not_owner_bound",
        "native_webfetch_source_missing",
        "owner0_turn_not_completed",
        "owner0_model_id_mismatch",
        "owner0_answer_empty",
        "owner0_workspace_summary_receipt_count_invalid",
        "owner0_workspace_summary_digest_mismatch",
        "owner0_selected_model_mismatch",
        "owner1_turn_not_completed",
        "owner1_model_id_mismatch",
        "owner1_answer_empty",
        "owner1_workspace_summary_receipt_count_invalid",
        "owner1_workspace_summary_digest_mismatch",
        "owner1_selected_model_mismatch",
        "owner0_conversation_delete_failed",
        "owner1_conversation_delete_failed",
        "cross_owner_access_not_denied",
        "forged_internal_mcp_not_denied",
        "worker_not_ready_after_turns",
        "supervised_app_not_reachable",
    }
)
_NATIVE_SAFE_TURN_ERROR_CODES = frozenset(
    {
        "worker_unavailable",
        "provider_unavailable",
        "provider_policy_changed",
        "tool_failed",
        "tool_unavailable",
        "turn_timeout",
        "turn_cancelled",
        "invalid_runtime_event",
        "runtime_restarted",
        "output_too_large",
        "empty_response",
        "sensitive_output_rejected",
        "session_revoked",
    }
)
_NATIVE_DELETE_PUBLIC_ERROR_CODES = frozenset(
    {
        "assistant_authorization_required",
        "assistant_busy",
        "assistant_cache_clear_pending",
        "assistant_conflict",
        "assistant_quota_exceeded",
        "assistant_storage_unavailable",
        "assistant_worker_unavailable",
        "conversation_revision",
        "delete_confirmation",
        "not_found",
        "session_revoked",
    }
)
_NATIVE_DELETE_DIAGNOSTIC_ERROR_CODES = _NATIVE_DELETE_PUBLIC_ERROR_CODES | {
    "none",
    "unknown",
}
_NATIVE_DELETE_DIAGNOSTIC_MAX_ATTEMPTS = 256
_NATIVE_TURN_FAILURE_STAGES = frozenset(
    {"none", "before_model_session_event", "after_model_session_event", "unknown_terminal"}
)
_SAFE_CONTAINER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_SAFE_VOLUME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_EXPECTED_TMPFS_OPTIONS = {
    "/tmp": frozenset(  # noqa: S108 - checks the container's private temporary mount.
        {"rw", "nosuid", "nodev", "noexec", "size=64m", "uid=10001", "gid=10001", "mode=0700"}
    ),
    "/run/assistant": frozenset({"rw", "nosuid", "nodev", "noexec", "size=16m", "mode=0711"}),
    "/run/assistant-worker-home": frozenset(
        {"rw", "nosuid", "nodev", "noexec", "size=64m", "uid=10002", "gid=10002", "mode=0700"}
    ),
}


class ProbeError(RuntimeError):
    """A bounded failure without command output, cookies, or private app details."""

    def __init__(self, message: str, *, safe_details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.safe_details = safe_details or {}


@dataclass(frozen=True)
class Candidate:
    container: str
    container_id: str
    image_id: str
    data_volume: str
    base_url: str
    host_port: int
    host_pid: int
    cgroup: Path
    network_name: str | None = None
    network_id: str | None = None
    candidate_revision: str | None = None


_SEED_SCRIPT = r'''import hashlib, json, secrets, sqlite3, sys
from datetime import UTC, datetime, timedelta
from stock_probs.config import Settings
from stock_probs.repository import Repository
from stock_probs.totp import encrypt_secret, generate_secret

def digest(value):
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

settings = Settings.from_env()
repository = Repository(settings.database_path)
# A unique named disposable volume must contain only the schema's legacy-owner placeholder.
with repository.connect() as connection:
    checks = {
        "users": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "sessions": connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        "totp_factors": connection.execute("SELECT COUNT(*) FROM totp_factors").fetchone()[0],
        "user_instrument_list_items": connection.execute(
            "SELECT COUNT(*) FROM user_instrument_list_items"
        ).fetchone()[0],
        "assistant_conversations": connection.execute(
            "SELECT COUNT(*) FROM assistant_conversations"
        ).fetchone()[0],
    }
    expected = {
        "users": 1,
        "sessions": 0,
        "totp_factors": 0,
        "user_instrument_list_items": 0,
        "assistant_conversations": 0,
    }
    if checks != expected:
        raise RuntimeError("candidate data volume is not a fresh assistant fixture")
    legacy = connection.execute(
        "SELECT login, legacy_owner_claimed_at FROM users WHERE id=1"
    ).fetchone()
    if legacy is None or legacy[0] != "legacy-owner" or legacy[1] is not None:
        raise RuntimeError("candidate legacy owner is not pristine")
counts = repository.representative_counts()
if any(counts.values()):
    raise RuntimeError("candidate research history is not empty")

now = datetime.now(UTC).replace(microsecond=0)
expires = now + timedelta(hours=23)
users = []
for index, item_count in enumerate((1, 2)):
    suffix = secrets.token_hex(4)
    github_id = 2_000_000_000 + secrets.randbelow(100_000_000)
    login = "r120-probe-" + suffix
    user = repository.auth_create_user({
        "github_id": github_id,
        "github_login": login,
        "display_name": "Synthetic assistant probe " + suffix,
        "role": "admin" if index == 0 else "member",
        "status": "active",
        "created_at": now,
    })
    user_id = int(user["id"])
    totp_secret = generate_secret() if index == 0 else None
    encrypted_factor = (
        encrypt_secret(totp_secret, settings.auth_session_secret, user_id=user_id)
        if totp_secret is not None
        else "test-only-encrypted-factor-material"
    )
    with repository.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO totp_factors "
            "(user_id, secret_ciphertext, created_at, confirmed_at, "
            "last_accepted_step, updated_at) "
            "VALUES (?, ?, ?, ?, -1, ?)",
            (
                user_id,
                encrypted_factor,
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        factor_id = int(cursor.lastrowid)
        connection.commit()
    session_cookie = secrets.token_urlsafe(32)
    csrf_cookie = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(16)
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO sessions
            (user_id, session_id, token_hash, csrf_token_hash, issued_at, last_seen_at,
             idle_expires_at, absolute_expires_at, auth_method, mfa_method,
             mfa_verified_at, mfa_factor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'github', 'totp', ?, ?)""",
            (user_id, session_id, hashlib.sha256(session_cookie.encode()).hexdigest(),
             hashlib.sha256(csrf_cookie.encode()).hexdigest(), now.isoformat(), now.isoformat(),
             expires.isoformat(), expires.isoformat(), now.isoformat(), factor_id),
        )
        connection.commit()
    if repository.auth_get_session(hashlib.sha256(session_cookie.encode()).hexdigest()) is None:
        raise RuntimeError("synthetic session did not verify through AuthStore")
    for offset in range(item_count):
        symbol = "R120" + ("A" if index == 0 else "B") + str(offset + 1)
        repository.add_instrument_list_item(
            "portfolio", owner_user_id=user_id, provider="Synthetic Test",
            canonical_symbol=symbol, asset_type="stock", exchange="TEST",
            display_name="Synthetic probe holding " + symbol, added_at=now, quantity=1.0,
        )
    result = {"saved_searches": 0, "watchlist_items": 0, "portfolio_items": item_count}
    identity = {
        "session_cookie": session_cookie,
        "csrf_cookie": csrf_cookie,
        "expected_tool_result_sha256": digest(result),
    }
    if totp_secret is not None:
        identity["totp_secret"] = totp_secret
    users.append(identity)
sys.stdout.write(json.dumps({"users": users}, separators=(",", ":")))
'''


_PROCESS_SNAPSHOT_SCRIPT = r"""import json, os, pathlib
rows = []
for entry in pathlib.Path("/proc").iterdir():
    if not entry.name.isdecimal():
        continue
    try:
        pid = int(entry.name)
        cmd = (entry / "cmdline").read_bytes()
        status = {}
        for line in (entry / "status").read_text(encoding="ascii").splitlines():
            key, _, value = line.partition(":")
            if key in {"Uid", "Gid", "CapEff", "CapPrm", "CapBnd", "NoNewPrivs"}:
                status[key] = value.strip()
        comm = (entry / "comm").read_text(encoding="ascii").strip()
        if pid == 1:
            role = "supervisor"
        elif b"--child\x00app" in cmd:
            role = "app_wrapper"
        elif b"--child\x00worker" in cmd:
            role = "worker_wrapper"
        elif comm == "opencode":
            role = "native_worker"
        else:
            continue
        try:
            oom = (entry / "oom_score_adj").read_text(encoding="ascii").strip()
        except OSError:
            oom = None
        rows.append({"pid": pid, "role": role, "comm": comm,
                     "uid": int(status.get("Uid", "-1").split()[0]),
                     "gid": int(status.get("Gid", "-1").split()[0]),
                     "cap_eff": status.get("CapEff"), "cap_prm": status.get("CapPrm"),
                     "cap_bnd": status.get("CapBnd"),
                     "no_new_privileges": status.get("NoNewPrivs"), "oom_score_adj": oom})
    except (OSError, ValueError, IndexError):
        continue
print(json.dumps(rows, separators=(",", ":")))
"""


_LOCATION_SNAPSHOT_SCRIPT = r"""import json, pathlib, re, stat
root = pathlib.Path("/run/assistant/worker-locations")
rows = []
try:
    for entry in root.iterdir():
        if not re.fullmatch(r"[0-9a-f]{32}", entry.name):
            continue
        path = entry / "opencode.json"
        try:
            info = path.lstat()
            rows.append({"path": str(path), "uid": info.st_uid, "gid": info.st_gid,
                         "mode": stat.S_IMODE(info.st_mode), "regular": stat.S_ISREG(info.st_mode)})
        except OSError:
            continue
except OSError:
    pass
print(json.dumps(rows, separators=(",", ":")))
"""


_ACTIVE_OWNER_EXECUTION_SCRIPT = r"""import json, re, sqlite3, sys
payload = json.load(sys.stdin)
session_hash = payload.get("session_token_sha256") if isinstance(payload, dict) else None
if not isinstance(session_hash, str) or re.fullmatch(r"[0-9a-f]{64}", session_hash) is None:
    raise SystemExit(2)
connection = sqlite3.connect("file:/data/stock_probs.sqlite3?mode=ro", uri=True, timeout=1.0)
try:
    rows = connection.execute(
        "SELECT execution_id FROM assistant_execution_leases "
        "WHERE session_token_hash=? AND status='active'",
        (session_hash,),
    ).fetchall()
finally:
    connection.close()
if (
    len(rows) != 1
    or not isinstance(rows[0][0], str)
    or re.fullmatch(r"[0-9a-f]{32}", rows[0][0]) is None
):
    raise SystemExit(2)
print(json.dumps({"execution_id": rows[0][0]}, separators=(",", ":")))
"""


_WORKER_DENIAL_SCRIPT = r"""import errno, json, os, socket, sys
data_path, app_pid, config_path = sys.argv[1:]
def denied(call):
    try:
        call()
    except OSError as error:
        return error.errno in {errno.EACCES, errno.EPERM}
    return False
read_denied = denied(lambda: open(data_path, "rb").read(1))
write_denied = denied(lambda: open(data_path, "ab"))
unlink_denied = denied(lambda: os.unlink(data_path))
proc_denied = denied(lambda: open(f"/proc/{app_pid}/environ", "rb").read(1))
def connect_control():
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer.connect("/run/assistant/control.sock")
    finally:
        peer.close()
control_denied = denied(connect_control)
config_readable = False
try:
    with open(config_path, "rb") as stream:
        config_readable = bool(stream.read(1) or True)
except OSError:
    pass
config_write_denied = denied(lambda: open(config_path, "ab"))
tmp_info = os.stat("/tmp", follow_symlinks=False)
tmp_read_denied = denied(lambda: os.listdir("/tmp"))
print(json.dumps({"uid": os.geteuid(), "gid": os.getegid(), "data_read_denied": read_denied,
                  "data_write_denied": write_denied, "data_unlink_denied": unlink_denied,
                  "app_proc_environ_denied": proc_denied, "control_socket_denied": control_denied,
                  "config_readable": config_readable, "config_write_denied": config_write_denied,
                  "tmp_read_denied": tmp_read_denied, "tmp_owner_uid": tmp_info.st_uid,
                  "tmp_owner_gid": tmp_info.st_gid,
                  "tmp_mode": __import__("stat").S_IMODE(tmp_info.st_mode)},
                 separators=(",", ":")))
"""


_APP_CONFIG_DENIAL_SCRIPT = r"""import errno, json, os, sys
path = sys.argv[1]
try:
    with open(path, "ab"):
        denied = False
except OSError as error:
    denied = error.errno in {errno.EACCES, errno.EPERM}
print(json.dumps({"uid": os.geteuid(), "config_write_denied": denied}, separators=(",", ":")))
"""


_APP_TMP_BOUNDARY_SCRIPT = r"""import json, os, stat, tempfile
info = os.stat("/tmp", follow_symlinks=False)
fd, path = tempfile.mkstemp(prefix=".assistant-r120-app-tmp-")
try:
    os.write(fd, b"synthetic-r120-app-tmp-probe")
finally:
    os.close(fd)
    os.unlink(path)
print(json.dumps({"uid": os.geteuid(), "gid": os.getegid(), "tmp_uid": info.st_uid,
                  "tmp_gid": info.st_gid, "tmp_mode": stat.S_IMODE(info.st_mode),
                  "write_unlink_succeeded": True}, separators=(",", ":")))
"""


_WORKER_CACHE_SCAN_SCRIPT = r"""import errno, json, os, stat, sys
request = json.load(sys.stdin)
markers = request.get("markers")
if not isinstance(markers, dict) or len(markers) > 8:
    raise SystemExit(2)
for key, value in markers.items():
    if (not isinstance(key, str) or not isinstance(value, str)
        or len(key) > 40 or len(value.encode("utf-8")) > 4096):
        raise SystemExit(2)
marker_bytes = {key: value.encode("utf-8") for key, value in markers.items()}
roots = {"home": "/run/assistant-worker-home", "tmp": "/run/assistant-worker-home/tmp"}
totals = {key: 0 for key in marker_bytes}
result = {"complete": True, "bytes_scanned": 0, "regular_files": 0,
          "unreadable_files": 0, "symlinks": 0, "special_files": 0, "roots": {}}
limit = 64 * 1024 * 1024
for label, root in roots.items():
    try:
        root_info = os.lstat(root)
    except FileNotFoundError:
        result["complete"] = False
        result["roots"][label] = {"present": False}
        continue
    root_fields = {"present": True, "uid": root_info.st_uid, "gid": root_info.st_gid,
                   "mode": stat.S_IMODE(root_info.st_mode),
                   "directory": stat.S_ISDIR(root_info.st_mode),
                   "symlink": stat.S_ISLNK(root_info.st_mode)}
    result["roots"][label] = root_fields
    if (not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode)
        or root_info.st_uid != 10002 or root_info.st_gid != 10002
        or stat.S_IMODE(root_info.st_mode) != 0o700):
        result["complete"] = False
        continue
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            result["unreadable_files"] += 1
            result["complete"] = False
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                result["unreadable_files"] += 1
                result["complete"] = False
                continue
            if stat.S_ISLNK(info.st_mode):
                result["symlinks"] += 1
                result["complete"] = False
            elif stat.S_ISDIR(info.st_mode):
                if label == "home" and entry.path == roots["tmp"]:
                    continue
                pending.append(entry.path)
            elif stat.S_ISREG(info.st_mode):
                result["regular_files"] += 1
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(entry.path, flags)
                    with os.fdopen(descriptor, "rb") as stream:
                        tail = b""
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            result["bytes_scanned"] += len(chunk)
                            if result["bytes_scanned"] > limit:
                                result["complete"] = False
                                raise SystemExit(3)
                            block = tail + chunk
                            for key, marker in marker_bytes.items():
                                position = block.find(marker, max(0, len(tail) - len(marker) + 1))
                                while position >= 0:
                                    if position + len(marker) > len(tail):
                                        totals[key] += 1
                                    position = block.find(marker, position + 1)
                            overlap = max(
                                (len(value) for value in marker_bytes.values()), default=1
                            )
                            tail = block[-overlap:]
                except OSError as error:
                    if error.errno in {errno.EACCES, errno.EPERM, errno.ELOOP}:
                        result["unreadable_files"] += 1
                        result["complete"] = False
                    else:
                        raise
            else:
                result["special_files"] += 1
result["marker_counts"] = totals
print(json.dumps(result, separators=(",", ":")))
"""


_WORKER_CACHE_MARKERS = {
    "owner_a_prompt": (
        "Use workspace.summary to read my saved instruments. State the number of saved "
        "instruments and do not infer data that the tool did not return."
    ),
    "owner_b_prompt": (
        "Use workspace.summary to read my saved instruments, then use built-in web search "
        "with exactly this public query: NASA Artemis II official mission timeline. "
        "Summarize both results briefly and do not invent facts."
    ),
    "search_query": "NASA Artemis II official mission timeline",
    "owner_a_tool_json": '{"portfolio_items":1,"saved_searches":0,"watchlist_items":0}',
    "owner_b_tool_json": '{"portfolio_items":2,"saved_searches":0,"watchlist_items":0}',
}


def _command_operation(args: list[str]) -> str:
    """Classify a closed operation name; never retain caller arguments in diagnostics."""

    if args and Path(args[0]).name == "docker":
        if len(args) > 1 and args[1] in {
            "exec",
            "image",
            "inspect",
            "logs",
            "network",
            "port",
            "top",
            "volume",
        }:
            if args[1] == "exec" and _SEED_SCRIPT in args:
                return "docker_seed_exec"
            return f"docker_{args[1]}"
        return "docker_other"
    if args and Path(args[0]).name in {"python", "python3"}:
        return "python"
    return "fixed_helper"


def _command(
    args: list[str],
    *,
    timeout: float = 10,
    input_text: str | None = None,
    _stderr_capture: bytearray | None = None,
) -> str:
    """Run one fixed command with concurrent bounded capture and private group cleanup."""

    if _stderr_capture is not None and (type(_stderr_capture) is not bytearray or _stderr_capture):
        raise ProbeError("fixed candidate stderr projection buffer was invalid")
    operation = _command_operation(args)
    process: subprocess.Popen[bytes] | None = None
    docker_config: tempfile.TemporaryDirectory[str] | None = None
    selector: selectors.BaseSelector | None = None
    output = {"stdout": bytearray(), "stderr": bytearray()}
    observed = {"stdout": 0, "stderr": 0}
    input_bytes = input_text.encode("utf-8") if input_text is not None else b""
    input_offset = 0
    limits = {"stdout": OUTPUT_LIMIT, "stderr": ERROR_OUTPUT_LIMIT}
    stopped = False
    complete = False
    stage = "spawn"
    oversized: str | None = None
    timed_out = False

    def fail(reason: str, failure_stage: str, exit_code: int | None = None) -> ProbeError:
        return ProbeError(
            reason,
            safe_details={
                "command_operation": operation,
                "command_stage": failure_stage,
                "command_exit_code": exit_code,
                "stdout_bytes": observed["stdout"],
                "stderr_bytes": observed["stderr"],
            },
        )

    def stop_group(child: subprocess.Popen[bytes]) -> None:
        """Signal the exact owned process group, escalate, then reap its direct child."""

        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise fail("fixed candidate command cleanup failed", "cleanup_signal") from exc
        term_deadline = time.monotonic() + 0.25
        while True:
            remaining = term_deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.01, max(0.0, remaining)))
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise fail("fixed candidate command cleanup failed", "cleanup_kill") from exc
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired as exc:
            raise fail("fixed candidate command child was not reaped", "cleanup_reap") from exc

    try:
        command_environment: dict[str, str] | None = None
        if args and Path(args[0]).name == "docker":
            docker_config = tempfile.TemporaryDirectory(
                prefix="stock-probs-assistant-docker-config-", dir="/tmp"
            )
            command_environment = {
                "PATH": "/usr/bin:/bin",
                "DOCKER_CONFIG": docker_config.name,
                "DOCKER_HOST": DOCKER_DAEMON_ENDPOINT,
            }
        process = subprocess.Popen(  # noqa: S603 - callers use validated IDs and fixed commands.
            args,
            stdin=subprocess.PIPE if input_bytes else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
            env=command_environment,
        )
        selector = selectors.DefaultSelector()
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            if pipe is None:
                raise fail("fixed candidate command pipes were unavailable", "pipe_setup")
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        if input_bytes:
            if process.stdin is None:
                raise fail("fixed candidate command input pipe was unavailable", "pipe_setup")
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")

        deadline = time.monotonic() + timeout
        stage = "running"
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(min(remaining, 0.05))
            for key, _ in events:
                if key.data == "stdin":
                    try:
                        written = os.write(
                            key.fileobj.fileno(), input_bytes[input_offset : input_offset + 8192]
                        )
                    except BlockingIOError:
                        continue
                    except (BrokenPipeError, OSError):
                        written = 0
                        input_offset = len(input_bytes)
                    else:
                        input_offset += written
                    if input_offset >= len(input_bytes):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue

                name = key.data
                buffer = output[name]
                room = limits[name] - len(buffer)
                try:
                    chunk = os.read(key.fileobj.fileno(), min(8192, room + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                observed[name] += len(chunk)
                if len(chunk) > room:
                    buffer.extend(chunk[:room])
                    oversized = name
                    break
                buffer.extend(chunk)
            if oversized is not None:
                break
            if not events and not selector.get_map() and process.poll() is None:
                time.sleep(min(0.01, max(0.0, remaining)))

        if timed_out or oversized is not None:
            stage = "timeout" if timed_out else f"{oversized}_limit"
            stopped = True
            stop_group(process)
            raise fail(
                "fixed candidate command timed out"
                if timed_out
                else "fixed candidate command exceeded its output bound",
                stage,
                process.returncode,
            )

        return_code = process.returncode
        complete = True
        if return_code != 0:
            raise fail("fixed candidate command exited unsuccessfully", "exit_status", return_code)
        if _stderr_capture is not None:
            _stderr_capture.extend(output["stderr"])
        return bytes(output["stdout"]).decode("utf-8", errors="replace").strip()
    except ProbeError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        exit_code = process.returncode if process is not None else None
        raise fail("fixed candidate command did not complete", stage, exit_code) from exc
    finally:
        try:
            if process is not None and not complete and not stopped:
                stop_group(process)
        finally:
            if selector is not None:
                with suppress(OSError):
                    selector.close()
            if process is not None:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe is not None:
                        with suppress(OSError):
                            pipe.close()
            if docker_config is not None:
                docker_config.cleanup()


def _validated_candidate_revision(candidate_revision: str | None) -> str | None:
    """Accept an optional exact reviewed commit SHA, never an arbitrary image label."""

    if candidate_revision is not None and (
        not isinstance(candidate_revision, str) or _COMMIT_SHA.fullmatch(candidate_revision) is None
    ):
        raise ProbeError("candidate revision must be an exact lowercase commit SHA")
    return candidate_revision


def _image_identity(
    image_id: str,
    context_sha256: str,
    candidate_revision: str | None = None,
) -> None:
    """Bind the immutable image ID to platform and either its context or reviewed revision."""

    candidate_revision = _validated_candidate_revision(candidate_revision)
    if _HEX64.fullmatch(context_sha256) is None:
        raise ProbeError("candidate source context must use an exact SHA-256 identity")
    output = _command(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}|{{.Os}}|{{.Architecture}}|"
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
            image_id,
        ]
    )
    fields = output.split("|")
    expected_revision_label = candidate_revision or f"local-source-{context_sha256}"
    if fields != [image_id, "linux", "amd64", expected_revision_label]:
        raise ProbeError("candidate image ID, platform, or frozen source label did not match")


def _normalize_added_capabilities(values: set[str]) -> set[str]:
    """Normalize Docker's optional CAP_ display prefix without widening the allowlist."""

    normalized = {
        value[4:] if value.startswith("CAP_") else value
        for value in values
        if re.fullmatch(r"(?:CAP_)?[A-Z][A-Z0-9_]*", value)
    }
    if len(normalized) != len(values):
        raise ProbeError("candidate capability inspection contained an unknown spelling")
    if normalized != {"SETUID", "SETGID"}:
        raise ProbeError("candidate added capabilities did not match the fixed set")
    return normalized


def _validate_candidate_mounts(mount_lines: list[str], tmpfs_value: object, volume: str) -> None:
    """Check Docker's persistent mount rows and HostConfig tmpfs map exactly."""

    try:
        if not isinstance(tmpfs_value, dict) or set(tmpfs_value) != set(_EXPECTED_TMPFS_OPTIONS):
            raise ValueError
        for path, expected_options in _EXPECTED_TMPFS_OPTIONS.items():
            value = tmpfs_value[path]
            if not isinstance(value, str):
                raise ValueError
            options = value.split(",")
            if len(options) != len(set(options)) or frozenset(options) != expected_options:
                raise ValueError

        rows = [line.split("|") for line in mount_lines if line]
        if any(len(row) != 4 for row in rows):
            raise ValueError
        data_rows = [row for row in rows if row[2] == "/data"]
        if data_rows != [["volume", volume, "/data", "true"]]:
            raise ValueError
        non_data = [row for row in rows if row[2] != "/data"]
        destinations = [row[2] for row in non_data]
        if len(destinations) != len(set(destinations)):
            raise ValueError
        if any(row[0] != "tmpfs" or row[1] != "" or row[3] != "true" for row in non_data):
            raise ValueError
        if not set(destinations).issubset(_EXPECTED_TMPFS_OPTIONS):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ProbeError("candidate must use only the fixed volume and tmpfs mounts") from exc


def _validate_candidate_network(
    *,
    container: str,
    container_id: str,
    volume: str,
    network_mode: str,
    attached_networks: object,
    network_inspect: str,
) -> tuple[str, str]:
    """Require the candidate's private user-defined bridge to contain only itself."""

    expected_name = f"{volume}-candidate-network"
    if (
        not _SAFE_CONTAINER.fullmatch(expected_name)
        or expected_name in {"bridge", "host", "none"}
        or not _HEX64.fullmatch(container_id)
        or network_mode != expected_name
        or not isinstance(attached_networks, dict)
        or set(attached_networks) != {expected_name}
        or not isinstance(attached_networks[expected_name], dict)
    ):
        raise ProbeError("candidate must use its exact owned user-defined network")
    attached_id = attached_networks[expected_name].get("NetworkID")
    if not isinstance(attached_id, str) or not _HEX64.fullmatch(attached_id):
        raise ProbeError("candidate network attachment identity was malformed")

    try:
        fields = network_inspect.split("|")
        if len(fields) != 7:
            raise ValueError
        network_id, name, driver, scope, internal, ipam_driver = fields[:6]
        members = json.loads(fields[6])
        member = members.get(container_id) if isinstance(members, dict) else None
        member_name = member.get("Name") if isinstance(member, dict) else None
        if (
            network_id != attached_id
            or name != expected_name
            or driver != "bridge"
            or scope != "local"
            or internal != "false"
            or ipam_driver != "default"
            or not isinstance(members, dict)
            or set(members) != {container_id}
            or not isinstance(member_name, str)
            or member_name.strip("/") != container
        ):
            raise ValueError
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProbeError("candidate network ownership or membership did not match") from exc
    return expected_name, attached_id


def _candidate_container(
    name: str,
    image_id: str,
    context_sha256: str,
    volume: str,
    candidate_revision: str | None = None,
) -> Candidate:
    candidate_revision = _validated_candidate_revision(candidate_revision)
    suffix = context_sha256[:12]
    if (
        not _SAFE_CONTAINER.fullmatch(name)
        or name != f"{CONTAINER_PREFIX}{suffix}"
        or not _SAFE_VOLUME.fullmatch(volume)
        or volume != f"{VOLUME_PREFIX}{suffix}"
    ):
        raise ProbeError("candidate container and volume must use the dedicated R-ASTRA-120 names")
    _image_identity(image_id, context_sha256, candidate_revision)
    fields = _command(
        [
            "docker",
            "inspect",
            "--type",
            "container",
            "--format",
            "{{.Id}}|{{.Image}}|{{.Name}}|{{.State.Running}}|{{.State.Pid}}|"
            "{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|"
            "{{.HostConfig.CpuQuota}}|{{.HostConfig.CpuPeriod}}|{{.HostConfig.PidsLimit}}|"
            f'{{{{index .Config.Labels "{CONTROL_CANDIDATE_LABEL}"}}}}|'
            '{{range (index .NetworkSettings.Ports "8000/tcp")}}{{.HostIp}}:{{.HostPort}};{{end}}|'
            "{{.HostConfig.NetworkMode}}|{{json .NetworkSettings.Networks}}",
            name,
        ]
    ).split("|")
    if len(fields) != 15:
        raise ProbeError("candidate container inspect did not return the expected bounded fields")
    container_id, actual_image, actual_name, running, host_pid_text = fields[:5]
    read_only, memory_text, nano_cpus_text, cpu_quota_text, cpu_period_text, pids_text = fields[
        5:11
    ]
    candidate_label, port_text, network_mode, attached_networks_text = fields[11:15]
    if (
        actual_image != image_id
        or actual_name.strip("/") != name
        or running != "true"
        or read_only != "true"
        or int(memory_text) != MEMORY_LIMIT_BYTES
        or (
            nano_cpus_text != "1000000000"
            and (int(cpu_quota_text) != 100000 or int(cpu_period_text) != 100000)
        )
        or int(pids_text) != PROCESS_LIMIT
        or candidate_label != "true"
    ):
        raise ProbeError("candidate process, resource, image, or read-only contract did not match")
    try:
        host_pid = int(host_pid_text)
        port_bindings = [item for item in port_text.split(";") if item]
        if len(port_bindings) != 1:
            raise ValueError
        host_ip, port_value = port_bindings[0].rsplit(":", 1)
        host_port = int(port_value)
        if host_ip != "127.0.0.1" or not 1 <= host_port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise ProbeError("candidate app must publish exactly one loopback-only port") from exc
    try:
        attached_networks = json.loads(attached_networks_text)
    except json.JSONDecodeError as exc:
        raise ProbeError("candidate network attachment inspection was malformed") from exc
    candidate_network_name = f"{volume}-candidate-network"
    network_inspect = _command(
        [
            "docker",
            "network",
            "inspect",
            "--format",
            "{{.Id}}|{{.Name}}|{{.Driver}}|{{.Scope}}|{{.Internal}}|"
            "{{.IPAM.Driver}}|{{json .Containers}}",
            candidate_network_name,
        ]
    )
    network_name, network_id = _validate_candidate_network(
        container=name,
        container_id=container_id,
        volume=volume,
        network_mode=network_mode,
        attached_networks=attached_networks,
        network_inspect=network_inspect,
    )

    caps = _command(
        [
            "docker",
            "inspect",
            "--type",
            "container",
            "--format",
            "{{range .HostConfig.CapDrop}}{{.}};{{end}}|{{range .HostConfig.CapAdd}}{{.}};{{end}}|"
            "{{range .HostConfig.SecurityOpt}}{{.}};{{end}}",
            name,
        ]
    ).split("|")
    if len(caps) != 3:
        raise ProbeError("candidate capability inspection was malformed")
    dropped = {value for value in caps[0].split(";") if value}
    added_raw = {value for value in caps[1].split(";") if value}
    added = _normalize_added_capabilities(added_raw)
    options = {value for value in caps[2].split(";") if value}
    if (
        dropped != {"ALL"}
        or added != {"SETUID", "SETGID"}
        or "no-new-privileges:true" not in options
    ):
        raise ProbeError("candidate capabilities or no-new-privileges boundary did not match")

    mounts = _command(
        [
            "docker",
            "inspect",
            "--type",
            "container",
            "--format",
            "{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Destination}}|{{.RW}}{{println}}{{end}}",
            name,
        ]
    ).splitlines()
    try:
        tmpfs_value = json.loads(
            _command(
                [
                    "docker",
                    "inspect",
                    "--type",
                    "container",
                    "--format",
                    "{{json .HostConfig.Tmpfs}}",
                    name,
                ]
            )
        )
    except json.JSONDecodeError as exc:
        raise ProbeError("candidate tmpfs inspection was malformed") from exc
    _validate_candidate_mounts(mounts, tmpfs_value, volume)
    volume_label = _command(
        [
            "docker",
            "volume",
            "inspect",
            "--format",
            f'{{{{.Name}}}}|{{{{index .Labels "{DISPOSABLE_VOLUME_LABEL}"}}}}',
            volume,
        ]
    )
    if volume_label != f"{volume}|true":
        raise ProbeError("candidate volume is not explicitly labelled disposable")

    cgroup = _container_cgroup(host_pid)
    return Candidate(
        container=name,
        container_id=container_id,
        image_id=image_id,
        data_volume=volume,
        base_url=f"http://127.0.0.1:{host_port}",
        host_port=host_port,
        host_pid=host_pid,
        cgroup=cgroup,
        network_name=network_name,
        network_id=network_id,
        candidate_revision=candidate_revision,
    )


def _refresh_candidate_for_write(
    candidate: Candidate,
    context_sha256: str,
    candidate_revision: str | None = None,
) -> Candidate:
    """Reinspect and bind every candidate identity immediately before a state-writing exec."""

    if _HEX64.fullmatch(context_sha256) is None:
        raise ProbeError("candidate source context must use an exact SHA-256 identity")
    expected_revision = _validated_candidate_revision(
        candidate.candidate_revision if candidate_revision is None else candidate_revision
    )
    if candidate.candidate_revision != expected_revision:
        raise ProbeError("candidate revision changed before synthetic state seeding")
    refreshed = _candidate_container(
        candidate.container,
        candidate.image_id,
        context_sha256,
        candidate.data_volume,
        expected_revision,
    )
    expected_identity = (
        candidate.container,
        candidate.container_id,
        candidate.image_id,
        candidate.data_volume,
        candidate.base_url,
        candidate.host_port,
        candidate.host_pid,
        candidate.cgroup,
        candidate.network_name,
        candidate.network_id,
        candidate.candidate_revision,
    )
    observed_identity = (
        refreshed.container,
        refreshed.container_id,
        refreshed.image_id,
        refreshed.data_volume,
        refreshed.base_url,
        refreshed.host_port,
        refreshed.host_pid,
        refreshed.cgroup,
        refreshed.network_name,
        refreshed.network_id,
        refreshed.candidate_revision,
    )
    if observed_identity != expected_identity:
        raise ProbeError("candidate identity changed before synthetic state seeding")
    return refreshed


def _container_cgroup(host_pid: int) -> Path:
    try:
        lines = Path(f"/proc/{host_pid}/cgroup").read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise ProbeError("candidate cgroup path is unavailable on this host") from exc
    relative = next((line.partition("::")[2] for line in lines if line.startswith("0::")), None)
    if relative is None:
        raise ProbeError("candidate must use a readable cgroup-v2 resource boundary")
    root = Path("/sys/fs/cgroup").resolve()
    path = (root / relative.lstrip("/")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ProbeError("candidate cgroup escaped the host cgroup root") from exc
    if not all(
        (path / name).is_file()
        for name in (
            "memory.current",
            "memory.peak",
            "memory.max",
            "memory.events",
            "cpu.stat",
            "pids.current",
        )
    ):
        raise ProbeError("candidate cgroup resource counters are incomplete")
    if int((path / "memory.max").read_text(encoding="ascii").strip()) != MEMORY_LIMIT_BYTES:
        raise ProbeError("candidate cgroup memory limit differs from the 768 MiB contract")
    return path


def _health(candidate: Candidate) -> dict[str, object]:
    connection = http.client.HTTPConnection("127.0.0.1", candidate.host_port, timeout=3)
    try:
        connection.request(
            "GET",
            "/api/v1/readiness",
            headers={
                "Host": PUBLIC_HOST,
                "Origin": PUBLIC_ORIGIN,
                "Accept": "application/json",
                "X-Forwarded-Host": PUBLIC_HOST,
                "X-Forwarded-Proto": "https",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ProbeError("candidate readiness did not return HTTP 200")
        body = response.read(32 * 1024 + 1)
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        raise ProbeError("candidate app readiness request failed") from exc
    finally:
        connection.close()
    if len(body) > 32 * 1024:
        raise ProbeError("candidate readiness response exceeded its bound")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("candidate readiness response was invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "ready"
        or payload.get("schema_version") != 13
    ):
        raise ProbeError("candidate app is not ready on the expected schema")
    assistant = payload.get("assistant")
    if not isinstance(assistant, dict):
        raise ProbeError("candidate readiness omitted the assistant status projection")
    return {"status": "ready", "schema_version": 13, "assistant": assistant}


def _seed_users(candidate: Candidate) -> list[dict[str, str]]:
    expected_network = f"{candidate.data_volume}-candidate-network"
    if (
        not isinstance(candidate.container_id, str)
        or _HEX64.fullmatch(candidate.container_id) is None
        or not isinstance(candidate.image_id, str)
        or _SHA256_IMAGE.fullmatch(candidate.image_id) is None
        or not isinstance(candidate.data_volume, str)
        or not _SAFE_VOLUME.fullmatch(candidate.data_volume)
        or candidate.network_name != expected_network
        or not isinstance(candidate.network_id, str)
        or _HEX64.fullmatch(candidate.network_id) is None
    ):
        raise ProbeError("synthetic owner seeder requires an exact inspected candidate identity")
    output = _command(
        [
            "docker",
            "exec",
            "-i",
            "--user",
            "10001:10001",
            candidate.container_id,
            "python",
            "-c",
            _SEED_SCRIPT,
        ],
        timeout=30,
    )
    try:
        payload = json.loads(output)
        users = payload["users"]
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ProbeError("synthetic owner seeder returned an invalid private payload") from exc
    if not isinstance(users, list) or len(users) != 2:
        raise ProbeError("synthetic owner seeder did not create exactly two owners")
    selected: list[dict[str, str]] = []
    for index, user in enumerate(users):
        expected_keys = {
            "session_cookie",
            "csrf_cookie",
            "expected_tool_result_sha256",
        }
        if index == 0:
            expected_keys.add("totp_secret")
        if not isinstance(user, dict) or set(user) != expected_keys:
            raise ProbeError("synthetic owner seeder returned an invalid bounded identity")
        if any(
            not isinstance(value, str) or not value or len(value) > 128 for value in user.values()
        ):
            raise ProbeError("synthetic owner seeder returned an invalid bounded identity")
        if _HEX64.fullmatch(user["expected_tool_result_sha256"]) is None:
            raise ProbeError("synthetic owner seeder returned an invalid result digest")
        if index == 0 and re.fullmatch(r"[A-Z2-7]{16,64}", user["totp_secret"]) is None:
            raise ProbeError("synthetic admin fixture returned an invalid TOTP secret")
        selected.append(dict(user))
    return selected


def _read_resources(candidate: Candidate) -> dict[str, int]:
    try:
        cpu: dict[str, int] = {}
        cpu_keys = {
            "usage_usec",
            "user_usec",
            "system_usec",
            "nr_periods",
            "nr_throttled",
            "throttled_usec",
        }
        for line in (candidate.cgroup / "cpu.stat").read_text(encoding="ascii").splitlines():
            fields = line.split()
            if fields and fields[0] in cpu_keys:
                key = fields[0]
                if len(fields) != 2 or key in cpu:
                    raise ValueError
                value = fields[1]
                if not value.isascii() or not value.isdecimal():
                    raise ValueError
                parsed = int(value)
                if parsed > _RESOURCE_COUNTER_MAX:
                    raise ValueError
                cpu[key] = parsed
        memory_events = {}
        for line in (candidate.cgroup / "memory.events").read_text(encoding="ascii").splitlines():
            key, _, value = line.partition(" ")
            if key in {"high", "max", "oom", "oom_kill"}:
                memory_events[key] = int(value)
        return {
            "memory_current": int(
                (candidate.cgroup / "memory.current").read_text(encoding="ascii")
            ),
            "memory_peak": int((candidate.cgroup / "memory.peak").read_text(encoding="ascii")),
            "pids_current": int((candidate.cgroup / "pids.current").read_text(encoding="ascii")),
            "cpu_usage_usec": cpu["usage_usec"],
            "cpu_nr_periods": cpu["nr_periods"],
            "cpu_nr_throttled": cpu["nr_throttled"],
            "cpu_throttled_usec": cpu["throttled_usec"],
            "memory_events_high": memory_events.get("high", 0),
            "memory_events_max": memory_events.get("max", 0),
            "memory_events_oom": memory_events.get("oom", 0),
            "memory_events_oom_kill": memory_events.get("oom_kill", 0),
        }
    except (OSError, ValueError, KeyError) as exc:
        raise ProbeError("candidate cgroup resource counters became unavailable") from exc


def _docker_exec_json(
    candidate: Candidate,
    user: str,
    script: str,
    *args: str,
    input_text: str | None = None,
    timeout: float = 8,
) -> Any:
    if (
        not isinstance(candidate.container_id, str)
        or _HEX64.fullmatch(candidate.container_id) is None
    ):
        raise ProbeError("candidate exec requires an exact immutable container ID")
    output = _command(
        [
            "docker",
            "exec",
            "-i",
            "--user",
            user,
            candidate.container_id,
            "python",
            "-c",
            script,
            *args,
        ],
        timeout=timeout,
        input_text=input_text,
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProbeError("candidate identity probe returned an invalid bounded response") from exc


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite number")


def _project_native_timing_v1(value: object) -> dict[str, object]:
    fields = {
        "event",
        "version",
        "scope",
        "terminal_status",
        "turn_elapsed_ms",
        "workspace_summary_completed_ms",
        "provider_requests",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ProbeError("native timing diagnostic schema was malformed")
    terminal_status = value.get("terminal_status")
    if (
        value.get("event") != "assistant_turn_timing_v1"
        or type(value.get("version")) is not int
        or value["version"] != 1
        or value.get("scope") != "diagnostic_only"
        or type(terminal_status) is not str
        or terminal_status not in {"completed", "cancelled", "failed", "timed_out"}
    ):
        raise ProbeError("native timing diagnostic schema was malformed")

    turn_elapsed = value.get("turn_elapsed_ms")
    workspace_ms = value.get("workspace_summary_completed_ms")
    if (
        type(turn_elapsed) is not int
        or not 0 <= turn_elapsed <= _NATIVE_TIMING_OBSERVATION_LIMIT_MS
        or workspace_ms is not None
        and (
            type(workspace_ms) is not int
            or not 0 <= workspace_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
            or workspace_ms > turn_elapsed
        )
    ):
        raise ProbeError("native timing diagnostic offsets were malformed")

    requests = value.get("provider_requests")
    if not isinstance(requests, list) or len(requests) > _NATIVE_TIMING_MAX_PROVIDER_REQUESTS:
        raise ProbeError("native timing diagnostic provider rows were malformed")
    projected_requests: list[dict[str, object]] = []
    request_fields = {
        "ordinal",
        "start_ms",
        "first_sanitized_chunk_ms",
        "end_ms",
        "outcome",
    }
    for ordinal, request in enumerate(requests, start=1):
        if not isinstance(request, dict) or set(request) != request_fields:
            raise ProbeError("native timing diagnostic provider rows were malformed")
        start_ms = request.get("start_ms")
        first_ms = request.get("first_sanitized_chunk_ms")
        end_ms = request.get("end_ms")
        outcome = request.get("outcome")
        if (
            type(request.get("ordinal")) is not int
            or request["ordinal"] != ordinal
            or type(start_ms) is not int
            or not 0 <= start_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
            or start_ms > turn_elapsed
            or first_ms is not None
            and (
                type(first_ms) is not int
                or not start_ms <= first_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
                or first_ms > turn_elapsed
            )
            or end_ms is not None
            and (
                type(end_ms) is not int
                or not start_ms <= end_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
                or end_ms > turn_elapsed
                or first_ms is not None
                and first_ms > end_ms
            )
            or not isinstance(outcome, str)
            or outcome not in {"ended", "failed", "cancelled"}
            or end_ms is None
            and outcome == "ended"
        ):
            raise ProbeError("native timing diagnostic provider rows were malformed")
        projected_requests.append(
            {
                "ordinal": ordinal,
                "start_ms": start_ms,
                "first_sanitized_chunk_ms": first_ms,
                "end_ms": end_ms,
                "outcome": outcome,
            }
        )
    return {
        "terminal_status": terminal_status,
        "turn_elapsed_ms": turn_elapsed,
        "workspace_summary_completed_ms": workspace_ms,
        "provider_requests": projected_requests,
    }


def _project_native_timing_v2(value: object) -> dict[str, object]:
    """Project a legacy v2 timing row without embedded provider-failure fields."""

    projected, _failures = _project_native_timing_version(value, version=2)
    return projected


def _project_native_timing_v3(value: object) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Project a v3 timing row and its closed per-request failure records."""

    return _project_native_timing_version(value, version=3)


def _project_native_timing_v4(value: object) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Project a v4 timing row with bounded upstream 403 classifications."""

    return _project_native_timing_version(value, version=4)


def _project_native_timing_v5(value: object) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Project a v5 timing row with closed pre-session failure classification."""

    return _project_native_timing_version(value, version=5)


def _project_native_timing_version(
    value: object, *, version: int
) -> tuple[dict[str, object], list[dict[str, object]]]:
    fields = {
        "event",
        "version",
        "scope",
        "terminal_status",
        "turn_elapsed_ms",
        "workspace_summary_completed_ms",
        "provider_requests",
    }
    if version == 5:
        fields.update({"pre_session_phase", "pre_session_failure_code"})
    event = f"assistant_turn_timing_v{version}"
    terminal_status = value.get("terminal_status") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value.get("event") != event
        or type(value.get("version")) is not int
        or value["version"] != version
        or value.get("scope") != "diagnostic_only"
        or type(terminal_status) is not str
        or terminal_status not in {"completed", "cancelled", "failed", "timed_out"}
    ):
        raise ProbeError("native timing diagnostic schema was malformed")

    pre_session_phase: str | None = None
    pre_session_failure_code: str | None = None
    if version == 5:
        pre_session_phase = value.get("pre_session_phase")
        pre_session_failure_code = value.get("pre_session_failure_code")
        if (pre_session_phase is None) != (pre_session_failure_code is None):
            raise ProbeError("native timing diagnostic pre-session classification was malformed")
        if pre_session_phase is not None and (
            type(pre_session_phase) is not str
            or pre_session_phase not in _NATIVE_TIMING_PRESESSION_PHASES
            or type(pre_session_failure_code) is not str
            or pre_session_failure_code not in _NATIVE_TIMING_PRESESSION_FAILURE_CODES
            or terminal_status == "completed"
        ):
            raise ProbeError("native timing diagnostic pre-session classification was invalid")

    turn_elapsed = value.get("turn_elapsed_ms")
    workspace_ms = value.get("workspace_summary_completed_ms")
    if (
        type(turn_elapsed) is not int
        or not 0 <= turn_elapsed <= _NATIVE_TIMING_OBSERVATION_LIMIT_MS
        or workspace_ms is not None
        and (
            type(workspace_ms) is not int
            or not 0 <= workspace_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
            or workspace_ms > turn_elapsed
        )
    ):
        raise ProbeError("native timing diagnostic offsets were malformed")

    requests = value.get("provider_requests")
    if not isinstance(requests, list) or len(requests) > _NATIVE_TIMING_MAX_PROVIDER_REQUESTS:
        raise ProbeError("native timing diagnostic provider rows were malformed")
    if version == 5 and pre_session_phase is not None and (workspace_ms is not None or requests):
        raise ProbeError("native timing diagnostic pre-session classification was malformed")
    projected_requests: list[dict[str, object]] = []
    request_fields = {
        "ordinal",
        "start_ms",
        "first_sanitized_chunk_ms",
        "sanitized_chunk_count",
        "sanitized_byte_count",
        "last_sanitized_yield_ms",
        "end_ms",
        "outcome",
        "stream_lifecycle",
        "stream_lifecycle_observed",
    }
    if version in {3, 4, 5}:
        request_fields.add("failure_diagnostic")
    observed_lifecycles = {
        "clean_eof": "ended",
        "cancelled_error": "cancelled",
        "generator_closed": "cancelled",
        "proxy_timeout": "failed",
        "safe_protocol_error": "failed",
    }
    unresolved_lifecycles = {
        "unresolved_at_turn_timeout",
        "unresolved_at_turn_terminal",
    }
    embedded_failures: list[dict[str, object]] = []
    for ordinal, request in enumerate(requests, start=1):
        if not isinstance(request, dict) or set(request) != request_fields:
            raise ProbeError("native timing diagnostic provider rows were malformed")
        start_ms = request.get("start_ms")
        first_ms = request.get("first_sanitized_chunk_ms")
        chunk_count = request.get("sanitized_chunk_count")
        byte_count = request.get("sanitized_byte_count")
        last_yield_ms = request.get("last_sanitized_yield_ms")
        end_ms = request.get("end_ms")
        outcome = request.get("outcome")
        lifecycle = request.get("stream_lifecycle")
        lifecycle_observed = request.get("stream_lifecycle_observed")
        if (
            type(request.get("ordinal")) is not int
            or request["ordinal"] != ordinal
            or type(start_ms) is not int
            or not 0 <= start_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
            or start_ms > turn_elapsed
            or type(chunk_count) is not int
            or not 0 <= chunk_count <= _NATIVE_TIMING_MAX_PROVIDER_CHUNKS
            or type(byte_count) is not int
            or not 0 <= byte_count <= _NATIVE_TIMING_MAX_PROVIDER_BYTES
            or type(lifecycle_observed) is not bool
        ):
            raise ProbeError("native timing diagnostic provider rows were malformed")
        if first_ms is not None and (
            type(first_ms) is not int
            or not start_ms <= first_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
            or first_ms > turn_elapsed
        ):
            raise ProbeError("native timing diagnostic offsets were malformed")
        if last_yield_ms is not None and (
            type(last_yield_ms) is not int
            or not start_ms <= last_yield_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
            or last_yield_ms > turn_elapsed
        ):
            raise ProbeError("native timing diagnostic offsets were malformed")
        if chunk_count == 0:
            if byte_count != 0 or first_ms is not None or last_yield_ms is not None:
                raise ProbeError("native timing diagnostic chunk counts were malformed")
        elif (
            first_ms is None
            or last_yield_ms is None
            or first_ms > last_yield_ms
            or byte_count > chunk_count * _NATIVE_TIMING_MAX_PROVIDER_CHUNK_BYTES
        ):
            raise ProbeError("native timing diagnostic chunk counts were malformed")
        if not isinstance(outcome, str) or outcome not in {"ended", "failed", "cancelled"}:
            raise ProbeError("native timing diagnostic provider rows were malformed")
        if type(lifecycle) is not str:
            raise ProbeError("native timing diagnostic lifecycle was malformed")
        if lifecycle_observed is True:
            if lifecycle not in observed_lifecycles or outcome != observed_lifecycles[lifecycle]:
                raise ProbeError("native timing diagnostic lifecycle was malformed")
        elif (
            lifecycle not in unresolved_lifecycles
            or (lifecycle == "unresolved_at_turn_timeout") != (terminal_status == "timed_out")
            or outcome
            != ("cancelled" if terminal_status in {"cancelled", "timed_out"} else "failed")
        ):
            raise ProbeError("native timing diagnostic lifecycle was malformed")
        if version in {3, 4, 5}:
            failure = _project_native_embedded_provider_stream_failure(
                request["failure_diagnostic"],
                outcome=outcome,
                lifecycle=lifecycle,
                lifecycle_observed=lifecycle_observed,
                version=version,
            )
            if failure is not None:
                if len(embedded_failures) >= _NATIVE_PROVIDER_STREAM_FAILURE_MAX_RECORDS:
                    raise ProbeError("native provider stream diagnostic record count was malformed")
                embedded_failures.append(failure)
        if end_ms is not None and (
            type(end_ms) is not int
            or not start_ms <= end_ms <= _NATIVE_TIMING_WORK_LIMIT_MS
            or end_ms > turn_elapsed
            or first_ms is not None
            and first_ms > end_ms
            or last_yield_ms is not None
            and last_yield_ms > end_ms
        ):
            raise ProbeError("native timing diagnostic offsets were malformed")
        if lifecycle_observed is False and end_ms is not None:
            raise ProbeError("native timing diagnostic lifecycle was malformed")
        projected_requests.append(
            {
                "ordinal": ordinal,
                "start_ms": start_ms,
                "first_sanitized_chunk_ms": first_ms,
                "sanitized_chunk_count": chunk_count,
                "sanitized_byte_count": byte_count,
                "last_sanitized_yield_ms": last_yield_ms,
                "end_ms": end_ms,
                "outcome": outcome,
                "stream_lifecycle": lifecycle,
                "stream_lifecycle_observed": lifecycle_observed,
            }
        )
    return (
        {
            "terminal_status": terminal_status,
            "turn_elapsed_ms": turn_elapsed,
            "workspace_summary_completed_ms": workspace_ms,
            **(
                {
                    "pre_session_phase": pre_session_phase,
                    "pre_session_failure_code": pre_session_failure_code,
                }
                if version == 5
                else {}
            ),
            "provider_requests": projected_requests,
        },
        embedded_failures,
    )


def _project_native_embedded_provider_stream_failure(
    value: object,
    *,
    outcome: object,
    lifecycle: object,
    lifecycle_observed: object,
    version: int,
) -> dict[str, object] | None:
    """Validate and project one failure attached to its bounded provider request."""

    if value is None:
        return None
    base_fields = {"stage", "error_code", "http_status"}
    header_class_fields = base_fields | {"content_type_class", "cf_mitigated_class"}
    error_type_fields = base_fields | {"provider_error_type_class"}
    classified_fields = header_class_fields | {"provider_error_type_class"}
    valid_shapes = (
        (base_fields,)
        if version == 3
        else (base_fields, header_class_fields, error_type_fields, classified_fields)
    )
    if type(value) is not dict or set(value) not in valid_shapes:
        raise ProbeError("native provider stream diagnostic payload was malformed")
    stage = value.get("stage")
    if type(stage) is not str or stage not in _NATIVE_PROVIDER_STREAM_FAILURE_STAGES:
        raise ProbeError("native provider stream diagnostic stage was invalid")
    error_code = value.get("error_code")
    if type(error_code) is not str or error_code not in _NATIVE_PROVIDER_STREAM_FAILURE_CODES:
        raise ProbeError("native provider stream diagnostic error code was invalid")
    status_code = value.get("http_status")
    if status_code is not None:
        if type(status_code) is not int:
            raise ProbeError("native provider stream diagnostic HTTP status was malformed")
        if not 100 <= status_code <= 599:
            raise ProbeError("native provider stream diagnostic HTTP status was invalid")
    is_classified_403 = (
        stage == "upstream_stream"
        and error_code == "provider_upstream_unavailable"
        and status_code == 403
    )
    has_header_classes = {"content_type_class", "cf_mitigated_class"}.issubset(value)
    has_error_type_class = "provider_error_type_class" in value
    if version in {4, 5} and (has_header_classes or has_error_type_class) and not is_classified_403:
        raise ProbeError("native provider stream diagnostic payload was malformed")
    if has_header_classes and (
        type(value.get("content_type_class")) is not str
        or value["content_type_class"] not in _NATIVE_PROVIDER_403_CONTENT_TYPE_CLASSES
        or type(value.get("cf_mitigated_class")) is not str
        or value["cf_mitigated_class"] not in _NATIVE_PROVIDER_403_CF_MITIGATED_CLASSES
    ):
        raise ProbeError("native provider stream diagnostic classes were invalid")
    if has_error_type_class and (
        type(value.get("provider_error_type_class")) is not str
        or value["provider_error_type_class"] not in _NATIVE_PROVIDER_403_ERROR_TYPE_CLASSES
    ):
        raise ProbeError("native provider stream diagnostic error type class was invalid")
    if (
        outcome != "failed"
        or lifecycle_observed is not True
        or lifecycle not in {"proxy_timeout", "safe_protocol_error"}
    ):
        raise ProbeError("native provider stream diagnostic lifecycle was invalid")
    projected: dict[str, object] = {
        "kind": "provider_stream_failure",
        "stage": stage,
        "error_code": error_code,
        "http_status": status_code,
    }
    if has_header_classes:
        projected["content_type_class"] = value["content_type_class"]
        projected["cf_mitigated_class"] = value["cf_mitigated_class"]
    if has_error_type_class:
        projected["provider_error_type_class"] = value["provider_error_type_class"]
    return projected


def _project_native_timing_row(
    value: object,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if isinstance(value, dict) and value.get("event") == "assistant_turn_timing_v5":
        return _project_native_timing_v5(value)
    if isinstance(value, dict) and value.get("event") == "assistant_turn_timing_v4":
        return _project_native_timing_v4(value)
    if isinstance(value, dict) and value.get("event") == "assistant_turn_timing_v3":
        return _project_native_timing_v3(value)
    if isinstance(value, dict) and value.get("event") == "assistant_turn_timing_v2":
        return _project_native_timing_v2(value), []
    return _project_native_timing_v1(value), []


def _warning_integer(raw: str, *, maximum: int) -> int:
    if not _NATIVE_WARNING_INT.fullmatch(raw):
        raise ProbeError("native warning diagnostic integer was malformed")
    value = int(raw)
    if value > maximum:
        raise ProbeError("native warning diagnostic integer was out of bounds")
    return value


def _warning_category_list(
    raw: str,
    allowed: frozenset[str],
    *,
    empty: str = "none",
) -> list[str]:
    if raw == empty:
        return []
    if not _NATIVE_WARNING_CATEGORY_LIST.fullmatch(raw):
        raise ProbeError("native warning diagnostic category list was malformed")
    values = raw.split(",")
    if (
        len(values) > len(allowed)
        or values != sorted(set(values))
        or any(value not in allowed for value in values)
    ):
        raise ProbeError("native warning diagnostic category list was invalid")
    return values


def _warning_timeout_seconds(raw: str) -> float | None:
    if raw == "none":
        return None
    if not _NATIVE_WARNING_SECONDS.fullmatch(raw):
        raise ProbeError("native warning diagnostic timeout was malformed")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ProbeError("native warning diagnostic timeout was malformed") from exc
    if (
        not math.isfinite(value)
        or not 0 < value <= _NATIVE_WARNING_PROVIDER_TIMEOUT_MAX_SECONDS
        or format(value, ".17g") != raw
    ):
        raise ProbeError("native warning diagnostic timeout was out of bounds")
    return value


def _project_native_terminal_warning(payload: str) -> dict[str, object]:
    match = _NATIVE_WARNING_TERMINAL_PATTERN.fullmatch(payload)
    if match is None:
        raise ProbeError("native terminal warning diagnostic was malformed")
    values = match.groupdict()
    session_outcome = values["session_outcome"]
    snapshot_status = values["snapshot"]
    if session_outcome not in _NATIVE_WARNING_SESSION_OUTCOMES:
        raise ProbeError("native terminal warning diagnostic was invalid")
    if snapshot_status not in _NATIVE_WARNING_SNAPSHOT_STATUSES | {"read"}:
        raise ProbeError("native terminal warning diagnostic was invalid")
    assistant_finish = _warning_category_list(
        values["assistant_finish"], _NATIVE_WARNING_ASSISTANT_FINISHES
    )
    webfetch_state = _warning_category_list(
        values["webfetch_state"], _NATIVE_WARNING_WEBFETCH_STATES, empty="absent"
    )
    timeout_stage = _warning_category_list(
        values["webfetch_timeout_stage"], _NATIVE_WARNING_WEBFETCH_TIMEOUT_STAGES
    )
    timeout_seconds = _warning_timeout_seconds(values["webfetch_timeout_seconds_max"])
    elapsed_raw = values["webfetch_tool_elapsed_ms_max"]
    elapsed_ms = (
        None
        if elapsed_raw == "none"
        else _warning_integer(elapsed_raw, maximum=_NATIVE_WARNING_TOOL_ELAPSED_MAX_MS)
    )
    return {
        "kind": "native_terminal_failure",
        "session_outcome": session_outcome,
        "snapshot_status": snapshot_status,
        "assistant_finish": assistant_finish,
        "assistant_failure_categories": _warning_category_list(
            values["assistant_failure"], _NATIVE_WARNING_FAILURE_CATEGORIES
        ),
        "assistant_error_count": _warning_integer(
            values["assistant_error_count"], maximum=_NATIVE_WARNING_COUNT_MAX
        ),
        "webfetch_state": webfetch_state,
        "webfetch_failure_categories": _warning_category_list(
            values["webfetch_failure"], _NATIVE_WARNING_FAILURE_CATEGORIES
        ),
        "webfetch_timeout_stages": timeout_stage,
        "webfetch_timeout_seconds_max": timeout_seconds,
        "webfetch_tool_elapsed_ms_max": elapsed_ms,
        "webfetch_completion_categories": _warning_category_list(
            values["webfetch_completion"], _NATIVE_WARNING_WEBFETCH_COMPLETIONS
        ),
        "native_failure_categories": _warning_category_list(
            values["native_failure"], _NATIVE_WARNING_FAILURE_CATEGORIES
        ),
        "native_tool_error_count": _warning_integer(
            values["native_tool_error_count"], maximum=_NATIVE_WARNING_TOOL_ERROR_MAX
        ),
    }


def _project_native_model_discovery_warning(payload: str) -> dict[str, object]:
    """Project the runtime's fixed model-discovery counters without retaining raw text."""

    match = _NATIVE_WARNING_MODEL_DISCOVERY_PATTERN.fullmatch(payload)
    if match is None:
        raise ProbeError("native model discovery diagnostic was malformed")
    values = match.groupdict()
    outcome = values["outcome"]
    if outcome not in _NATIVE_MODEL_DISCOVERY_OUTCOMES:
        raise ProbeError("native model discovery diagnostic outcome was invalid")
    projected: dict[str, object] = {
        "kind": "model_discovery_diagnostic",
        "phase": "model_discovery",
        "outcome": outcome,
    }
    for field in (
        "readiness_attempts",
        "readiness_timeouts",
        "catalog_attempts",
        "catalog_timeouts",
        "empty_catalog_responses",
        "missing_alias_responses",
        "post_readiness_catalog_responses",
        "post_readiness_missing_alias_responses",
    ):
        projected[field] = _warning_integer(values[field], maximum=_NATIVE_WARNING_COUNT_MAX)
    projected["elapsed_ms"] = _warning_integer(
        values["elapsed_ms"], maximum=_NATIVE_WARNING_ELAPSED_MAX_MS
    )
    return projected


def _project_native_runtime_warning(line: str) -> dict[str, object] | None:
    """Project one exact existing runtime warning without retaining its raw log line."""

    matches = [(marker, line.find(marker)) for marker in _NATIVE_WARNING_MARKERS]
    matches = [(marker, position) for marker, position in matches if position >= 0]
    if not matches:
        return None
    if len(matches) != 1 or line.count(matches[0][0]) != 1:
        raise ProbeError("native warning diagnostic marker was malformed")
    marker, position = matches[0]
    payload = line[position + len(marker) :]
    if marker == _NATIVE_WARNING_SNAPSHOT_MARKER:
        return _project_native_terminal_warning(payload)
    if marker == _NATIVE_WARNING_MODEL_DISCOVERY_MARKER:
        return _project_native_model_discovery_warning(payload)
    if marker in {_NATIVE_WARNING_STARTUP_MARKER, _NATIVE_WARNING_PRESESSION_MARKER}:
        pattern = (
            _NATIVE_WARNING_STARTUP_PATTERN
            if marker == _NATIVE_WARNING_STARTUP_MARKER
            else _NATIVE_WARNING_PRESESSION_PATTERN
        )
        match = pattern.fullmatch(payload)
        if match is None:
            raise ProbeError("native warning diagnostic was malformed")
        stage = match.group("stage")
        allowed_stages = (
            _NATIVE_WARNING_STARTUP_STAGES
            if marker == _NATIVE_WARNING_STARTUP_MARKER
            else _NATIVE_WARNING_PRESESSION_STAGES
        )
        failure_code = match.group("failure_code")
        if stage not in allowed_stages or failure_code not in _NATIVE_WARNING_FAILURE_CODES:
            raise ProbeError("native warning diagnostic stage was invalid")
        return {
            "kind": (
                "worker_startup_failure"
                if marker == _NATIVE_WARNING_STARTUP_MARKER
                else "pre_session_failure"
            ),
            "stage": stage,
            "failure_code": failure_code,
        }
    if marker == _NATIVE_WARNING_DEADLINE_MARKER:
        match = _NATIVE_WARNING_DEADLINE_PATTERN.fullmatch(payload)
        if match is None:
            raise ProbeError("native warning diagnostic was malformed")
        phase = match.group("phase")
        if phase not in _NATIVE_WARNING_PHASES:
            raise ProbeError("native warning diagnostic phase was invalid")
        return {
            "kind": "turn_deadline_expired",
            "phase": phase,
            "elapsed_ms": _warning_integer(
                match.group("elapsed_ms"), maximum=_NATIVE_WARNING_ELAPSED_MAX_MS
            ),
        }
    if marker == _NATIVE_WARNING_REQUEST_TIMEOUT_MARKER:
        match = _NATIVE_WARNING_REQUEST_TIMEOUT_PATTERN.fullmatch(payload)
        if match is None:
            raise ProbeError("native warning diagnostic was malformed")
        phase = match.group("phase")
        if phase not in _NATIVE_WARNING_PHASES:
            raise ProbeError("native warning diagnostic phase was invalid")
        return {
            "kind": "native_request_timeout",
            "phase": phase,
            "error_code": "request_timeout",
            "elapsed_ms": _warning_integer(
                match.group("elapsed_ms"), maximum=_NATIVE_WARNING_ELAPSED_MAX_MS
            ),
        }
    raise ProbeError("native warning diagnostic marker was invalid")


def _project_native_provider_stream_failure(line: str) -> dict[str, object] | None:
    """Project one exact private stream-failure marker into its closed schema."""

    if _NATIVE_PROVIDER_STREAM_FAILURE_PREFIX not in line:
        return None
    if line.count(_NATIVE_PROVIDER_STREAM_FAILURE_PREFIX) != 1:
        raise ProbeError("native provider stream diagnostic marker was malformed")
    if _NATIVE_PROVIDER_STREAM_FAILURE_MARKER not in line:
        raise ProbeError("native provider stream diagnostic marker was invalid")
    if line.count(_NATIVE_PROVIDER_STREAM_FAILURE_MARKER) != 1:
        raise ProbeError("native provider stream diagnostic marker was malformed")
    payload = line.split(_NATIVE_PROVIDER_STREAM_FAILURE_MARKER, 1)[1]
    match = _NATIVE_PROVIDER_STREAM_FAILURE_PATTERN.fullmatch(payload)
    if match is None:
        raise ProbeError("native provider stream diagnostic payload was malformed")
    stage = match.group("stage")
    if stage not in _NATIVE_PROVIDER_STREAM_FAILURE_STAGES:
        raise ProbeError("native provider stream diagnostic stage was invalid")
    error_code = match.group("error_code")
    if error_code not in _NATIVE_PROVIDER_STREAM_FAILURE_CODES:
        raise ProbeError("native provider stream diagnostic error code was invalid")
    raw_status = match.group("http_status")
    status_code = None if raw_status is None else int(raw_status)
    if status_code is not None and not 100 <= status_code <= 599:
        raise ProbeError("native provider stream diagnostic HTTP status was invalid")
    return {
        "kind": "provider_stream_failure",
        "stage": stage,
        "error_code": error_code,
        "http_status": status_code,
    }


def _native_timing_projection(log_output: object) -> dict[str, object]:
    """Extract fixed timing and runtime-warning schemas; never retain raw log text."""

    if type(log_output) is str:
        streams = [(log_output, _NATIVE_TIMING_MAX_LOG_BYTES)]
    elif (
        type(log_output) is tuple
        and len(log_output) == 2
        and all(type(stream) is str for stream in log_output)
    ):
        streams = [
            (log_output[0], OUTPUT_LIMIT),
            (log_output[1], ERROR_OUTPUT_LIMIT),
        ]
    else:
        raise ProbeError("native timing diagnostic log input was malformed")
    for stream, byte_limit in streams:
        try:
            if len(stream.encode("utf-8")) > byte_limit:
                raise ProbeError("native timing diagnostic log input was malformed")
        except UnicodeEncodeError as exc:
            raise ProbeError("native timing diagnostic log input was malformed") from exc
    rows: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    warning_indices: dict[str, int] = {}
    warnings_truncated = False
    provider_stream_failures: list[dict[str, object]] = []
    embedded_provider_stream_failures: list[dict[str, object]] = []
    timing_versions: set[str] = set()
    saw_legacy_provider_failure_marker = False
    for stream, _byte_limit in streams:
        for line in stream.splitlines():
            timing_markers = [marker for marker in _NATIVE_TIMING_MARKERS if marker in line]
            if timing_markers:
                marker = timing_markers[0]
                marker_count = sum(line.count(candidate) for candidate in _NATIVE_TIMING_MARKERS)
                if marker_count != 1 or len(rows) >= _NATIVE_TIMING_MAX_ROWS:
                    raise ProbeError("native timing diagnostic marker count was malformed")
                timing_versions.add(marker)
                if len(timing_versions) != 1:
                    raise ProbeError("native timing diagnostic marker version was mixed")
                payload = line.split(marker, 1)[1]
                try:
                    value = json.loads(
                        payload,
                        object_pairs_hook=_reject_duplicate_json_keys,
                        parse_constant=_reject_json_constant,
                    )
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ProbeError("native timing diagnostic payload was malformed") from exc
                expected_event = {
                    _NATIVE_TIMING_MARKER: "assistant_turn_timing_v1",
                    _NATIVE_TIMING_V2_MARKER: "assistant_turn_timing_v2",
                    _NATIVE_TIMING_V3_MARKER: "assistant_turn_timing_v3",
                    _NATIVE_TIMING_V4_MARKER: "assistant_turn_timing_v4",
                    _NATIVE_TIMING_V5_MARKER: "assistant_turn_timing_v5",
                }[marker]
                if type(value) is not dict or value.get("event") != expected_event:
                    raise ProbeError("native timing diagnostic schema was malformed")
                row, embedded_failures = _project_native_timing_row(value)
                rows.append(row)
                if (
                    len(embedded_provider_stream_failures) + len(embedded_failures)
                    > _NATIVE_PROVIDER_STREAM_FAILURE_MAX_RECORDS
                ):
                    raise ProbeError("native provider stream diagnostic record count was malformed")
                embedded_provider_stream_failures.extend(embedded_failures)
            warning = _project_native_runtime_warning(line)
            if warning is not None:
                warning_key = json.dumps(warning, sort_keys=True, separators=(",", ":"))
                warning_index = warning_indices.get(warning_key)
                if warning_index is not None:
                    occurrence_count = warnings[warning_index]["occurrence_count"]
                    if (
                        type(occurrence_count) is not int
                        or occurrence_count >= _NATIVE_WARNING_OCCURRENCE_COUNT_MAX
                    ):
                        raise ProbeError("native warning diagnostic record count was malformed")
                    warnings[warning_index]["occurrence_count"] = occurrence_count + 1
                elif len(warnings) >= _NATIVE_WARNING_MAX_RECORDS:
                    warnings_truncated = True
                else:
                    warning["occurrence_count"] = 1
                    warning_indices[warning_key] = len(warnings)
                    warnings.append(warning)
            provider_failure = _project_native_provider_stream_failure(line)
            if provider_failure is not None:
                if len(provider_stream_failures) >= _NATIVE_PROVIDER_STREAM_FAILURE_MAX_RECORDS:
                    raise ProbeError("native provider stream diagnostic record count was malformed")
                provider_stream_failures.append(provider_failure)
                saw_legacy_provider_failure_marker = True
    if (
        timing_versions
        & {_NATIVE_TIMING_V3_MARKER, _NATIVE_TIMING_V4_MARKER, _NATIVE_TIMING_V5_MARKER}
        and saw_legacy_provider_failure_marker
    ):
        raise ProbeError("native provider stream diagnostic source was mixed")
    if embedded_provider_stream_failures and provider_stream_failures:
        raise ProbeError("native provider stream diagnostic source was mixed")
    provider_stream_failures.extend(embedded_provider_stream_failures)
    projection: dict[str, object] = {
        "scope": "diagnostic_only",
        "status": "available" if rows or warnings or provider_stream_failures else "unavailable",
        "rows": rows,
        "runtime_warnings": warnings,
    }
    if provider_stream_failures:
        projection["provider_stream_failures"] = provider_stream_failures
    if warnings_truncated:
        projection["runtime_warnings_truncated"] = True
        projection["marker_counts"] = _native_timing_marker_counts(log_output)
        projection["marker_counts_capped"] = True
    return projection


def _native_timing_marker_counts(log_output: object) -> dict[str, int]:
    """Count diagnostic markers only, capped to the first value beyond each accepted limit."""

    if type(log_output) is str:
        streams = (log_output,)
    elif (
        type(log_output) is tuple
        and len(log_output) == 2
        and all(type(stream) is str for stream in log_output)
    ):
        streams = log_output
    else:
        streams = ()
    timing_count = sum(
        stream.count(marker) for stream in streams for marker in _NATIVE_TIMING_MARKERS
    )
    warning_count = sum(
        stream.count(marker) for stream in streams for marker in _NATIVE_WARNING_MARKERS
    )
    provider_stream_failure_count = sum(
        stream.count(_NATIVE_PROVIDER_STREAM_FAILURE_PREFIX) for stream in streams
    )
    counts = {
        "timing": min(timing_count, _NATIVE_TIMING_MARKER_COUNT_CAP),
        "warning": min(warning_count, _NATIVE_WARNING_MARKER_COUNT_CAP),
    }
    if provider_stream_failure_count:
        counts["provider_stream_failures"] = min(
            provider_stream_failure_count, _NATIVE_PROVIDER_STREAM_FAILURE_MARKER_COUNT_CAP
        )
    return counts


def _native_timing_failure_reason(error: ProbeError) -> str:
    """Map authored parser errors to closed public codes without retaining error text."""

    return _NATIVE_TIMING_FAILURE_REASON_CODES.get(
        str(error), _NATIVE_TIMING_FAILURE_REASON_FALLBACK
    )


def _candidate_native_timing_projection(candidate: Candidate, since: str) -> dict[str, object]:
    """Read one bounded candidate log tail and discard everything but fixed diagnostics."""

    if not _SAFE_CONTAINER.fullmatch(candidate.container):
        return {
            "scope": "diagnostic_only",
            "status": "unavailable",
            "rows": [],
            "runtime_warnings": [],
        }
    try:
        started = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if started.tzinfo is None:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        return {
            "scope": "diagnostic_only",
            "status": "unavailable",
            "rows": [],
            "runtime_warnings": [],
        }
    try:
        stderr_capture = bytearray()
        stdout_capture = _command(
            [
                "docker",
                "logs",
                "--timestamps",
                "--since",
                started.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "--tail",
                "256",
                candidate.container,
            ],
            timeout=4,
            _stderr_capture=stderr_capture,
        )
    except ProbeError:
        return {
            "scope": "diagnostic_only",
            "status": "unavailable",
            "rows": [],
            "runtime_warnings": [],
        }
    log_output = (stdout_capture, stderr_capture.decode("utf-8", errors="replace"))
    try:
        return _native_timing_projection(log_output)
    except ProbeError as exc:
        return {
            "scope": "diagnostic_only",
            "status": "invalid",
            "rows": [],
            "runtime_warnings": [],
            "failure_reason": _native_timing_failure_reason(exc),
            "marker_counts": _native_timing_marker_counts(log_output),
        }


_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


def _project_native_delete_diagnostics(
    value: object,
    *,
    expected_statuses: list[int] | None = None,
    require_final_status: bool,
) -> list[dict[str, object]]:
    """Project bounded per-owner delete counts and the final public result."""

    if (
        not isinstance(value, list)
        or len(value) > 2
        or (require_final_status and len(value) != 2)
        or (expected_statuses is not None and len(expected_statuses) != len(value))
    ):
        raise ProbeError("native attach driver deletion diagnostics were malformed")
    projected: list[dict[str, object]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or type(row.get("owner_index")) is not int:
            raise ProbeError("native attach driver deletion diagnostics were malformed")
        if row["owner_index"] != index:
            raise ProbeError("native attach driver deletion diagnostics were misattributed")
        attempt_count = row.get("attempt_count")
        pending_count = row.get("pending_count")
        if (
            type(attempt_count) is not int
            or not 0 <= attempt_count <= _NATIVE_DELETE_DIAGNOSTIC_MAX_ATTEMPTS
            or type(pending_count) is not int
            or not 0 <= pending_count <= attempt_count
        ):
            raise ProbeError("native attach driver deletion retry counts were malformed")
        status = row.get("http_status")
        error_code = row.get("public_error_code")
        if attempt_count == 0:
            if require_final_status or status is not None or error_code is not None:
                raise ProbeError("native attach driver deletion final result was malformed")
            projected.append(
                {
                    "owner_index": index,
                    "attempt_count": attempt_count,
                    "pending_count": pending_count,
                }
            )
            continue
        if type(status) is not int or not 100 <= status <= 599:
            raise ProbeError("native attach driver deletion HTTP status was malformed")
        if expected_statuses is not None and status != expected_statuses[index]:
            raise ProbeError(
                "native attach driver deletion diagnostics disagreed with final status"
            )
        expected_pending_count = (
            attempt_count
            if status == 503 and error_code == "assistant_cache_clear_pending"
            else attempt_count - 1
        )
        if pending_count != expected_pending_count:
            raise ProbeError("native attach driver pending-delete count was inconsistent")
        if require_final_status and (status != 200 or error_code != "none"):
            raise ProbeError("native attach driver final deletion result was not successful")
        if (
            not isinstance(error_code, str)
            or len(error_code) > 64
            or error_code not in _NATIVE_DELETE_DIAGNOSTIC_ERROR_CODES
            or (status == 200 and error_code not in {"none", "unknown"})
            or (status != 200 and error_code == "none")
        ):
            error_code = "unknown"
        projected.append(
            {
                "owner_index": index,
                "http_status": status,
                "public_error_code": error_code,
                "attempt_count": attempt_count,
                "pending_count": pending_count,
            }
        )
    return projected


def _native_driver_projection(driver: object) -> dict[str, object]:
    """Keep only the attached driver's bounded, reviewable acceptance facts."""

    if (
        not isinstance(driver, dict)
        or driver.get("mode") != "attach-existing-app"
        or driver.get("phase") != "final"
    ):
        raise ProbeError("native attach driver did not return its expected receipt type")
    owner_rows = driver.get("owners")
    if not isinstance(owner_rows, list) or len(owner_rows) != 2:
        raise ProbeError("native attach driver did not return exactly two owner receipts")
    owners: list[dict[str, object]] = []
    for index, row in enumerate(owner_rows):
        if not isinstance(row, dict):
            raise ProbeError("native attach driver owner receipt was malformed")
        hosts = row.get("native_search_source_hosts")
        source_types = row.get("native_search_source_types")
        fetch_hosts = row.get("native_webfetch_source_hosts")
        fetch_types = row.get("native_webfetch_source_types")
        fetch_hashes = row.get("native_webfetch_source_url_sha256")
        if (
            not isinstance(hosts, list)
            or not isinstance(source_types, list)
            or not isinstance(fetch_hosts, list)
            or not isinstance(fetch_types, list)
            or not isinstance(fetch_hashes, list)
        ):
            raise ProbeError("native attach driver source projection was malformed")
        safe_hosts = sorted({host.casefold() for host in hosts if isinstance(host, str)})
        if len(safe_hosts) != len(hosts) or any(
            len(host) > 253
            or any(not _DNS_LABEL.fullmatch(label) for label in host.rstrip(".").split("."))
            for host in safe_hosts
        ):
            raise ProbeError("native attach driver returned an unsafe search source host")
        if len(source_types) > 20 or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
            for value in source_types
        ):
            raise ProbeError("native attach driver returned an unsafe search source type")
        safe_fetch_hosts = sorted(
            {host.casefold() for host in fetch_hosts if isinstance(host, str)}
        )
        if len(safe_fetch_hosts) != len(fetch_hosts) or any(
            len(host) > 253
            or any(not _DNS_LABEL.fullmatch(label) for label in host.rstrip(".").split("."))
            for host in safe_fetch_hosts
        ):
            raise ProbeError("native attach driver returned an unsafe WebFetch source host")
        if len(fetch_types) > 20 or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
            for value in fetch_types
        ):
            raise ProbeError("native attach driver returned an unsafe WebFetch source type")
        if len(fetch_hashes) > 20 or any(
            not isinstance(value, str) or _HEX64.fullmatch(value) is None for value in fetch_hashes
        ):
            raise ProbeError("native attach driver returned an invalid WebFetch URL digest")
        if row.get("webfetch_approved") is not (index == 1):
            raise ProbeError("native attach driver WebFetch approval was not owner-bound")
        if index == 1 and (
            row.get("native_webfetch_source_count") != 1
            or safe_fetch_hosts != ["www.iana.org"]
            or sorted(set(fetch_types)) != ["native_webfetch_guarded"]
            or len(set(fetch_hashes)) != 1
        ):
            raise ProbeError("native attach driver guarded WebFetch evidence was incomplete")
        if index == 0 and (fetch_hosts or fetch_types or fetch_hashes):
            raise ProbeError("native attach driver attributed WebFetch to the wrong owner")
        digest_fields = (
            "answer_sha256",
            "workspace_summary_result_sha256",
        )
        if any(
            row.get(field) is not None
            and (not isinstance(row.get(field), str) or _HEX64.fullmatch(row[field]) is None)
            for field in digest_fields
        ):
            raise ProbeError("native attach driver returned an invalid evidence digest")
        booleans = (
            "model_id_matches",
            "nonempty_answer",
            "workspace_summary_digest_matches",
            "selected_model_id_matches",
            "search_approved",
            "webfetch_approved",
        )
        if any(type(row.get(field)) is not bool for field in booleans):
            raise ProbeError("native attach driver owner acceptance fields were malformed")
        for field in (
            "answer_bytes",
            "workspace_summary_receipt_count",
            "native_search_source_count",
            "native_webfetch_source_count",
            "conversation_event_count",
        ):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ProbeError("native attach driver owner counts were malformed")
        terminal = row.get("terminal_status")
        if terminal not in {"completed", "cancelled", "failed", "timed_out"}:
            raise ProbeError("native attach driver terminal status was malformed")
        turn_error_code = row.get("turn_error_code")
        turn_failure_stage = row.get("turn_failure_stage")
        if turn_error_code is not None and (
            not isinstance(turn_error_code, str)
            or turn_error_code not in _NATIVE_SAFE_TURN_ERROR_CODES
        ):
            raise ProbeError("native attach driver turn error code was malformed")
        if (
            not isinstance(turn_failure_stage, str)
            or turn_failure_stage not in _NATIVE_TURN_FAILURE_STAGES
        ):
            raise ProbeError("native attach driver turn failure stage was malformed")
        owners.append(
            {
                "terminal_status": terminal,
                "turn_error_code": turn_error_code,
                "turn_failure_stage": turn_failure_stage,
                "model_id_matches": row["model_id_matches"],
                "nonempty_answer": row["nonempty_answer"],
                "answer_bytes": row["answer_bytes"],
                "answer_sha256": row["answer_sha256"],
                "workspace_summary_receipt_count": row["workspace_summary_receipt_count"],
                "workspace_summary_digest_matches": row["workspace_summary_digest_matches"],
                "workspace_summary_result_sha256": row["workspace_summary_result_sha256"],
                "selected_model_id_matches": row["selected_model_id_matches"],
                "native_search_source_count": row["native_search_source_count"],
                "native_search_source_hosts": safe_hosts,
                "native_search_source_types": sorted(set(source_types)),
                "search_approved": row["search_approved"],
                "native_webfetch_source_count": row["native_webfetch_source_count"],
                "native_webfetch_source_hosts": safe_fetch_hosts,
                "native_webfetch_source_types": sorted(set(fetch_types)),
                "native_webfetch_source_url_sha256": sorted(set(fetch_hashes)),
                "webfetch_approved": row["webfetch_approved"],
                "conversation_event_count": row["conversation_event_count"],
            }
        )
    statuses = driver.get("conversation_delete_statuses")
    if (
        not isinstance(statuses, list)
        or len(statuses) != 2
        or any(type(value) is not int for value in statuses)
    ):
        raise ProbeError("native attach driver deletion statuses were malformed")
    if statuses != [200, 200]:
        raise ProbeError("native attach driver final deletion status was not successful")
    deletion_diagnostics = _project_native_delete_diagnostics(
        driver.get("conversation_delete_diagnostics"),
        expected_statuses=statuses,
        require_final_status=True,
    )
    for field in ("cross_owner_conversation_status", "forged_internal_mcp_status"):
        if type(driver.get(field)) is not int:
            raise ProbeError("native attach driver denial statuses were malformed")
    if driver.get("cross_owner_error_code") not in {None, "not_found"}:
        raise ProbeError("native attach driver returned an unexpected owner-isolation error")
    for field in (
        "same_supervised_app_reachable",
        "turn_requests_issued_concurrently",
        "attached_candidate_acceptance",
    ):
        if type(driver.get(field)) is not bool:
            raise ProbeError("native attach driver acceptance status was malformed")
    if driver.get("assistant_worker_status_after_turns") not in {
        "ready",
        "unavailable",
        "disabled",
        "stopped",
    }:
        raise ProbeError("native attach driver worker status was malformed")
    search_digest = driver.get("search_query_sha256")
    if not isinstance(search_digest, str) or _HEX64.fullmatch(search_digest) is None:
        raise ProbeError("native attach driver search digest was malformed")
    model_id = driver.get("approved_model_id")
    if not isinstance(model_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}", model_id
    ):
        raise ProbeError("native attach driver model identity was malformed")
    policy_digest = driver.get("policy_generation_sha256")
    if not isinstance(policy_digest, str) or _HEX64.fullmatch(policy_digest) is None:
        raise ProbeError("native attach driver policy digest was malformed")
    approval_count = driver.get("search_approval_count")
    if type(approval_count) is not int or approval_count < 0:
        raise ProbeError("native attach driver search approval count was malformed")
    webfetch_approval_count = driver.get("webfetch_approval_count")
    if type(webfetch_approval_count) is not int or webfetch_approval_count < 0:
        raise ProbeError("native attach driver WebFetch approval count was malformed")
    if driver.get("webfetch_approved") is not True:
        raise ProbeError("native attach driver did not approve the fixed WebFetch target")
    if driver.get("webfetch_requested_url_sha256") != _WEBFETCH_TARGET_SHA256:
        raise ProbeError("native attach driver WebFetch target digest was malformed")
    if webfetch_approval_count != 1:
        raise ProbeError("native attach driver WebFetch approval count was invalid")
    timestamps: dict[str, str] = {}
    for field in ("started_at", "finished_at"):
        value = driver.get(field)
        if not isinstance(value, str) or len(value) > 40:
            raise ProbeError("native attach driver timestamps were malformed")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProbeError("native attach driver timestamps were malformed") from exc
        timestamps[field] = value
    return {
        "mode": "attach-existing-app",
        "phase": "final",
        **timestamps,
        "synthetic_owners": 2,
        "approved_model_id": model_id,
        "policy_generation_sha256": policy_digest,
        "turn_requests_issued_concurrently": driver["turn_requests_issued_concurrently"],
        "owners": owners,
        "search_query_sha256": search_digest,
        "search_approval_count": approval_count,
        "webfetch_requested_url_sha256": _WEBFETCH_TARGET_SHA256,
        "webfetch_approval_count": webfetch_approval_count,
        "webfetch_approved": True,
        "cross_owner_conversation_status": driver["cross_owner_conversation_status"],
        "cross_owner_error_code": driver.get("cross_owner_error_code"),
        "forged_internal_mcp_status": driver["forged_internal_mcp_status"],
        "conversation_delete_statuses": statuses,
        "conversation_delete_diagnostics": deletion_diagnostics,
        "assistant_worker_status_after_turns": driver["assistant_worker_status_after_turns"],
        "same_supervised_app_reachable": driver["same_supervised_app_reachable"],
        "attached_candidate_acceptance": driver["attached_candidate_acceptance"],
    }


def _native_driver_failure_projection(driver: object) -> dict[str, object]:
    """Retain only the fixed native driver's safe final failure fields."""

    if (
        not isinstance(driver, dict)
        or driver.get("mode") != "attach-existing-app"
        or driver.get("phase") != "final"
        or driver.get("attached_candidate_acceptance") is not False
    ):
        raise ProbeError("native attach driver did not return a safe final failure receipt")
    code = driver.get("safe_error_code")
    missing_conditions = driver.get("missing_conditions")
    failure_code = driver.get("acceptance_failure_code")
    if failure_code is not None:
        if (
            failure_code != "acceptance_conditions_unmet"
            or code != failure_code
            or not isinstance(missing_conditions, list)
            or not missing_conditions
        ):
            raise ProbeError("native attach driver acceptance failure summary was malformed")
    elif missing_conditions is not None:
        raise ProbeError("native attach driver acceptance failure summary was malformed")
    if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) is None:
        raise ProbeError("native attach driver failure code was malformed")
    if failure_code is None and code == "acceptance_conditions_unmet":
        raise ProbeError("native attach driver acceptance failure code lacked conditions")
    if failure_code is not None and any(
        not isinstance(condition, str) or condition not in _NATIVE_ACCEPTANCE_FAILURES
        for condition in missing_conditions
    ):
        raise ProbeError("native attach driver returned an unknown acceptance condition")
    if failure_code is not None and len(set(missing_conditions)) != len(missing_conditions):
        raise ProbeError("native attach driver repeated an acceptance condition")
    projection: dict[str, object] = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": code,
    }
    if failure_code is not None:
        projection["acceptance_failure_code"] = failure_code
        projection["missing_conditions"] = missing_conditions
    if "conversation_delete_diagnostics" in driver:
        projection["conversation_delete_diagnostics"] = _project_native_delete_diagnostics(
            driver["conversation_delete_diagnostics"],
            require_final_status=False,
        )
    failure_stage = driver.get("failure_stage")
    if failure_stage not in _NATIVE_FAILURE_STAGES:
        raise ProbeError("native attach driver failure stage was malformed")
    projection["failure_stage"] = failure_stage
    status = driver.get("http_status")
    if status is not None:
        if type(status) is not int or not 100 <= status <= 599:
            raise ProbeError("native attach driver failure status was malformed")
        projection["http_status"] = status
    for field in ("started_at", "finished_at"):
        value = driver.get(field)
        if value is not None:
            if not isinstance(value, str) or len(value) > 40:
                raise ProbeError("native attach driver failure timestamp was malformed")
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ProbeError("native attach driver failure timestamp was malformed") from exc
            projection[field] = value
    for field in (
        "turn_requests_issued_concurrently",
        "active_search_scan_acknowledged",
        "same_supervised_app_reachable",
        "attached_candidate_acceptance",
        "search_approved",
        "webfetch_approved",
    ):
        value = driver.get(field)
        if value is not None:
            if type(value) is not bool:
                raise ProbeError("native attach driver failure status was malformed")
            projection[field] = value
    if "assistant_worker_status_after_turns" in driver:
        worker_status = driver["assistant_worker_status_after_turns"]
        if not isinstance(worker_status, str) or worker_status not in {
            "ready",
            "starting",
            "unavailable",
            "disabled",
            "stopped",
        }:
            raise ProbeError("native attach driver failure worker status was malformed")
        projection["assistant_worker_status_after_turns"] = worker_status
    approvals = driver.get("search_approval_count")
    if approvals is not None:
        if type(approvals) is not int or approvals < 0:
            raise ProbeError("native attach driver failure approval count was malformed")
        projection["search_approval_count"] = approvals
    fetch_approvals = driver.get("webfetch_approval_count")
    if fetch_approvals is not None:
        if type(fetch_approvals) is not int or not 0 <= fetch_approvals <= 1:
            raise ProbeError("native attach driver failure WebFetch approval count was malformed")
        projection["webfetch_approval_count"] = fetch_approvals
    requested_url_digest = driver.get("webfetch_requested_url_sha256")
    if requested_url_digest is not None:
        if requested_url_digest != _WEBFETCH_TARGET_SHA256:
            raise ProbeError("native attach driver failure WebFetch target was malformed")
        projection["webfetch_requested_url_sha256"] = requested_url_digest
    owner_evidence = driver.get("owner_evidence")
    if not isinstance(owner_evidence, list) or len(owner_evidence) != 2:
        raise ProbeError("native attach driver owner failure evidence was malformed")
    if owner_evidence is not None:
        projected_owners: list[dict[str, object]] = []
        for index, row in enumerate(owner_evidence):
            if not isinstance(row, dict) or row.get("owner_index") != index:
                raise ProbeError("native attach driver owner failure evidence was malformed")
            status = row.get("terminal_status")
            if status not in {
                "not_started",
                "unknown",
                "running",
                "completed",
                "cancelled",
                "failed",
                "timed_out",
            }:
                raise ProbeError("native attach driver owner failure status was malformed")
            for field in (
                "model_id_matches",
                "answer_nonempty",
                "workspace_summary_digest_present",
                "workspace_summary_digest_matches",
                "selected_model_id_matches",
            ):
                if type(row.get(field)) is not bool:
                    raise ProbeError("native attach driver owner failure evidence was malformed")
            turn_error_code = row.get("turn_error_code")
            turn_failure_stage = row.get("turn_failure_stage")
            if turn_error_code is not None and (
                not isinstance(turn_error_code, str)
                or turn_error_code not in _NATIVE_SAFE_TURN_ERROR_CODES
            ):
                raise ProbeError("native attach driver owner failure evidence was malformed")
            if (
                not isinstance(turn_failure_stage, str)
                or turn_failure_stage not in _NATIVE_TURN_FAILURE_STAGES
            ):
                raise ProbeError("native attach driver owner failure evidence was malformed")
            counts: dict[str, int] = {}
            for field, maximum in (
                ("assistant_message_count", 256),
                ("assistant_text_bytes", 1_048_576),
                ("workspace_summary_receipt_count", 64),
                ("selected_model_event_count", 64),
                ("native_search_source_count", 64),
                ("native_webfetch_source_count", 64),
                ("conversation_event_count", 512),
            ):
                value = row.get(field)
                if type(value) is not int or not 0 <= value <= maximum:
                    raise ProbeError("native attach driver owner failure count was malformed")
                counts[field] = value
            projected_owners.append(
                {
                    "owner_index": index,
                    "terminal_status": status,
                    "turn_error_code": turn_error_code,
                    "turn_failure_stage": turn_failure_stage,
                    "model_id_matches": row["model_id_matches"],
                    "assistant_message_count": counts["assistant_message_count"],
                    "assistant_text_bytes": counts["assistant_text_bytes"],
                    "answer_nonempty": row["answer_nonempty"],
                    "workspace_summary_receipt_count": counts["workspace_summary_receipt_count"],
                    "workspace_summary_digest_present": row["workspace_summary_digest_present"],
                    "workspace_summary_digest_matches": row["workspace_summary_digest_matches"],
                    "selected_model_event_count": counts["selected_model_event_count"],
                    "selected_model_id_matches": row["selected_model_id_matches"],
                    "native_search_source_count": counts["native_search_source_count"],
                    "native_webfetch_source_count": counts["native_webfetch_source_count"],
                    "conversation_event_count": counts["conversation_event_count"],
                }
            )
        projection["owner_evidence"] = projected_owners
    readiness = driver.get("worker_readiness_diagnostic")
    if readiness is not None:
        if not isinstance(readiness, dict):
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        expected = {
            "readiness_http_status",
            "readiness_status",
            "schema_version",
            "assistant_enabled",
            "assistant_readiness",
        }
        if set(readiness) != expected:
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        status_code = readiness.get("readiness_http_status")
        schema_version = readiness.get("schema_version")
        if type(status_code) is not int or not 100 <= status_code <= 599:
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        if schema_version is not None and (type(schema_version) is not int or schema_version != 13):
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        readiness_status = readiness.get("readiness_status")
        if readiness_status not in {None, "ready", "unavailable"}:
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        if readiness_status == "ready" and schema_version != 13:
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        enabled = readiness.get("assistant_enabled")
        if enabled is not None and type(enabled) is not bool:
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        if readiness.get("assistant_readiness") not in {
            None,
            "disabled",
            "starting",
            "ready",
            "unavailable",
            "stopped",
        }:
            raise ProbeError("native attach driver readiness diagnostic was malformed")
        projection["worker_readiness_diagnostic"] = {
            key: readiness[key] for key in sorted(expected)
        }
    interaction = driver.get("interaction_diagnostic")
    if not isinstance(interaction, dict):
        raise ProbeError("native attach driver interaction diagnostic was malformed")
    if (
        interaction.get("scope") != "failure_diagnostic_only"
        or interaction.get("elapsed_time_source") != "host_monotonic"
        or interaction.get("worker_restart_evidence") != "unavailable"
    ):
        raise ProbeError("native attach driver interaction diagnostic was malformed")
    interaction_status = interaction.get("status")
    if interaction_status == "unavailable":
        if (
            set(interaction)
            != {
                "scope",
                "status",
                "elapsed_time_source",
                "owners",
                "worker_restart_evidence",
            }
            or interaction.get("owners") != []
        ):
            raise ProbeError("native attach driver interaction diagnostic was malformed")
        projection["interaction_diagnostic"] = {
            "scope": "failure_diagnostic_only",
            "status": "unavailable",
            "elapsed_time_source": "host_monotonic",
            "owners": [],
            "worker_restart_evidence": "unavailable",
        }
    elif interaction_status == "available":
        if set(interaction) != {
            "scope",
            "status",
            "elapsed_time_source",
            "owners",
            "worker_restart_evidence",
        }:
            raise ProbeError("native attach driver interaction diagnostic was malformed")
        owner_rows = interaction.get("owners")
        if not isinstance(owner_rows, list) or len(owner_rows) != 2:
            raise ProbeError("native attach driver interaction diagnostic was malformed")
        projected_timeline_owners: list[dict[str, object]] = []
        phase_names = {
            "search_preview",
            "search_approval",
            "search_source",
            "fetch_preview",
            "fetch_approval",
            "fetch_source",
            "terminal",
        }
        for index, row in enumerate(owner_rows):
            if (
                not isinstance(row, dict)
                or set(row) != {"owner_index", "turn_elapsed_ms", "terminal_status", "phases"}
                or type(row.get("owner_index")) is not int
                or row.get("owner_index") != index
            ):
                raise ProbeError("native attach driver interaction diagnostic was malformed")
            elapsed = row.get("turn_elapsed_ms")
            if elapsed is not None and (type(elapsed) is not int or not 0 <= elapsed <= 180_000):
                raise ProbeError("native attach driver interaction elapsed time was malformed")
            terminal_status = row.get("terminal_status")
            if terminal_status is not None and (
                not isinstance(terminal_status, str)
                or terminal_status not in {"completed", "cancelled", "failed", "timed_out"}
            ):
                raise ProbeError("native attach driver interaction terminal status was malformed")
            evidence_rows = projection.get("owner_evidence")
            if terminal_status is not None and (
                not isinstance(evidence_rows, list)
                or len(evidence_rows) != 2
                or not isinstance(evidence_rows[index], dict)
                or evidence_rows[index].get("terminal_status") != terminal_status
            ):
                raise ProbeError(
                    "native attach driver interaction terminal status was inconsistent"
                )
            phases = row.get("phases")
            if not isinstance(phases, list) or len(phases) > len(phase_names):
                raise ProbeError("native attach driver interaction phases were malformed")
            if elapsed is None and phases:
                raise ProbeError("native attach driver interaction elapsed time was malformed")
            projected_phases: list[dict[str, object]] = []
            seen_phases: set[str] = set()
            prior_elapsed = -1
            for phase_row in phases:
                if not isinstance(phase_row, dict) or set(phase_row) != {
                    "phase",
                    "count",
                    "first_elapsed_ms",
                    "last_elapsed_ms",
                }:
                    raise ProbeError("native attach driver interaction phase was malformed")
                phase = phase_row.get("phase")
                count = phase_row.get("count")
                first_elapsed = phase_row.get("first_elapsed_ms")
                last_elapsed = phase_row.get("last_elapsed_ms")
                if (
                    not isinstance(phase, str)
                    or phase not in phase_names
                    or phase in seen_phases
                    or type(count) is not int
                ):
                    raise ProbeError("native attach driver interaction phase was malformed")
                phase_limit = 1 if phase == "terminal" else 64
                if (
                    not 1 <= count <= phase_limit
                    or type(first_elapsed) is not int
                    or type(last_elapsed) is not int
                    or not 0 <= first_elapsed <= last_elapsed <= 180_000
                    or elapsed is None
                    or last_elapsed > elapsed
                    or first_elapsed < prior_elapsed
                ):
                    raise ProbeError("native attach driver interaction phase was malformed")
                seen_phases.add(phase)
                prior_elapsed = first_elapsed
                projected_phases.append(
                    {
                        "phase": phase,
                        "count": count,
                        "first_elapsed_ms": first_elapsed,
                        "last_elapsed_ms": last_elapsed,
                    }
                )
            terminal_count = next(
                (phase["count"] for phase in projected_phases if phase["phase"] == "terminal"),
                0,
            )
            if (terminal_status is None) != (terminal_count == 0):
                raise ProbeError("native attach driver interaction terminal phase was malformed")
            if terminal_count == 1 and (
                elapsed is None
                or next(
                    phase["last_elapsed_ms"]
                    for phase in projected_phases
                    if phase["phase"] == "terminal"
                )
                != elapsed
            ):
                raise ProbeError(
                    "native attach driver interaction terminal elapsed time was malformed"
                )
            projected_timeline_owners.append(
                {
                    "owner_index": index,
                    "turn_elapsed_ms": elapsed,
                    "terminal_status": terminal_status,
                    "phases": projected_phases,
                }
            )
        projection["interaction_diagnostic"] = {
            "scope": "failure_diagnostic_only",
            "status": "available",
            "elapsed_time_source": "host_monotonic",
            "owners": projected_timeline_owners,
            "worker_restart_evidence": "unavailable",
        }
    else:
        raise ProbeError("native attach driver interaction diagnostic was malformed")
    if projection.get("attached_candidate_acceptance") is True:
        raise ProbeError("native attach driver failure receipt claimed acceptance")
    return projection


_NATIVE_RESOURCE_FIELDS = frozenset(
    {
        "memory_current",
        "memory_peak",
        "pids_current",
        "cpu_usage_usec",
        "cpu_nr_periods",
        "cpu_nr_throttled",
        "cpu_throttled_usec",
        "memory_events_high",
        "memory_events_max",
        "memory_events_oom",
        "memory_events_oom_kill",
    }
)
_RESOURCE_COUNTER_MAX = (1 << 63) - 1
_NATIVE_RESOURCE_MAXIMUMS = {
    "memory_current": 1 << 50,
    "memory_peak": 1 << 50,
    "pids_current": 1_000_000,
    "cpu_usage_usec": _RESOURCE_COUNTER_MAX,
    "cpu_nr_periods": _RESOURCE_COUNTER_MAX,
    "cpu_nr_throttled": _RESOURCE_COUNTER_MAX,
    "cpu_throttled_usec": _RESOURCE_COUNTER_MAX,
    "memory_events_high": _RESOURCE_COUNTER_MAX,
    "memory_events_max": _RESOURCE_COUNTER_MAX,
    "memory_events_oom": _RESOURCE_COUNTER_MAX,
    "memory_events_oom_kill": _RESOURCE_COUNTER_MAX,
}
_NATIVE_RESOURCE_MONOTONIC_FIELDS = (
    "cpu_usage_usec",
    "cpu_nr_periods",
    "cpu_nr_throttled",
    "cpu_throttled_usec",
    "memory_peak",
    "memory_events_high",
    "memory_events_max",
    "memory_events_oom",
    "memory_events_oom_kill",
)
_CPU_THROTTLE_FIELDS = {
    "nr_periods": "cpu_nr_periods",
    "nr_throttled": "cpu_nr_throttled",
    "throttled_usec": "cpu_throttled_usec",
}


def _validated_native_resource_samples(
    samples: object, baseline: object, diagnostic: str
) -> tuple[list[dict[str, int]], dict[str, int]]:
    """Validate exact bounded resource snapshots and their monotonic counters."""

    if (
        not isinstance(samples, list)
        or not 1 <= len(samples) <= 1000
        or not isinstance(baseline, dict)
        or set(baseline) != _NATIVE_RESOURCE_FIELDS
    ):
        raise ProbeError(f"{diagnostic} diagnostic was malformed")

    def validate_snapshot(snapshot: object) -> dict[str, int]:
        """Validate one exact, bounded cgroup resource snapshot."""

        if not isinstance(snapshot, dict) or set(snapshot) != _NATIVE_RESOURCE_FIELDS:
            raise ProbeError(f"{diagnostic} diagnostic was malformed")
        checked: dict[str, int] = {}
        for field, maximum in _NATIVE_RESOURCE_MAXIMUMS.items():
            value = snapshot.get(field)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ProbeError(f"{diagnostic} diagnostic was malformed")
            checked[field] = value
        if checked["memory_peak"] < checked["memory_current"]:
            raise ProbeError(f"{diagnostic} diagnostic was malformed")
        return checked

    checked_baseline = validate_snapshot(baseline)
    checked_samples = [validate_snapshot(sample) for sample in samples]
    if checked_baseline != checked_samples[0]:
        raise ProbeError(f"{diagnostic} baseline did not match its first sample")
    for previous, current in zip(checked_samples, checked_samples[1:], strict=False):
        if any(current[field] < previous[field] for field in _NATIVE_RESOURCE_MONOTONIC_FIELDS):
            raise ProbeError(f"{diagnostic} counters were not monotonic")
    return checked_samples, checked_baseline


def _native_cpu_throttling_projection(
    samples: object, baseline: object
) -> dict[str, dict[str, int]]:
    """Project bounded cgroup CPU throttle counters and reject invalid snapshots."""

    checked, checked_baseline = _validated_native_resource_samples(
        samples, baseline, "native CPU throttling"
    )
    first = {name: checked_baseline[field] for name, field in _CPU_THROTTLE_FIELDS.items()}
    ending = {name: checked[-1][field] for name, field in _CPU_THROTTLE_FIELDS.items()}
    return {
        "baseline": first,
        "delta": {name: ending[name] - first[name] for name in _CPU_THROTTLE_FIELDS},
    }


def _native_failure_resource_projection(
    samples: object,
    baseline: object,
    health_samples: object,
    duration_seconds: object,
) -> dict[str, object]:
    """Summarize only already-collected observations after a native-driver failure."""

    if (
        not isinstance(samples, list)
        or not 1 <= len(samples) <= 1000
        or not isinstance(baseline, dict)
        or set(baseline) != _NATIVE_RESOURCE_FIELDS
        or not isinstance(health_samples, list)
        or len(health_samples) > 256
        or isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, int | float)
        or not 0 <= duration_seconds <= 200
        or isinstance(duration_seconds, float)
        and not math.isfinite(duration_seconds)
    ):
        raise ProbeError("native failure resource diagnostic was malformed")
    checked_samples, checked_baseline = _validated_native_resource_samples(
        samples, baseline, "native failure resource"
    )

    app_readiness = {"ready": 0, "unavailable": 0}
    worker_readiness = {
        "ready": 0,
        "starting": 0,
        "unavailable": 0,
        "disabled": 0,
        "stopped": 0,
    }
    active_turn_samples = 0
    for sample in health_samples:
        if not isinstance(sample, dict) or set(sample) != {
            "status",
            "schema_version",
            "worker_status",
            "native_turn_active",
        }:
            raise ProbeError("native failure health diagnostic was malformed")
        app_status = sample.get("status")
        schema_version = sample.get("schema_version")
        worker_status = sample.get("worker_status")
        active = sample.get("native_turn_active")
        if (
            not isinstance(app_status, str)
            or app_status not in {"ready", "unavailable"}
            or schema_version is not None
            and (type(schema_version) is not int or schema_version != 13)
            or app_status == "ready"
            and schema_version != 13
            or (type(active) is not bool and not (app_status == "unavailable" and active is None))
            or worker_status is not None
            and (not isinstance(worker_status, str) or worker_status not in worker_readiness)
            or worker_status is None
            and app_status != "unavailable"
        ):
            raise ProbeError("native failure health diagnostic was malformed")
        app_readiness[app_status] += 1
        worker_readiness[worker_status or "unavailable"] += 1
        active_turn_samples += int(active is True)

    ending = checked_samples[-1]
    cpu_throttling = _native_cpu_throttling_projection(checked_samples, checked_baseline)
    event_names = ("high", "max", "oom", "oom_kill")
    return {
        "scope": "failure_diagnostic_only",
        "sample_count": len(checked_samples),
        "duration_ms": int(round(duration_seconds * 1000)),
        "duration_source": "host_monotonic",
        "memory_start_bytes": checked_samples[0]["memory_current"],
        "memory_peak_bytes": max(sample["memory_peak"] for sample in checked_samples),
        "memory_end_bytes": ending["memory_current"],
        "memory_limit_bytes": MEMORY_LIMIT_BYTES,
        "memory_events_baseline": {
            name: checked_baseline[f"memory_events_{name}"] for name in event_names
        },
        "memory_events_delta": {
            name: ending[f"memory_events_{name}"] - checked_baseline[f"memory_events_{name}"]
            for name in event_names
        },
        "cpu_usage_delta_usec": ending["cpu_usage_usec"] - checked_baseline["cpu_usage_usec"],
        "cpu_throttling_baseline": cpu_throttling["baseline"],
        "cpu_throttling_delta": cpu_throttling["delta"],
        "pids_peak": max(sample["pids_current"] for sample in checked_samples),
        "health_sample_count": len(health_samples),
        "app_readiness_counts": app_readiness,
        "worker_readiness_counts": worker_readiness,
        "native_turn_active_samples": active_turn_samples,
        "worker_restart_evidence": "unavailable",
    }


def _native_success_resource_projection(samples: object, baseline: object) -> dict[str, object]:
    """Project a successful native run's bounded resource counters and deltas."""

    checked_samples, checked_baseline = _validated_native_resource_samples(
        samples, baseline, "native success resource"
    )
    ending = checked_samples[-1]
    cpu_throttling = _native_cpu_throttling_projection(checked_samples, checked_baseline)
    event_names = ("high", "max", "oom", "oom_kill")
    memory_events_delta = {
        name: ending[f"memory_events_{name}"] - checked_baseline[f"memory_events_{name}"]
        for name in event_names
    }
    return {
        "samples": len(checked_samples),
        "memory_start_bytes": checked_samples[0]["memory_current"],
        "memory_peak_bytes": max(sample["memory_peak"] for sample in checked_samples),
        "memory_end_bytes": ending["memory_current"],
        "memory_limit_bytes": MEMORY_LIMIT_BYTES,
        "memory_events_baseline": {
            name: checked_baseline[f"memory_events_{name}"] for name in event_names
        },
        "memory_events_delta": memory_events_delta,
        "cpu_usage_delta_usec": ending["cpu_usage_usec"] - checked_baseline["cpu_usage_usec"],
        "cpu_throttling_baseline": cpu_throttling["baseline"],
        "cpu_throttling_delta": cpu_throttling["delta"],
        "pids_peak": max(sample["pids_current"] for sample in checked_samples),
        "within_memory_limit": max(sample["memory_peak"] for sample in checked_samples)
        <= MEMORY_LIMIT_BYTES,
    }


def _process_snapshot(candidate: Candidate) -> list[dict[str, object]]:
    value = _docker_exec_json(candidate, "0:0", _PROCESS_SNAPSHOT_SCRIPT)
    if not isinstance(value, list):
        raise ProbeError("candidate process snapshot was invalid")
    return [item for item in value if isinstance(item, dict)]


def _fixed_location_snapshot(candidate: Candidate) -> list[dict[str, object]]:
    value = _docker_exec_json(candidate, "0:0", _LOCATION_SNAPSHOT_SCRIPT)
    if not isinstance(value, list):
        raise ProbeError("candidate fixed-location snapshot was invalid")
    return [item for item in value if isinstance(item, dict)]


def _active_owner_config_path(candidate: Candidate, session_cookie: str) -> str:
    """Resolve exactly one live worker config from an owner's active session lease."""

    if (
        not isinstance(session_cookie, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", session_cookie) is None
    ):
        raise ProbeError("candidate owner-1 session could not identify its active worker config")
    session_hash = hashlib.sha256(session_cookie.encode("ascii")).hexdigest()
    lease = _docker_exec_json(
        candidate,
        "10001:10001",
        _ACTIVE_OWNER_EXECUTION_SCRIPT,
        input_text=json.dumps({"session_token_sha256": session_hash}, separators=(",", ":")),
        timeout=8,
    )
    if (
        not isinstance(lease, dict)
        or set(lease) != {"execution_id"}
        or not isinstance(lease.get("execution_id"), str)
        or re.fullmatch(r"[0-9a-f]{32}", lease["execution_id"]) is None
    ):
        raise ProbeError("candidate owner-1 active worker lease was absent or malformed")
    config_path = f"/run/assistant/worker-locations/{lease['execution_id']}/opencode.json"
    configs = _fixed_location_snapshot(candidate)
    matches = [item for item in configs if item.get("path") == config_path]
    if (
        len(matches) != 1
        or matches[0].get("regular") is not True
        or matches[0].get("uid") != 0
        or matches[0].get("gid") != 10002
        or matches[0].get("mode") != 0o640
    ):
        raise ProbeError("candidate owner-1 active worker config was absent or invalid")
    return config_path


def _require_active_owner_config(
    candidate: Candidate, session_cookie: str, expected_path: str
) -> None:
    """Fail closed if the owner lease or its exact config changed during DAC checks."""

    if (
        not isinstance(expected_path, str)
        or re.fullmatch(
            r"/run/assistant/worker-locations/[0-9a-f]{32}/opencode\.json",
            expected_path,
        )
        is None
        or _active_owner_config_path(candidate, session_cookie) != expected_path
    ):
        raise ProbeError("candidate owner-1 active worker config changed during DAC checks")


def _verify_worker_processes(snapshot: list[dict[str, object]]) -> dict[str, object]:
    by_role = {item.get("role"): item for item in snapshot}
    expected = {
        "supervisor": (0, 0),
        "app_wrapper": (10001, 10001),
        "worker_wrapper": (10002, 10002),
        "native_worker": (10002, 10002),
    }
    for role, (uid, gid) in expected.items():
        process = by_role.get(role)
        if not isinstance(process, dict) or process.get("uid") != uid or process.get("gid") != gid:
            raise ProbeError(f"candidate process identity missing for {role}")
        if role == "supervisor":
            if process.get("cap_prm") != "00000000000000c0":
                raise ProbeError("candidate PID 1 permitted capabilities changed")
        elif process.get("cap_eff") not in {"0000000000000000", "0"} or process.get(
            "cap_prm"
        ) not in {"0000000000000000", "0"}:
            raise ProbeError(f"candidate {role} has unexpected effective or permitted capabilities")
        if process.get("no_new_privileges") != "1":
            raise ProbeError(f"candidate {role} lacks no-new-privileges")
    supervisor = by_role["supervisor"]
    if (
        supervisor.get("cap_eff") != "00000000000000c0"
        or supervisor.get("cap_bnd") != "00000000000000c0"
    ):
        raise ProbeError("candidate PID 1 does not have only SETUID and SETGID capabilities")
    worker = by_role["worker_wrapper"]
    native = by_role["native_worker"]
    if worker.get("oom_score_adj") != "500" or native.get("oom_score_adj") != "500":
        raise ProbeError("candidate worker process tree lacks the bounded OOM preference")
    return {
        "roles": {
            role: {
                "uid": by_role[role]["uid"],
                "gid": by_role[role]["gid"],
                "cap_eff": by_role[role]["cap_eff"],
                "cap_prm": by_role[role]["cap_prm"],
                "cap_bnd": by_role[role]["cap_bnd"],
                "no_new_privileges": by_role[role]["no_new_privileges"],
                "oom_score_adj": by_role[role]["oom_score_adj"],
            }
            for role in expected
        }
    }


def _probe_private_boundaries(
    candidate: Candidate, users: list[dict[str, str]], config_path: str
) -> dict[str, object]:
    if len(users) != 2:
        raise ProbeError("candidate probe requires exactly two synthetic owner sessions")
    owner1_cookie = users[1].get("session_cookie")
    if not isinstance(owner1_cookie, str):
        raise ProbeError("candidate owner-1 session was unavailable for the DAC probe")
    _require_active_owner_config(candidate, owner1_cookie, config_path)
    marker = "/data/.assistant-r120-private-probe-" + os.urandom(8).hex()
    marker_bytes = os.urandom(32)
    writer = (
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "p.write_bytes(bytes.fromhex(sys.argv[2])); p.chmod(0o600)"
    )
    _command(
        [
            "docker",
            "exec",
            "--user",
            "10001:10001",
            candidate.container_id,
            "python",
            "-c",
            writer,
            marker,
            marker_bytes.hex(),
        ],
        timeout=8,
    )
    app = next(
        (item for item in _process_snapshot(candidate) if item.get("role") == "app_wrapper"), None
    )
    if not isinstance(app, dict) or not isinstance(app.get("pid"), int):
        raise ProbeError("candidate app process identity was unavailable for the DAC probe")
    _require_active_owner_config(candidate, owner1_cookie, config_path)
    worker_probe = _docker_exec_json(
        candidate,
        "10002:10002",
        _WORKER_DENIAL_SCRIPT,
        marker,
        str(app["pid"]),
        config_path,
    )
    _require_active_owner_config(candidate, owner1_cookie, config_path)
    app_probe = _docker_exec_json(candidate, "10001:10001", _APP_CONFIG_DENIAL_SCRIPT, config_path)
    app_tmp_probe = _docker_exec_json(candidate, "10001:10001", _APP_TMP_BOUNDARY_SCRIPT)
    if not isinstance(worker_probe, dict) or worker_probe != {
        "uid": 10002,
        "gid": 10002,
        "data_read_denied": True,
        "data_write_denied": True,
        "data_unlink_denied": True,
        "app_proc_environ_denied": True,
        "control_socket_denied": True,
        "config_readable": True,
        "config_write_denied": True,
        "tmp_read_denied": True,
        "tmp_owner_uid": 10001,
        "tmp_owner_gid": 10001,
        "tmp_mode": 0o700,
    }:
        raise ProbeError("candidate worker UID crossed an application or supervisor boundary")
    if not isinstance(app_probe, dict) or app_probe != {"uid": 10001, "config_write_denied": True}:
        raise ProbeError("candidate app UID could modify the root-owned worker config")
    if not isinstance(app_tmp_probe, dict) or app_tmp_probe != {
        "uid": 10001,
        "gid": 10001,
        "tmp_uid": 10001,
        "tmp_gid": 10001,
        "tmp_mode": 0o700,
        "write_unlink_succeeded": True,
    }:
        raise ProbeError("candidate app temp area did not match its private ownership contract")
    _require_active_owner_config(candidate, owner1_cookie, config_path)
    verify = (
        "import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "print(hashlib.sha256(p.read_bytes()).hexdigest())"
    )
    actual_hash = _command(
        [
            "docker",
            "exec",
            "--user",
            "10001:10001",
            candidate.container_id,
            "python",
            "-c",
            verify,
            marker,
        ],
        timeout=8,
    )
    expected_hash = hashlib.sha256(marker_bytes).hexdigest()
    cleanup = "import pathlib,sys; pathlib.Path(sys.argv[1]).unlink(missing_ok=True)"
    _command(
        [
            "docker",
            "exec",
            "--user",
            "10001:10001",
            candidate.container_id,
            "python",
            "-c",
            cleanup,
            marker,
        ],
        timeout=8,
    )
    if actual_hash != expected_hash:
        raise ProbeError("candidate private app data changed during the worker denial probe")
    return {
        "worker_uid_10002": (
            "denied app data read/write/unlink, app environ and control socket; "
            "read-only worker config"
        ),
        "app_uid_10001": "denied worker config write",
        "app_tmp_uid_10001": "write/unlink passed in mode0700 app-only /tmp",
        "worker_tmp_uid_10002": "permission denied on app-only /tmp",
        "synthetic_app_file": "unchanged and removed",
    }


def _scan_worker_cache(candidate: Candidate) -> dict[str, object]:
    payload = json.dumps(
        {"markers": _WORKER_CACHE_MARKERS}, ensure_ascii=False, separators=(",", ":")
    )
    result = _docker_exec_json(
        candidate,
        "10002:10002",
        _WORKER_CACHE_SCAN_SCRIPT,
        input_text=payload,
        timeout=25,
    )
    if not isinstance(result, dict) or result.get("complete") is not True:
        raise ProbeError("worker HOME/TMPDIR scan was incomplete or crossed a symlink")
    roots = result.get("roots")
    if not isinstance(roots, dict) or set(roots) != {"home", "tmp"}:
        raise ProbeError("worker HOME/TMPDIR scan returned malformed roots")
    for root in roots.values():
        if not isinstance(root, dict) or root.get("present") is not True:
            raise ProbeError("worker HOME or TMPDIR was absent during cache verification")
    if (
        result.get("symlinks") != 0
        or result.get("unreadable_files") != 0
        or type(result.get("bytes_scanned")) is not int
        or result["bytes_scanned"] > 64 * 1024 * 1024
    ):
        raise ProbeError("worker HOME/TMPDIR scan was not bounded and complete")
    for root in roots.values():
        if (
            root.get("uid") != 10002
            or root.get("gid") != 10002
            or root.get("mode") != 0o700
            or root.get("directory") is not True
            or root.get("symlink") is not False
        ):
            raise ProbeError(
                "worker HOME/TMPDIR ownership or mode did not match its fixed boundary"
            )
    marker_counts = result.get("marker_counts")
    if not isinstance(marker_counts, dict) or set(marker_counts) != set(_WORKER_CACHE_MARKERS):
        raise ProbeError("worker HOME/TMPDIR marker scan was malformed")
    if any(type(count) is not int or count < 0 for count in marker_counts.values()):
        raise ProbeError("worker HOME/TMPDIR marker counts were malformed")
    return {
        "complete": True,
        "bytes_scanned": result["bytes_scanned"],
        "regular_files": result.get("regular_files"),
        "special_files": result.get("special_files"),
        "marker_counts": marker_counts,
        "roots": roots,
    }


def _validate_active_search_checkpoint(value: object) -> None:
    expected_query_hash = hashlib.sha256(
        _WORKER_CACHE_MARKERS["search_query"].encode("utf-8")
    ).hexdigest()
    if (
        not isinstance(value, dict)
        or value.get("mode") != "attach-existing-app"
        or value.get("phase") != "active_search_wait"
        or value.get("origin") != PUBLIC_ORIGIN
        or value.get("owner_index") != 1
        or value.get("turn_status") != "running"
        or value.get("search_preview_pending") is not True
        or value.get("workspace_summary_digest_matches") is not True
        or value.get("search_query_sha256") != expected_query_hash
    ):
        raise ProbeError("native attach driver did not reach its exact active-search checkpoint")


def _active_native_health_sample(health: object) -> dict[str, object]:
    """Require the app's assistant readiness projection ready during an active turn."""

    assistant = health.get("assistant") if isinstance(health, dict) else None
    assistant_status = assistant.get("status") if isinstance(assistant, dict) else None
    sample = {
        "status": health.get("status") if isinstance(health, dict) else None,
        "schema_version": health.get("schema_version") if isinstance(health, dict) else None,
        "worker_status": assistant_status,
        "native_turn_active": True,
    }
    if (
        sample["status"] != "ready"
        or sample["schema_version"] != 13
        or sample["worker_status"] != "ready"
    ):
        raise ProbeError(
            "candidate app or worker was not ready at the active native-turn checkpoint"
        )
    return sample


def _run_native_driver(
    candidate: Candidate, users: list[dict[str, str]]
) -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, object], dict[str, object]
]:
    timing_since = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    driver_input = json.dumps(
        {"base_url": candidate.base_url, "origin": PUBLIC_ORIGIN, "users": users},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        child = subprocess.Popen(  # noqa: S603 - executable and script are fixed paths.
            [str(PYTHON), str(NATIVE_DRIVER), "--attach-existing-app"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ProbeError("the fixed native assistant driver could not start") from exc
    assert child.stdin is not None and child.stdout is not None and child.stderr is not None
    try:
        child.stdin.write((driver_input + "\n").encode("utf-8"))
        child.stdin.flush()
    except OSError as exc:
        child.kill()
        raise ProbeError("private native-driver input pipe failed") from exc

    stdout_lines: queue.Queue[bytes | None] = queue.Queue()
    stderr_capture = bytearray()
    overflow = {"stdout": False, "stderr": False}

    def read_stdout() -> None:
        while True:
            line = child.stdout.readline()
            if not line:
                stdout_lines.put(None)
                return
            stdout_lines.put(line)

    def drain_stderr() -> None:
        while True:
            chunk = child.stderr.read(4096)
            if not chunk:
                return
            remaining = OUTPUT_LIMIT - len(stderr_capture)
            if remaining > 0:
                stderr_capture.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow["stderr"] = True

    stdout_reader = threading.Thread(target=read_stdout, daemon=True)
    stderr_reader = threading.Thread(target=drain_stderr, daemon=True)
    stdout_reader.start()
    stderr_reader.start()

    def stop_child() -> None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)
        if child.stdin is not None:
            with suppress(OSError, ValueError):
                child.stdin.close()

    start = time.monotonic()
    baseline = _read_resources(candidate)
    samples: list[dict[str, int]] = [baseline]
    health_samples: list[dict[str, object]] = []
    next_health_sample = start
    stdout_capture = bytearray()
    parsed_lines: list[dict[str, object]] = []
    checkpoint_scan: dict[str, object] | None = None
    purge_scan: dict[str, object] | None = None
    driver_failure: dict[str, object] | None = None
    config_boundary: dict[str, object] | None = None
    dac_boundary: dict[str, object] | None = None
    stream_ended = False

    while not stream_ended or child.poll() is None:
        if time.monotonic() - start > NATIVE_TIMEOUT_SECONDS:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
            child.stdin.close()
            raise ProbeError(
                "native attach driver exceeded its bounded runtime",
                safe_details={
                    "native_turn_timing_diagnostic": _candidate_native_timing_projection(
                        candidate, timing_since
                    )
                },
            )
        samples.append(_read_resources(candidate))
        now = time.monotonic()
        if now >= next_health_sample:
            try:
                health = _health(candidate)
                assistant = health.get("assistant")
                health_samples.append(
                    {
                        "status": health["status"],
                        "schema_version": health["schema_version"],
                        "worker_status": assistant.get("status")
                        if isinstance(assistant, dict)
                        else None,
                        "native_turn_active": False,
                    }
                )
            except ProbeError:
                health_samples.append(
                    {
                        "status": "unavailable",
                        "schema_version": None,
                        "worker_status": None,
                        "native_turn_active": None,
                    }
                )
            next_health_sample = now + 1.0
        try:
            line = stdout_lines.get(timeout=0.1)
        except queue.Empty:
            line = b""
        if line is None:
            stream_ended = True
        elif line:
            if len(line) > 16 * 1024 or len(stdout_capture) + len(line) > OUTPUT_LIMIT:
                overflow["stdout"] = True
                child.terminate()
                continue
            stdout_capture.extend(line)
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                child.terminate()
                raise ProbeError("native attach driver emitted a malformed phase receipt") from exc
            if not isinstance(value, dict):
                child.terminate()
                raise ProbeError("native attach driver emitted a non-object phase receipt")
            parsed_lines.append(value)
            phase = value.get("phase")
            if phase == "active_search_wait":
                if checkpoint_scan is not None or len(parsed_lines) != 1:
                    child.terminate()
                    raise ProbeError("native attach driver repeated its active-search checkpoint")
                _validate_active_search_checkpoint(value)
                try:
                    active_health = _health(candidate)
                except ProbeError as exc:
                    child.terminate()
                    raise ProbeError(
                        "candidate app was unavailable at the active native-turn checkpoint"
                    ) from exc
                try:
                    active_health_sample = _active_native_health_sample(active_health)
                except ProbeError:
                    child.terminate()
                    raise
                health_samples.append(active_health_sample)
                checkpoint_scan = _scan_worker_cache(candidate)
                counts = checkpoint_scan["marker_counts"]
                if not isinstance(counts, dict) or sum(counts.values()) < 1:
                    child.terminate()
                    raise ProbeError("synthetic native markers were absent from worker HOME/TMPDIR")
                owner1_cookie = users[1].get("session_cookie") if len(users) == 2 else None
                if not isinstance(owner1_cookie, str):
                    child.terminate()
                    raise ProbeError("candidate owner-1 session was unavailable at active search")
                try:
                    config_path = _active_owner_config_path(candidate, owner1_cookie)
                except ProbeError:
                    stop_child()
                    raise
                config_boundary = {
                    "owner_uid": 0,
                    "group_gid": 10002,
                    "mode": 0o640,
                    "app_write_denied": True,
                    "worker_read_only": True,
                }
                try:
                    child.stdin.write(b'{"continue":true}\n')
                    child.stdin.flush()
                    child.stdin.close()
                except OSError as exc:
                    child.terminate()
                    raise ProbeError("native active-search acknowledgement pipe failed") from exc
                try:
                    dac_boundary = _probe_private_boundaries(candidate, users, config_path)
                except ProbeError:
                    stop_child()
                    raise
            elif phase == "final":
                if value.get("attached_candidate_acceptance") is False:
                    expected_line_count = 1 if checkpoint_scan is None else 2
                    if len(parsed_lines) != expected_line_count:
                        child.terminate()
                        raise ProbeError("native attach driver repeated or skipped a phase receipt")
                    driver_failure = _native_driver_failure_projection(value)
                elif checkpoint_scan is None or len(parsed_lines) != 2:
                    child.terminate()
                    raise ProbeError("native attach driver omitted its active-search checkpoint")
                elif value.get("attached_candidate_acceptance") is True:
                    # The driver waits for both synthetic deletions and the HOME purge.
                    purge_scan = _scan_worker_cache(candidate)
                else:
                    child.terminate()
                    raise ProbeError("native attach driver omitted its final acceptance status")
            else:
                child.terminate()
                raise ProbeError("native attach driver emitted an unexpected phase")
        if child.poll() is not None and stream_ended:
            break
        time.sleep(RESOURCE_POLL_SECONDS)

    child.wait(timeout=3)
    stdout_reader.join(timeout=2)
    stderr_reader.join(timeout=2)
    samples.append(_read_resources(candidate))
    if any(
        user[key].encode("utf-8") in stdout_capture or user[key].encode("utf-8") in stderr_capture
        for user in users
        for key in ("session_cookie", "csrf_cookie", "totp_secret")
        if key in user
    ):
        raise ProbeError("native attach driver output unexpectedly contained a synthetic cookie")
    if overflow["stdout"] or overflow["stderr"]:
        raise ProbeError("native attach driver exceeded its bounded output")
    if driver_failure is not None:
        resource_diagnostic = _native_failure_resource_projection(
            samples,
            baseline,
            health_samples,
            time.monotonic() - start,
        )
        timing_diagnostic = _candidate_native_timing_projection(candidate, timing_since)
        raise ProbeError(
            "native attach driver reported a bounded failure",
            safe_details={
                "native_driver_failure": driver_failure,
                "native_driver_exit_status": child.returncode,
                "native_failure_resource_diagnostic": resource_diagnostic,
                "native_turn_timing_diagnostic": timing_diagnostic,
            },
        )
    if child.returncode != 0:
        raise ProbeError("native attach driver failed or exceeded its bounded output")
    if (
        len(parsed_lines) != 2
        or checkpoint_scan is None
        or purge_scan is None
        or config_boundary is None
        or dac_boundary is None
    ):
        raise ProbeError("native attach protocol or candidate boundary evidence was incomplete")
    driver = parsed_lines[1]
    driver_projection = _native_driver_projection(driver)
    if driver_projection["attached_candidate_acceptance"] is not True:
        raise ProbeError("native attach driver did not report a complete application/native pass")
    counts_after = purge_scan.get("marker_counts")
    if not isinstance(counts_after, dict) or any(count != 0 for count in counts_after.values()):
        raise ProbeError(
            "native cache purge left a synthetic prompt or tool marker in worker storage"
        )
    if (
        not health_samples
        or any(
            sample.get("status") != "ready" or sample.get("schema_version") != 13
            for sample in health_samples
        )
        or not any(
            sample.get("worker_status") == "ready" and sample.get("native_turn_active") is True
            for sample in health_samples
        )
    ):
        raise ProbeError("candidate app was unhealthy or native worker readiness was not observed")
    resource_projection = _native_success_resource_projection(samples, baseline)
    resource_receipt = {
        **resource_projection,
        "duration_seconds": round(time.monotonic() - start, 3),
        "health_samples": health_samples,
    }
    if (
        resource_receipt["within_memory_limit"] is not True
        or resource_receipt["pids_peak"] > PROCESS_LIMIT
        or resource_receipt["memory_events_delta"]["oom"] > 0
        or resource_receipt["memory_events_delta"]["oom_kill"] > 0
    ):
        raise ProbeError("candidate exceeded its cgroup memory or PID limit during native turns")
    driver_receipt = {
        "status": "pass",
        "sha256": hashlib.sha256(bytes(stdout_capture)).hexdigest(),
        "stdout_bytes": len(stdout_capture),
        "stderr_bytes": len(stderr_capture),
        "acceptance": driver_projection,
        "turn_timing_diagnostic": _candidate_native_timing_projection(candidate, timing_since),
    }
    cache_receipt = {"before_cleanup": checkpoint_scan, "after_cleanup": purge_scan}
    return driver_receipt, resource_receipt, config_boundary, dac_boundary, cache_receipt


def run_probe(
    container: str,
    image_id: str,
    context_sha256: str,
    volume: str,
    candidate_revision: str | None = None,
) -> dict[str, object]:
    """Run against a verified image; PR mode trusts revision/context from its build receipt.

    The caller supplies the immutable image ID, filtered-context digest, and exact reviewed
    revision from the verified PR-candidate build receipt. Image inspection then binds that
    existing image ID to linux/amd64 and the supplied revision label; this probe never builds or
    relabels an image.
    """

    candidate_revision = _validated_candidate_revision(candidate_revision)
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if _SHA256_IMAGE.fullmatch(image_id) is None or _HEX64.fullmatch(context_sha256) is None:
        raise ProbeError("candidate image and source context must use exact SHA-256 identities")
    candidate = _candidate_container(
        container, image_id, context_sha256, volume, candidate_revision
    )
    before = _health(candidate)
    candidate = _refresh_candidate_for_write(candidate, context_sha256, candidate_revision)
    users = _seed_users(candidate)
    native, resources, config_boundary, boundary_receipt, cache_receipt = _run_native_driver(
        candidate, users
    )
    after = _health(candidate)
    process_receipt = _verify_worker_processes(_process_snapshot(candidate))
    return {
        "status": "pass",
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "execution_environment": (
            "local disposable candidate, linux/amd64, cgroup-v2 768 MiB / 1 CPU"
        ),
        "candidate": {
            "container": candidate.container,
            "container_id": candidate.container_id,
            "image_id": candidate.image_id,
            "data_volume": candidate.data_volume,
            "architecture": "linux/amd64",
            "source_context_sha256": context_sha256,
            "candidate_revision": candidate_revision,
            "revision_label": candidate_revision or f"local-source-{context_sha256}",
            "app_origin": PUBLIC_ORIGIN,
            "loopback_port": candidate.host_port,
        },
        "readiness_before": before,
        "readiness_after": after,
        "native_driver": native,
        "resource_load": resources,
        "worker_config_boundary": config_boundary,
        "process_boundary": process_receipt,
        "dac_boundary": boundary_receipt,
        "worker_cache_purge": cache_receipt,
        "candidate_container_and_volume_removed": False,
    }


def main(argv: list[str] | None = None) -> int:
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
