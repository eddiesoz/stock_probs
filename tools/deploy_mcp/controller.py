"""Validate deployment requests before sending fixed operations over SSH."""

from __future__ import annotations

import json
import os
import re
import selectors
import stat
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
PLAN_ID = re.compile(r"^[0-9a-f]{32}$")
IMAGE_REPOSITORY = "ghcr.io/jtmb/signal-ledger"
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
MAX_RESPONSE_BYTES = 65_536
STREAM_CHUNK_BYTES = 4_096


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


@dataclass(frozen=True)
class DeployConfig:
    """Allow one explicitly configured production target and SSH identity."""

    host: str
    user: str
    identity_file: Path
    known_hosts_file: Path

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
        return cls(host, user, identity_path, known_hosts_path)


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

    def plan_deploy(self, revision: str, expected_image_digest: str) -> dict[str, Any]:
        """Stage a reviewed main commit against the publisher's immutable image digest."""

        if not REVISION.fullmatch(revision):
            raise DeployError("revision_invalid")
        if not SHA256.fullmatch(expected_image_digest):
            raise DeployError("image_digest_invalid")
        # A cold clone, fetch, checkout, registry pull, and schema probe are serialized on
        # the host.  The SSH deadline must exceed their combined fixed command budgets.
        response = self._invoke(
            "plan_deploy",
            {"revision": revision, "expected_image_digest": expected_image_digest},
            timeout=3_600,
        )
        image_digest = response.get("image_digest")
        if (
            response.get("revision") != revision
            or not isinstance(response.get("plan_id"), str)
            or not PLAN_ID.fullmatch(response["plan_id"])
            or not isinstance(image_digest, str)
            or not SHA256.fullmatch(image_digest)
            or image_digest != expected_image_digest
            or response.get("image_ref")
            != f"{IMAGE_REPOSITORY}@sha256:{image_digest}"
        ):
            raise DeployError("remote_response_invalid")
        return response

    def deploy(self, plan_id: str, revision: str, image_digest: str) -> dict[str, Any]:
        """Promote exactly the previously prepared revision and image digest."""

        if not PLAN_ID.fullmatch(plan_id):
            raise DeployError("plan_id_invalid")
        if not REVISION.fullmatch(revision):
            raise DeployError("revision_invalid")
        if not SHA256.fullmatch(image_digest):
            raise DeployError("image_digest_invalid")
        response = self._invoke(
            "deploy",
            {"plan_id": plan_id, "revision": revision, "image_digest": image_digest},
            timeout=1_800,
        )
        if (
            response.get("plan_id") != plan_id
            or response.get("revision") != revision
            or response.get("image_digest") != image_digest
            or response.get("result") not in {"deployed", "already_applied"}
        ):
            raise DeployError("remote_response_invalid")
        return response

    def status(self) -> dict[str, Any]:
        """Read current and recent release status without changing the host."""

        return self._invoke("status", {}, timeout=60)

    def rollback(self, revision: str) -> dict[str, Any]:
        """Request a rollback to a locally recorded release, subject to schema checks."""

        if not REVISION.fullmatch(revision):
            raise DeployError("revision_invalid")
        response = self._invoke("rollback", {"revision": revision}, timeout=900)
        if (
            response.get("revision") != revision
            or response.get("result") != "rolled_back"
            or not isinstance(response.get("image_digest"), str)
            or not SHA256.fullmatch(response["image_digest"])
        ):
            raise DeployError("remote_response_invalid")
        return response


def _run_bounded_ssh(command: list[str], request: bytes, *, timeout: float) -> tuple[bytes, int]:
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
                if len(output) > MAX_RESPONSE_BYTES:
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
