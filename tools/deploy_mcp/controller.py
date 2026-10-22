"""Validate deployment requests before sending fixed operations over SSH."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
PLAN_ID = re.compile(r"^[0-9a-f]{32}$")
IMAGE_REPOSITORY = "ghcr.io/jtmb/signal-ledger"
RELEASE_TRANSPORT = "github_release"
ASSISTANT_ROLLOUT_MODES = frozenset({"disabled", "owner_canary", "invited"})
ASSISTANT_READY_SCHEMA = 13
LOCAL_IMAGE_REPOSITORY = "signal-ledger"
HOTFIX_CANDIDATE_REVISION = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
HOTFIX_V3_CANDIDATE_REVISION = "e40dbc3b721080057a2ab2b9b23565ebf4d85982"
HOTFIX_RECOVERY_REVISION = "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"
TEMPORARY_RECOVERY_SOURCE_REVISION = "63597953c9d1ab387563dadfe705b78a2861a426"
TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB = 128 * 1024
TEMPORARY_RECOVERY_STARTUP_FLOOR_KIB = 512 * 1024
HOTFIX_PAIR_CONTRACT = "schema13_same_schema_hotfix_v1"
HOTFIX_PAIR_CONTRACT_V3 = "schema13_same_schema_hotfix_v3"
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
MAX_RESPONSE_BYTES = 65_536
MAX_TERRAFORM_PLAN_BYTES = 4 * 1024 * 1024
STREAM_CHUNK_BYTES = 4_096
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LINODE_ROOT = REPOSITORY_ROOT / "infra" / "linode"
TERRAFORM_STATE_PATH = Path("/home/james/.config/signal-ledger/terraform/linode/terraform.tfstate")
FIREWALL_RESOURCE = "linode_firewall.signal_ledger"
FIREWALL_ID = "177236117"
FIREWALL_LABEL = "signal-ledger-fw"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=-]{1,512}$")


class DeployError(Exception):
    """A safe, non-secret deployment error suitable for an MCP response."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _valid_hotfix_identity(
    response: dict[str, Any],
    requested_revision: str,
    *,
    rollback: bool = False,
) -> bool:
    """Keep the app artifact revision separate from the registered helper source revision."""

    identity_fields = {
        "recovery_contract",
        "helper_source_revision",
        "candidate_release_revision",
        "reviewed_pr_head_sha",
    }
    if requested_revision == HOTFIX_CANDIDATE_REVISION:
        expected_contract = HOTFIX_PAIR_CONTRACT
    elif requested_revision == HOTFIX_V3_CANDIDATE_REVISION:
        expected_contract = HOTFIX_PAIR_CONTRACT_V3
    else:
        return not any(field in response for field in identity_fields)
    helper_revision = response.get("helper_source_revision")
    if (
        response.get("recovery_contract") != expected_contract
        or not isinstance(helper_revision, str)
        or REVISION.fullmatch(helper_revision) is None
        or helper_revision == requested_revision
    ):
        return False
    reviewed_pr_head_sha = response.get("reviewed_pr_head_sha")
    if requested_revision == HOTFIX_V3_CANDIDATE_REVISION:
        if (
            not isinstance(reviewed_pr_head_sha, str)
            or REVISION.fullmatch(reviewed_pr_head_sha) is None
        ):
            return False
    elif "reviewed_pr_head_sha" in response:
        return False
    if not rollback:
        return "candidate_release_revision" not in response
    if response.get("candidate_release_revision") != requested_revision:
        return False
    if response.get("release_role") == "recovery":
        return response.get("revision") == HOTFIX_RECOVERY_REVISION
    return (
        response.get("release_role") == "candidate"
        and response.get("revision") == requested_revision
    )


def _next_temporary_recovery_operation_id(prior_operation_id: str, prior_view_sha256: str) -> str:
    """Derive the same stable successor ID as the fixed host helper."""

    identity = (
        b"signal-ledger-temporary-recovery-next-cycle-v1\0"
        + prior_operation_id.encode("ascii")
        + b"\0"
        + prior_view_sha256.encode("ascii")
    )
    operation_id = hashlib.sha256(identity).hexdigest()[:32]
    if operation_id == prior_operation_id:
        raise DeployError("temporary_recovery_prior_identity_invalid")
    return operation_id


