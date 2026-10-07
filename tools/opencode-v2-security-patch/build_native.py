#!/usr/bin/env python3
"""Build the patched, pinned OpenCode CLI for one Docker target architecture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from apply_native_patch import GUARD_PATH, MANIFEST_PATH, apply_patch

MAX_DOWNLOAD_CHUNK = 1024 * 1024
MAX_REDIRECT_HOSTS = {"codeload.github.com", "github.com", "release-assets.githubusercontent.com"}
MAX_DOWNLOAD_REDIRECTS = 4
BUILD_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BUILD_RECEIPT_SCHEMA = 1
MAX_LICENSE_BYTES = 1024 * 1024
MANAGED_OAUTH_TEST_NAMES = (
    "keeps managed OpenCode OAuth ephemeral behind the fixed broker",
    "cancels a managed OpenCode device attempt before any credential handoff",
    "relays managed browser OAuth through the fixed broker without a local listener",
    "managed browser OAuth relays one state-bound callback into a one-time handoff",
    "isolates concurrent managed OAuth broker contexts per native attempt",
    "rejects managed OAuth without an app broker before provider authorization",
)
# Frozen registered-case inventory: 49 mocked guard cases and 8 pinned native integrations.
WEBFETCH_GUARD_TEST_CASES = 49
WEBFETCH_NATIVE_INTEGRATION_TEST_CASES = 8
WEBFETCH_TEST_CASES = WEBFETCH_GUARD_TEST_CASES + WEBFETCH_NATIVE_INTEGRATION_TEST_CASES
_SAFE_NATIVE_STATUSES = frozenset(
    {"pending", "complete", "handoff_ready", "connected", "denied", "cancelled", "expired"}
)


def _verify_bun_test_summary(
    stdout: str, stderr: str, *, expected_passes: int, expected_names: tuple[str, ...] = ()
) -> None:
    """Reject successful Bun exits that ran zero, skipped, or unexpected test cases."""

    output = f"{stdout}\n{stderr}"
    passed = re.search(r"(?m)^\s*(\d+) pass\s*$", output)
    failed = re.search(r"(?m)^\s*(\d+) fail\s*$", output)
    skipped = re.search(r"(?m)^\s*(\d+) skip\s*$", output)
    ran = re.search(
        r"(?m)^Ran (\d+) tests? across (\d+) files?\. "
        r"\[[0-9]+(?:\.[0-9]+)?(?:ms|s)\]$",
        output,
    )
    missing_names = tuple(name for name in expected_names if name not in output)
    if (
        passed is None
        or int(passed.group(1)) != expected_passes
        or failed is None
        or int(failed.group(1)) != 0
        or (skipped is not None and int(skipped.group(1)) != 0)
        or ran is None
        or int(ran.group(1)) != expected_passes
        or missing_names
    ):
        raise ValueError(
            "pinned native test command did not run its exact expected passing cases "
            f"(pass={passed.group(1) if passed else 'unknown'}, "
            f"fail={failed.group(1) if failed else 'unknown'}, "
            f"skip={skipped.group(1) if skipped else 'unknown'}, "
            f"ran={ran.group(1) if ran else 'unknown'}, missing_names={missing_names})"
        )


def _safe_bun_test_frames(output: str) -> tuple[str, ...]:
    """Keep only relative pinned-core test/source frame locations from Bun diagnostics."""

    frames = re.findall(
        r"(?m)^\s+at\s+[^\r\n]*?[/\\]packages[/\\]core[/\\]"
        r"((?:test|src)[/\\][^:\s)]+):(\d+):(\d+)",
        output,
    )
    safe_frames = []
    for path, line, column in frames[:8]:
        relative_path = path.replace(chr(92), "/")
        safe_frames.append(f"packages/core/{relative_path}:{line}:{column}")
    return tuple(safe_frames)


def _safe_bun_failure_categories(output: str) -> tuple[str, ...]:
    """Project each failed case to a safe matcher or exception category, never raw values."""

    headers = tuple(re.finditer(r"(?m)^\s*\(fail\) ([^\r\n]+)", output))
    safe: list[str] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(output)
        block = output[header.end() : end]
        name = re.sub(r"\s+\[[0-9]+(?:\.[0-9]+)?(?:ms|s)\]$", "", header.group(1))
        expected = re.search(r"(?m)^\s*Expected:\s*(\S.*)?$", block)
        received = re.search(r"(?m)^\s*Received:\s*(\S.*)?$", block)
        if expected and received:
            expected_category = _safe_bun_assertion_atom(expected.group(1) or "")
            received_category = _safe_bun_assertion_atom(received.group(1) or "")
            safe.append(
                f"{name}:assertion_mismatch:expected_{expected_category}:received_{received_category}"
            )
            continue
        error = re.search(
            r"\b(AssertionError|TypeError|RangeError|SyntaxError|TimeoutError|Error)\b", block
        )
        if error:
            safe.append(f"{name}:exception_{error.group(1)}")
        elif re.search(r"(?i)\b(?:timed out|timeout)\b", block):
            safe.append(f"{name}:timeout")
        else:
            safe.append(f"{name}:unclassified_failure")
    return tuple(safe)


def _safe_bun_assertion_atom(value: str) -> str:
    """Keep only known statuses or the JSON value category from an assertion diagnostic."""

    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] in {'"', "'"} and normalized[-1] == normalized[0]:
        content = normalized[1:-1]
        return f"status_{content}" if content in _SAFE_NATIVE_STATUSES else "string"
    if normalized in _SAFE_NATIVE_STATUSES:
        return f"status_{normalized}"
    if normalized in {"true", "false", "null", "undefined"}:
        return normalized
    if normalized.startswith("{"):
        return "object"
    if normalized.startswith("["):
        return "array"
    if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", normalized):
        return "number"
    return "string"


def _run_bun_test_suite(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int,
    suite_name: str,
    expected_passes: int,
    expected_names: tuple[str, ...] = (),
) -> None:
    """Run a fixed suite and keep failure diagnostics to counts and pinned case names."""

    result = subprocess.run(  # noqa: S603 - only fixed pinned Bun test commands are passed
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        output = f"{result.stdout}\n{result.stderr}"
        passed = re.search(r"(?m)^\s*(\d+) pass\s*$", output)
        failed = re.search(r"(?m)^\s*(\d+) fail\s*$", output)
        failed_cases = re.findall(r"(?m)^\s*\(fail\) ([^\r\n]+)", output)
        missing_cases = tuple(name for name in expected_names if name not in output)
        frames = _safe_bun_test_frames(output)
        failure_categories = _safe_bun_failure_categories(output)
        details = (
            f"exit={result.returncode}, pass={passed.group(1) if passed else 'unknown'}, "
            f"fail={failed.group(1) if failed else 'unknown'}, "
            f"failed_cases={tuple(failed_cases)}, missing_cases={missing_cases}, "
            f"failure_categories={failure_categories}, frames={frames}"
        )
        raise ValueError(f"pinned {suite_name} test suite failed ({details})")
    _verify_bun_test_summary(
        result.stdout,
        result.stderr,
        expected_passes=expected_passes,
        expected_names=expected_names,
    )


def _managed_oauth_test_invocation(
    bun_executable: Path, source_root: Path
) -> tuple[list[str], Path]:
    """Run the three fixed OAuth test files from core so its Bun config/preload applies."""

    return (
        [
            str(bun_executable),
            "test",
            "--test-name-pattern=managed",
            "./test/integration.test.ts",
            "./test/plugin/provider-openai.test.ts",
            "./test/plugin/provider-opencode.test.ts",
        ],
        source_root / "packages/core",
    )


def _validate_download_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in MAX_REDIRECT_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("pinned download URL is outside the native build allowlist")
    return parsed


def _build_environment(work: Path, version: str) -> dict[str, str]:
    return {
        "HOME": str(work),
        "TMPDIR": str(work),
        "PATH": BUILD_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CI": "1",
        "OPENCODE_CHANNEL": "latest",
        "OPENCODE_VERSION": version,
        "HUSKY": "0",
    }


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self._redirect_count = 0

    def redirect_request(self, request, response, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        self._redirect_count += 1
        if self._redirect_count > MAX_DOWNLOAD_REDIRECTS:
            raise ValueError("pinned download exceeded its redirect bound")
        _validate_download_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MAX_DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_upstream_license(source_root: Path, output_dir: Path) -> Path:
    """Carry the pinned upstream license beside the compiled native binary."""

    source = source_root / "LICENSE"
    before = source.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > MAX_LICENSE_BYTES
    ):
        raise ValueError("pinned native license file is invalid")
    descriptor = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_size != before.st_size
        ):
            raise ValueError("pinned native license file is invalid")
        contents = bytearray()
        while len(contents) <= MAX_LICENSE_BYTES:
            chunk = os.read(
                descriptor, min(MAX_DOWNLOAD_CHUNK, MAX_LICENSE_BYTES + 1 - len(contents))
            )
            if not chunk:
                break
            contents.extend(chunk)
        if not contents or len(contents) != before.st_size or len(contents) > MAX_LICENSE_BYTES:
            raise ValueError("pinned native license file is invalid")
    finally:
        os.close(descriptor)
    output_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    target = output_dir / "opencode-LICENSE"
    with target.open("xb") as output:
        output.write(contents)
    target.chmod(0o644)
    return target


def _private_temp_root() -> Path:
    """Require the caller to supply a task-owned temporary directory."""

    root = Path(tempfile.gettempdir())
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise ValueError("native build temporary directory must be private and caller-owned")
    return root


def download(url: str, target: Path, *, limit: int) -> str:
    _validate_download_url(url)
    request = urllib.request.Request(  # noqa: S310 - exact-host HTTPS URL validated above
        url,
        headers={"User-Agent": "stock-probs-r120-native-build/1"},
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _AllowlistedRedirectHandler(),
    )
    digest = hashlib.sha256()
    total = 0
    with opener.open(request, timeout=45) as response, target.open("xb") as output:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != "https" or final.hostname not in MAX_REDIRECT_HOSTS:
            raise ValueError("pinned download redirected outside the native build allowlist")
        while True:
            chunk = response.read(MAX_DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("pinned build download exceeds its byte limit")
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def _inside_root(root: str, relative: PurePosixPath) -> bool:
    stack: list[str] = [root]
    for part in relative.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if len(stack) == 1:
                return False
            stack.pop()
        else:
            stack.append(part)
    return True


def extract_source(
    archive_path: Path,
    destination: Path,
    *,
    member_limit: int,
    byte_limit: int,
) -> Path:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        if not members or len(members) > member_limit:
            raise ValueError("pinned source archive member count is outside the build bound")
        expanded_size = sum(member.size for member in members if member.isfile())
        if expanded_size > byte_limit:
            raise ValueError("pinned source archive exceeds its expanded byte bound")
        roots = {
            PurePosixPath(member.name).parts[0]
            for member in members
            if PurePosixPath(member.name).parts
        }
        if len(roots) != 1:
            raise ValueError("pinned source archive has an unexpected root layout")
        root_name = next(iter(roots))
        if root_name in {".", ".."} or "/" in root_name:
            raise ValueError("pinned source archive root is unsafe")
        root = destination / root_name
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        symlinks: list[tuple[Path, str]] = []
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or name.parts[0] != root_name:
                raise ValueError("pinned source archive contains an unsafe path")
            if not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError("pinned source archive contains an unsupported entry type")
            target = destination.joinpath(*name.parts)
            relative = PurePosixPath(*name.parts[1:])
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or not _inside_root(root_name, relative.parent / link):
                    raise ValueError("pinned source archive contains an unsafe symbolic link")
                symlinks.append((target, member.linkname))
                continue
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("pinned source archive is incomplete")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=MAX_DOWNLOAD_CHUNK)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
        for target, linkname in symlinks:
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError("pinned source archive contains a duplicate path")
            target.symlink_to(linkname)
    return root


def bun_asset(manifest: dict[str, object], build_arch: str) -> tuple[str, str, str, str]:
    bun = manifest["bun"]
    if build_arch == "amd64":
        return (
            str(bun["linux_amd64_url"]),
            str(bun["linux_amd64_archive_sha256"]),
            "bun-linux-x64-baseline/bun",
            str(bun["linux_amd64_binary_sha256"]),
        )
    if build_arch == "arm64":
        return (
            str(bun["linux_arm64_url"]),
            str(bun["linux_arm64_archive_sha256"]),
            "bun-linux-aarch64/bun",
            "",
        )
    raise ValueError("unsupported Docker build architecture")


def target_name(target_arch: str) -> tuple[str, str, int]:
    if target_arch == "amd64":
        return "opencode-linux-x64-baseline", "cli-linux-x64-baseline/bin/opencode", 62
    if target_arch == "arm64":
        return "opencode-linux-arm64", "cli-linux-arm64/bin/opencode", 183
    raise ValueError("unsupported Docker target architecture")


def _build_receipt(
    *,
    target_arch: str,
    build_arch: str,
    binary: Path,
    source_archive_sha256: str,
    bun_archive_sha256: str,
    patch_receipt: dict[str, str],
    oauth_receipt: dict[str, str],
) -> dict[str, object]:
    """Validate and serialize the fixed native artifact trust receipt."""

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    opencode = manifest["opencode"]
    expected_patch = {
        "webfetch_source_sha256": opencode["webfetch_sha256"],
        "webfetch_patched_sha256": opencode["webfetch_patched_sha256"],
        "webfetch_guard_sha256": opencode["webfetch_guard_sha256"],
        "mcp_tool_source_sha256": opencode["mcp_tool_sha256"],
        "mcp_tool_patched_sha256": opencode["mcp_tool_patched_sha256"],
    }
    if patch_receipt != {
        **{"opencode_version": opencode["version"], "source_commit": opencode["source_commit"]},
        **expected_patch,
    }:
        raise ValueError("native source patch receipt does not match fixed inputs")

    expected_oauth = {
        "oauth_broker_sha256": opencode["oauth_broker_sha256"],
        "oauth_callback_sha256": opencode["oauth_callback_sha256"],
        "oauth_transformed_source_set_sha256": opencode["oauth_transformed_source_set_sha256"],
    }
    if oauth_receipt != expected_oauth:
        raise ValueError("native OAuth transform receipt does not match fixed inputs")

    patch_directory = Path(__file__).parent
    expected_oauth_inputs = {
        "oauth_patch_runner_sha256": opencode["oauth_patch_runner_sha256"],
        "oauth_handoff_patch_sha256": opencode["oauth_handoff_sha256"],
    }
    if any(
        sha256_file(patch_directory / filename) != expected
        for filename, expected in (
            ("apply_oauth_patch.ts", expected_oauth_inputs["oauth_patch_runner_sha256"]),
            ("oauth-handoff.ts", expected_oauth_inputs["oauth_handoff_patch_sha256"]),
            ("oauth-broker.ts", opencode["oauth_broker_sha256"]),
            ("oauth-callback.ts", opencode["oauth_callback_sha256"]),
        )
    ):
        raise ValueError("native OAuth build source does not match fixed pins")

    _, _, elf_machine = target_name(target_arch)
    if build_arch not in {"amd64", "arm64"}:
        raise ValueError("unsupported Docker build architecture")
    if source_archive_sha256 != opencode["source_archive_sha256"]:
        raise ValueError("native source archive does not match the fixed pin")
    bun_archive_expected = manifest["bun"][
        f"linux_{'amd64' if build_arch == 'amd64' else 'arm64'}_archive_sha256"
    ]
    if bun_archive_sha256 != bun_archive_expected:
        raise ValueError("native Bun archive does not match the fixed build architecture pin")

    return {
        "schema_version": BUILD_RECEIPT_SCHEMA,
        "native_version": str(opencode["version"]),
        "source_commit": str(opencode["source_commit"]),
        "source_archive_sha256": source_archive_sha256,
        "target_arch": target_arch,
        "build_arch": build_arch,
        "bun_version": str(manifest["bun"]["version"]),
        "bun_archive_sha256": bun_archive_sha256,
        "binary_sha256": sha256_file(binary),
        "binary_bytes": binary.stat().st_size,
        **expected_patch,
        "mcp_patch_script_sha256": sha256_file(patch_directory / "google_mcp_patch.py"),
        "native_integration_test": "passed",
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        **expected_oauth_inputs,
        "oauth_broker_patch_sha256": oauth_receipt["oauth_broker_sha256"],
        "oauth_callback_patch_sha256": oauth_receipt["oauth_callback_sha256"],
        "oauth_transformed_source_set_sha256": oauth_receipt["oauth_transformed_source_set_sha256"],
        "oauth_patch_tests": "passed",
        "oauth_native_tests": "passed",
    }


def install_arguments(*, target_arch: str, build_arch: str) -> list[str]:
    build_cpu = "x64" if build_arch == "amd64" else "arm64"
    target_cpu = "x64" if target_arch == "amd64" else "arm64"
    cpu_selection = build_cpu if build_cpu == target_cpu else "*"
    return [
        "install",
        "--frozen-lockfile",
        "--os=linux",
        f"--cpu={cpu_selection}",
        "--filter=@opencode/cli",
        "--filter=@opencode/app",
        "--network-concurrency=8",
        "--concurrent-scripts=2",
    ]


def compile_for_target(
    *, target_arch: str, build_arch: str, output: Path, tests_only: bool = False
) -> dict[str, object]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    opencode = manifest["opencode"]
    patch_directory = Path(__file__).parent
    pinned_local_inputs = (
        (GUARD_PATH, opencode["webfetch_guard_sha256"]),
        (
            patch_directory / "google_mcp_patch.py",
            opencode["mcp_patch_script_sha256"],
        ),
        (patch_directory / "webfetch-guard.test.ts", opencode["webfetch_guard_test_sha256"]),
        (
            patch_directory / "webfetch-native.integration.test.ts",
            opencode["native_integration_test_sha256"],
        ),
        (patch_directory / "apply_oauth_patch.ts", opencode["oauth_patch_runner_sha256"]),
        (patch_directory / "oauth-handoff.ts", opencode["oauth_handoff_sha256"]),
        (patch_directory / "oauth-handoff.test.ts", opencode["oauth_handoff_test_sha256"]),
        (patch_directory / "oauth-broker.ts", opencode["oauth_broker_sha256"]),
        (patch_directory / "oauth-broker.test.ts", opencode["oauth_broker_test_sha256"]),
        (patch_directory / "oauth-callback.ts", opencode["oauth_callback_sha256"]),
        (patch_directory / "oauth-callback.test.ts", opencode["oauth_callback_test_sha256"]),
    )
    for path, expected_digest in pinned_local_inputs:
        if sha256_file(path) != expected_digest:
            raise ValueError("pinned native WebFetch build input digest mismatch")
    bun_config = manifest["bun"]
    limits = manifest["limits"]
    build_target, output_relative, elf_machine = target_name(target_arch)
    bun_url, bun_archive_sha, bun_member, bun_binary_sha = bun_asset(manifest, build_arch)

    output.mkdir(mode=0o755, parents=True, exist_ok=True)
    work_root = _private_temp_root()
    with tempfile.TemporaryDirectory(prefix="r120-opencode-build-", dir=work_root) as work_value:
        work = Path(work_value)
        source_archive = work / "opencode-source.tar.gz"
        source_sha = download(
            str(opencode["source_archive_url"]),
            source_archive,
            limit=int(limits["source_archive_bytes"]),
        )
        if source_sha != opencode["source_archive_sha256"]:
            raise ValueError("pinned OpenCode source archive digest mismatch")
        extracted = extract_source(
            source_archive,
            work / "source",
            member_limit=int(limits["source_members"]),
            byte_limit=int(limits["source_expanded_bytes"]),
        )
        copy_upstream_license(extracted, output)

        bun_archive = work / "bun.zip"
        bun_archive_sha_actual = download(
            bun_url,
            bun_archive,
            limit=int(limits["bun_archive_bytes"]),
        )
        if bun_archive_sha_actual != bun_archive_sha:
            raise ValueError("pinned Bun archive digest mismatch")
        bun_executable = work / "bun"
        with zipfile.ZipFile(bun_archive) as archive:
            matches = [item for item in archive.infolist() if item.filename == bun_member]
            if len(matches) != 1 or matches[0].file_size > 256 * 1024 * 1024:
                raise ValueError("pinned Bun executable archive entry is invalid")
            with archive.open(matches[0]) as source, bun_executable.open("xb") as target:
                shutil.copyfileobj(source, target, length=MAX_DOWNLOAD_CHUNK)
        bun_executable.chmod(0o755)
        if bun_binary_sha and sha256_file(bun_executable) != bun_binary_sha:
            raise ValueError("pinned Bun executable digest mismatch")
        version = subprocess.run(  # noqa: S603 - executable is checksum-verified fixed Bun
            [str(bun_executable), "--version"],
            cwd=extracted,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()
        if version != bun_config["version"]:
            raise ValueError("pinned Bun version mismatch")

        oauth_test_command = [
            str(bun_executable),
            "test",
            "oauth-handoff.test.ts",
            "oauth-broker.test.ts",
            "oauth-callback.test.ts",
        ]
        _run_bun_test_suite(
            oauth_test_command,
            suite_name="OAuth helper",
            cwd=patch_directory,
            environment=_build_environment(work, str(opencode["version"])),
            timeout=180,
            expected_passes=40,
        )

        patch_receipt = apply_patch(extracted)
        oauth_transform = subprocess.run(  # noqa: S603 - fixed runner and verified source tree
            [
                str(bun_executable),
                "run",
                str(patch_directory / "apply_oauth_patch.ts"),
                str(extracted),
            ],
            cwd=patch_directory,
            env=_build_environment(work, str(opencode["version"])),
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        try:
            oauth_receipt = json.loads(oauth_transform.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("native OAuth patch returned an invalid build receipt") from exc
        if (
            not isinstance(oauth_receipt, dict)
            or set(oauth_receipt)
            != {
                "oauth_transformed_source_set_sha256",
                "oauth_broker_sha256",
                "oauth_callback_sha256",
            }
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in oauth_receipt.values()
            )
        ):
            raise ValueError("native OAuth patch returned an invalid build receipt")
        if (
            oauth_receipt["oauth_transformed_source_set_sha256"]
            != opencode["oauth_transformed_source_set_sha256"]
            or oauth_receipt["oauth_broker_sha256"] != opencode["oauth_broker_sha256"]
            or oauth_receipt["oauth_callback_sha256"] != opencode["oauth_callback_sha256"]
        ):
            raise ValueError("native OAuth transform output does not match fixed pins")
        test_source = Path(__file__).with_name("webfetch-native.integration.test.ts")
        test_helper = Path(__file__).with_name("webfetch-guard.test.ts")
        shutil.copyfile(
            test_source, extracted / "packages/core/test/webfetch-native.integration.test.ts"
        )
        shutil.copyfile(
            extracted / "packages/core/src/tool/plugin/webfetch-guard.ts",
            extracted / "packages/core/src/tool/plugin/webfetch-guard-test-copy.ts",
        )
        shutil.copyfile(test_helper, work / "webfetch-guard.test.ts")
        shutil.copyfile(GUARD_PATH, work / "webfetch-guard.ts")

        environment = _build_environment(work, str(opencode["version"]))
        subprocess.run(  # noqa: S603 - fixed executable from the checksum-verified Bun archive
            [
                str(bun_executable),
                *install_arguments(target_arch=target_arch, build_arch=build_arch),
            ],
            cwd=extracted,
            env=environment,
            check=True,
            timeout=900,
        )
        _run_bun_test_suite(
            [
                str(bun_executable),
                "test",
                "packages/core/test/webfetch-native.integration.test.ts",
                str(work / "webfetch-guard.test.ts"),
            ],
            suite_name="WebFetch integration",
            cwd=extracted,
            environment=environment,
            timeout=180,
            expected_passes=WEBFETCH_TEST_CASES,
        )
        native_oauth_command, native_oauth_cwd = _managed_oauth_test_invocation(
            bun_executable, extracted
        )
        _run_bun_test_suite(
            native_oauth_command,
            suite_name="managed OAuth native",
            cwd=native_oauth_cwd,
            environment=environment,
            timeout=240,
            expected_passes=6,
            expected_names=MANAGED_OAUTH_TEST_NAMES,
        )
        if tests_only:
            receipt = {
                **patch_receipt,
                **oauth_receipt,
                "bun_version": version,
                "bun_archive_sha256": bun_archive_sha_actual,
                "target_arch": target_arch,
                "build_arch": build_arch,
                "native_integration_test": "passed",
                "oauth_patch_tests": "passed",
                "oauth_native_tests": "passed",
            }
            (output / "tests.json").write_text(
                json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
            )
            return receipt
        output_dir = work / "out"
        subprocess.run(  # noqa: S603 - fixed Bun compiler and fixed pinned source build script
            [
                str(bun_executable),
                "run",
                "packages/cli/script/build.ts",
                "--single",
                f"--target={build_target}",
                f"--outdir={output_dir}",
                "--skip-install",
            ],
            cwd=extracted,
            env=environment,
            check=True,
            timeout=1800,
        )
        executable = output_dir / output_relative
        with executable.open("rb") as stream:
            header = stream.read(20)
        if (
            len(header) < 20
            or header[:4] != b"\x7fELF"
            or int.from_bytes(header[18:20], "little") != elf_machine
        ):
            raise ValueError("compiled OpenCode binary has the wrong target architecture")
        shutil.copyfile(executable, output / "opencode")
        (output / "opencode").chmod(0o755)
        build_receipt = _build_receipt(
            target_arch=target_arch,
            build_arch=build_arch,
            binary=output / "opencode",
            source_archive_sha256=source_sha,
            bun_archive_sha256=bun_archive_sha_actual,
            patch_receipt=patch_receipt,
            oauth_receipt=oauth_receipt,
        )
        (output / "build.json").write_text(
            json.dumps(build_receipt, sort_keys=True) + "\n", encoding="utf-8"
        )
        return build_receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-arch", choices=("amd64", "arm64"), required=True)
    parser.add_argument("--build-arch", choices=("amd64", "arm64"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tests-only", action="store_true")
    args = parser.parse_args()
    result = compile_for_target(
        target_arch=args.target_arch,
        build_arch=args.build_arch,
        output=args.output,
        tests_only=args.tests_only,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
