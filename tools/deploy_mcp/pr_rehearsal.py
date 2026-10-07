"""Stage and run the fixed schema-13 rehearsal pair through the operator boundary."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIRECTORY = REPOSITORY_ROOT / "test-results" / "assistant-r120-pr-pair"
HOST = "45.79.180.32"
USER = "signalops"
REPOSITORY = "eddiesoz/stock_probs"
PULL_NUMBER = 1
HELPER_PATH = "/usr/local/libexec/signal-ledger-pr-rehearsal/host_helper.py"
STATE_ROOT = "/var/lib/signal-ledger-pr-rehearsal"
INCOMING_DIRECTORY = "/var/lib/signal-ledger-pr-rehearsal/incoming"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 65_536
REVISION = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
OOM_EVENT_COUNTERS = ("oom", "oom_kill", "oom_group_kill")
MAX_RESOURCE_COUNTER = (1 << 64) - 1
EXPECTED_CANDIDATE_MEMORY_LIMIT = 768 * 1024 * 1024
EXPECTED_RECOVERY_MEMORY_LIMIT = 384 * 1024 * 1024
DEPLOYED_BASELINE = {
    "revision": "da2764e8477698fa7d686be93a4711e35478e802",
    "image_id": "sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1",
    "archive_sha256": "669f840a3141b0fb95ae248b5ea0799733b9e5b5b81e224d4637571c24d8f640",
}
MIGRATION_SHA256 = "41e7d0ef5e5267ab50a67666862bf01e4c6cfd8986b6096bd8b92deed70ff31b"
SOURCE_ASSETS = {
    "bootstrap": ("scripts/pr_rehearsal_bootstrap.py", "bootstrap.py", 256 * 1024),
    "host_helper": ("scripts/pr_rehearsal_host_helper.py", "host_helper.py", 256 * 1024),
    "seed": ("scripts/pr_rehearsal_seed.py", "seed.py", 64 * 1024),
    "driver": ("tests/native_assistant_probe.py", "native_driver.py", 2 * 1024 * 1024),
}


class RehearsalError(Exception):
    """A safe rehearsal failure category for the local MCP boundary."""

    def __init__(self, code: str, *, details: dict[str, object] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


@dataclass(frozen=True)
class RehearsalConfig:
    """Hold operator SSH metadata and exact reviewed source/artifact pins."""

    identity_file: Path
    known_hosts_file: Path
    reviewed_head_sha: str
    reviewed_pair_manifest_sha256: str

    @classmethod
    def from_env(cls) -> RehearsalConfig:
        """Load fixed-target operator metadata without reading either private file."""

        home = Path.home()
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        identity = Path(
            os.environ.get(
                "SIGNAL_LEDGER_OPERATOR_IDENTITY_FILE",
                str(home / ".ssh" / "signal-ledger-operator-2026"),
            )
        ).expanduser()
        known_hosts = Path(
            os.environ.get(
                "SIGNAL_LEDGER_KNOWN_HOSTS_FILE",
                str(config_home / "signal-ledger" / "credentials" / "linode-known-hosts"),
            )
        ).expanduser()
        reviewed_head = os.environ.get("SIGNAL_LEDGER_REHEARSAL_REVIEWED_PR_HEAD_SHA", "")
        reviewed_manifest = os.environ.get(
            "SIGNAL_LEDGER_REHEARSAL_REVIEWED_PAIR_MANIFEST_SHA256", ""
        )
        _private_file_metadata(identity, "operator_identity")
        _private_file_metadata(known_hosts, "known_hosts")
        if REVISION.fullmatch(reviewed_head) is None:
            raise RehearsalError("reviewed_pr_head_unconfigured")
        if DIGEST.fullmatch(reviewed_manifest) is None:
            raise RehearsalError("reviewed_pair_manifest_unconfigured")
        return cls(
            identity.absolute(),
            known_hosts.absolute(),
            reviewed_head,
            reviewed_manifest,
        )


def _private_file_metadata(path: Path, label: str) -> None:
    """Check SSH file metadata without opening or printing its contents."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RehearsalError(f"{label}_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise RehearsalError(f"{label}_permissions")


