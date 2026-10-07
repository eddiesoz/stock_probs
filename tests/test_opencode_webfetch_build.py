"""The pinned native WebFetch build stays closed to unreviewed inputs."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIRECTORY = ROOT / "tools/opencode-v2-security-patch"
sys.path.insert(0, str(PATCH_DIRECTORY))

import build_native  # noqa: E402


def test_managed_oauth_suite_uses_core_relative_paths_and_exact_case_count() -> None:
    command, cwd = build_native._managed_oauth_test_invocation(
        Path("/fixed/bun"), Path("/fixed/source")
    )

    assert cwd == Path("/fixed/source/packages/core")
    assert command == [
        "/fixed/bun",
        "test",
        "--test-name-pattern=managed",
        "./test/integration.test.ts",
        "./test/plugin/provider-openai.test.ts",
        "./test/plugin/provider-opencode.test.ts",
    ]
    assert len(build_native.MANAGED_OAUTH_TEST_NAMES) == 6


def test_bun_test_summary_rejects_empty_or_incomplete_success() -> None:
    expected = "\n".join(
        [f"(pass) {name}" for name in build_native.MANAGED_OAUTH_TEST_NAMES]
        + [" 6 pass", " 0 fail", "Ran 6 tests across 3 files. [12.00ms]"]
    )
    build_native._verify_bun_test_summary(
        expected,
        "",
        expected_passes=6,
        expected_names=build_native.MANAGED_OAUTH_TEST_NAMES,
    )
    build_native._verify_bun_test_summary(
        expected.replace("[12.00ms]", "[1.20s]"),
        "",
        expected_passes=6,
        expected_names=build_native.MANAGED_OAUTH_TEST_NAMES,
    )

    with pytest.raises(ValueError, match="exact expected passing cases"):
        build_native._verify_bun_test_summary(" 0 pass\n 0 fail\n 6 skip\n", "", expected_passes=6)

    with pytest.raises(ValueError, match="exact expected passing cases"):
        build_native._verify_bun_test_summary(" 5 pass\n 0 fail\n", "", expected_passes=6)

    with pytest.raises(ValueError, match="exact expected passing cases"):
        build_native._verify_bun_test_summary(
            " 6 pass\n 0 fail\n", "", expected_passes=6, expected_names=("missing",)
        )


def test_webfetch_suite_summary_requires_the_guard_and_native_case_inventory() -> None:
    """The native build accepts exactly the 49 guard and 8 integration cases."""

    assert (
        build_native.WEBFETCH_GUARD_TEST_CASES,
        build_native.WEBFETCH_NATIVE_INTEGRATION_TEST_CASES,
        build_native.WEBFETCH_TEST_CASES,
    ) == (49, 8, 57)
    expected = " 57 pass\n 0 fail\nRan 57 tests across 2 files. [1.23s]"
    build_native._verify_bun_test_summary(expected, "", expected_passes=57)

    with pytest.raises(ValueError, match="exact expected passing cases"):
        build_native._verify_bun_test_summary(
            " 40 pass\n 0 fail\nRan 40 tests across 2 files. [1.23s]",
            "",
            expected_passes=build_native.WEBFETCH_TEST_CASES,
        )


def test_bun_failure_projection_keeps_only_fixed_relative_source_frames() -> None:
    output = (
        "Error: fixture-only detail\n"
        "    at callback (/tmp/private/source/packages/core/test/"
        "integration.test.ts:123:45)\n"
        "    at callback (/tmp/private/source/other/secret.ts:7:9)\n"
    )

    assert build_native._safe_bun_test_frames(output) == (
        "packages/core/test/integration.test.ts:123:45",
    )


def test_bun_failure_categories_expose_only_matcher_or_exception_class() -> None:
    output = (
        "(fail) fixture connect case [1.20ms]\n"
        "AssertionError: expected a status\n"
        'Expected: "complete"\n'
        'Received: "synthetic-secret-marker"\n'
        "at connect (/tmp/private/source/packages/core/src/integration.ts:5:8)\n"
        "(fail) fixture cancellation case [2.00ms]\n"
        "TimeoutError: fixture endpoint query=private-value\n"
    )

    categories = build_native._safe_bun_failure_categories(output)

    assert categories == (
        "fixture connect case:assertion_mismatch:expected_status_complete:received_string",
        "fixture cancellation case:exception_TimeoutError",
    )
    assert "synthetic-secret-marker" not in repr(categories)
    assert "private-value" not in repr(categories)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/anomalyco/opencode/archive.tar.gz",
        "https://user@github.com/anomalyco/opencode/archive.tar.gz",
        "https://github.com:8443/anomalyco/opencode/archive.tar.gz",
        "https://127.0.0.1/archive.tar.gz",
        "https://github.com/archive.tar.gz#fragment",
    ],
)
def test_download_rejects_unpinned_url_shapes_before_open(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = False

    def unexpected_open(*_args: object, **_kwargs: object) -> None:
        nonlocal opened
        opened = True
        raise AssertionError("disallowed download reached the opener")

    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_handlers: type("Opener", (), {"open": unexpected_open})(),
    )

    with pytest.raises(ValueError, match="outside the native build allowlist"):
        build_native.download(url, Path("unused-download"), limit=1024)

    assert not opened


def test_redirect_destination_is_rejected_before_default_handler() -> None:
    request = urllib.request.Request("https://github.com/anomalyco/opencode/archive.tar.gz")
    handler = build_native._AllowlistedRedirectHandler()

    with pytest.raises(ValueError, match="outside the native build allowlist"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/private")


def test_redirect_chain_has_a_fixed_bound() -> None:
    request = urllib.request.Request("https://github.com/anomalyco/opencode/archive.tar.gz")
    handler = build_native._AllowlistedRedirectHandler()

    for index in range(build_native.MAX_DOWNLOAD_REDIRECTS):
        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            f"https://github.com/archive/{index}",
        )
        assert redirected is not None

    with pytest.raises(ValueError, match="redirect bound"):
        handler.redirect_request(
            request, None, 302, "Found", {}, "https://github.com/archive/final"
        )


def test_build_environment_does_not_inherit_credentials_or_project_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "GITHUB_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "OPENCODE_DISABLE_PROJECT_CONFIG",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(name, "synthetic-secret-marker")

    environment = build_native._build_environment(tmp_path, "2.0.7")

    assert environment == {
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PATH": build_native.BUILD_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CI": "1",
        "OPENCODE_CHANNEL": "latest",
        "OPENCODE_VERSION": "2.0.7",
        "HUSKY": "0",
    }
    assert "synthetic-secret-marker" not in repr(environment)


def test_build_requires_private_caller_owned_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    monkeypatch.setattr(build_native.tempfile, "tempdir", str(private))
    assert build_native._private_temp_root() == private

    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    monkeypatch.setattr(build_native.tempfile, "tempdir", str(shared))
    with pytest.raises(ValueError, match="must be private"):
        build_native._private_temp_root()


def test_native_build_receipt_has_the_exact_guarded_artifact_contract(tmp_path: Path) -> None:
    manifest = json.loads(build_native.MANIFEST_PATH.read_text(encoding="utf-8"))
    opencode = manifest["opencode"]
    binary = tmp_path / "opencode"
    binary.write_bytes(b"synthetic native binary")
    patch_receipt = {
        "opencode_version": opencode["version"],
        "source_commit": opencode["source_commit"],
        "webfetch_source_sha256": opencode["webfetch_sha256"],
        "webfetch_patched_sha256": opencode["webfetch_patched_sha256"],
        "webfetch_guard_sha256": opencode["webfetch_guard_sha256"],
        "mcp_tool_source_sha256": opencode["mcp_tool_sha256"],
        "mcp_tool_patched_sha256": opencode["mcp_tool_patched_sha256"],
    }
    oauth_receipt = {
        "oauth_broker_sha256": opencode["oauth_broker_sha256"],
        "oauth_callback_sha256": opencode["oauth_callback_sha256"],
        "oauth_transformed_source_set_sha256": opencode["oauth_transformed_source_set_sha256"],
    }

    receipt = build_native._build_receipt(
        target_arch="amd64",
        build_arch="amd64",
        binary=binary,
        source_archive_sha256=opencode["source_archive_sha256"],
        bun_archive_sha256=manifest["bun"]["linux_amd64_archive_sha256"],
        patch_receipt=patch_receipt,
        oauth_receipt=oauth_receipt,
    )

    assert set(receipt) == {
        "schema_version",
        "native_version",
        "source_commit",
        "source_archive_sha256",
        "target_arch",
        "build_arch",
        "bun_version",
        "bun_archive_sha256",
        "binary_sha256",
        "binary_bytes",
        "webfetch_source_sha256",
        "webfetch_patched_sha256",
        "webfetch_guard_sha256",
        "mcp_tool_source_sha256",
        "mcp_tool_patched_sha256",
        "mcp_patch_script_sha256",
        "native_integration_test",
        "manifest_sha256",
        "oauth_patch_runner_sha256",
        "oauth_handoff_patch_sha256",
        "oauth_broker_patch_sha256",
        "oauth_callback_patch_sha256",
        "oauth_transformed_source_set_sha256",
        "oauth_patch_tests",
        "oauth_native_tests",
    }
    assert receipt["schema_version"] == 1
    assert receipt["native_version"] == "2.0.7"
    assert receipt["binary_bytes"] == len(b"synthetic native binary")
    assert receipt["native_integration_test"] == "passed"
    assert receipt["oauth_patch_tests"] == "passed"
    assert receipt["oauth_native_tests"] == "passed"

    with pytest.raises(ValueError, match="OAuth transform receipt"):
        build_native._build_receipt(
            target_arch="amd64",
            build_arch="amd64",
            binary=binary,
            source_archive_sha256=opencode["source_archive_sha256"],
            bun_archive_sha256=manifest["bun"]["linux_amd64_archive_sha256"],
            patch_receipt=patch_receipt,
            oauth_receipt={**oauth_receipt, "oauth_transformed_source_set_sha256": "0" * 64},
        )


def test_pinned_upstream_license_is_copied_as_a_bounded_regular_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_root.mkdir()
    license_text = b"MIT License\nCopyright (c) OpenCode contributors\n"
    (source_root / "LICENSE").write_bytes(license_text)

    result = build_native.copy_upstream_license(source_root, output_dir)

    assert result == output_dir / "opencode-LICENSE"
    assert result.read_bytes() == license_text
    assert result.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("invalid_source", ("symlink", "oversized", "missing"))
def test_pinned_upstream_license_rejects_invalid_files(tmp_path: Path, invalid_source: str) -> None:
    source_root = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_root.mkdir()
    license_path = source_root / "LICENSE"
    if invalid_source == "symlink":
        target = source_root / "target"
        target.write_text("MIT License\n", encoding="utf-8")
        license_path.symlink_to(target)
    elif invalid_source == "oversized":
        license_path.write_bytes(b"x" * (build_native.MAX_LICENSE_BYTES + 1))

    with pytest.raises((OSError, ValueError)):
        build_native.copy_upstream_license(source_root, output_dir)


@pytest.mark.parametrize(
    ("architecture", "expected"),
    [
        ("amd64", ("opencode-linux-x64-baseline", "cli-linux-x64-baseline/bin/opencode", 62)),
        ("arm64", ("opencode-linux-arm64", "cli-linux-arm64/bin/opencode", 183)),
    ],
)
def test_native_binary_targets_are_explicit(
    architecture: str, expected: tuple[str, str, int]
) -> None:
    assert build_native.target_name(architecture) == expected


def test_native_binary_target_rejects_unknown_architecture() -> None:
    with pytest.raises(ValueError, match="unsupported Docker target architecture"):
        build_native.target_name("s390x")


def test_build_install_is_filtered_to_app_cli_and_required_cpu_variants() -> None:
    amd64 = build_native.install_arguments(target_arch="amd64", build_arch="amd64")
    arm64_cross = build_native.install_arguments(target_arch="arm64", build_arch="amd64")

    assert "--os=linux" in amd64
    assert "--cpu=x64" in amd64
    assert "--filter=@opencode/cli" in amd64
    assert "--filter=@opencode/app" in amd64
    assert "--cpu=*" in arm64_cross
    assert all("darwin" not in item and "win32" not in item for item in arm64_cross)