def _temporary_recovery_cycle_link_sha256(
    prior_operation_id: str,
    prior_record_sha256: str,
    prior_view_sha256: str,
    new_operation_id: str,
) -> str:
    """Hash the canonical immutable link body published by the fixed host helper."""

    history_name = f"closed-{prior_operation_id}-{prior_record_sha256}.json"
    link = {
        "format_version": 1,
        "kind": "temporary_recovery_cycle_link",
        "status": "intent",
        "prior_operation_id": prior_operation_id,
        "prior_record_sha256": prior_record_sha256,
        "prior_view_sha256": prior_view_sha256,
        "new_operation_id": new_operation_id,
        "history_name": history_name,
        "database_policy": "reuse_schema_13_no_restore",
    }
    encoded = json.dumps(link, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _valid_temporary_recovery_ready_response(
    response: dict[str, Any], prior_operation_id: str, prior_view_sha256: str
) -> bool:
    """Validate the complete existing helper response without inventing response fields."""

    expected_fields = {
        "status",
        "result",
        "operation_kind",
        "operation_id",
        "source_revision",
        "image_ref",
        "image_id",
        "archive_sha256",
        "manifest_sha256",
        "schema_version",
        "assistant_rollout_mode",
        "backup",
        "available_kib",
        "startup_floor_kib",
        "start_admission_allowed",
        "health",
        "prior_operation_id",
        "prior_record_sha256",
        "prior_view_sha256",
        "cycle_link_sha256",
        "cycle_link_status",
    }
    operation_id = _next_temporary_recovery_operation_id(prior_operation_id, prior_view_sha256)
    record_sha256 = response.get("prior_record_sha256")
    backup = response.get("backup")
    health = response.get("health")
    available_kib = response.get("available_kib")
    admission_allowed = response.get("start_admission_allowed")
    return not (
        set(response) != expected_fields
        or response.get("status") != "ok"
        or response.get("result")
        not in {
            "temporary_recovery_ready",
            "temporary_recovery_ready_startup_floor_unmet",
        }
        or response.get("operation_kind") != "temporary_recovery"
        or response.get("operation_id") != operation_id
        or response.get("source_revision") != TEMPORARY_RECOVERY_SOURCE_REVISION
        or response.get("image_ref") != f"signal-ledger:temporary-recovery-{operation_id}"
        or not isinstance(response.get("image_id"), str)
        or IMAGE_ID.fullmatch(response["image_id"]) is None
        or not isinstance(response.get("archive_sha256"), str)
        or SHA256.fullmatch(response["archive_sha256"]) is None
        or not isinstance(response.get("manifest_sha256"), str)
        or SHA256.fullmatch(response["manifest_sha256"]) is None
        or type(response.get("schema_version")) is not int
        or response.get("schema_version") != ASSISTANT_READY_SCHEMA
        or response.get("assistant_rollout_mode") != "disabled"
        or not isinstance(backup, dict)
        or set(backup) != {"trigger", "name", "sha256", "schema_version", "verified", "promoted"}
        or backup.get("trigger") != "pre_deploy"
        or not isinstance(backup.get("name"), str)
        or not backup["name"].startswith(f"pre-deploy-{HOTFIX_RECOVERY_REVISION[:16]}-")
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.spbackup", backup["name"]) is None
        or not isinstance(backup.get("sha256"), str)
        or SHA256.fullmatch(backup["sha256"]) is None
        or type(backup.get("schema_version")) is not int
        or backup.get("schema_version") != ASSISTANT_READY_SCHEMA
        or backup.get("verified") is not True
        or backup.get("promoted") is not False
        or not isinstance(health, dict)
        or set(health) != {"status", "schema_version", "assistant"}
        or health.get("status") != "ready"
        or type(health.get("schema_version")) is not int
        or health.get("schema_version") != ASSISTANT_READY_SCHEMA
        or not isinstance(health.get("assistant"), dict)
        or set(health["assistant"]) != {"enabled", "status"}
        or health["assistant"].get("enabled") is not False
        or health["assistant"].get("status") != "disabled"
        or type(available_kib) is not int
        or available_kib < TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        or type(response.get("startup_floor_kib")) is not int
        or response.get("startup_floor_kib") != TEMPORARY_RECOVERY_STARTUP_FLOOR_KIB
        or type(admission_allowed) is not bool
        or admission_allowed != (available_kib >= TEMPORARY_RECOVERY_STARTUP_FLOOR_KIB)
        or response.get("result")
        != (
            "temporary_recovery_ready"
            if admission_allowed
            else "temporary_recovery_ready_startup_floor_unmet"
        )
        or response.get("prior_operation_id") != prior_operation_id
        or not isinstance(record_sha256, str)
        or SHA256.fullmatch(record_sha256) is None
        or response.get("prior_view_sha256") != prior_view_sha256
        or response.get("cycle_link_sha256")
        != _temporary_recovery_cycle_link_sha256(
            prior_operation_id, record_sha256, prior_view_sha256, operation_id
        )
        or response.get("cycle_link_status") != "started"
    )


def _regular_private_file(path: Path) -> None:
    """Reject linked or group-readable SSH material before invoking SSH."""

    try:
        info = path.lstat()
    except OSError as exc:
        raise DeployError("ssh_material_unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise DeployError("ssh_material_permissions")


def _regular_private_file_with_codes(
    path: Path, *, unavailable_code: str, permissions_code: str
) -> None:
    """Validate a configured private file without following links or reading it."""

    try:
        info = path.lstat()
    except OSError as exc:
        raise DeployError(unavailable_code) from exc
    if not stat.S_ISREG(info.st_mode):
        raise DeployError(permissions_code)
    if info.st_mode & 0o077:
        raise DeployError(permissions_code)


def _regular_executable(path: Path) -> None:
    """Validate a configured Terraform executable without accepting a symlink."""

    try:
        info = path.lstat()
    except OSError as exc:
        raise DeployError("terraform_unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
        raise DeployError("terraform_permissions")


def _validate_terraform_state() -> Path:
    """Use only the preconfigured private local state file for firewall changes."""

    try:
        info = TERRAFORM_STATE_PATH.lstat()
    except OSError as exc:
        raise DeployError("terraform_state_unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise DeployError("terraform_state_permissions")
    return TERRAFORM_STATE_PATH


def _validate_operator_cidr(value: str) -> str:
    """Accept one canonical IPv4 address expressed as a `/32` network."""

    if not isinstance(value, str):
        raise DeployError("operator_ipv4_cidr_invalid")
    try:
        network = ipaddress.ip_network(value, strict=True)
    except (TypeError, ValueError) as exc:
        raise DeployError("operator_ipv4_cidr_invalid") from exc
    if not isinstance(network, ipaddress.IPv4Network) or network.prefixlen != 32:
        raise DeployError("operator_ipv4_cidr_invalid")
    if str(network) != value:
        raise DeployError("operator_ipv4_cidr_invalid")
    return value


def _read_linode_token(path: Path) -> str:
    """Read one bounded operator token without ever returning it to the MCP layer."""

    _regular_private_file_with_codes(
        path,
        unavailable_code="terraform_token_unavailable",
        permissions_code="terraform_token_permissions",
    )
    try:
        if path.stat().st_size > 513:
            raise DeployError("terraform_token_invalid")
        value = path.read_bytes()
    except DeployError:
        raise
    except OSError as exc:
        raise DeployError("terraform_token_unavailable") from exc
    if value.endswith(b"\n"):
        value = value[:-1]
    if value.endswith(b"\r"):
        value = value[:-1]
    try:
        token = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DeployError("terraform_token_invalid") from exc
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise DeployError("terraform_token_invalid")
    return token


def _resolve_terraform_binary(configured: Path | None) -> Path:
    """Resolve one executable Terraform binary without accepting a tool argument."""

    if configured is not None:
        _regular_executable(configured)
        return configured
    candidate = shutil.which("terraform", path="/usr/bin:/bin")
    if candidate is None:
        raise DeployError("terraform_unavailable")
    path = Path(candidate).absolute()
    _regular_executable(path)
    return path


def _terraform_environment(token: str) -> dict[str, str]:
    """Build a minimal environment so Terraform cannot inherit caller overrides."""

    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "LANG": "C",
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
        "LINODE_TOKEN": token,
    }


def _run_quiet_command(command: list[str], *, environment: dict[str, str], timeout: float) -> None:
    """Run a fixed local command while discarding provider output at the trust boundary."""

    try:
        result = subprocess.run(  # noqa: S603 - command and cwd are fixed by this module
            command,
            cwd=LINODE_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DeployError("terraform_unavailable") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeployError("terraform_failed") from exc
    if result.returncode != 0:
        raise DeployError("terraform_failed")


def _firewall_without_operator_cidr(value: object) -> object:
    """Normalize only provider metadata and the expected operator CIDR before comparing."""

    if not isinstance(value, dict):
        return value
    normalized = copy.deepcopy(value)
    for field in ("fingerprint", "updated", "version"):
        normalized.pop(field, None)
    inbound = normalized.get("inbound")
    if isinstance(inbound, list):
        for rule in inbound:
            if isinstance(rule, dict) and rule.get("label") == "ssh-operator":
                rule["ipv4"] = ["<operator-cidr>"]
    return normalized


def _validate_firewall_state(value: object, cidr: str) -> None:
    """Require the planned firewall to retain the fixed SSH-only contract."""

    if not isinstance(value, dict):
        raise DeployError("terraform_scope_violation")
    if value.get("id") != FIREWALL_ID or value.get("label") != FIREWALL_LABEL:
        raise DeployError("terraform_scope_violation")
    if value.get("inbound_policy") != "DROP" or value.get("outbound_policy") != "ACCEPT":
        raise DeployError("terraform_scope_violation")
    inbound = value.get("inbound")
    if not isinstance(inbound, list) or len(inbound) != 1:
        raise DeployError("terraform_scope_violation")
    rule = inbound[0]
    if not isinstance(rule, dict):
        raise DeployError("terraform_scope_violation")
    if (
        rule.get("label") != "ssh-operator"
        or rule.get("action") != "ACCEPT"
        or rule.get("protocol") != "TCP"
        or rule.get("ports") != "22"
        or rule.get("ipv4") != [cidr]
        or rule.get("ipv6", []) not in (None, [])
    ):
        raise DeployError("terraform_scope_violation")


def _validate_firewall_plan(plan_document: object, cidr: str) -> list[str]:
    """Reject every plan except an update of the configured operator IPv4 list."""

    if not isinstance(plan_document, dict):
        raise DeployError("terraform_plan_invalid")
    changes = plan_document.get("resource_changes")
    if not isinstance(changes, list):
        raise DeployError("terraform_plan_invalid")
    managed_changes: list[dict[str, object]] = []
    target_change: dict[str, object] | None = None
    for change in changes:
        if not isinstance(change, dict) or change.get("mode", "managed") != "managed":
            continue
        detail = change.get("change")
        actions = detail.get("actions") if isinstance(detail, dict) else None
        if actions == ["no-op"]:
            if change.get("address") == FIREWALL_RESOURCE:
                if target_change is not None:
                    raise DeployError("terraform_scope_violation")
                target_change = change
            continue
        managed_changes.append(change)
    if target_change is not None:
        if managed_changes:
            raise DeployError("terraform_scope_violation")
        change = target_change.get("change")
        if not isinstance(change, dict):
            raise DeployError("terraform_plan_invalid")
        _validate_firewall_state(change.get("after"), cidr)
        return ["no-op"]
    if len(managed_changes) != 1 or managed_changes[0].get("address") != FIREWALL_RESOURCE:
        raise DeployError("terraform_scope_violation")
    change = managed_changes[0].get("change")
    if not isinstance(change, dict):
        raise DeployError("terraform_plan_invalid")
    actions = change.get("actions")
    if actions != ["update"]:
        raise DeployError("terraform_scope_violation")
    before = change.get("before")
    after = change.get("after")
    _validate_firewall_state(after, cidr)
    if not isinstance(before, dict):
        raise DeployError("terraform_scope_violation")
    before_inbound = before.get("inbound")
    if not isinstance(before_inbound, list) or len(before_inbound) != 1:
        raise DeployError("terraform_scope_violation")
    before_rule = before_inbound[0]
    if not isinstance(before_rule, dict):
        raise DeployError("terraform_scope_violation")
    before_ipv4 = before_rule.get("ipv4")
    if not isinstance(before_ipv4, list) or len(before_ipv4) != 1:
        raise DeployError("terraform_scope_violation")
    before_cidr = before_ipv4[0]
    if not isinstance(before_cidr, str):
        raise DeployError("terraform_scope_violation")
    try:
        _validate_operator_cidr(before_cidr)
    except DeployError as exc:
        raise DeployError("terraform_scope_violation") from exc
    _validate_firewall_state(before, before_cidr)
    if _firewall_without_operator_cidr(before) != _firewall_without_operator_cidr(after):
        raise DeployError("terraform_scope_violation")
    return ["update"]


@dataclass(frozen=True)
class DeployConfig:
    """Allow one explicitly configured production target and SSH identity."""

    host: str
    user: str
    identity_file: Path
    known_hosts_file: Path
    terraform_bin: Path | None = None
    linode_token_file: Path | None = None
    reviewed_revision: str | None = None

    @classmethod
    def from_env(cls) -> DeployConfig:
        """Load a target without accepting per-tool host, path, or command overrides."""

        host = os.getenv("SIGNAL_LEDGER_DEPLOY_HOST", "")
        user = os.getenv("SIGNAL_LEDGER_DEPLOY_USER", "")
        identity = os.getenv("SIGNAL_LEDGER_DEPLOY_IDENTITY_FILE", "")
        known_hosts = os.getenv("SIGNAL_LEDGER_DEPLOY_KNOWN_HOSTS_FILE", "")
        if not HOST.fullmatch(host) or not USER.fullmatch(user):
            raise DeployError("deploy_target_unconfigured")
        if not identity or not known_hosts:
            raise DeployError("ssh_material_unconfigured")
        identity_path = Path(identity).expanduser().absolute()
        known_hosts_path = Path(known_hosts).expanduser().absolute()
        _regular_private_file(identity_path)
        _regular_private_file(known_hosts_path)
        terraform_bin = os.getenv("SIGNAL_LEDGER_TERRAFORM_BIN", "")
        terraform_path = Path(terraform_bin).expanduser().absolute() if terraform_bin else None
        token_file = os.getenv("SIGNAL_LEDGER_LINODE_TOKEN_FILE", "")
        token_path = Path(token_file).expanduser().absolute() if token_file else None
        return cls(host, user, identity_path, known_hosts_path, terraform_path, token_path)


class DeployController:
    """Expose only typed deployment operations to a fixed remote helper."""

    def __init__(self, config: DeployConfig) -> None:
        self.config = config

    def _invoke(
        self, operation: str, payload: dict[str, object], *, timeout: int
    ) -> dict[str, Any]:
        request = json.dumps(
            {"operation": operation, "payload": payload}, separators=(",", ":")
        ).encode()
        if len(request) > 8_192:
            raise DeployError("request_too_large")
        command = [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            f"UserKnownHostsFile={self.config.known_hosts_file}",
            "-i",
            str(self.config.identity_file),
            f"{self.config.user}@{self.config.host}",
            "signal-ledger-deploy-helper",
        ]
        try:
            response_bytes, returncode = _run_bounded_ssh(command, request, timeout=timeout)
        except DeployError:
            raise
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeployError("remote_unavailable") from exc
        if returncode != 0:
            raise DeployError("remote_rejected")
        try:
            response = json.loads(response_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DeployError("remote_response_invalid") from exc
        if not isinstance(response, dict) or response.get("status") not in {"ok", "error"}:
            raise DeployError("remote_response_invalid")
        if response["status"] == "error":
            raise DeployError("remote_operation_failed")
        return response

    def inspect(self) -> dict[str, Any]:
        """Read the fixed target's release, health, and storage status."""

        return self._invoke("inspect", {}, timeout=180)

    def plan_deploy(
        self,
        revision: str,
        expected_archive_sha256: str | None = None,
        expected_image_id: str | None = None,
        *,
        expected_image_digest: str | None = None,
        expected_pair_manifest_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Stage a reviewed revision from a locally published GitHub Release archive.

        The optional two-argument form is retained only for an already staged GHCR deployment;
        the MCP server exposes the archive form with both the archive hash and image ID required.
        """

        if not REVISION.fullmatch(revision):
            raise DeployError("revision_invalid")
        legacy = expected_image_digest is not None
        if legacy:
            if expected_archive_sha256 is not None or expected_image_id is not None:
                raise DeployError("image_identity_invalid")
            expected_archive_sha256 = expected_image_digest
        if expected_archive_sha256 is None or not SHA256.fullmatch(expected_archive_sha256):
            raise DeployError("archive_digest_invalid" if not legacy else "image_digest_invalid")
        if expected_image_id is not None and not IMAGE_ID.fullmatch(expected_image_id):
            raise DeployError("image_id_invalid")
        if expected_pair_manifest_sha256 is not None and not SHA256.fullmatch(
            expected_pair_manifest_sha256
        ):
            raise DeployError("pair_manifest_digest_invalid")
        # A cold clone, fetch, checkout, registry pull, and schema probe are serialized on
        # the host.  The SSH deadline must exceed their combined fixed command budgets.
        payload: dict[str, object]
        if expected_image_id is None:
            payload = {
                "revision": revision,
                "expected_image_digest": expected_archive_sha256,
            }
        else:
            payload = {
                "revision": revision,
                "archive_sha256": expected_archive_sha256,
                "image_id": expected_image_id,
            }
            if expected_pair_manifest_sha256 is not None:
                payload["pair_manifest_sha256"] = expected_pair_manifest_sha256
        response = self._invoke(
            "plan_deploy",
            payload,
            timeout=3_600,
        )
        valid_common = (
            response.get("revision") == revision
            and isinstance(response.get("plan_id"), str)
            and PLAN_ID.fullmatch(response["plan_id"]) is not None
        )
        if not valid_common:
            raise DeployError("remote_response_invalid")
        if expected_image_id is None:
            image_digest = response.get("image_digest")
            if (
                not isinstance(image_digest, str)
                or not SHA256.fullmatch(image_digest)
                or image_digest != expected_archive_sha256
                or response.get("image_ref") != f"{IMAGE_REPOSITORY}@sha256:{image_digest}"
            ):
                raise DeployError("remote_response_invalid")
        elif (
            response.get("transport") != RELEASE_TRANSPORT
            or response.get("archive_sha256") != expected_archive_sha256
            or response.get("image_id") != expected_image_id
            or response.get("image_ref") != f"{LOCAL_IMAGE_REPOSITORY}:sha-{revision}"
            or response.get("platform") != "linux/amd64"
            or type(response.get("archive_size")) is not int
            or not 1 <= response["archive_size"] <= MAX_ARCHIVE_BYTES
        ):
            raise DeployError("remote_response_invalid")
        if expected_pair_manifest_sha256 is not None and (
            response.get("pair_manifest_sha256") != expected_pair_manifest_sha256
            or response.get("recovery_schema_version") != ASSISTANT_READY_SCHEMA
            or response.get("recovery_platform") != "linux/amd64"
            or not isinstance(response.get("recovery_image_id"), str)
            or not IMAGE_ID.fullmatch(response["recovery_image_id"])
            or not isinstance(response.get("recovery_archive_sha256"), str)
            or not SHA256.fullmatch(response["recovery_archive_sha256"])
        ):
            raise DeployError("remote_response_invalid")
        if not _valid_hotfix_identity(response, revision):
            raise DeployError("remote_response_invalid")
        return response

    def deploy(
        self,
        plan_id: str,
        revision: str,
        archive_sha256: str | None = None,
        image_id: str | None = None,
        *,
        image_digest: str | None = None,
        pair_manifest_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Promote exactly the previously prepared revision and image digest."""

        if not PLAN_ID.fullmatch(plan_id):
            raise DeployError("plan_id_invalid")
        if not REVISION.fullmatch(revision):
            raise DeployError("revision_invalid")
        legacy = image_digest is not None
        if legacy:
            if archive_sha256 is not None or image_id is not None:
                raise DeployError("image_identity_invalid")
            archive_sha256 = image_digest
        if archive_sha256 is None or not SHA256.fullmatch(archive_sha256):
            raise DeployError("archive_digest_invalid" if not legacy else "image_digest_invalid")
        if image_id is not None and not IMAGE_ID.fullmatch(image_id):
            raise DeployError("image_id_invalid")
        if pair_manifest_sha256 is not None and not SHA256.fullmatch(pair_manifest_sha256):
            raise DeployError("pair_manifest_digest_invalid")
        payload: dict[str, object] = {
            "plan_id": plan_id,
            "revision": revision,
        }
        if image_id is None:
            payload["image_digest"] = archive_sha256
        else:
            payload["archive_sha256"] = archive_sha256
            payload["image_id"] = image_id
            if pair_manifest_sha256 is not None:
                payload["pair_manifest_sha256"] = pair_manifest_sha256
        response = self._invoke(
            "deploy",
            payload,
            timeout=1_800,
        )
        if response.get("plan_id") != plan_id or response.get("revision") != revision:
            raise DeployError("remote_response_invalid")
        if response.get("result") not in {"deployed", "already_applied"}:
            raise DeployError("remote_response_invalid")
        if image_id is None:
            if response.get("image_digest") != archive_sha256:
                raise DeployError("remote_response_invalid")
        elif (
            response.get("transport") != RELEASE_TRANSPORT
            or response.get("archive_sha256") != archive_sha256
            or response.get("image_id") != image_id
        ):
            raise DeployError("remote_response_invalid")
        if (
            pair_manifest_sha256 is not None
            and response.get("pair_manifest_sha256") != pair_manifest_sha256
        ):
            raise DeployError("remote_response_invalid")
        if not _valid_hotfix_identity(response, revision):
            raise DeployError("remote_response_invalid")
        return response

    def status(self) -> dict[str, Any]:
        """Read current and recent release status without changing the host."""

        return self._invoke("status", {}, timeout=60)

    def start_next_temporary_recovery(
        self, prior_operation_id: str, prior_view_sha256: str
    ) -> dict[str, Any]:
        """Start the fixed successor cycle from the exact inspected restored operation."""

        if not isinstance(prior_operation_id, str) or not PLAN_ID.fullmatch(prior_operation_id):
            raise DeployError("temporary_recovery_prior_identity_invalid")
        if not isinstance(prior_view_sha256, str) or not SHA256.fullmatch(prior_view_sha256):
            raise DeployError("temporary_recovery_prior_identity_invalid")
        response = self._invoke(
            "start_next_temporary_recovery",
            {
                "prior_operation_id": prior_operation_id,
                "prior_view_sha256": prior_view_sha256,
            },
            timeout=900,
        )
        if not isinstance(response, dict) or not _valid_temporary_recovery_ready_response(
            response, prior_operation_id, prior_view_sha256
        ):
            raise DeployError("remote_response_invalid")
        return response

    def rollback(self, revision: str, image_id: str | None = None) -> dict[str, Any]:
        """Roll back to a recorded release bound to its full image ID."""

        if not REVISION.fullmatch(revision):
            raise DeployError("revision_invalid")
        if image_id is not None and not IMAGE_ID.fullmatch(image_id):
            raise DeployError("image_id_invalid")
        payload: dict[str, object] = {"revision": revision}
        if image_id is not None:
            payload["image_id"] = image_id
        response = self._invoke("rollback", payload, timeout=900)
        expected_response_revision = revision
        if (
            revision in {HOTFIX_CANDIDATE_REVISION, HOTFIX_V3_CANDIDATE_REVISION}
            and response.get("release_role") == "recovery"
        ):
            expected_response_revision = HOTFIX_RECOVERY_REVISION
        if (
            response.get("revision") != expected_response_revision
            or response.get("result") != "rolled_back"
            or not isinstance(response.get("image_digest"), str)
            or not SHA256.fullmatch(response["image_digest"])
            or not _valid_hotfix_identity(response, revision, rollback=True)
        ):
            raise DeployError("remote_response_invalid")
        if image_id is not None and (
            response.get("transport") != RELEASE_TRANSPORT or response.get("image_id") != image_id
        ):
            raise DeployError("remote_response_invalid")
        return response

    def set_assistant_rollout(self, mode: str) -> dict[str, Any]:
        """Change the typed rollout only for the currently deployed reviewed image."""

        if not isinstance(mode, str) or mode not in ASSISTANT_ROLLOUT_MODES:
            raise DeployError("assistant_rollout_invalid")
        status = self.status()
        current = status.get("current") if isinstance(status, dict) else None
        if not isinstance(current, dict):
            raise DeployError("active_release_unavailable")
        revision = current.get("revision")
        archive_sha256 = current.get("archive_sha256")
        image_id = current.get("image_id")
        schema_version = current.get("schema_version")
        if (
            status.get("status") != "ok"
            or current.get("transport") != RELEASE_TRANSPORT
            or not isinstance(revision, str)
            or not REVISION.fullmatch(revision)
            or not isinstance(archive_sha256, str)
            or not SHA256.fullmatch(archive_sha256)
            or current.get("image_digest") != archive_sha256
            or not isinstance(image_id, str)
            or not IMAGE_ID.fullmatch(image_id)
            or current.get("platform") != "linux/amd64"
            or type(schema_version) is not int
            or schema_version != ASSISTANT_READY_SCHEMA
            or not isinstance(current.get("compose_digest"), str)
            or not SHA256.fullmatch(current["compose_digest"])
            or current.get("assistant_rollout_mode", "disabled") not in ASSISTANT_ROLLOUT_MODES
        ):
            raise DeployError("active_release_identity_invalid")
        if mode != "disabled":
            if current.get("release_role", "candidate") != "candidate":
                raise DeployError("assistant_recovery_image_disabled")
            local_revision = self._local_rollout_revision()
            if revision in {HOTFIX_CANDIDATE_REVISION, HOTFIX_V3_CANDIDATE_REVISION}:
                helper_revision = current.get("helper_source_revision")
                pair_manifest_sha256 = current.get("pair_manifest_sha256")
                if (
                    not _valid_hotfix_identity(current, revision)
                    or not isinstance(pair_manifest_sha256, str)
                    or not SHA256.fullmatch(pair_manifest_sha256)
                    or local_revision != helper_revision
                ):
                    raise DeployError("reviewed_release_mismatch")
            elif local_revision != revision:
                raise DeployError("reviewed_release_mismatch")
            if (
                self.config.reviewed_revision is not None
                and self.config.reviewed_revision != revision
            ):
                raise DeployError("reviewed_release_mismatch")
        response = self._invoke(
            "set_assistant_rollout",
            {
                "mode": mode,
                "revision": revision,
                "archive_sha256": archive_sha256,
                "image_id": image_id,
            },
            timeout=600,
        )
        health = response.get("health")
        if (
            response.get("status") != "ok"
            or response.get("result") != "rollout_updated"
            or response.get("revision") != revision
            or response.get("archive_sha256") != archive_sha256
            or response.get("image_id") != image_id
            or response.get("schema_version") != ASSISTANT_READY_SCHEMA
            or response.get("assistant_rollout_mode") != mode
            or not isinstance(health, dict)
            or health.get("status") != "ready"
            or health.get("schema_version") != ASSISTANT_READY_SCHEMA
        ):
            raise DeployError("remote_response_invalid")
        assistant = health.get("assistant")
        if mode == "disabled":
            if isinstance(assistant, dict) and assistant.get("enabled") is not False:
                raise DeployError("remote_response_invalid")
        elif (
            not isinstance(assistant, dict)
            or assistant.get("enabled") is not True
            or assistant.get("status") != "ready"
        ):
            raise DeployError("assistant_not_ready")
        return response

    def _local_rollout_revision(self) -> str:
        """Return the clean local checkout revision for caller-specific rollout checks."""

        environment = {
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        try:
            head = subprocess.run(  # noqa: S603 - fixed local Git argv
                [
                    "/usr/bin/git",
                    "-C",
                    str(REPOSITORY_ROOT),
                    "rev-parse",
                    "--verify",
                    "HEAD^{commit}",
                ],
                cwd=REPOSITORY_ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
                check=False,
            )
            changes = subprocess.run(  # noqa: S603 - fixed local Git argv
                [
                    "/usr/bin/git",
                    "-C",
                    str(REPOSITORY_ROOT),
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                cwd=REPOSITORY_ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeployError("reviewed_revision_unavailable") from exc
        revision = head.stdout.strip()
        if head.returncode != 0 or changes.returncode != 0 or not REVISION.fullmatch(revision):
            raise DeployError("reviewed_revision_unavailable")
        if changes.stdout:
            raise DeployError("worktree_dirty")
        return revision

    def refresh_operator_access(self, operator_ipv4_cidr: str) -> dict[str, Any]:
        """Update only the fixed production firewall's operator SSH `/32` through Terraform.

        The reviewed revision comes from the current checkout, while Terraform's existing source
        gate independently requires a clean tree and an exact public `origin/main` match before
        either plan or apply. The MCP accepts no Terraform path, command, state, or credential
        arguments from the caller.
        """

        cidr = _validate_operator_cidr(operator_ipv4_cidr)
        state_path = _validate_terraform_state()
        if self.config.linode_token_file is None:
            raise DeployError("terraform_token_unconfigured")
        token = _read_linode_token(self.config.linode_token_file)
        terraform_bin = _resolve_terraform_binary(self.config.terraform_bin)
        revision = self._reviewed_revision()
        environment = _terraform_environment(token)
        plan_actions = self._run_terraform_access_plan(
            terraform_bin,
            environment,
            cidr,
            revision,
            state_path,
        )
        return {
            "status": "ok",
            "result": "applied",
            "resource": FIREWALL_RESOURCE,
            "firewall_id": int(FIREWALL_ID),
            "operator_ipv4_cidr": cidr,
            "reviewed_revision": revision,
            "plan_actions": plan_actions,
        }

    def _reviewed_revision(self) -> str:
        """Resolve the reviewed SHA without accepting a caller-supplied revision."""

        if self.config.reviewed_revision is not None:
            if REVISION.fullmatch(self.config.reviewed_revision) is None:
                raise DeployError("revision_invalid")
            return self.config.reviewed_revision
        try:
            completed = subprocess.run(  # noqa: S603 - fixed local Git argv
                [
                    "/usr/bin/git",
                    "-C",
                    str(REPOSITORY_ROOT),
                    "rev-parse",
                    "--verify",
                    "HEAD^{commit}",
                ],
                cwd=REPOSITORY_ROOT,
                env={
                    "PATH": "/usr/bin:/bin",
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_TERMINAL_PROMPT": "0",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeployError("reviewed_revision_unavailable") from exc
        if completed.returncode != 0:
            raise DeployError("reviewed_revision_unavailable")
        revision = completed.stdout.strip()
        if REVISION.fullmatch(revision) is None:
            raise DeployError("reviewed_revision_unavailable")
        return revision

    def _run_terraform_access_plan(
        self,
        terraform_bin: Path,
        environment: dict[str, str],
        cidr: str,
        revision: str,
        state_path: Path,
    ) -> list[str]:
        """Plan, inspect, and apply one bounded firewall-only Terraform plan."""

        if state_path != TERRAFORM_STATE_PATH:
            raise DeployError("terraform_state_scope_violation")
        with tempfile.TemporaryDirectory(prefix="signal-ledger-firewall-") as temporary_dir:
            plan_path = Path(temporary_dir) / "operator-access.tfplan"
            init_command = [
                str(terraform_bin),
                f"-chdir={LINODE_ROOT}",
                "init",
                "-backend=false",
                "-input=false",
                "-upgrade=false",
            ]
            _run_quiet_command(init_command, environment=environment, timeout=180)
            plan_command = [
                str(terraform_bin),
                f"-chdir={LINODE_ROOT}",
                "plan",
                "-input=false",
                "-no-color",
                "-refresh=true",
                "-lock-timeout=60s",
                f"-state={state_path}",
                f"-target={FIREWALL_RESOURCE}",
                f"-out={plan_path}",
                f"-var=operator_ipv4_cidr={cidr}",
                f"-var=reviewed_revision={revision}",
                f"-var=firewall_id={FIREWALL_ID}",
                f"-var=firewall_label={FIREWALL_LABEL}",
            ]
            _run_quiet_command(plan_command, environment=environment, timeout=300)

            show_command = [
                str(terraform_bin),
                f"-chdir={LINODE_ROOT}",
                "show",
                "-json",
                str(plan_path),
            ]
            try:
                output, returncode = _run_bounded_ssh(
                    show_command,
                    b"",
                    timeout=120,
                    cwd=LINODE_ROOT,
                    env=environment,
                    max_output_bytes=MAX_TERRAFORM_PLAN_BYTES,
                )
            except DeployError as exc:
                if exc.code == "remote_response_too_large":
                    raise DeployError("terraform_plan_too_large") from exc
                raise DeployError("terraform_plan_unavailable") from exc
            if returncode != 0:
                raise DeployError("terraform_plan_unavailable")
            try:
                plan_document = json.loads(output)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise DeployError("terraform_plan_invalid") from exc
            plan_actions = _validate_firewall_plan(plan_document, cidr)

            apply_command = [
                str(terraform_bin),
                f"-chdir={LINODE_ROOT}",
                "apply",
                "-input=false",
                "-auto-approve",
                "-no-color",
                "-lock-timeout=60s",
                f"-state={state_path}",
                str(plan_path),
            ]
            _run_quiet_command(apply_command, environment=environment, timeout=300)
        return plan_actions


def _run_bounded_ssh(
    command: list[str],
    request: bytes,
    *,
    timeout: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    max_output_bytes: int = MAX_RESPONSE_BYTES,
) -> tuple[bytes, int]:
    """Run SSH while bounding response memory and cleaning up timed out children.

    ``subprocess.run(..., stdout=PIPE)`` accumulates all remote output before returning.  The
    helper is intentionally a fixed command, but a compromised or broken host can still emit
    unbounded bytes.  Read the response incrementally and kill the child as soon as the limit is
    crossed; stderr is discarded at the SSH boundary and never becomes an MCP response.
    """

    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    stdin_registered = False
    stdin_closed = False
    output = bytearray()
    offset = 0
    deadline = time.monotonic() + timeout

    def close_stdin() -> None:
        nonlocal stdin_closed, stdin_registered
        if process is None or process.stdin is None or stdin_closed:
            return
        if selector is not None and stdin_registered:
            selector.unregister(process.stdin)
            stdin_registered = False
        with suppress(OSError):
            process.stdin.close()
        stdin_closed = True

    def terminate() -> None:
        if process is None or process.poll() is not None:
            return
        with suppress(OSError):
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # ``kill`` is best effort; there is no safe way to return an MCP response while a
            # child retaining the pipe can keep producing output or holding the SSH session.
            with suppress(OSError):
                process.kill()
            with suppress(subprocess.TimeoutExpired):
                process.wait()

    try:
        # The SSH argv is fixed apart from validated startup configuration, never tool input.
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if process.stdin is None or process.stdout is None:
            raise DeployError("remote_unavailable")
        os.set_blocking(process.stdin.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        if request:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            stdin_registered = True
        else:
            close_stdin()

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeployError("remote_unavailable")
            events = selector.select(remaining)
            if not events:
                raise DeployError("remote_unavailable")
            for key, _ in events:
                if key.data == "stdin":
                    try:
                        written = os.write(process.stdin.fileno(), request[offset:])
                    except BrokenPipeError:
                        close_stdin()
                        continue
                    if written <= 0:
                        raise DeployError("remote_unavailable")
                    offset += written
                    if offset == len(request):
                        close_stdin()
                    continue

                chunk = os.read(process.stdout.fileno(), STREAM_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(process.stdout)
                    continue
                output.extend(chunk)
                if len(output) > max_output_bytes:
                    raise DeployError("remote_response_too_large")

        close_stdin()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DeployError("remote_unavailable")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise DeployError("remote_unavailable") from exc
        return bytes(output), returncode
    except DeployError:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeployError("remote_unavailable") from exc
    finally:
        terminate()
        close_stdin()
        if process is not None and process.stdout is not None:
            with suppress(OSError):
                process.stdout.close()
        if selector is not None:
            selector.close()