def _fixed_environment() -> dict[str, str]:
    """Drop inherited Git, SSH, proxy, and credential environment from child tools."""

    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "LANG": "C",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run_fixed(command: list[str], *, timeout: float, input_bytes: bytes | None = None) -> bytes:
    """Run one fixed executable with bounded captured output and no diagnostic forwarding."""

    try:
        result = subprocess.run(  # noqa: S603 - every command is fixed or digest-validated.
            command,
            cwd=REPOSITORY_ROOT,
            env=_fixed_environment(),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalError("fixed_operation_unavailable") from exc
    if result.returncode != 0:
        raise RehearsalError("fixed_operation_failed")
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise RehearsalError("fixed_operation_response_too_large")
    return result.stdout


def _validated_resource_evidence(response: dict[str, object]) -> dict[str, object]:
    """Project only complete, bounded host and cgroup resource observations."""

    capacity = response.get("host_memory_capacity_evidence")
    if (
        not isinstance(capacity, dict)
        or set(capacity) != {"complete", "unit", "memtotal_before", "memtotal_after", "stable"}
        or capacity.get("complete") is not True
        or capacity.get("unit") != "kib"
        or type(capacity.get("memtotal_before")) is not int
        or type(capacity.get("memtotal_after")) is not int
        or capacity.get("memtotal_before", 0) <= 0
        or capacity.get("memtotal_after", 0) <= 0
        or capacity.get("memtotal_before", MAX_RESOURCE_COUNTER + 1) > MAX_RESOURCE_COUNTER
        or capacity.get("memtotal_after", MAX_RESOURCE_COUNTER + 1) > MAX_RESOURCE_COUNTER
        or capacity.get("memtotal_before") != capacity.get("memtotal_after")
        or capacity.get("stable") is not True
    ):
        raise RehearsalError("host_response_invalid")

    candidate_peak = response.get("candidate_memory_peak_bytes")
    candidate_limit = response.get("candidate_memory_limit_bytes")
    recovery_peak = response.get("recovery_memory_peak_bytes")
    recovery_limit = response.get("recovery_memory_limit_bytes")
    if (
        type(candidate_peak) is not int
        or type(candidate_limit) is not int
        or type(recovery_peak) is not int
        or type(recovery_limit) is not int
        or candidate_limit != EXPECTED_CANDIDATE_MEMORY_LIMIT
        or recovery_limit != EXPECTED_RECOVERY_MEMORY_LIMIT
        or not 0 <= candidate_peak <= candidate_limit
        or not 0 <= recovery_peak <= recovery_limit
    ):
        raise RehearsalError("host_response_invalid")

    def validate_oom_evidence(value: object) -> dict[str, object]:
        if (
            not isinstance(value, dict)
            or set(value) != {"complete", "baseline", "final", "delta", "zero_oom_events"}
            or value.get("complete") is not True
            or value.get("zero_oom_events") is not True
        ):
            raise RehearsalError("host_response_invalid")
        observed: dict[str, dict[str, int]] = {}
        for field in ("baseline", "final", "delta"):
            counters = value.get(field)
            if not isinstance(counters, dict) or set(counters) != set(OOM_EVENT_COUNTERS):
                raise RehearsalError("host_response_invalid")
            if any(
                type(counters[counter]) is not int
                or not 0 <= counters[counter] <= MAX_RESOURCE_COUNTER
                for counter in OOM_EVENT_COUNTERS
            ):
                raise RehearsalError("host_response_invalid")
            observed[field] = {counter: counters[counter] for counter in OOM_EVENT_COUNTERS}
        for counter in OOM_EVENT_COUNTERS:
            baseline = observed["baseline"][counter]
            final = observed["final"][counter]
            delta = observed["delta"][counter]
            if baseline != 0 or final != 0 or delta != final - baseline:
                raise RehearsalError("host_response_invalid")
        return {
            "complete": True,
            "baseline": observed["baseline"],
            "final": observed["final"],
            "delta": observed["delta"],
            "zero_oom_events": True,
        }

    candidate_oom = validate_oom_evidence(response.get("candidate_oom_event_evidence"))
    recovery_oom = validate_oom_evidence(response.get("recovery_oom_event_evidence"))
    if (
        response.get("oom_event_evidence_complete") is not True
        or response.get("zero_oom_events_verified") is not True
    ):
        raise RehearsalError("host_response_invalid")

    return {
        "host_memory_capacity_evidence": {
            "complete": True,
            "unit": "kib",
            "memtotal_before": capacity["memtotal_before"],
            "memtotal_after": capacity["memtotal_after"],
            "stable": True,
        },
        "candidate_memory_peak_bytes": candidate_peak,
        "candidate_memory_limit_bytes": candidate_limit,
        "candidate_oom_event_evidence": candidate_oom,
        "recovery_memory_peak_bytes": recovery_peak,
        "recovery_memory_limit_bytes": recovery_limit,
        "recovery_oom_event_evidence": recovery_oom,
        "oom_event_evidence_complete": True,
        "zero_oom_events_verified": True,
    }


def verify_pull_request(reviewed_head_sha: str) -> dict[str, object]:
    """Require public PR #1 to remain open, based on main, at the reviewed SHA."""

    if REVISION.fullmatch(reviewed_head_sha) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    connection = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(
            "GET",
            f"/repos/{REPOSITORY}/pulls/{PULL_NUMBER}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "signal-ledger-r120-pr-rehearsal",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RehearsalError("reviewed_pr_unavailable")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RehearsalError("reviewed_pr_unavailable") from exc
    finally:
        connection.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RehearsalError("reviewed_pr_response_too_large")
    try:
        payload: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("reviewed_pr_response_invalid") from exc
    if not isinstance(payload, dict):
        raise RehearsalError("reviewed_pr_response_invalid")
    base = payload.get("base")
    head = payload.get("head")
    repository = payload.get("head")
    source_repository = repository.get("repo") if isinstance(repository, dict) else None
    if (
        payload.get("state") != "open"
        or not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(head, dict)
        or head.get("sha") != reviewed_head_sha
        or not isinstance(source_repository, dict)
        or source_repository.get("full_name") != REPOSITORY
    ):
        raise RehearsalError("reviewed_pr_mismatch")
    return {
        "repository": REPOSITORY,
        "pull_number": PULL_NUMBER,
        "state": "open",
        "base": "main",
        "head_sha": reviewed_head_sha,
        "draft": payload.get("draft") is True,
    }


def _read_regular_file(path: Path, *, maximum: int, label: str) -> bytes:
    """Read one fixed artifact only after rejecting links, special files, and size drift."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RehearsalError(f"{label}_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= maximum:
        raise RehearsalError(f"{label}_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            data = source.read(maximum + 1)
    except OSError as exc:
        raise RehearsalError(f"{label}_unavailable") from exc
    if len(data) != metadata.st_size or len(data) > maximum:
        raise RehearsalError(f"{label}_changed")
    return data


def _artifact_pair(
    reviewed_head_sha: str,
    *,
    candidate_image_id: str,
    candidate_source_context_sha256: str,
    recovery_image_id: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
    pair_manifest_sha256: str,
) -> tuple[dict[str, object], dict[str, bytes]]:
    """Bind the fixed local release assets to every typed identity supplied by the caller."""

    if REVISION.fullmatch(reviewed_head_sha) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    if not IMAGE_ID.fullmatch(candidate_image_id) or not IMAGE_ID.fullmatch(recovery_image_id):
        raise RehearsalError("image_identity_invalid")
    for value in (
        candidate_source_context_sha256,
        recovery_source_context_sha256,
        recovery_overlay_sha256,
        pair_manifest_sha256,
    ):
        if DIGEST.fullmatch(value) is None:
            raise RehearsalError("pair_digest_invalid")
    try:
        directory_info = ARTIFACT_DIRECTORY.lstat()
    except OSError as exc:
        raise RehearsalError("pair_assets_unavailable") from exc
    if not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode):
        raise RehearsalError("pair_assets_unsafe")
    names = {
        "candidate": f"signal-ledger-image-{reviewed_head_sha}.tar.gz",
        "recovery": f"signal-ledger-recovery-{reviewed_head_sha}.tar.gz",
        "manifest": f"signal-ledger-pair-{reviewed_head_sha}.json",
    }
    assets = {
        role: _read_regular_file(
            ARTIFACT_DIRECTORY / name,
            maximum=MAX_MANIFEST_BYTES if role == "manifest" else MAX_ARCHIVE_BYTES,
            label=f"{role}_asset",
        )
        for role, name in names.items()
    }
    manifest_bytes = assets["manifest"]
    if hashlib.sha256(manifest_bytes).hexdigest() != pair_manifest_sha256:
        raise RehearsalError("pair_manifest_digest_mismatch")
    try:
        manifest: object = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("pair_manifest_invalid") from exc
    if not isinstance(manifest, dict):
        raise RehearsalError("pair_manifest_invalid")
    candidate = manifest.get("candidate")
    recovery = manifest.get("recovery")
    migration = manifest.get("migration")
    expected = (
        set(manifest)
        == {
            "format_version",
            "repository",
            "revision",
            "source_context_sha256",
            "migration",
            "candidate",
            "recovery",
        }
        and type(manifest.get("format_version")) is int
        and manifest.get("format_version") == 1
        and manifest.get("repository") == REPOSITORY
        and manifest.get("revision") == reviewed_head_sha
        and manifest.get("source_context_sha256") == candidate_source_context_sha256
        and isinstance(candidate, dict)
        and candidate.get("asset") == names["candidate"]
        and candidate.get("image_id") == candidate_image_id
        and candidate.get("archive_sha256") == hashlib.sha256(assets["candidate"]).hexdigest()
        and candidate.get("archive_size") == len(assets["candidate"])
        and candidate.get("platform") == "linux/amd64"
        and candidate.get("revision") == reviewed_head_sha
        and candidate.get("schema_version") == 13
        and candidate.get("source_context_sha256") == candidate_source_context_sha256
        and isinstance(recovery, dict)
        and recovery.get("asset") == names["recovery"]
        and recovery.get("image_id") == recovery_image_id
        and recovery.get("archive_sha256") == hashlib.sha256(assets["recovery"]).hexdigest()
        and recovery.get("archive_size") == len(assets["recovery"])
        and recovery.get("platform") == "linux/amd64"
        and recovery.get("revision") == reviewed_head_sha
        and recovery.get("schema_version") == 13
        and recovery.get("assistant_enabled") is False
        and recovery.get("source_context_sha256") == recovery_source_context_sha256
        and recovery.get("base_revision") == DEPLOYED_BASELINE["revision"]
        and recovery.get("base_image_id") == DEPLOYED_BASELINE["image_id"]
        and recovery.get("base_archive_sha256") == DEPLOYED_BASELINE["archive_sha256"]
        and recovery.get("overlay_sha256") == recovery_overlay_sha256
        and recovery.get("migration_sha256") == MIGRATION_SHA256
        and isinstance(migration, dict)
        and migration.get("from_schema") == 12
        and migration.get("to_schema") == 13
        and migration.get("sha256") == recovery.get("migration_sha256")
    )
    if not expected:
        raise RehearsalError("pair_manifest_identity_mismatch")
    return manifest, assets


def _verify_local_reviewed_source(
    reviewed_head_sha: str,
    *,
    candidate_source_context_sha256: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
) -> None:
    """Require a clean exact PR checkout and independently recompute both source manifests."""

    head = (
        _run_fixed(
            ["/usr/bin/git", "-C", str(REPOSITORY_ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
            timeout=15,
        )
        .decode("ascii", errors="strict")
        .strip()
    )
    origin = (
        _run_fixed(
            ["/usr/bin/git", "-C", str(REPOSITORY_ROOT), "remote", "get-url", "origin"],
            timeout=15,
        )
        .decode("utf-8", errors="strict")
        .strip()
    )
    changes = _run_fixed(
        [
            "/usr/bin/git",
            "-C",
            str(REPOSITORY_ROOT),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        timeout=15,
    )
    if head != reviewed_head_sha or origin != "https://github.com/eddiesoz/stock_probs.git":
        raise RehearsalError("reviewed_local_source_mismatch")
    if changes:
        raise RehearsalError("reviewed_local_source_dirty")
    script = str(REPOSITORY_ROOT / "scripts" / "rehearse_schema13.py")
    manifests: list[dict[str, object]] = []
    for argument in ("--source-context-manifest", "--overlay-manifest"):
        raw = _run_fixed(["/usr/bin/python3", script, argument], timeout=120)
        try:
            value: object = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RehearsalError("reviewed_source_manifest_invalid") from exc
        if not isinstance(value, dict) or value.get("status") != "prepared":
            raise RehearsalError("reviewed_source_manifest_invalid")
        manifests.append(value)
    source_context = manifests[0].get("source_context_sha256")
    overlay = manifests[1].get("recovery_overlay")
    recovery_context = manifests[1].get("recovery_context_sha256")
    overlay_digest = overlay.get("overlay_sha256") if isinstance(overlay, dict) else None
    if (
        source_context != candidate_source_context_sha256
        or recovery_context != recovery_source_context_sha256
        or overlay_digest != recovery_overlay_sha256
    ):
        raise RehearsalError("reviewed_source_context_mismatch")


def _ssh_prefix(config: RehearsalConfig) -> list[str]:
    """Return the only permitted operator SSH option set and target."""

    return [
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
        f"UserKnownHostsFile={config.known_hosts_file}",
        "-i",
        str(config.identity_file),
        f"{USER}@{HOST}",
    ]


def _stage_assets(config: RehearsalConfig, revision: str, assets: dict[str, bytes]) -> None:
    """Copy the three fixed pair files to names derived only from the validated PR SHA."""

    names = {
        "candidate": f"signal-ledger-pr1-{revision}-candidate.tar.gz",
        "recovery": f"signal-ledger-pr1-{revision}-recovery.tar.gz",
        "manifest": f"signal-ledger-pr1-{revision}-pair.json",
    }
    _stage_named_assets(config, names, assets)


def _stage_named_assets(
    config: RehearsalConfig,
    names: dict[str, str],
    assets: dict[str, bytes],
) -> None:
    """Stage only caller-independent names already derived from fixed asset roles."""

    for role, content in assets.items():
        descriptor, raw_path = tempfile.mkstemp(prefix="signal-ledger-pr-pair-")
        path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            path.chmod(0o600)
            remote_path = f"{USER}@{HOST}:{INCOMING_DIRECTORY}/{names[role]}"
            command = [
                "scp",
                "-q",
                "-B",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "ClearAllForwardings=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                f"UserKnownHostsFile={config.known_hosts_file}",
                "-i",
                str(config.identity_file),
                str(path),
                remote_path,
            ]
            _run_fixed(command, timeout=180)
        finally:
            path.unlink(missing_ok=True)


def _ensure_incoming_directories(config: RehearsalConfig) -> None:
    """Create only the fixed sidecar staging path, with no production path involved."""

    command = [
        *_ssh_prefix(config),
        "sudo -n /usr/bin/install -d -o root -g signalops -m 0750 "
        f"{STATE_ROOT} && sudo -n /usr/bin/install -d -o {USER} -g {USER} -m 0700 "
        f"{INCOMING_DIRECTORY}",
    ]
    _run_fixed(command, timeout=30)


def _source_bundle() -> tuple[dict[str, bytes], dict[str, str]]:
    assets: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for role, (relative, _remote_name, maximum) in SOURCE_ASSETS.items():
        content = _read_regular_file(
            REPOSITORY_ROOT / relative,
            maximum=maximum,
            label="bootstrap_source",
        )
        assets[role] = content
        hashes[role] = hashlib.sha256(content).hexdigest()
    return assets, hashes


def _source_stage_names(revision: str) -> dict[str, str]:
    """Derive only the fixed incoming basenames for one validated reviewed SHA."""

    if REVISION.fullmatch(revision) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    return {
        role: f"signal-ledger-pr1-{revision}-{remote_name}"
        for role, (_path, remote_name, _maximum) in SOURCE_ASSETS.items()
    }


def _stage_source_bundle(
    config: RehearsalConfig,
    revision: str,
    pair_manifest_sha256: str,
    assets: dict[str, bytes],
    hashes: dict[str, str],
) -> None:
    names = _source_stage_names(revision)
    _stage_named_assets(config, names, assets)
    request = {
        "operation": "install",
        "payload": {
            "reviewed_head_sha": revision,
            "reviewed_pair_manifest_sha256": pair_manifest_sha256,
            "asset_sha256": hashes,
        },
    }
    encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8")
    bootstrap_path = f"{INCOMING_DIRECTORY}/{names['bootstrap']}"
    response_raw = _run_fixed(
        [*_ssh_prefix(config), "sudo -n /usr/bin/python3 " + bootstrap_path],
        timeout=120,
        input_bytes=encoded,
    )
    try:
        response: object = json.loads(response_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("bootstrap_response_invalid") from exc
    if (
        not isinstance(response, dict)
        or response.get("status") != "installed"
        or response.get("reviewed_head_sha") != revision
        or response.get("reviewed_pair_manifest_sha256") != pair_manifest_sha256
        or response.get("asset_sha256") != hashes
    ):
        raise RehearsalError("bootstrap_install_failed")


def rehearse_pr_pair(
    *,
    reviewed_head_sha: str,
    candidate_image_id: str,
    candidate_source_context_sha256: str,
    recovery_image_id: str,
    recovery_source_context_sha256: str,
    recovery_overlay_sha256: str,
    pair_manifest_sha256: str,
) -> dict[str, object]:
    """Run only the fixed PR #1 disposable pair rehearsal through the operator helper."""

    config = RehearsalConfig.from_env()
    if reviewed_head_sha != config.reviewed_head_sha:
        raise RehearsalError("reviewed_pr_head_mismatch")
    if pair_manifest_sha256 != config.reviewed_pair_manifest_sha256:
        raise RehearsalError("reviewed_pair_manifest_mismatch")
    pr_receipt = verify_pull_request(reviewed_head_sha)
    _verify_local_reviewed_source(
        reviewed_head_sha,
        candidate_source_context_sha256=candidate_source_context_sha256,
        recovery_source_context_sha256=recovery_source_context_sha256,
        recovery_overlay_sha256=recovery_overlay_sha256,
    )
    manifest, assets = _artifact_pair(
        reviewed_head_sha,
        candidate_image_id=candidate_image_id,
        candidate_source_context_sha256=candidate_source_context_sha256,
        recovery_image_id=recovery_image_id,
        recovery_source_context_sha256=recovery_source_context_sha256,
        recovery_overlay_sha256=recovery_overlay_sha256,
        pair_manifest_sha256=pair_manifest_sha256,
    )
    source_assets, source_hashes = _source_bundle()
    _ensure_incoming_directories(config)
    try:
        _stage_source_bundle(
            config,
            reviewed_head_sha,
            pair_manifest_sha256,
            source_assets,
            source_hashes,
        )
        _stage_assets(config, reviewed_head_sha, assets)
    except RehearsalError:
        _cleanup_staged_assets(config, reviewed_head_sha)
        raise
    request = {
        "operation": "rehearse_pr_pair",
        "payload": {
            "repository": REPOSITORY,
            "pull_number": PULL_NUMBER,
            "reviewed_head_sha": reviewed_head_sha,
            "candidate_image_id": candidate_image_id,
            "candidate_source_context_sha256": candidate_source_context_sha256,
            "recovery_image_id": recovery_image_id,
            "recovery_source_context_sha256": recovery_source_context_sha256,
            "recovery_overlay_sha256": recovery_overlay_sha256,
            "pair_manifest_sha256": pair_manifest_sha256,
            "candidate_archive_sha256": manifest["candidate"]["archive_sha256"],
            "recovery_archive_sha256": manifest["recovery"]["archive_sha256"],
        },
    }
    encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8")
    try:
        response_raw = _run_fixed(
            [*_ssh_prefix(config), "sudo -n", HELPER_PATH],
            timeout=1_200,
            input_bytes=encoded,
        )
    except RehearsalError:
        _cleanup_staged_assets(config, reviewed_head_sha)
        raise
    try:
        response: object = json.loads(response_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("host_response_invalid") from exc
    if not isinstance(response, dict):
        raise RehearsalError("host_response_invalid")
    if response.get("status") != "pass":
        code = response.get("code")
        if not isinstance(code, str) or re.fullmatch(r"[a-z0-9_:-]{1,96}", code) is None:
            code = "host_rehearsal_failed"
        failure = _safe_native_failure(response.get("failure"))
        details = {"failure": failure} if failure is not None else None
        raise RehearsalError(code, details=details)
    if (
        response.get("reviewed_head_sha") != reviewed_head_sha
        or response.get("pair_manifest_sha256") != pair_manifest_sha256
        or response.get("candidate_image_id") != candidate_image_id
        or response.get("recovery_image_id") != recovery_image_id
        or response.get("same_disposable_volume") is not True
        or response.get("production_mutation") is not False
        or response.get("candidate_container_removed") is not True
        or response.get("recovery_container_removed") is not True
        or response.get("volume_removed") is not True
        or response.get("images_retained") is not True
        or response.get("recovery_process_isolation_verified") is not True
        or response.get("architecture") not in {"x86_64", "aarch64"}
    ):
        raise RehearsalError("host_response_invalid")
    resource_evidence = _validated_resource_evidence(response)
    return {
        "status": "pass",
        "rehearsal": "pr_bound_schema13_pair",
        "pull_request": pr_receipt,
        "reviewed_head_sha": reviewed_head_sha,
        "candidate_image_id": candidate_image_id,
        "candidate_source_context_sha256": candidate_source_context_sha256,
        "recovery_image_id": recovery_image_id,
        "recovery_source_context_sha256": recovery_source_context_sha256,
        "recovery_overlay_sha256": recovery_overlay_sha256,
        "pair_manifest_sha256": pair_manifest_sha256,
        "host_receipt": {
            **{
                key: value
                for key, value in response.items()
                if key
                in {
                    "receipt_id",
                    "architecture",
                    "started_at",
                    "finished_at",
                    "host_memavailable_before_kib",
                    "host_memavailable_after_kib",
                    "production_health_samples",
                    "migration_backup_verified",
                    "post_migration_write_preserved",
                    "ownership_isolation_verified",
                    "restore_guard_verified",
                    "recovery_process_isolation_verified",
                    "candidate_container_removed",
                    "recovery_container_removed",
                    "volume_removed",
                    "images_retained",
                    "native_model_id",
                    "mcp_workspace_summary_calls",
                    "native_search_source_count",
                    "simultaneous_two_owner_turns",
                }
            },
            **resource_evidence,
        },
    }


_SAFE_NATIVE_FAILURE_STAGES = {
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
    "result_unavailable",
}
_SAFE_NATIVE_FAILURE_CONDITIONS = {
    "turn_requests_not_concurrent",
    "search_not_approved",
    "active_search_checkpoint_missing",
    "native_search_sources_missing",
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
_SAFE_NATIVE_TURN_ERROR_CODES = {
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
_SAFE_NATIVE_TURN_FAILURE_STAGES = {
    "none",
    "before_model_session_event",
    "after_model_session_event",
    "unknown_terminal",
}


def _safe_native_failure(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or set(value) - {
        "failure_stage",
        "missing_conditions",
        "owners",
        "owner_evidence",
        "turn_requests_issued_concurrently",
        "search_approved",
        "active_search_scan_acknowledged",
        "same_supervised_app_reachable",
        "attached_candidate_acceptance",
        "cross_owner_conversation_status",
        "forged_internal_mcp_status",
        "builtin_search_source_count",
    }:
        return None
    stage = value.get("failure_stage")
    missing = value.get("missing_conditions")
    if (
        not isinstance(stage, str)
        or stage not in _SAFE_NATIVE_FAILURE_STAGES
        or not isinstance(missing, list)
        or len(missing) > len(_SAFE_NATIVE_FAILURE_CONDITIONS)
        or any(item not in _SAFE_NATIVE_FAILURE_CONDITIONS for item in missing)
    ):
        return None
    result: dict[str, object] = {
        "failure_stage": stage,
        "missing_conditions": missing,
    }
    owners = value.get("owners")
    if owners is not None:
        if not isinstance(owners, list) or len(owners) > 2:
            return None
        safe_owners: list[dict[str, object]] = []
        allowed_owner = {
            "terminal_status",
            "turn_error_code",
            "turn_failure_stage",
            "model_id_matches",
            "nonempty_answer",
            "workspace_summary_digest_matches",
            "selected_model_id_matches",
            "workspace_summary_receipt_count",
            "native_search_source_count",
        }
        for owner in owners:
            if not isinstance(owner, dict) or set(owner) - allowed_owner:
                return None
            if any(
                type(owner[key]) is not bool
                for key in set(owner)
                & {
                    "model_id_matches",
                    "nonempty_answer",
                    "workspace_summary_digest_matches",
                    "selected_model_id_matches",
                }
            ):
                return None
            if any(
                type(owner[key]) is not int or not 0 <= owner[key] <= 10_000
                for key in set(owner)
                & {"workspace_summary_receipt_count", "native_search_source_count"}
            ):
                return None
            status = owner.get("terminal_status")
            if status not in {
                "running",
                "completed",
                "cancelled",
                "failed",
                "timed_out",
                "unknown",
            }:
                return None
            error_code = owner.get("turn_error_code")
            if error_code is not None and error_code not in _SAFE_NATIVE_TURN_ERROR_CODES:
                return None
            failure_stage = owner.get("turn_failure_stage")
            if failure_stage is not None and failure_stage not in _SAFE_NATIVE_TURN_FAILURE_STAGES:
                return None
            safe_owners.append(dict(owner))
        result["owners"] = safe_owners
    evidence = value.get("owner_evidence")
    if evidence is not None:
        if not isinstance(evidence, list) or len(evidence) > 2:
            return None
        allowed_evidence = {
            "owner_index",
            "terminal_status",
            "turn_error_code",
            "turn_failure_stage",
            "model_id_matches",
            "answer_nonempty",
            "workspace_summary_digest_present",
            "workspace_summary_digest_matches",
            "selected_model_id_matches",
            "assistant_message_count",
            "assistant_text_bytes",
            "workspace_summary_receipt_count",
            "selected_model_event_count",
            "native_search_source_count",
            "conversation_event_count",
        }
        safe_evidence: list[dict[str, object]] = []
        for row in evidence:
            if not isinstance(row, dict) or set(row) - allowed_evidence:
                return None
            if type(row.get("owner_index")) is not int or row["owner_index"] not in {0, 1}:
                return None
            if row.get("terminal_status") not in {
                "not_started",
                "running",
                "completed",
                "cancelled",
                "failed",
                "timed_out",
                "unknown",
            }:
                return None
            error_code = row.get("turn_error_code")
            if error_code is not None and error_code not in _SAFE_NATIVE_TURN_ERROR_CODES:
                return None
            if row.get("turn_failure_stage") not in _SAFE_NATIVE_TURN_FAILURE_STAGES:
                return None
            for key in {
                "model_id_matches",
                "answer_nonempty",
                "workspace_summary_digest_present",
                "workspace_summary_digest_matches",
                "selected_model_id_matches",
            } & set(row):
                if type(row[key]) is not bool:
                    return None
            for key in {
                "assistant_message_count",
                "assistant_text_bytes",
                "workspace_summary_receipt_count",
                "selected_model_event_count",
                "native_search_source_count",
                "conversation_event_count",
            } & set(row):
                if type(row[key]) is not int or not 0 <= row[key] <= 1_000_000:
                    return None
            safe_evidence.append(dict(row))
        result["owner_evidence"] = safe_evidence
    for key in (
        "turn_requests_issued_concurrently",
        "search_approved",
        "active_search_scan_acknowledged",
        "same_supervised_app_reachable",
        "attached_candidate_acceptance",
    ):
        if key in value:
            if type(value[key]) is not bool:
                return None
            result[key] = value[key]
    for key in (
        "cross_owner_conversation_status",
        "forged_internal_mcp_status",
        "builtin_search_source_count",
    ):
        if key in value:
            if type(value[key]) is not int or not 0 <= value[key] <= 10_000:
                return None
            result[key] = value[key]
    return result


def _cleanup_staged_assets(config: RehearsalConfig, revision: str) -> None:
    """Ask only the installed sidecar helper to unlink this SHA's fixed staged filenames."""

    request = json.dumps(
        {"operation": "cleanup_assets", "payload": {"reviewed_head_sha": revision}},
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        _run_fixed([*_ssh_prefix(config), "sudo -n", HELPER_PATH], timeout=30, input_bytes=request)
    except RehearsalError:
        return
