#!/usr/bin/env python3
"""Rehearse schema-12 to schema-13 migration and the fixed disabled recovery image locally."""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import importlib.util
import json
import os
import platform
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

BASE_SHA = "da2764e8477698fa7d686be93a4711e35478e802"
DEPLOYED_BASELINE = {
    "source_revision": BASE_SHA,
    "image_id": "sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1",
    "release_archive_sha256": "669f840a3141b0fb95ae248b5ea0799733b9e5b5b81e224d4637571c24d8f640",
    "release_transport": "GitHub Release",
    "source": "root-provided observed deployment metadata",
}
MIGRATION_013_SHA256 = "41e7d0ef5e5267ab50a67666862bf01e4c6cfd8986b6096bd8b92deed70ff31b"
APP_UID = 10001
APP_GID = 10001
IMAGE_MEMORY_BYTES = 768 * 1024 * 1024
IMAGE_CPUS = 1
IMAGE_PIDS = 128
# Project only fields used for recovery-profile and source-label checks; never fetch Config.Env.
_CONTAINER_PROFILE_INSPECT_FORMAT = (
    '{"HostConfig":{'
    '"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},'
    '"NetworkMode":{{json .HostConfig.NetworkMode}},'
    '"Memory":{{json .HostConfig.Memory}},'
    '"NanoCpus":{{json .HostConfig.NanoCpus}},'
    '"PidsLimit":{{json .HostConfig.PidsLimit}},'
    '"CapDrop":{{json .HostConfig.CapDrop}},'
    '"CapAdd":{{json .HostConfig.CapAdd}},'
    '"SecurityOpt":{{json .HostConfig.SecurityOpt}}'
    '},"Config":{"Labels":{"org.opencontainers.image.revision":'
    '{{json (index .Config.Labels "org.opencontainers.image.revision")}}'
    "}}}"
)
_DEPLOYED_BASELINE_INSPECT_FORMAT = (
    "{{.Id}}|{{.Os}}|{{.Architecture}}|"
    '{{index .Config.Labels "org.opencontainers.image.revision"}}|{{json .RepoTags}}'
)
MAX_RELEASE_ARCHIVE_BYTES = 512 * 1024 * 1024
PRE_CONSENT_BACKUP = "schema13-pre-consent.spbackup"
CONTAINER_REMOVAL_TIMEOUT_SECONDS = 10
_APP_READINESS_TIMEOUT_SECONDS = 60
_CANDIDATE_VERIFICATION_STEPS = frozenset(
    {
        "assistant_owner_boundary",
        "assistant_owner_conversation_shape",
        "candidate_verification_internal",
        "readiness_status",
        "readiness_payload",
        "readiness_schema",
        "assistant_disabled_readiness",
        "local_login_status",
        "local_login_payload",
        "local_login_csrf_cookie",
        "owner_portfolio_write",
        "member_portfolio_write",
        "owner_portfolio_isolation",
        "owner_portfolio_read_status",
        "owner_portfolio_read_payload",
        "member_portfolio_isolation",
        "member_portfolio_read_status",
        "member_portfolio_read_payload",
        "cross_owner_delete_denied",
        "member_restore_denied",
        "restore_step_up_required",
        "schema_migration_history",
        "assistant_conversation_persisted",
        "candidate_consent_isolation",
    }
    | {
        f"{phase}_internal:{kind}"
        for phase in ("assistant_owner_boundary", "candidate_http")
        for kind in (
            "assertion",
            "http_error",
            "sqlite_error",
            "key_error",
            "type_error",
            "value_error",
            "runtime_error",
            "os_error",
            "unknown",
        )
    }
)
_CONTAINER_CLEANUP_ERRORS = {
    "the task-owned container identity is invalid": "container_identity_invalid",
    "the task-owned container is still running": "container_still_running",
    "the task-owned container state could not be verified": "container_state_unverified",
    "the task-owned container absence could not be verified": "container_absence_unverified",
    "the Docker container filter returned an unexpected identity": (
        "container_filter_identity_invalid"
    ),
    "the task-owned container auto-removal was not verified": "container_autoremove_timeout",
}
_GIT_EXECUTABLE = "/usr/bin/git"
_MIN_BUILD_FREE_BYTES = 4 * 1024**3
_STOP_BUILD_FREE_BYTES = 1 * 1024**3
_BUILD_TIMEOUT_SECONDS = 900
_BUILD_STOP_TIMEOUT_SECONDS = 5
_BUILD_TERM_GRACE_SECONDS = 1
_BUILD_KILL_GRACE_SECONDS = 2
_VERIFIER_IN_CONTAINER = "/run/assistant/rehearsal.py"
_EXCLUDED_NAMES = frozenset(
    {
        ".git",
        ".aws",
        ".ssh",
        ".npmrc",
        ".pypirc",
        ".next",
        ".dev-venv",
        ".venv",
        ".vscode",
        ".tools",
        ".codex",
        ".opencode",
        ".agents",
        ".terraform",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "backups",
        "data",
        "node_modules",
        "out",
        "venv",
        "burry_env",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        "test-results",
        "playwright-report",
        "__pycache__",
        ".netrc",
        "secrets",
        "credentials",
    }
)
_ROOT_ONLY_EXCLUDED_NAMES = frozenset(
    {
        "docs",
        "export",
        "exports",
        "infra",
        "scripts",
        "test-results",
        "tests",
        "tools",
    }
)
_NATIVE_PATCH_DIRECTORY = ("tools", "opencode-v2-security-patch")
_NATIVE_PATCH_FILES = frozenset(
    {
        "manifest.json",
        "apply_native_patch.py",
        "apply_oauth_patch.ts",
        "build_native.py",
        "google_mcp_patch.py",
        "oauth-handoff.ts",
        "oauth-handoff.test.ts",
        "oauth-broker.ts",
        "oauth-broker.test.ts",
        "oauth-callback.ts",
        "oauth-callback.test.ts",
        "webfetch-guard.ts",
        "webfetch-guard.test.ts",
        "webfetch-native.integration.test.ts",
    }
)


class RehearsalError(RuntimeError):
    """A bounded local rehearsal failure with no command output or secrets attached."""

    def __init__(self, message: str, *, cleanup_unverified: tuple[str, ...] = ()) -> None:
        allowed = {
            "container_identity_invalid",
            "container_stop",
            "container_still_running",
            "container_state_unverified",
            "container_absence_unverified",
            "container_filter_identity_invalid",
            "container_autoremove_timeout",
            "volume_identity_invalid",
            "volume_reference_unverified",
            "volume_removal",
            "volume_removal_unverified",
            "volume_retained_for_unverified_container",
            "local_image_tag_removal",
        }
        if any(item not in allowed for item in cleanup_unverified):
            raise ValueError("cleanup error code is not allowlisted")
        self.cleanup_unverified = cleanup_unverified
        super().__init__(message)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RehearsalError("source context contains a symbolic link")
        if not stat.S_ISREG(metadata.st_mode):
            if stat.S_ISDIR(metadata.st_mode):
                continue
            raise RehearsalError("source context contains a special file")
        if _excluded_relative_path(path.relative_to(root).parts):
            raise RehearsalError("source context contains an excluded filename")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        contents = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def _excluded_name(name: str) -> bool:
    """Recognize generated material and credential-bearing names without opening them."""

    lowered = name.casefold()
    return (
        name in _EXCLUDED_NAMES
        or lowered == ".env"
        or lowered.startswith(".env.")
        or lowered
        in {
            "credentials",
            "credential",
            "credentials.json",
            "auth.json",
            "secrets",
            "secret",
            "tokens",
            "token",
        }
        or any(
            fnmatch.fnmatchcase(lowered, pattern)
            for pattern in (
                "*.pem",
                "*.key",
                "*.p12",
                "*.pfx",
                "*.spbackup",
                "*.spbackup-*",
                "*.db",
                "*.db-*",
                "*.sqlite",
                "*.sqlite-*",
                "*.sqlite3",
                "*.sqlite3-*",
                "*.py[cod]",
                "*.tfstate",
                "*.tfstate.*",
                "*.tfvars",
                "*.tfvars.json",
                "*.tfplan",
                "*.plan",
                "*.egg-info",
                "*.tsbuildinfo",
                "*.md",
            )
        )
        or lowered.startswith(("credentials.", "credential.", "secrets.", "secret."))
        or any(
            marker in lowered
            for marker in (
                "access-token",
                "access_token",
                "api-token",
                "api_token",
                "auth-token",
                "auth_token",
            )
        )
        or lowered.startswith(("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"))
        or "private-key" in lowered
        or "private_key" in lowered
    )


def _is_native_patch_build_input(parts: tuple[str, ...]) -> bool:
    return (
        len(parts) == 3 and parts[:2] == _NATIVE_PATCH_DIRECTORY and parts[2] in _NATIVE_PATCH_FILES
    )


def _excluded_relative_path(parts: tuple[str, ...]) -> bool:
    """Apply Docker context exclusions to a relative path before opening or copying it."""

    # Fixed source inputs include the frontend tree, where `tools/` and `tests/` are
    # application routes and Docker build fixtures. These names are excluded only at repo root.
    native_patch_path = len(parts) == 2 and parts == _NATIVE_PATCH_DIRECTORY
    native_patch_path = native_patch_path or _is_native_patch_build_input(parts)
    if (
        parts
        and parts[0] in _ROOT_ONLY_EXCLUDED_NAMES
        and not (parts[0] == "tools" and native_patch_path)
    ):
        return True
    if parts and parts[0] == "tools" and not native_patch_path:
        return True
    if any(_excluded_name(part) for part in parts):
        return True
    return (len(parts) >= 2 and parts[:2] == ("static", "next")) or (
        len(parts) >= 4 and parts[:4] == ("src", "stock_probs", "static", "next")
    )


def _validate_copy_tree(root: Path, *, context_prefix: tuple[str, ...] = ()) -> None:
    """Reject source links/special files before copy operations can read their targets."""

    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise RehearsalError("a fixed source directory could not be inspected") from exc
        for entry in entries:
            relative = (*context_prefix, *entry.relative_to(root).parts)
            if _excluded_relative_path(relative):
                continue
            try:
                metadata = entry.lstat()
            except OSError as exc:
                raise RehearsalError("a fixed source entry could not be inspected") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise RehearsalError("source context contains a symbolic link")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(entry)
            elif not stat.S_ISREG(metadata.st_mode):
                raise RehearsalError("source context contains a special file")


def _copy_source_tree(source: Path, destination: Path) -> None:
    """Copy only fixed build inputs, excluding generated and credential-named files."""

    source_files = [
        source / name
        for name in ("Dockerfile", ".dockerignore", "pyproject.toml", "requirements.lock")
    ]
    source_directories = [
        source / name
        for name in (
            "frontend",
            "src/stock_probs",
            "tools/opencode-v2-security-patch",
        )
    ]
    for source_file in source_files:
        try:
            metadata = source_file.lstat()
        except OSError as exc:
            raise RehearsalError("required source build input is missing") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise RehearsalError("required source build input is missing")
    for source_dir in source_directories:
        context_prefix = source_dir.relative_to(source).parts
        try:
            metadata = source_dir.lstat()
        except OSError as exc:
            raise RehearsalError("required source directory is missing") from exc
        if not stat.S_ISDIR(metadata.st_mode):
            raise RehearsalError("required source directory is missing")
        _validate_copy_tree(source_dir, context_prefix=context_prefix)

    for source_file in source_files:
        name = source_file.name
        _copy_regular_no_follow(source_file, destination / name)

    for source_dir in source_directories:
        context_prefix = source_dir.relative_to(source).parts
        name = (
            source_dir.name
            if source_dir.parent == source
            else source_dir.relative_to(source).as_posix()
        )
        target_dir = destination / name

        def ignore(
            directory: str,
            names: list[str],
            *,
            source_root: Path = source_dir,
            source_prefix: tuple[str, ...] = context_prefix,
        ) -> set[str]:
            relative_directory = Path(directory).relative_to(source_root).parts
            return {
                child
                for child in names
                if _excluded_relative_path((*source_prefix, *relative_directory, child))
            }

        # Preserve links at copy time too: if the source changes between preflight and copy,
        # copytree cannot follow a newly substituted symlink before our destination check.
        shutil.copytree(source_dir, target_dir, ignore=ignore, symlinks=True)
        _validate_copy_tree(target_dir, context_prefix=context_prefix)


