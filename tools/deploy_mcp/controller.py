"""Validate deployment requests before sending fixed operations over SSH."""

from __future__ import annotations

import copy
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
LOCAL_IMAGE_REPOSITORY = "signal-ledger"
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
        return response

    def deploy(
        self,
        plan_id: str,
        revision: str,
        archive_sha256: str | None = None,
        image_id: str | None = None,
        *,
        image_digest: str | None = None,
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
        payload: dict[str, object] = {
            "plan_id": plan_id,
            "revision": revision,
        }
        if image_id is None:
            payload["image_digest"] = archive_sha256
        else:
            payload["archive_sha256"] = archive_sha256
            payload["image_id"] = image_id
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
        return response

    def status(self) -> dict[str, Any]:
        """Read current and recent release status without changing the host."""

        return self._invoke("status", {}, timeout=60)

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
        if (
            response.get("revision") != revision
            or response.get("result") != "rolled_back"
            or not isinstance(response.get("image_digest"), str)
            or not SHA256.fullmatch(response["image_digest"])
        ):
            raise DeployError("remote_response_invalid")
        if image_id is not None and (
            response.get("transport") != RELEASE_TRANSPORT or response.get("image_id") != image_id
        ):
            raise DeployError("remote_response_invalid")
        return response

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