def _copy_regular_no_follow(source: Path, destination: Path) -> None:
    """Copy a named build input without following a swapped or pre-existing symlink."""

    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        raise RehearsalError("a fixed source file could not be opened safely") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RehearsalError("a fixed source file is not regular")
        with (
            os.fdopen(descriptor, "rb", closefd=False) as input_file,
            destination.open("xb") as output,
        ):
            shutil.copyfileobj(input_file, output)
    finally:
        os.close(descriptor)


def _fixed_base_source_paths(repository_root: Path) -> list[str]:
    """Enumerate safe regular blobs without opening tracked credential-named objects."""

    completed = subprocess.run(  # noqa: S603 - fixed Git executable and revision, no shell
        [_GIT_EXECUTABLE, "ls-tree", "-r", "-z", BASE_SHA],
        cwd=repository_root,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        raise RehearsalError("the fixed schema-12 Git tree could not be inspected")
    selected: list[str] = []
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode, object_type, _object_id = metadata.decode("ascii").split(" ", 2)
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RehearsalError("the fixed schema-12 Git tree has an invalid entry") from exc
        pure_path = PurePosixPath(path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise RehearsalError("the fixed schema-12 Git tree has an unsafe path")
        if _excluded_relative_path(pure_path.parts):
            continue
        fixed = path in {
            "Dockerfile",
            ".dockerignore",
            "pyproject.toml",
            "requirements.lock",
        } or any(path.startswith(prefix + "/") for prefix in ("frontend", "src/stock_probs"))
        fixed = fixed or _is_native_patch_build_input(pure_path.parts)
        if not fixed:
            continue
        if mode not in {"100644", "100755"} or object_type != "blob":
            raise RehearsalError("the fixed schema-12 source contains a non-regular build input")
        selected.append(path)
    required = {"Dockerfile", ".dockerignore", "pyproject.toml", "requirements.lock"}
    if not required.issubset(selected):
        raise RehearsalError("the fixed schema-12 source archive is incomplete")
    return sorted(selected)


def _extract_base_archive(repository_root: Path, destination: Path) -> dict[str, str]:
    """Extract safe fixed inputs from the deployed schema-12 commit archive."""

    archive_path = destination.parent / "schema12-base.tar"
    source_paths = _fixed_base_source_paths(repository_root)
    command = [
        _GIT_EXECUTABLE,
        "archive",
        "--format=tar",
        BASE_SHA,
        "--",
        *(f":(literal){path}" for path in source_paths),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed Git archive with validated literal paths
        command,
        cwd=repository_root,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        raise RehearsalError("the fixed schema-12 source archive could not be read")
    archive_sha256 = _sha256(completed.stdout)
    archive_path.write_bytes(completed.stdout)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise RehearsalError("the base source archive contains an unsupported entry")
            if _excluded_relative_path(path.parts):
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RehearsalError("the base source archive is incomplete")
            with extracted, target.open("xb") as output:
                shutil.copyfileobj(extracted, output)
            target.chmod(0o600)
    archive_path.unlink(missing_ok=True)
    _validate_copy_tree(destination)
    return {
        "revision": BASE_SHA,
        "selected_path_list_sha256": _sha256(_canonical_json(source_paths)),
        "archive_sha256": archive_sha256,
        "source_context_sha256": _tree_sha256(destination),
    }


def _replace_once(path: Path, old: str, new: str) -> None:
    value = path.read_text(encoding="utf-8")
    if value.count(old) != 1:
        raise RehearsalError("a pinned forward-compatibility overlay anchor changed")
    path.write_text(value.replace(old, new, 1), encoding="utf-8")


def _apply_recovery_overlay(repository_root: Path, context: Path) -> dict[str, object]:
    """Apply the fixed schema-13 migration, readiness, restore, and UID-drop overlay."""

    repository_path = context / "src/stock_probs/repository.py"
    _replace_once(repository_path, "SCHEMA_VERSION = 12", "SCHEMA_VERSION = 13")
    _replace_once(
        repository_path,
        '    12: "03bf4834c594e7e7704484e520202ff14a459d339397aefec2916b09a4fccd5c",\n',
        '    12: "03bf4834c594e7e7704484e520202ff14a459d339397aefec2916b09a4fccd5c",\n'
        f'    13: "{MIGRATION_013_SHA256}",\n',
    )

    migration_source = (
        repository_root / "src/stock_probs/migrations/013_assistant_conversations.sql"
    )
    if not migration_source.is_file() or migration_source.is_symlink():
        raise RehearsalError("the reviewed schema-13 migration is missing")
    migration_bytes = migration_source.read_bytes()
    if _sha256(migration_bytes) != MIGRATION_013_SHA256:
        raise RehearsalError("the schema-13 migration checksum does not match the reviewed value")
    migration_target = context / "src/stock_probs/migrations/013_assistant_conversations.sql"
    migration_target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    migration_target.write_bytes(migration_bytes)

    api_path = context / "src/stock_probs/api.py"
    _replace_once(
        api_path,
        """class ReadinessResponse(ApiResponse):
    status: Literal[\"ready\"]
    schema_version: int
    provider: str
""",
        """class AssistantReadinessResponse(ApiResponse):
    enabled: bool
    status: Literal[\"disabled\"]


class ReadinessResponse(ApiResponse):
    status: Literal[\"ready\"]
    schema_version: int
    provider: str
    assistant: AssistantReadinessResponse
""",
    )
    _replace_once(
        api_path,
        '        return {"status": "ready", "schema_version": SCHEMA_VERSION, '
        '"provider": config.provider}\n',
        """        return {
            "status": "ready",
            "schema_version": SCHEMA_VERSION,
            "provider": config.provider,
            "assistant": {"enabled": False, "status": "disabled"},
        }
""",
    )

    _replace_once(
        api_path,
        """    (
        "totp_attempt_throttles",
        (
            "user_id",
            "window_started_at",
            "attempt_count",
            "last_attempt_at",
            "locked_until",
        ),
    ),
)""",
        """    (
        "totp_attempt_throttles",
        (
            "user_id",
            "window_started_at",
            "attempt_count",
            "last_attempt_at",
            "locked_until",
        ),
    ),
    (
        "assistant_model_consents",
        (
            "id",
            "user_id",
            "model_id",
            "policy_version",
            "accepted_terms",
            "data_collection_opt_in",
            "recorded_at",
        ),
    ),
)""",
    )
    _replace_once(
        api_path,
        """            for table, columns in _RESTORE_SECURITY_TABLES:
                quoted_columns = ", ".join(columns)
""",
        """            for table, columns in _RESTORE_SECURITY_TABLES:
                if table == "assistant_model_consents":
                    exists = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (table,),
                    ).fetchone()
                    if exists is None:
                        state.append((table, []))
                        continue
                quoted_columns = ", ".join(columns)
""",
    )

    supervisor = context / "src/stock_probs/recovery_supervisor.py"
    supervisor.write_text(
        '''"""Fixed app-only PID 1 for schema-13 recovery under production Compose."""

from __future__ import annotations

import ctypes
import os

APP_UID = 10001
APP_GID = 10001
APP_COMMAND = (
    "/usr/local/bin/stock-probs",
    "serve",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--allow-non-loopback",
)


def main() -> None:
    """Drop the two Compose startup capabilities and run only the local FastAPI process."""

    if os.geteuid() != 0:
        raise SystemExit("recovery supervisor requires the fixed root Compose identity")
    os.setgroups([])
    os.setgid(APP_GID)
    os.setuid(APP_UID)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "no-new-privileges could not be set")
    environment = dict(os.environ)
    os.execve(APP_COMMAND[0], list(APP_COMMAND), environment)


if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )
    _replace_once(
        context / "Dockerfile",
        'CMD ["stock-probs", "serve", "--host", "0.0.0.0", "--port", "8000", '
        '"--allow-non-loopback"]',
        'ENTRYPOINT ["python", "-m", "stock_probs.recovery_supervisor"]\n'
        'CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--allow-non-loopback"]',
    )

    overlay_paths = (
        "Dockerfile",
        "src/stock_probs/api.py",
        "src/stock_probs/migrations/013_assistant_conversations.sql",
        "src/stock_probs/recovery_supervisor.py",
        "src/stock_probs/repository.py",
    )
    overlay_files = {name: _sha256((context / name).read_bytes()) for name in overlay_paths}
    overlay_identity = {
        "base_revision": BASE_SHA,
        "schema_version": 13,
        "files": overlay_files,
    }
    return {**overlay_identity, "overlay_sha256": _sha256(_canonical_json(overlay_identity))}


def _candidate_context(repository_root: Path, destination: Path) -> str:
    destination.mkdir(mode=0o700, parents=True)
    _copy_source_tree(repository_root, destination)
    return _tree_sha256(destination)


def _docker_environment(config_dir: Path) -> dict[str, str]:
    """Run Docker with an empty task-local config instead of reading user auth material."""

    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return {"PATH": os.defpath, "HOME": str(config_dir), "DOCKER_CONFIG": str(config_dir)}


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: int = 120,
    check: bool = True,
    diagnostic_stage: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # noqa: S603 - fixed Docker command vectors, no shell parsing
            command,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stage = diagnostic_stage or _command_stage(command)
        raise RehearsalError(f"local_command_timeout:{stage}:after_{timeout}s") from exc
    except OSError as exc:
        stage = diagnostic_stage or _command_stage(command)
        raise RehearsalError(f"local_command_unavailable:{stage}:os_error") from exc
    if check and result.returncode:
        stage = diagnostic_stage or _command_stage(command)
        raise RehearsalError(f"local_command_failed:{stage}:exit_{result.returncode}")
    return result


def _command_stage(command: list[str]) -> str:
    """Name only the fixed executable/action when reporting a failed subprocess."""

    if not command:
        return "unknown"
    executable = Path(command[0]).name.casefold()
    if executable == "docker" and len(command) > 1:
        action = command[1].casefold()
        if action in {
            "build",
            "create",
            "exec",
            "image",
            "inspect",
            "load",
            "run",
            "save",
            "start",
            "stop",
            "volume",
        }:
            if action == "image" and len(command) > 2:
                nested = command[2].casefold()
                if nested in {"inspect", "load", "rm", "save", "tag"}:
                    return f"docker_image_{nested}"
            if action == "volume" and len(command) > 2:
                nested = command[2].casefold()
                if nested in {"create", "inspect", "rm"}:
                    return f"docker_volume_{nested}"
            return f"docker_{action}"
    if executable in {"git", "usr/bin/git"}:
        return f"git_{command[1].casefold()}" if len(command) > 1 else "git"
    return executable if re.fullmatch(r"[a-z0-9_-]{1,32}", executable) else "fixed_command"


def _stop_git_status_process(process: subprocess.Popen[bytes]) -> bool:
    """Stop and reap the fixed Git status child without signaling the parent group."""

    try:
        process.terminate()
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.wait(timeout=1)
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        process.wait(timeout=_BUILD_STOP_TIMEOUT_SECONDS)
        return True
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=_BUILD_STOP_TIMEOUT_SECONDS)
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False


def _process_group_exists(process_group_id: int) -> bool:
    if process_group_id <= 1:
        return True
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _signal_process_group(process_group_id: int, signal_number: int) -> bool:
    if process_group_id <= 1:
        return False
    try:
        os.killpg(process_group_id, signal_number)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True


def _wait_process_group_absent(process_group_id: int, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while _process_group_exists(process_group_id):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _stop_build_process_group(process: subprocess.Popen[bytes], process_group_id: int) -> bool:
    """Terminate, reap, and verify absence of one owned new-session build group."""

    if process_group_id <= 1 or process_group_id != process.pid:
        return False
    if _process_group_exists(process_group_id) and not _signal_process_group(
        process_group_id, signal.SIGTERM
    ):
        return False
    leader_reaped = True
    try:
        process.wait(timeout=_BUILD_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        leader_reaped = False
    except OSError:
        return False
    if not _wait_process_group_absent(
        process_group_id, _BUILD_TERM_GRACE_SECONDS
    ) and not _signal_process_group(process_group_id, signal.SIGKILL):
        return False
    if not leader_reaped:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except OSError:
            return False
        try:
            process.wait(timeout=_BUILD_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            return False
    return _wait_process_group_absent(process_group_id, _BUILD_KILL_GRACE_SECONDS)


def _docker_data_root(env: dict[str, str]) -> Path:
    result = _run(
        ["docker", "info", "--format", "{{.DockerRootDir}}"],
        env=env,
        timeout=15,
        diagnostic_stage="docker_data_root",
    )
    raw_path = result.stdout.strip()
    if (
        not raw_path
        or len(raw_path) > 4096
        or "\n" in raw_path
        or "\r" in raw_path
        or not Path(raw_path).is_absolute()
    ):
        raise RehearsalError("the Docker data-root could not be verified")
    try:
        resolved = Path(raw_path).resolve(strict=True)
    except OSError as exc:
        raise RehearsalError("the Docker data-root could not be verified") from exc
    if not resolved.is_dir():
        raise RehearsalError("the Docker data-root could not be verified")
    return resolved


def _build_free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError as exc:
        raise RehearsalError("a required image-build filesystem could not be checked") from exc


def _check_build_space(paths: tuple[Path, ...], minimum: int) -> bool:
    """Check every distinct build filesystem without exposing local path details."""

    devices: set[int] = set()
    for path in paths:
        try:
            info = path.stat()
        except OSError as exc:
            raise RehearsalError("a required image-build filesystem could not be checked") from exc
        if info.st_dev in devices:
            continue
        devices.add(info.st_dev)
        if _build_free_bytes(path) < minimum:
            return False
    return True


def _build_image(
    context: Path,
    tag: str,
    revision_label: str,
    env: dict[str, str],
    *,
    build_disk_paths: tuple[Path, ...] = (),
) -> str:
    """Build a fixed amd64 image with bounded output, time, and disk usage."""

    iidfile = context.parent / f"{tag.replace(':', '_')}.iid"
    command = [
        "docker",
        "build",
        "--pull=false",
        "--platform=linux/amd64",
        "--build-arg",
        f"REVISION={revision_label}",
        "--iidfile",
        str(iidfile),
        "--tag",
        tag,
        str(context),
    ]
    docker_root = _docker_data_root(env)
    paths = (docker_root, context, context.parent, Path(tempfile.gettempdir()), *build_disk_paths)
    if not _check_build_space(paths, _MIN_BUILD_FREE_BYTES):
        raise RehearsalError("image build requires at least 4 GiB free on every build filesystem")
    started = time.monotonic()
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed Docker command vector, no shell
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise RehearsalError("local_build_unavailable:docker_build:os_error") from exc
    process_group_id = process.pid
    try:
        while True:
            return_code = process.poll()
            if return_code is not None:
                group_remained = _process_group_exists(process_group_id)
                if not _stop_build_process_group(process, process_group_id):
                    raise RehearsalError(
                        "local_build_process_group_unverified; generated image tag retained"
                    )
                if group_remained:
                    raise RehearsalError(
                        "Docker build left child processes; group stopped and image tag retained"
                    )
                break
            if time.monotonic() - started >= _BUILD_TIMEOUT_SECONDS:
                raise RehearsalError("local_build_timeout:docker_build:after_900s")
            if not _check_build_space(paths, _STOP_BUILD_FREE_BYTES):
                raise RehearsalError(
                    "image build stopped below 1 GiB free space; generated image tag retained"
                )
            time.sleep(0.5)
    except BaseException as exc:
        if not _stop_build_process_group(process, process_group_id):
            raise RehearsalError(
                "local_build_process_group_unverified; generated image tag retained"
            ) from exc
        raise
    if return_code != 0:
        raise RehearsalError(
            f"local_build_failed:docker_build:exit_{return_code}; generated image tag retained"
        )
    try:
        image_id = iidfile.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RehearsalError(
            "Docker build identity is unavailable; generated image tag retained"
        ) from exc
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise RehearsalError(
            "Docker did not return an immutable image ID; generated image tag retained"
        )
    inspected = _run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag], env=env, timeout=30
    ).stdout.strip()
    if inspected != image_id:
        raise RehearsalError("built image identity did not match; generated image tag retained")
    return image_id


def _image_platform(image_id: str, env: dict[str, str]) -> str:
    value = _run(
        ["docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image_id],
        env=env,
        timeout=30,
    ).stdout.strip()
    if value != "linux/amd64":
        raise RehearsalError("release image platform is not linux/amd64")
    return value


def _verify_deployed_baseline_image(env: dict[str, str]) -> dict[str, object]:
    """Verify the one fixed deployed baseline using only its required projected fields."""

    image_id = str(DEPLOYED_BASELINE["image_id"])
    result = _run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            _DEPLOYED_BASELINE_INSPECT_FORMAT,
            image_id,
        ],
        env=env,
        timeout=15,
        check=False,
    )
    fields = result.stdout.rstrip("\n").split("|", 4)
    if result.returncode or len(fields) != 5:
        raise RehearsalError("the fixed deployed schema-12 image is unavailable")
    try:
        tags: object = json.loads(fields[4])
    except json.JSONDecodeError as exc:
        raise RehearsalError("the fixed deployed schema-12 image metadata is invalid") from exc
    if (
        fields[0] != image_id
        or fields[1:4] != ["linux", "amd64", str(DEPLOYED_BASELINE["source_revision"])]
        or not isinstance(tags, list)
        or not tags
        or any(
            not isinstance(tag, str) or not tag.strip() or tag == "<none>:<none>" for tag in tags
        )
    ):
        raise RehearsalError("the fixed deployed schema-12 image metadata did not match")
    return {
        "id": image_id,
        "architecture": "linux/amd64",
        "revision_label": str(DEPLOYED_BASELINE["source_revision"]),
        "retained_tags": tags,
    }


def _prepare_schema12_base_image(
    context: Path,
    tag: str,
    revision_label: str,
    env: dict[str, str],
    *,
    use_deployed_baseline_image: bool,
) -> tuple[str, str, dict[str, object]]:
    """Select the fixed deployed image or build the verified base source context locally."""

    if use_deployed_baseline_image:
        verified = _verify_deployed_baseline_image(env)
        image_id = str(verified["id"])
        return (
            image_id,
            image_id,
            {
                "mode": "reused_exact_deployed_image",
                "verified_projected_metadata": verified,
                "relationship_to_deployed_image": "exact immutable deployed image ID reused",
            },
        )
    image_id = _build_image(context, tag, revision_label, env)
    return (
        image_id,
        tag,
        {
            "mode": "locally_rebuilt_from_verified_archive",
            "relationship_to_deployed_image": (
                "rebuilt from exact source; image ID is not asserted equal"
            ),
        },
    )


def _remove_generated_image_tag(tag: str, env: dict[str, str]) -> bool:
    """Remove only a task-generated tag without allowing Docker to prune its ancestors."""

    removed = _run(
        ["docker", "image", "rm", "--no-prune", tag],
        env=env,
        timeout=30,
        check=False,
    )
    remains = _run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
        env=env,
        timeout=10,
        check=False,
    )
    return removed.returncode == 0 and remains.returncode != 0


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_RELEASE_ARCHIVE_BYTES:
                raise RehearsalError("a release image archive exceeded the fixed size limit")
            digest.update(chunk)
    if not size:
        raise RehearsalError("a release image archive is empty")
    return digest.hexdigest(), size


def _save_image_archive(image_id: str, path: Path, env: dict[str, str]) -> tuple[str, int]:
    """Save one immutable image ID into a deterministic, private gzip archive."""

    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise RehearsalError("release image ID is invalid")
    if path.exists() or path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise RehearsalError("release artifact destination is not a fresh private directory")
    raw_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tar"
    try:
        _run(
            ["docker", "save", "--output", str(raw_path), image_id],
            env=env,
            timeout=600,
        )
        if raw_path.is_symlink() or not raw_path.is_file():
            raise RehearsalError("Docker did not create a regular image archive")
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with (
                os.fdopen(descriptor, "wb", closefd=False) as target,
                raw_path.open("rb") as source,
                gzip.GzipFile(
                    filename="", mode="wb", compresslevel=9, fileobj=target, mtime=0
                ) as compressed,
            ):
                shutil.copyfileobj(source, compressed, length=1024 * 1024)
                compressed.close()
                target.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return _file_sha256(path)
    except RehearsalError:
        path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise RehearsalError("a bounded release image archive could not be written") from exc
    finally:
        raw_path.unlink(missing_ok=True)


def _run_cli(
    image: str,
    volume: str,
    data_env: list[str],
    args: list[str],
    env: dict[str, str],
    *,
    expected_rejection: str | None = None,
) -> str:
    command = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--user",
        f"{APP_UID}:{APP_GID}",
        "--memory",
        f"{IMAGE_MEMORY_BYTES}",
        "--cpus",
        str(IMAGE_CPUS),
        "--pids-limit",
        str(IMAGE_PIDS),
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - app-private tmpfs
        "--volume",
        f"{volume}:/data",
        *data_env,
        "--entrypoint",
        "stock-probs",
        image,
        *args,
    ]
    stage_prefix = (
        "schema12"
        if ":schema12-base-" in image
        else "recovery"
        if ":schema13-recovery-" in image
        else "candidate"
    )
    stage_suffix = (
        args[0] if args and args[0] in {"backup", "migrate", "restore", "verify"} else "operation"
    )
    result = _run(
        command,
        env=env,
        timeout=180,
        check=expected_rejection is None,
        diagnostic_stage=f"{stage_prefix}_cli_{stage_suffix}",
    )
    if expected_rejection is not None:
        if result.returncode != 2 or expected_rejection not in result.stderr:
            raise RehearsalError("the CLI did not safely refuse the incompatible restore")
        return result.stdout
    return result.stdout


def _run_historical_backup_verification(
    image: str,
    volume: str,
    verifier_path: Path,
    backup_name: str,
    env: dict[str, str],
) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.spbackup", backup_name) is None:
        raise RehearsalError("historical backup identity is invalid")
    command = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user",
        f"{APP_UID}:{APP_GID}",
        "--memory",
        str(IMAGE_MEMORY_BYTES),
        "--cpus",
        str(IMAGE_CPUS),
        "--pids-limit",
        str(IMAGE_PIDS),
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - app-private tmpfs
        "--tmpfs",
        "/run/assistant:rw,nosuid,nodev,noexec,size=16m,mode=0711",
        "--volume",
        f"{volume}:/data",
        "--mount",
        f"type=bind,src={verifier_path},dst={_VERIFIER_IN_CONTAINER},readonly",
        "--env=STOCK_PROBS_DATA_DIR=/data",
        "--entrypoint",
        "python",
        image,
        _VERIFIER_IN_CONTAINER,
        "verify-historical-backup",
        backup_name,
    ]
    return _run(command, env=env, timeout=60, diagnostic_stage="historical_backup_verify").stdout


def _schema_check(
    image: str, volume: str, data_env: list[str], env: dict[str, str]
) -> dict[str, object]:
    script = (
        "import json,sqlite3; "
        "c=sqlite3.connect('/data/stock_probs.sqlite3'); "
        "v=[r[0] for r in c.execute('select version from schema_migrations order by version')]; "
        "print(json.dumps({'versions':v,'max':max(v) if v else 0}))"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--user",
        f"{APP_UID}:{APP_GID}",
        "--memory",
        str(IMAGE_MEMORY_BYTES),
        "--cpus",
        str(IMAGE_CPUS),
        "--pids-limit",
        str(IMAGE_PIDS),
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - app-private tmpfs
        "--volume",
        f"{volume}:/data",
        *data_env,
        "--entrypoint",
        "python",
        image,
        "-c",
        script,
    ]
    return json.loads(_run(command, env=env, timeout=30).stdout)


def _verify_historical_backup_without_promotion(
    manager: object, backup_name: str, *, expected_schema: int
) -> dict[str, object]:
    """Authenticate an old artifact offline without relaxing active-schema restore rules."""

    from stock_probs.backup import BackupManager, _check_deadline, _run_with_deadline

    if not isinstance(manager, BackupManager) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.spbackup", backup_name
    ):
        raise RehearsalError("historical backup identity is invalid")

    def inspect() -> tuple[dict[str, object], Path, object]:
        with manager.repository.exclusive():
            result = manager._verify_unlocked(backup_name, require_active_schema=False)
            try:
                _check_deadline()
            except Exception:
                result[2].cleanup()
                raise
            return result

    manifest, _database, staging = _run_with_deadline(inspect)
    try:
        if manifest.get("schema_version") != expected_schema:
            raise RehearsalError("historical backup schema mismatch")
        return {
            "verified": True,
            "schema_version": manifest["schema_version"],
            "integrity_verified": True,
        }
    finally:
        staging.cleanup()


def _verification_source() -> str:
    return """from __future__ import annotations

import json
import sys
import http.client
from contextlib import suppress

BASE_URL = "http://127.0.0.1:8000"


def _probe_readiness() -> None:
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=2.0)
    try:
        connection.request("GET", "/api/v1/readiness", headers={"Host": "localhost"})
        response = connection.getresponse()
        body = response.read(16_385)
        assert response.status == 200 and len(body) <= 16_384
        value = json.loads(body)
        assert isinstance(value, dict)
        print(json.dumps(value, sort_keys=True))
    finally:
        connection.close()


# The readiness subprocess runs under a one-CPU cap beside the starting app. Exit before
# loading the scientific/application dependency graph; retain its fixed two-second HTTP bound.
if len(sys.argv) > 1 and sys.argv[1] == "probe":
    _probe_readiness()
    raise SystemExit(0)

import hashlib
import os
import sqlite3
from datetime import UTC, datetime

import httpx
from stock_probs.api import create_app
from stock_probs.api import _restore_security_digest
from stock_probs.auth import CSRF_COOKIE_NAME
from stock_probs.backup import BackupManager, _check_deadline, _run_with_deadline
from stock_probs.config import Settings
from stock_probs.repository import Repository

ADMIN_NAME = "rehearsal-admin"
ADMIN_PASSWORD = "schema13-local-rehearsal-admin-password"
MEMBER_NAME = "rehearsal-member"
MEMBER_PASSWORD = "schema13-local-rehearsal-member-password"


class VerificationFailure(Exception):
    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


def _internal_failure(phase: str, error: BaseException) -> str:
    # Keep unexpected generated-verifier diagnostics to fixed phases and closed class labels.
    kinds = {
        AssertionError: "assertion",
        httpx.HTTPError: "http_error",
        sqlite3.Error: "sqlite_error",
        KeyError: "key_error",
        TypeError: "type_error",
        ValueError: "value_error",
        RuntimeError: "runtime_error",
        OSError: "os_error",
    }
    kind = next(
        (label for exception_type, label in kinds.items() if type(error) is exception_type),
        "unknown",
    )
    return f"{phase}_internal:{kind}"


def require(condition: bool, step: str) -> None:
    if not condition:
        raise VerificationFailure(step)


def _request_safely(operation, step: str):
    # Keep fixed local HTTP failures in a closed phase without response details.

    try:
        return operation()
    except httpx.HTTPError:
        raise VerificationFailure(step) from None


def _response_payload(response, *, status: int, step: str) -> dict[str, object]:
    # Check status and object shape before any fixed-field indexing.

    require(response.status_code == status, step)
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        raise VerificationFailure(step) from None
    require(isinstance(payload, dict), step)
    return payload


def _portfolio_items(response, step: str) -> list[dict[str, object]]:
    payload = _response_payload(response, status=200, step=step)
    items = payload.get("items")
    require(
        isinstance(items, list)
        and all(
            isinstance(item, dict) and isinstance(item.get("symbol"), str) for item in items
        ),
        step,
    )
    return items


def repo() -> Repository:
    return Repository(Settings.from_env().database_path)


def _verify_historical_backup(name: str, expected_schema: int) -> dict[str, object]:
    repository = repo()
    manager = BackupManager(repository, Settings.from_env().backup_dir)

    def inspect():
        with repository.exclusive():
            result = manager._verify_unlocked(name, require_active_schema=False)
            try:
                _check_deadline()
            except Exception:
                result[2].cleanup()
                raise
            return result

    manifest, _database, staging = _run_with_deadline(inspect)
    try:
        assert manifest["schema_version"] == expected_schema
        return {
            "verified": True,
            "schema_version": manifest["schema_version"],
            "integrity_verified": True,
        }
    finally:
        staging.cleanup()


def _login(client: httpx.Client, username: str, password: str) -> str:
    response = _request_safely(
        lambda: client.post(
            "/api/v1/auth/local/login", json={"username": username, "password": password}
        ),
        "local_login_status",
    )
    payload = _response_payload(response, status=200, step="local_login_payload")
    token = payload.get("csrf_token")
    require(isinstance(token, str) and 16 <= len(token) <= 256, "local_login_payload")
    require(client.cookies.get(CSRF_COOKIE_NAME) == token, "local_login_csrf_cookie")
    return token


def _sign_in_pair() -> tuple[httpx.Client, httpx.Client, str, str]:
    owner = httpx.Client(base_url=BASE_URL, timeout=3.0)
    member = httpx.Client(base_url=BASE_URL, timeout=3.0)
    try:
        owner_csrf = _login(owner, ADMIN_NAME, ADMIN_PASSWORD)
        member_csrf = _login(member, MEMBER_NAME, MEMBER_PASSWORD)
        return owner, member, owner_csrf, member_csrf
    except Exception:
        owner.close()
        member.close()
        raise


def _verify_http(stage: str, pre_consent_name: str | None) -> dict[str, object]:
    with httpx.Client(base_url=BASE_URL, timeout=3.0) as probe:
        readiness = _request_safely(
            lambda: probe.get("/api/v1/readiness"), "readiness_status"
        )
        readiness_body = _response_payload(readiness, status=200, step="readiness_payload")
        require(readiness_body.get("schema_version") == 13, "readiness_schema")
        require(
            readiness_body.get("assistant") == {"enabled": False, "status": "disabled"},
            "assistant_disabled_readiness",
        )

    owner, member, owner_csrf, member_csrf = _sign_in_pair()
    try:
        if stage == "candidate":
            owner_add = _request_safely(
                lambda: owner.post(
                    "/api/v1/lists",
                    json={
                        "kind": "portfolio",
                        "item": {"symbol": "SPY", "asset_type": "etf", "quantity": 2.5},
                    },
                    headers={"x-csrf-token": owner_csrf},
                ),
                "owner_portfolio_write",
            )
            member_add = _request_safely(
                lambda: member.post(
                    "/api/v1/lists",
                    json={
                        "kind": "portfolio",
                        "item": {"symbol": "ACDC", "asset_type": "stock", "quantity": 3.0},
                    },
                    headers={"x-csrf-token": member_csrf},
                ),
                "member_portfolio_write",
            )
            require(owner_add.status_code == 201, "owner_portfolio_write")
            require(member_add.status_code == 201, "member_portfolio_write")
        owner_response = _request_safely(
            lambda: owner.get("/api/v1/lists", params={"kind": "portfolio"}),
            "owner_portfolio_read_status",
        )
        member_response = _request_safely(
            lambda: member.get("/api/v1/lists", params={"kind": "portfolio"}),
            "member_portfolio_read_status",
        )
        owner_items = _portfolio_items(owner_response, "owner_portfolio_read_payload")
        member_items = _portfolio_items(member_response, "member_portfolio_read_payload")
        require([item["symbol"] for item in owner_items] == ["SPY"], "owner_portfolio_isolation")
        require(
            [item["symbol"] for item in member_items] == ["ACDC"],
            "member_portfolio_isolation",
        )
        cross_owner_delete = _request_safely(
            lambda: owner.delete(
                "/api/v1/lists",
                params={"kind": "portfolio", "symbol": "ACDC"},
                headers={"x-csrf-token": owner_csrf},
            ),
            "cross_owner_delete_denied",
        )
        require(cross_owner_delete.status_code == 404, "cross_owner_delete_denied")

        member_restore = _request_safely(
            lambda: member.post(
                "/api/v1/operations/restores",
                json={"name": "pre-migration-v12-to-v13-placeholder.spbackup", "promote": True},
                headers={"x-csrf-token": member_csrf},
            ),
            "member_restore_denied",
        )
        require(member_restore.status_code == 403, "member_restore_denied")
        admin_restore_without_step_up = _request_safely(
            lambda: owner.post(
                "/api/v1/operations/restores",
                json={"name": "pre-migration-v12-to-v13-placeholder.spbackup", "promote": True},
                headers={"x-csrf-token": owner_csrf},
            ),
            "restore_step_up_required",
        )
        require(admin_restore_without_step_up.status_code == 403, "restore_step_up_required")
    finally:
        owner.close()
        member.close()

    repository = repo()
    connection = sqlite3.connect(repository.database_path)
    try:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        require(versions == list(range(1, 14)), "schema_migration_history")
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("assistant_conversations", "assistant_model_consents")
        }
        require(counts["assistant_conversations"] == 1, "assistant_conversation_persisted")
        if stage == "recovery":
            require(counts["assistant_model_consents"] == 1, "recovery_consent_persisted")
        else:
            require(counts["assistant_model_consents"] == 0, "candidate_consent_isolation")
    finally:
        connection.close()
    return {"stage": stage, "assistant_tables": counts, "schema_versions": versions}


def _write_consent() -> dict[str, object]:
    repository = repo()
    account = repository.auth_get_user_by_username(ADMIN_NAME)
    assert account is not None
    from stock_probs.assistant.storage import AssistantStorage

    consent = AssistantStorage(repository).create_consent(
        int(account["id"]),
        model_id="synthetic-provider/recovery-test",
        policy_version="recovery-security-v1",
        accepted_terms=True,
        data_collection_opt_in=False,
        recorded_at=datetime.now(UTC),
    )
    return {"consent_recorded": bool(consent["accepted_terms"])}


def _check_assistant_owner_boundary() -> dict[str, object]:
    repository = repo()
    owner = repository.auth_get_user_by_username(ADMIN_NAME)
    member = repository.auth_get_user_by_username(MEMBER_NAME)
    assert owner is not None and member is not None
    from stock_probs.assistant.storage import AssistantStorage, AssistantStorageNotFound

    storage = AssistantStorage(repository)
    conversation = storage.create_conversation(
        int(owner["id"]),
        title="Synthetic recovery record",
        context={"scope": "local-test"},
        context_version=hashlib.sha256(b"schema13-recovery-context").hexdigest(),
        created_at=datetime.now(UTC),
    )
    public_conversation = conversation.get("conversation")
    require(
        isinstance(public_conversation, dict)
        and isinstance(public_conversation.get("id"), str),
        "assistant_owner_conversation_shape",
    )
    try:
        storage.get_conversation(int(member["id"]), str(public_conversation["id"]))
    except AssistantStorageNotFound:
        return {"assistant_owner_isolation": True}
    raise AssertionError("another user read the synthetic assistant conversation")


def main() -> None:
    stage = sys.argv[1]
    old_backup_name = sys.argv[2] if len(sys.argv) > 2 else None
    pre_consent_name = sys.argv[3] if len(sys.argv) > 3 else None
    if stage == "schema":
        repository = repo()
        repository.migrate()
        connection = sqlite3.connect(repository.database_path)
        try:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        finally:
            connection.close()
        print(json.dumps({"schema_versions": versions, "schema_version": max(versions)}))
        return
    if stage == "verify-historical-backup":
        assert old_backup_name is not None
        print(json.dumps(_verify_historical_backup(old_backup_name, 12), sort_keys=True))
        return
    if stage == "candidate":
        try:
            result = _check_assistant_owner_boundary()
        except VerificationFailure as exc:
            print(json.dumps({"verification_failure": exc.step}, sort_keys=True))
            raise SystemExit(1) from None
        except AssertionError:
            print(json.dumps({"verification_failure": "assistant_owner_boundary"}))
            raise SystemExit(1) from None
        except Exception as exc:
            print(
                json.dumps(
                    {"verification_failure": _internal_failure("assistant_owner_boundary", exc)},
                    sort_keys=True,
                )
            )
            raise SystemExit(1) from None
        try:
            result.update(_verify_http(stage, None))
        except VerificationFailure as exc:
            print(json.dumps({"verification_failure": exc.step}, sort_keys=True))
            raise SystemExit(1) from None
        except AssertionError:
            print(json.dumps({"verification_failure": "candidate_verification_internal:assertion"}))
            raise SystemExit(1) from None
        except Exception as exc:
            print(
                json.dumps(
                    {"verification_failure": _internal_failure("candidate_http", exc)},
                    sort_keys=True,
                )
            )
            raise SystemExit(1) from None
        print(json.dumps(result, sort_keys=True))
        return
    if stage == "write-consent":
        print(json.dumps(_write_consent(), sort_keys=True))
        return
    if stage == "recovery":
        repository = repo()
        repository.migrate()
        manager = BackupManager(repository, Settings.from_env().backup_dir)
        assert old_backup_name is not None and pre_consent_name is not None
        old_verification = _verify_historical_backup(old_backup_name, 12)
        consent_manifest, pre_consent_database, consent_staging = manager.verify(
            pre_consent_name
        )
        try:
            assert consent_manifest["schema_version"] == 13
            active_digest = _restore_security_digest(repository.database_path)
            pre_consent_digest = _restore_security_digest(pre_consent_database)
            assert active_digest != pre_consent_digest
        finally:
            consent_staging.cleanup()
        result = _verify_http(stage, pre_consent_name)
        result["historical_schema12_backup_integrity_verified"] = old_verification[
            "integrity_verified"
        ]
        print(json.dumps(result, sort_keys=True))
        return
    raise SystemExit("unknown fixed rehearsal stage")


if __name__ == "__main__":
    main()
"""


def _write_file(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o644)


def _image_run_args(
    volume: str, env_values: list[str], verifier_path: Path, *, identity_drop: bool
) -> list[str]:
    args = [
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--memory",
        str(IMAGE_MEMORY_BYTES),
        "--cpus",
        str(IMAGE_CPUS),
        "--pids-limit",
        str(IMAGE_PIDS),
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - app-private tmpfs
        "--tmpfs",
        "/run/assistant:rw,nosuid,nodev,noexec,size=16m,mode=0711",
        "--tmpfs",
        "/run/assistant-worker-home:rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700",
        "--volume",
        f"{volume}:/data",
        "--mount",
        f"type=bind,src={verifier_path},dst={_VERIFIER_IN_CONTAINER},readonly",
        *env_values,
        "--detach",
        "--rm",
    ]
    if identity_drop:
        args.extend(["--cap-add=SETUID", "--cap-add=SETGID", "--user=0:0"])
    else:
        args.append(f"--user={APP_UID}:{APP_GID}")
    return args


def _start_app(
    image: str,
    volume: str,
    env_values: list[str],
    verifier: Path,
    env: dict[str, str],
    secret_environment: dict[str, str] | None = None,
    *,
    identity_drop: bool,
) -> str:
    command = [
        "docker",
        "run",
        *_image_run_args(volume, env_values, verifier, identity_drop=identity_drop),
        image,
    ]
    child_env = dict(env)
    if secret_environment:
        allowed_secrets = {
            "STOCK_PROBS_AUTH_SESSION_SECRET",
            "STOCK_PROBS_BOOTSTRAP_PASSWORD",
            "STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD",
        }
        if set(secret_environment) != allowed_secrets or any(
            not isinstance(value, str) or not value for value in secret_environment.values()
        ):
            raise RehearsalError("synthetic_environment_invalid")
        child_env.update(secret_environment)
    container = _run(command, env=child_env, timeout=30).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{64}", container) is None:
        raise RehearsalError("Docker did not return a task-owned container identity")
    return container


def _wait_ready(
    container: str,
    image: str,
    env: dict[str, str],
    *,
    diagnostic_stage: str,
) -> dict[str, object]:
    deadline = time.monotonic() + _APP_READINESS_TIMEOUT_SECONDS
    last_status = "starting"
    while time.monotonic() < deadline:
        inspect = _run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            env=env,
            timeout=10,
            check=False,
            diagnostic_stage=diagnostic_stage,
        )
        if inspect.returncode or inspect.stdout.strip() != "true":
            raise RehearsalError("the bounded app container stopped before readiness")
        probe = _run(
            [
                "docker",
                "exec",
                "--user",
                f"{APP_UID}:{APP_GID}",
                container,
                "python",
                _VERIFIER_IN_CONTAINER,
                "probe",
            ],
            env=env,
            timeout=10,
            check=False,
            diagnostic_stage="readiness_exec",
        )
        if probe.returncode == 0:
            try:
                result = json.loads(probe.stdout)
            except json.JSONDecodeError as exc:
                raise RehearsalError("the local app readiness response was invalid") from exc
            if result.get("schema_version") == 13 and result.get("assistant") == {
                "enabled": False,
                "status": "disabled",
            }:
                return result
        else:
            last_status = "starting"
        time.sleep(0.5)
    if last_status == "starting":
        raise RehearsalError(f"local_check_failed:{diagnostic_stage}:not_ready")
    raise RehearsalError(f"local_check_failed:{diagnostic_stage}:invalid_response")


def _container_inspect(container: str, env: dict[str, str]) -> dict[str, object]:
    result = _run(
        ["docker", "inspect", "--format", _CONTAINER_PROFILE_INSPECT_FORMAT, container],
        env=env,
        timeout=10,
    )
    try:
        inspection = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RehearsalError("the local app container inspection was invalid") from exc
    configuration = inspection.get("Config") if isinstance(inspection, dict) else None
    labels = configuration.get("Labels") if isinstance(configuration, dict) else None
    if (
        not isinstance(inspection, dict)
        or not isinstance(inspection.get("HostConfig"), dict)
        or not isinstance(labels, dict)
        or not isinstance(labels.get("org.opencontainers.image.revision"), str)
    ):
        raise RehearsalError("the local app container inspection was invalid")
    return inspection


def _string_set(value: object) -> frozenset[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return frozenset(value)


def _normalized_capabilities(value: object) -> frozenset[str] | None:
    """Normalize Docker's optional CAP_ spelling for the fixed identity-drop pair only."""
    if not isinstance(value, list) or len(value) != 2:
        return None
    normalized: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        capability = item[4:] if item.startswith("CAP_") else item
        if capability not in {"SETUID", "SETGID"} or capability in normalized:
            return None
        normalized.add(capability)
    return frozenset(normalized)


def _recovery_profile_mismatch(host_config: dict[str, object]) -> str | None:
    """Return only a fixed field label when the recovery container is outside its profile."""
    fields: tuple[tuple[str, bool], ...] = (
        ("ReadonlyRootfs", host_config.get("ReadonlyRootfs") is True),
        ("NetworkMode", host_config.get("NetworkMode") == "none"),
        ("Memory", host_config.get("Memory") == IMAGE_MEMORY_BYTES),
        ("NanoCpus", host_config.get("NanoCpus") == 1_000_000_000),
        ("PidsLimit", host_config.get("PidsLimit") == IMAGE_PIDS),
        ("CapDrop", _string_set(host_config.get("CapDrop")) == frozenset({"ALL"})),
        (
            "CapAdd",
            _normalized_capabilities(host_config.get("CapAdd")) == frozenset({"SETUID", "SETGID"}),
        ),
        (
            "SecurityOpt",
            _string_set(host_config.get("SecurityOpt")) == frozenset({"no-new-privileges:true"}),
        ),
    )
    return next((field for field, matches in fields if not matches), None)


def _process_security_probe(container: str, env: dict[str, str]) -> dict[str, object]:
    command = [
        "docker",
        "exec",
        "--user",
        f"{APP_UID}:{APP_GID}",
        container,
        "python",
        "-c",
        """import json,os,pathlib
status={}
for line in pathlib.Path('/proc/1/status').read_text().splitlines():
    if line.startswith(('Uid:','Gid:','CapEff:','CapPrm:','CapBnd:','NoNewPrivs:')):
        key,value=line.split(':',1); status[key]=value.strip()
assert status['Uid'].split()[0]=='10001'
assert status['Gid'].split()[0]=='10001'
assert int(status['CapEff'],16)==0 and int(status['CapPrm'],16)==0
assert int(status['CapBnd'],16)==0xc0
assert status['NoNewPrivs']=='1'
import importlib.util
assert not pathlib.Path('/usr/local/bin/opencode').exists()
assert importlib.util.find_spec('stock_probs.assistant') is None
assert importlib.util.find_spec('stock_probs.container_supervisor') is None
pid1=pathlib.Path('/proc/1/cmdline').read_bytes().replace(b'\\x00',b' ').decode(errors='replace')
assert 'stock-probs' in pid1 and 'opencode' not in pid1 and 'container_supervisor' not in pid1
try:
    pathlib.Path('/usr/local/.schema13-write-check').write_text('x')
except OSError as error:
    assert error.errno==30
    root_read_only=True
else:
    pathlib.Path('/usr/local/.schema13-write-check').unlink(missing_ok=True)
    raise AssertionError('image root filesystem is writable')
pathlib.Path('/tmp/schema13-tmp-write-check').write_text('ok')
pathlib.Path('/tmp/schema13-tmp-write-check').unlink()
try:
    pathlib.Path('/run/assistant-worker-home/schema13-write-check').write_text('x')
except PermissionError:
    worker_home_private=True
else:
    pathlib.Path('/run/assistant-worker-home/schema13-write-check').unlink(missing_ok=True)
    raise AssertionError('the recovery app can write to a worker-only home')
print(json.dumps({'uid':10001,'gid':10001,'effective_capabilities':status['CapEff'],'permitted_capabilities':status['CapPrm'],'bounding_capabilities':status['CapBnd'],'no_new_privileges':True,'root_read_only':root_read_only,'tmp_writable':True,'worker_home_private':worker_home_private,'native_worker_absent':True,'pid1_command':pid1}))""",
    ]
    result = json.loads(
        _run(command, env=env, timeout=10, diagnostic_stage="process_identity").stdout
    )
    return result


def _stop_container(container: str, env: dict[str, str]) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", container) is None:
        raise RehearsalError("the task-owned container identity is invalid")
    _run(
        ["docker", "stop", "--time=5", container],
        env=env,
        timeout=15,
        check=False,
        diagnostic_stage="container_stop",
    )
    deadline = time.monotonic() + CONTAINER_REMOVAL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state = _run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            env=env,
            timeout=5,
            check=False,
            diagnostic_stage="container_stop_verify",
        )
        if state.returncode == 0 and state.stdout.strip() == "true":
            raise RehearsalError("the task-owned container is still running")
        if state.returncode == 0 and state.stdout.strip() != "false":
            raise RehearsalError("the task-owned container state could not be verified")
        listed = _run(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                "id=" + container,
            ],
            env=env,
            timeout=5,
            check=False,
            diagnostic_stage="container_autoremove_verify",
        )
        if listed.returncode != 0:
            raise RehearsalError("the task-owned container absence could not be verified")
        matches = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        if matches == []:
            if state.returncode != 0:
                return
            time.sleep(0.2)
            continue
        if matches != [container]:
            raise RehearsalError("the Docker container filter returned an unexpected identity")
        time.sleep(0.2)
    raise RehearsalError("the task-owned container auto-removal was not verified")


def _remove_disposable_volume(volume: str, env: dict[str, str]) -> str | None:
    """Remove only this run's exact volume after all container references are absent."""

    if re.fullmatch(r"stock-probs-schema13-[0-9a-f]{12}", volume) is None:
        return "volume_identity_invalid"
    references = _run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "volume=" + volume,
        ],
        env=env,
        timeout=10,
        check=False,
        diagnostic_stage="volume_reference_verify",
    )
    if references.returncode != 0:
        return "volume_reference_unverified"
    if references.stdout.strip():
        return "volume_retained_for_unverified_container"
    removed = _run(
        ["docker", "volume", "rm", volume],
        env=env,
        timeout=15,
        check=False,
        diagnostic_stage="volume_remove",
    )
    if removed.returncode != 0:
        return "volume_removal"
    remaining = _run(
        ["docker", "volume", "ls", "--quiet", "--filter", "name=" + volume],
        env=env,
        timeout=10,
        check=False,
        diagnostic_stage="volume_removal_verify",
    )
    if remaining.returncode != 0 or remaining.stdout.strip():
        return "volume_removal_unverified"
    return None


def _verify_candidate_image(
    image_id: str,
    candidate_context_sha256: str,
    env: dict[str, str],
    *,
    expected_revision_label: str | None = None,
) -> dict[str, str]:
    """Bind a local image by immutable ID, platform, and source-context digest label."""

    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise RehearsalError("candidate image must be supplied by immutable local image ID")
    if re.fullmatch(r"[0-9a-f]{64}", candidate_context_sha256) is None:
        raise RehearsalError("candidate source context must be supplied by its SHA-256")
    result = _run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            (
                "{{.Id}}|{{.Os}}|{{.Architecture}}|"
                '{{index .Config.Labels "org.opencontainers.image.revision"}}'
            ),
            image_id,
        ],
        env=env,
        timeout=10,
        check=False,
    )
    fields = result.stdout.strip().split("|")
    expected_label = expected_revision_label or f"local-source-{candidate_context_sha256}"
    if (
        result.returncode
        or len(fields) != 4
        or fields[0] != image_id
        or fields[1:] != ["linux", "amd64", expected_label]
    ):
        raise RehearsalError("candidate image identity does not match the frozen source context")
    return {
        "id": image_id,
        "architecture": "linux/amd64",
        "source_context_sha256": candidate_context_sha256,
        "revision_label": expected_label,
    }


def _git_environment() -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    }


def _verify_local_pr_head(repository_root: Path, expected_sha: str) -> None:
    """Require a clean checkout at the one exact reviewed PR head."""

    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise RehearsalError("reviewed PR head must be an exact commit SHA")
    if not (repository_root / ".git").exists():
        raise RehearsalError("the reviewed PR checkout is unavailable")
    try:
        head = subprocess.run(  # noqa: S603 - fixed Git executable and fixed revision query
            [_GIT_EXECUTABLE, "rev-parse", "--verify", "HEAD"],
            cwd=repository_root,
            env=_git_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalError("the reviewed PR checkout could not be verified") from exc
    if (
        head.returncode
        or len(head.stdout) > 128
        or head.stdout.decode("ascii", errors="ignore").strip() != expected_sha
    ):
        raise RehearsalError("local HEAD does not match the reviewed PR head")

    command = [
        _GIT_EXECUTABLE,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ]
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed Git executable and status arguments
            command,
            cwd=repository_root,
            env=_git_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError as exc:
        raise RehearsalError("the reviewed PR checkout could not be verified") from exc
    if process.stdout is None:
        if not _stop_git_status_process(process):
            raise RehearsalError("local checkout process state is unverified")
        raise RehearsalError("the reviewed PR checkout could not be verified")
    with process.stdout as status_output, selectors.DefaultSelector() as selector:
        selector.register(status_output, selectors.EVENT_READ)
        deadline = time.monotonic() + 30
        dirty = False
        output_closed = False
        while not output_closed and not dirty:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if not _stop_git_status_process(process):
                    raise RehearsalError("local checkout process state is unverified")
                raise RehearsalError("local checkout verification timed out")
            if selector.select(timeout=min(0.2, remaining)):
                chunk = os.read(status_output.fileno(), 1)
                if chunk:
                    dirty = True
                else:
                    output_closed = True
        if dirty:
            if not _stop_git_status_process(process):
                raise RehearsalError("local checkout process state is unverified")
            raise RehearsalError("the reviewed PR checkout is not clean")
    try:
        return_code = process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if not _stop_git_status_process(process):
            raise RehearsalError("local checkout process state is unverified") from exc
        raise RehearsalError("the reviewed PR checkout could not be verified") from exc
    if return_code != 0:
        raise RehearsalError("the reviewed PR checkout could not be verified")


def _verify_reviewed_pr(repository_root: Path, expected_sha: str) -> None:
    """Call the fixed adjacent PR-1 verifier and expose only its closed safe result."""

    scripts_directory = repository_root / "scripts"
    verifier_path = scripts_directory / "pr_rehearsal_bootstrap.py"
    try:
        scripts_info = scripts_directory.lstat()
        verifier_info = verifier_path.lstat()
    except OSError as exc:
        raise RehearsalError("the fixed reviewed PR verifier is unavailable") from exc
    if (
        not stat.S_ISDIR(scripts_info.st_mode)
        or stat.S_ISLNK(scripts_info.st_mode)
        or not stat.S_ISREG(verifier_info.st_mode)
        or stat.S_ISLNK(verifier_info.st_mode)
    ):
        raise RehearsalError("the fixed reviewed PR verifier is unsafe")
    try:
        resolved_root = repository_root.resolve(strict=True)
        resolved_scripts = scripts_directory.resolve(strict=True)
        if resolved_scripts != resolved_root / "scripts":
            raise RehearsalError("the fixed reviewed PR verifier is unsafe")
        spec = importlib.util.spec_from_file_location(
            "_stock_probs_pr_rehearsal_bootstrap", verifier_path
        )
        if spec is None or spec.loader is None:
            raise RehearsalError("the fixed reviewed PR verifier is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        verify = getattr(module, "_verify_pull_request", None)
        if not callable(verify):
            raise RehearsalError("the fixed reviewed PR verifier is unavailable")
        verify(expected_sha)
    except RehearsalError:
        raise
    except Exception as exc:
        safe_code = {
            "reviewed_pr_unavailable": "reviewed_pr_unavailable",
            "reviewed_pr_invalid": "reviewed_pr_invalid",
            "reviewed_pr_mismatch": "reviewed_pr_mismatch",
        }.get(getattr(exc, "code", None), "reviewed_pr_verification_failed")
        raise RehearsalError(safe_code) from exc


def build_pr_candidate(
    repository_root: Path,
    reviewed_sha: str,
    receipt_path: Path,
) -> dict[str, object]:
    """Build one private local image for the exact open PR-1 head."""

    if re.fullmatch(r"[0-9a-f]{40}", reviewed_sha) is None:
        raise RehearsalError("reviewed PR head must be an exact commit SHA")
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _verify_local_pr_head(repository_root, reviewed_sha)
    _verify_reviewed_pr(repository_root, reviewed_sha)
    unique = uuid.uuid4().hex[:12]
    tag = f"stock-probs:pr-candidate-{reviewed_sha[:12]}-{unique}"
    with tempfile.TemporaryDirectory(prefix="stock-probs-pr-candidate-") as temporary:
        workspace = Path(temporary)
        docker_config = workspace / "docker-config"
        env = _docker_environment(docker_config)
        context = workspace / "context"
        context_sha256 = _candidate_context(repository_root, context)
        _verify_local_pr_head(repository_root, reviewed_sha)
        existing = _run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
            env=env,
            timeout=10,
            check=False,
        )
        if existing.returncode == 0 or existing.stdout.strip():
            raise RehearsalError("the generated candidate image tag is already in use")
        image_id = _build_image(
            context,
            tag,
            reviewed_sha,
            env,
            build_disk_paths=(workspace,),
        )
        try:
            _verify_local_pr_head(repository_root, reviewed_sha)
            _verify_reviewed_pr(repository_root, reviewed_sha)
            image = _verify_candidate_image(
                image_id,
                context_sha256,
                env,
                expected_revision_label=reviewed_sha,
            )
        except RehearsalError as exc:
            # Keep the generated reference for safe inspection; a new tag does not prove its
            # underlying content-addressed image ID was not already shared or protected.
            raise RehearsalError(
                f"{exc}; generated candidate image tag retained",
                cleanup_unverified=exc.cleanup_unverified,
            ) from exc
    receipt: dict[str, object] = {
        "task": "R-ASTRA-120 PR-head candidate image build",
        "status": "built",
        "repository": "eddiesoz/stock_probs",
        "pull_request": 1,
        "reviewed_head": reviewed_sha,
        "source_context_sha256": context_sha256,
        "candidate_image": {
            "reference": tag,
            "id": image["id"],
            "architecture": image["architecture"],
            "revision_label": image["revision_label"],
        },
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "published": False,
    }
    receipt["receipt_sha256"] = _sha256(_canonical_json(receipt))
    _write_receipt(receipt_path, receipt)
    return receipt


def run_rehearsal(
    repository_root: Path,
    candidate_image_id: str,
    expected_candidate_context_sha256: str,
    *,
    candidate_revision: str | None = None,
    release_artifact_directory: Path | None = None,
    use_deployed_baseline_image: bool = False,
) -> dict[str, object]:
    """Migrate, write, and recover one disposable Docker volume with fixed local images."""

    if not (repository_root / ".git").exists():
        raise RehearsalError("the rehearsal must run from the assigned Git repository")
    unique = uuid.uuid4().hex[:12]
    volume = f"stock-probs-schema13-{unique}"
    base_tag = f"stock-probs:schema12-base-{unique}"
    recovery_tag = f"stock-probs:schema13-recovery-{unique}"
    containers: list[str] = []
    tags: list[str] = []
    volume_created = False
    base_env: dict[str, str] = {}
    receipt: dict[str, object] = {}
    started = datetime.now(UTC)
    try:
        with tempfile.TemporaryDirectory(prefix="stock-probs-schema13-") as temporary:
            workspace = Path(temporary)
            docker_config = workspace / "docker-config"
            base_env = _docker_environment(docker_config)
            base_context = workspace / "schema12-base"
            base_source = _extract_base_archive(repository_root, base_context)
            base_context_digest = _tree_sha256(base_context)
            candidate_context = workspace / "candidate"
            candidate_digest = _candidate_context(repository_root, candidate_context)
            if candidate_digest != expected_candidate_context_sha256:
                raise RehearsalError("the frozen candidate source context has changed")
            candidate_image = _verify_candidate_image(
                candidate_image_id,
                candidate_digest,
                base_env,
                expected_revision_label=candidate_revision,
            )
            recovery_context = workspace / "recovery"
            shutil.copytree(base_context, recovery_context, symlinks=True)
            _validate_copy_tree(recovery_context)
            overlay = _apply_recovery_overlay(repository_root, recovery_context)
            recovery_digest = _tree_sha256(recovery_context)
            overlay_source_digest = str(overlay["overlay_sha256"])
            recovery_revision_label = candidate_revision or (
                f"schema13-recovery-{overlay_source_digest}"
            )

            base_image_id, base_image_reference, base_image_provenance = (
                _prepare_schema12_base_image(
                    base_context,
                    base_tag,
                    BASE_SHA,
                    base_env,
                    use_deployed_baseline_image=use_deployed_baseline_image,
                )
            )
            if not use_deployed_baseline_image:
                tags.append(base_tag)
            recovery_image_id = _build_image(
                recovery_context,
                recovery_tag,
                recovery_revision_label,
                base_env,
            )
            tags.append(recovery_tag)
            volume_result = _run(["docker", "volume", "create", volume], env=base_env, timeout=15)
            if volume_result.stdout.strip() != volume:
                raise RehearsalError("Docker created an unexpected disposable volume")
            volume_created = True
            runtime_env = [
                "--env=STOCK_PROBS_DATA_DIR=/data",
                "--env=STOCK_PROBS_PROVIDER=fixture",
                "--env=STOCK_PROBS_ENV=test",
                "--env=STOCK_PROBS_AUTH_MODE=local",
                "--env=STOCK_PROBS_AUTH_SESSION_SECRET",
                "--env=STOCK_PROBS_PUBLIC_ORIGIN=http://127.0.0.1:8000",
                "--env=STOCK_PROBS_BOOTSTRAP_USERNAME=rehearsal-admin",
                "--env=STOCK_PROBS_BOOTSTRAP_PASSWORD",
                "--env=STOCK_PROBS_BOOTSTRAP_MEMBER_USERNAME=rehearsal-member",
                "--env=STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD",
                "--env=STOCK_PROBS_ASSISTANT_ENABLED=0",
                "--env=STOCK_PROBS_ASSISTANT_ROLLOUT=disabled",
                "--env=STOCK_PROBS_HOST=127.0.0.1",
                "--env=STOCK_PROBS_PORT=8000",
            ]
            runtime_secrets = {
                "STOCK_PROBS_AUTH_SESSION_SECRET": "schema13-test-session-secret-0123456789abcdef",
                "STOCK_PROBS_BOOTSTRAP_PASSWORD": "schema13-local-rehearsal-admin-password",
                "STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD": "schema13-local-rehearsal-member-password",
            }
            verifier = workspace / "schema13_rehearsal.py"
            _write_file(verifier, _verification_source())

            _run_cli(
                base_image_reference,
                volume,
                ["--env=STOCK_PROBS_DATA_DIR=/data", "--env=STOCK_PROBS_PROVIDER=fixture"],
                ["migrate"],
                base_env,
            )
            schema12 = _schema_check(
                base_image_reference,
                volume,
                ["--env=STOCK_PROBS_DATA_DIR=/data"],
                base_env,
            )
            if schema12.get("versions") != list(range(1, 13)):
                raise RehearsalError("the deployed schema-12 base image did not seed version 12")

            migration_output = _run_cli(
                candidate_image_id,
                volume,
                ["--env=STOCK_PROBS_DATA_DIR=/data", "--env=STOCK_PROBS_PROVIDER=fixture"],
                ["migrate"],
                base_env,
            )
            migration_result = json.loads(migration_output)
            pre_migration = migration_result.get("pre_migration_backup")
            if (
                not isinstance(pre_migration, dict)
                or pre_migration.get("verified") is not True
                or pre_migration.get("schema_version") != 12
                or not isinstance(pre_migration.get("name"), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(pre_migration.get("sha256"))) is None
            ):
                raise RehearsalError("the actual CLI pre-migration backup was not verified")
            schema13 = _schema_check(
                candidate_image_id, volume, ["--env=STOCK_PROBS_DATA_DIR=/data"], base_env
            )
            if schema13.get("versions") != list(range(1, 14)):
                raise RehearsalError("candidate CLI did not apply exactly schema 13")
            _run_cli(
                candidate_image_id,
                volume,
                ["--env=STOCK_PROBS_DATA_DIR=/data", "--env=STOCK_PROBS_PROVIDER=fixture"],
                ["restore", str(pre_migration["name"])],
                base_env,
                expected_rejection=(
                    "Backup schema version 12 cannot be restored over active schema version 13"
                ),
            )
            historical_verify_output = _run_historical_backup_verification(
                candidate_image_id,
                volume,
                verifier,
                str(pre_migration["name"]),
                base_env,
            )
            verified_pre_migration = json.loads(historical_verify_output)
            if (
                verified_pre_migration.get("verified") is not True
                or verified_pre_migration.get("schema_version") != 12
                or verified_pre_migration.get("integrity_verified") is not True
            ):
                raise RehearsalError("the historical pre-migration artifact did not authenticate")

            candidate_container = _start_app(
                candidate_image_id,
                volume,
                runtime_env,
                verifier,
                base_env,
                runtime_secrets,
                identity_drop=False,
            )
            containers.append(candidate_container)
            candidate_readiness = _wait_ready(
                candidate_container,
                candidate_image_id,
                base_env,
                diagnostic_stage="candidate_http_verify",
            )
            candidate_write = _run(
                [
                    "docker",
                    "exec",
                    "--user",
                    f"{APP_UID}:{APP_GID}",
                    candidate_container,
                    "python",
                    _VERIFIER_IN_CONTAINER,
                    "candidate",
                ],
                env=base_env,
                timeout=60,
                check=False,
                diagnostic_stage="candidate_data_verify",
            )
            try:
                candidate_payload: object = json.loads(candidate_write.stdout)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RehearsalError("candidate_data_verify:invalid_diagnostic") from exc
            if candidate_write.returncode:
                failure_step = (
                    candidate_payload.get("verification_failure")
                    if isinstance(candidate_payload, dict)
                    and set(candidate_payload) == {"verification_failure"}
                    else None
                )
                if failure_step not in _CANDIDATE_VERIFICATION_STEPS:
                    raise RehearsalError("candidate_data_verify:invalid_diagnostic")
                raise RehearsalError(f"candidate_data_verify:{failure_step}")
            if (
                not isinstance(candidate_payload, dict)
                or "verification_failure" in candidate_payload
            ):
                raise RehearsalError("candidate_data_verify:invalid_success_result")
            candidate_result = candidate_payload
            _stop_container(candidate_container, base_env)
            containers.remove(candidate_container)

            pre_consent_output = _run_cli(
                candidate_image_id,
                volume,
                ["--env=STOCK_PROBS_DATA_DIR=/data", "--env=STOCK_PROBS_PROVIDER=fixture"],
                ["backup", "--name", PRE_CONSENT_BACKUP],
                base_env,
            )
            pre_consent_result = json.loads(pre_consent_output)
            if pre_consent_result.get("schema_version") != 13:
                raise RehearsalError("the schema-13 comparison backup was not created")
            _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--read-only",
                    "--user",
                    f"{APP_UID}:{APP_GID}",
                    "--memory",
                    str(IMAGE_MEMORY_BYTES),
                    "--cpus",
                    str(IMAGE_CPUS),
                    "--pids-limit",
                    str(IMAGE_PIDS),
                    "--tmpfs",
                    "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",  # noqa: S108 - bounded container tmpfs
                    "--volume",
                    f"{volume}:/data",
                    "--mount",
                    f"type=bind,src={verifier},dst={_VERIFIER_IN_CONTAINER},readonly",
                    "--tmpfs",
                    "/run/assistant:rw,nosuid,nodev,noexec,size=16m,mode=0711",
                    "--env=STOCK_PROBS_DATA_DIR=/data",
                    "--entrypoint",
                    "python",
                    candidate_image_id,
                    _VERIFIER_IN_CONTAINER,
                    "write-consent",
                ],
                env=base_env,
                timeout=30,
            )

            recovery_container = _start_app(
                recovery_tag,
                volume,
                runtime_env,
                verifier,
                base_env,
                runtime_secrets,
                identity_drop=True,
            )
            containers.append(recovery_container)
            _wait_ready(
                recovery_container,
                recovery_tag,
                base_env,
                diagnostic_stage="recovery_http_verify",
            )
            recovery_inspection = _container_inspect(recovery_container, base_env)
            host_config = recovery_inspection.get("HostConfig")
            if not isinstance(host_config, dict):
                raise RehearsalError("recovery container security settings could not be read")
            profile_mismatch = _recovery_profile_mismatch(host_config)
            if profile_mismatch is not None:
                raise RehearsalError(f"recovery_container_profile_mismatch:{profile_mismatch}")
            recovery_process = _process_security_probe(recovery_container, base_env)
            recovery_result_raw = _run(
                [
                    "docker",
                    "exec",
                    "--user",
                    f"{APP_UID}:{APP_GID}",
                    recovery_container,
                    "python",
                    _VERIFIER_IN_CONTAINER,
                    "recovery",
                    str(pre_migration["name"]),
                    PRE_CONSENT_BACKUP,
                ],
                env=base_env,
                timeout=60,
                diagnostic_stage="recovery_state_verify",
            )
            recovery_result = json.loads(recovery_result_raw.stdout)
            recovery_schema = _schema_check(
                recovery_tag,
                volume,
                ["--env=STOCK_PROBS_DATA_DIR=/data"],
                base_env,
            )
            if recovery_schema.get("versions") != list(range(1, 14)):
                raise RehearsalError("recovery code changed or downgraded the migration history")

            release_pair: dict[str, object] | None = None
            if release_artifact_directory is not None:
                if (
                    candidate_revision is None
                    or re.fullmatch(r"[0-9a-f]{40}", candidate_revision) is None
                ):
                    raise RehearsalError(
                        "release pair artifacts require an exact reviewed revision"
                    )
                try:
                    release_artifact_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                    artifact_info = release_artifact_directory.lstat()
                except OSError as exc:
                    raise RehearsalError(
                        "the private release artifact directory is unavailable"
                    ) from exc
                if not stat.S_ISDIR(artifact_info.st_mode) or stat.S_ISLNK(artifact_info.st_mode):
                    raise RehearsalError("the release artifact directory is unsafe")
                candidate_archive_name = f"signal-ledger-image-{candidate_revision}.tar.gz"
                recovery_archive_name = f"signal-ledger-recovery-{candidate_revision}.tar.gz"
                pair_manifest_name = f"signal-ledger-pair-{candidate_revision}.json"
                candidate_archive_sha256, candidate_archive_size = _save_image_archive(
                    candidate_image_id,
                    release_artifact_directory / candidate_archive_name,
                    base_env,
                )
                recovery_image_platform = _image_platform(recovery_image_id, base_env)
                recovery_archive_sha256, recovery_archive_size = _save_image_archive(
                    recovery_image_id,
                    release_artifact_directory / recovery_archive_name,
                    base_env,
                )
                pair_manifest = {
                    "format_version": 1,
                    "repository": "eddiesoz/stock_probs",
                    "revision": candidate_revision,
                    "source_context_sha256": candidate_digest,
                    "migration": {
                        "from_schema": 12,
                        "to_schema": 13,
                        "sha256": MIGRATION_013_SHA256,
                    },
                    "candidate": {
                        "asset": candidate_archive_name,
                        "archive_sha256": candidate_archive_sha256,
                        "archive_size": candidate_archive_size,
                        "image_id": candidate_image_id,
                        "platform": "linux/amd64",
                        "revision": candidate_revision,
                        "schema_version": 13,
                        "source_context_sha256": candidate_digest,
                    },
                    "recovery": {
                        "asset": recovery_archive_name,
                        "archive_sha256": recovery_archive_sha256,
                        "archive_size": recovery_archive_size,
                        "image_id": recovery_image_id,
                        "platform": recovery_image_platform,
                        "revision": candidate_revision,
                        "schema_version": 13,
                        "assistant_enabled": False,
                        "base_revision": BASE_SHA,
                        "base_image_id": DEPLOYED_BASELINE["image_id"],
                        "base_archive_sha256": DEPLOYED_BASELINE["release_archive_sha256"],
                        "base_source_context_sha256": base_context_digest,
                        "overlay_sha256": overlay_source_digest,
                        "source_context_sha256": recovery_digest,
                        "migration_sha256": MIGRATION_013_SHA256,
                    },
                }
                pair_path = release_artifact_directory / pair_manifest_name
                pair_bytes = _canonical_json(pair_manifest)
                try:
                    descriptor = os.open(
                        pair_path,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                    )
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(pair_bytes)
                        output.flush()
                        os.fsync(output.fileno())
                except OSError as exc:
                    pair_path.unlink(missing_ok=True)
                    raise RehearsalError(
                        "the fixed release pair manifest could not be written"
                    ) from exc
                release_pair = {
                    "manifest_name": pair_manifest_name,
                    "manifest_sha256": _sha256(pair_bytes),
                    "candidate_archive_name": candidate_archive_name,
                    "candidate_archive_sha256": candidate_archive_sha256,
                    "candidate_archive_size": candidate_archive_size,
                    "recovery_archive_name": recovery_archive_name,
                    "recovery_archive_sha256": recovery_archive_sha256,
                    "recovery_archive_size": recovery_archive_size,
                }
            labels = recovery_inspection.get("Config", {}).get("Labels", {})
            if not isinstance(labels, dict) or labels.get("org.opencontainers.image.revision") != (
                recovery_revision_label
            ):
                raise RehearsalError("recovery image source identity label does not match overlay")

            receipt = {
                "task": "R-ASTRA-120 schema13 local recovery rehearsal",
                "status": "pass",
                "architecture": f"native-{platform.machine()}-{platform.system().lower()}",
                "started_at": started.isoformat().replace("+00:00", "Z"),
                "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "schema12_base_revision": BASE_SHA,
                "observed_deployment_baseline": DEPLOYED_BASELINE,
                "schema12_base_image": {
                    **base_image_provenance,
                    "source_archive": base_source,
                    "source_context_sha256": base_context_digest,
                    "image": {
                        "reference": base_image_reference,
                        "id": base_image_id,
                    },
                    "architecture": "linux/amd64",
                },
                "candidate_source_context_sha256": candidate_digest,
                "candidate_image": candidate_image,
                "recovery_overlay": overlay,
                "recovery_context_sha256": recovery_digest,
                "recovery_image": {"reference": recovery_tag, "id": recovery_image_id},
                "release_pair": release_pair,
                "migration": {
                    "schema_before": 12,
                    "schema_after": 13,
                    "pre_migration_backup": pre_migration,
                    "read_only_backup_verification": verified_pre_migration,
                    "post_consent_backup": {
                        "name": PRE_CONSENT_BACKUP,
                        "sha256": pre_consent_result.get("sha256"),
                        "schema_version": pre_consent_result.get("schema_version"),
                    },
                },
                "candidate": {**candidate_readiness, **candidate_result},
                "recovery": {
                    **recovery_result,
                    "process_security": recovery_process,
                    "container_profile": {
                        "rootfs_read_only": True,
                        "network": "none",
                        "memory_bytes": IMAGE_MEMORY_BYTES,
                        "cpus": IMAGE_CPUS,
                        "pids": IMAGE_PIDS,
                        "capabilities_added_for_identity_drop": ["SETGID", "SETUID"],
                        "capabilities_after_drop": 0,
                        "assistant_enabled": False,
                        "native_worker_present": False,
                    },
                    "schema_after_recovery": recovery_schema.get("max"),
                },
                "same_disposable_volume": True,
                "production_or_remote_mutation": False,
            }
            return receipt
    finally:
        cleanup_errors: list[str] = []
        containers_stopped = True
        for container in reversed(containers):
            try:
                _stop_container(container, base_env)
            except RehearsalError as exc:
                cleanup_errors.append(_CONTAINER_CLEANUP_ERRORS.get(str(exc), "container_stop"))
                containers_stopped = False
        if volume_created and containers_stopped:
            volume_cleanup = _remove_disposable_volume(volume, base_env)
            if volume_cleanup is not None:
                cleanup_errors.append(volume_cleanup)
        elif volume_created:
            cleanup_errors.append("volume_retained_for_unverified_container")
        for tag in reversed(tags):
            if not _remove_generated_image_tag(tag, base_env):
                cleanup_errors.append("local_image_tag_removal")
        if cleanup_errors:
            if receipt:
                raise RehearsalError(
                    "the local rehearsal cleanup could not be verified",
                    cleanup_unverified=tuple(cleanup_errors),
                )
            active_error = sys.exc_info()[1]
            if isinstance(active_error, RehearsalError):
                active_error.cleanup_unverified = tuple(cleanup_errors)
        if receipt:
            receipt["cleanup"] = {
                "containers_removed": True,
                "volume_removed": True,
                "local_image_tags_removed": True,
                "verification": "task containers absent, volume unlisted, and image tags absent",
            }


def prepare_overlay_manifest(repository_root: Path) -> dict[str, object]:
    """Hash the reviewed overlay against the fixed base without building or running images."""

    with tempfile.TemporaryDirectory(prefix="stock-probs-schema13-overlay-") as temporary:
        workspace = Path(temporary)
        base_context = workspace / "schema12-base"
        base_source = _extract_base_archive(repository_root, base_context)
        overlay = _apply_recovery_overlay(repository_root, base_context)
        return {
            "task": "R-ASTRA-120 schema13 recovery overlay manifest",
            "status": "prepared",
            "observed_deployment_baseline": DEPLOYED_BASELINE,
            "base_source_archive": base_source,
            "base_source_context_sha256": base_source["source_context_sha256"],
            "recovery_context_sha256": _tree_sha256(base_context),
            "recovery_overlay": overlay,
            "built_or_published": False,
        }


def prepare_source_context_manifest(repository_root: Path) -> dict[str, object]:
    """Hash the exact filtered production source inputs without building or reading secrets."""

    with tempfile.TemporaryDirectory(prefix="stock-probs-source-context-") as temporary:
        context = Path(temporary) / "context"
        context_sha256 = _candidate_context(repository_root, context)
    return {
        "status": "prepared",
        "repository": "eddiesoz/stock_probs",
        "source_context_sha256": context_sha256,
    }


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_receipt = path.with_suffix(path.suffix + ".tmp")
    temporary_receipt.write_bytes(_canonical_json(receipt) + b"\n")
    temporary_receipt.chmod(0o600)
    os.replace(temporary_receipt, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, help="write a mode-0600 JSON receipt")
    parser.add_argument(
        "--build-pr-candidate",
        action="store_true",
        help="build a private local image from the exact clean open PR-1 head",
    )
    parser.add_argument(
        "--reviewed-pr-head",
        help="exact lowercase commit SHA reviewed for PR-1 candidate building",
    )
    parser.add_argument(
        "--overlay-manifest",
        action="store_true",
        help="hash the fixed recovery overlay without building or running images",
    )
    parser.add_argument(
        "--source-context-manifest",
        action="store_true",
        help="hash the filtered candidate source context without building or running images",
    )
    parser.add_argument(
        "--candidate-image-id",
        help="immutable local sha256 image ID already built from the frozen source context",
    )
    parser.add_argument(
        "--expected-candidate-context-sha256",
        help="filtered source-context digest bound into the candidate image revision label",
    )
    parser.add_argument(
        "--candidate-revision",
        help="exact main revision label for a release candidate image",
    )
    parser.add_argument(
        "--release-artifact-directory",
        type=Path,
        help="write verified candidate, recovery, and pair-manifest assets after rehearsal",
    )
    parser.add_argument(
        "--use-deployed-baseline-image",
        action="store_true",
        help="reuse the verified fixed deployed schema-12 image instead of rebuilding it",
    )
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    try:
        if args.use_deployed_baseline_image and (
            args.build_pr_candidate
            or args.reviewed_pr_head is not None
            or args.overlay_manifest
            or args.source_context_manifest
        ):
            raise RehearsalError("--use-deployed-baseline-image is only valid for a full rehearsal")
        if args.build_pr_candidate:
            legacy_inputs = (
                args.overlay_manifest,
                args.source_context_manifest,
                args.candidate_image_id is not None,
                args.expected_candidate_context_sha256 is not None,
                args.candidate_revision is not None,
                args.release_artifact_directory is not None,
            )
            if any(legacy_inputs):
                raise RehearsalError(
                    "PR candidate build mode cannot be combined with rehearsal inputs"
                )
            if args.reviewed_pr_head is None or args.receipt is None:
                raise RehearsalError(
                    "PR candidate build mode requires --reviewed-pr-head and --receipt"
                )
            receipt = build_pr_candidate(repository_root, args.reviewed_pr_head, args.receipt)
        elif args.reviewed_pr_head is not None:
            raise RehearsalError("--reviewed-pr-head requires --build-pr-candidate")
        elif args.overlay_manifest:
            receipt = prepare_overlay_manifest(repository_root)
        elif args.source_context_manifest:
            receipt = prepare_source_context_manifest(repository_root)
        elif args.candidate_image_id and args.expected_candidate_context_sha256:
            if (
                args.candidate_revision
                and re.fullmatch(r"[0-9a-f]{40}", args.candidate_revision) is None
            ):
                raise RehearsalError("candidate revision must be an exact commit SHA")
            if args.release_artifact_directory is not None and args.candidate_revision is None:
                raise RehearsalError("release pair artifacts require --candidate-revision")
            receipt = run_rehearsal(
                repository_root,
                args.candidate_image_id,
                args.expected_candidate_context_sha256,
                candidate_revision=args.candidate_revision,
                release_artifact_directory=args.release_artifact_directory,
                use_deployed_baseline_image=args.use_deployed_baseline_image,
            )
        else:
            raise RehearsalError(
                "full rehearsal requires an immutable candidate image ID and source-context digest"
            )
    except RehearsalError as exc:
        failure: dict[str, object] = {"status": "fail", "reason": str(exc)}
        if exc.cleanup_unverified:
            failure["cleanup_unverified"] = list(exc.cleanup_unverified)
        print(json.dumps(failure), file=sys.stderr)
        return 2
    if args.receipt is not None and not args.build_pr_candidate:
        _write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
