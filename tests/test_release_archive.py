from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify-release-archive.py"
ROOT = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location("release_archive_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)

REHEARSAL_SCRIPT = ROOT / "scripts/rehearse_schema13.py"
REHEARSAL_SPEC = importlib.util.spec_from_file_location("schema13_test_context", REHEARSAL_SCRIPT)
assert REHEARSAL_SPEC is not None and REHEARSAL_SPEC.loader is not None
rehearsal = importlib.util.module_from_spec(REHEARSAL_SPEC)
REHEARSAL_SPEC.loader.exec_module(rehearsal)


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, contents in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    return output.getvalue()


# Preserve Docker's nested layer archive so verification covers paths without extracting files.
def _docker_archive(tmp_path: Path, layer_files: dict[str, bytes]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    layer = _tar_bytes(layer_files)
    manifest = json.dumps(
        [{"Config": "config.json", "RepoTags": [], "Layers": ["layer/layer.tar"]}]
    ).encode()
    path = tmp_path / "image.tar.gz"
    with tarfile.open(path, mode="w:gz") as archive:
        for name, contents in (
            ("manifest.json", manifest),
            ("layer/layer.tar", layer),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    return path


@pytest.fixture(scope="module")
def _publisher_harness(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, str, Path]:
    base = tmp_path_factory.mktemp("prebuilt-publisher")
    repository = base / "repository"
    repository.mkdir()
    rehearsal._copy_source_tree(ROOT, repository)
    scripts = repository / "scripts"
    scripts.mkdir()
    for filename in (
        "publish-production-image.sh",
        "rehearse_schema13.py",
        "verify-release-archive.py",
    ):
        shutil.copy2(ROOT / "scripts" / filename, scripts / filename)

    rehearsal_copy = scripts / "rehearse_schema13.py"
    rehearsal_source = rehearsal_copy.read_text(encoding="utf-8")
    guard = (
        '\nif __name__ == "__main__":\n'
        "    from pathlib import Path\n"
        "    import os\n"
        '    Path(os.environ["TOOL_MARKER"]).write_text("rehearsal called")\n'
        "    raise SystemExit(91)\n"
    )
    future_import = "from __future__ import annotations\n"
    assert future_import in rehearsal_source
    rehearsal_copy.write_text(
        rehearsal_source.replace(future_import, future_import + guard, 1),
        encoding="utf-8",
    )
    (scripts / "bounded_docker_build.py").write_text(
        "from pathlib import Path\n"
        "import os\n"
        'Path(os.environ["TOOL_MARKER"]).write_text("build called")\n'
        "raise SystemExit(92)\n",
        encoding="utf-8",
    )

    context_dir = base / "candidate-context"
    source_context = rehearsal._candidate_context(repository, context_dir)
    shutil.rmtree(context_dir)
    revision = "a" * 40
    marker = base / "build-or-rehearsal-called"
    return repository, revision, source_context, marker


def _private_write(path: Path, contents: bytes) -> None:
    path.write_bytes(contents)
    path.chmod(0o600)


def _write_pair(
    repository: Path,
    revision: str,
    source_context: str,
    temporary: Path,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    pair_root = repository / "test-results" / "assistant-r120-pr-pair"
    if pair_root.exists():
        shutil.rmtree(pair_root)
    pair_root.mkdir(parents=True, mode=0o700)
    pair_root.chmod(0o700)
    candidate_name = f"signal-ledger-image-{revision}.tar.gz"
    recovery_name = f"signal-ledger-recovery-{revision}.tar.gz"
    manifest_name = f"signal-ledger-pair-{revision}.json"
    receipt_name = f"signal-ledger-pair-receipt-{revision}.json"
    candidate_id = "sha256:" + "1" * 64
    recovery_id = "sha256:" + "2" * 64
    recovery_context = "3" * 64
    base_revision = rehearsal.BASE_SHA
    base_id = rehearsal.DEPLOYED_BASELINE["image_id"]
    base_archive = rehearsal.DEPLOYED_BASELINE["release_archive_sha256"]
    base_context = "4" * 64
    overlay_files = {
        name: "5" * 64
        for name in (
            "Dockerfile",
            "src/stock_probs/api.py",
            "src/stock_probs/migrations/013_assistant_conversations.sql",
            "src/stock_probs/recovery_supervisor.py",
            "src/stock_probs/repository.py",
        )
    }
    overlay_files["src/stock_probs/migrations/013_assistant_conversations.sql"] = (
        rehearsal.MIGRATION_013_SHA256
    )
    overlay_identity = {
        "base_revision": base_revision,
        "schema_version": 13,
        "files": overlay_files,
    }
    overlay_sha = rehearsal._sha256(rehearsal._canonical_json(overlay_identity))

    candidate_source = _docker_archive(temporary / "candidate", {"app.py": b"safe candidate"})
    recovery_source = _docker_archive(temporary / "recovery", {"app.py": b"safe recovery"})
    candidate_bytes = candidate_source.read_bytes()
    recovery_bytes = recovery_source.read_bytes()
    _private_write(pair_root / candidate_name, candidate_bytes)
    _private_write(pair_root / recovery_name, recovery_bytes)
    candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
    recovery_sha = hashlib.sha256(recovery_bytes).hexdigest()

    manifest: dict[str, object] = {
        "format_version": 1,
        "repository": "eddiesoz/stock_probs",
        "revision": revision,
        "source_context_sha256": source_context,
        "migration": {
            "from_schema": 12,
            "to_schema": 13,
            "sha256": rehearsal.MIGRATION_013_SHA256,
        },
        "candidate": {
            "asset": candidate_name,
            "archive_sha256": candidate_sha,
            "archive_size": len(candidate_bytes),
            "image_id": candidate_id,
            "platform": "linux/amd64",
            "revision": revision,
            "schema_version": 13,
            "source_context_sha256": source_context,
        },
        "recovery": {
            "asset": recovery_name,
            "archive_sha256": recovery_sha,
            "archive_size": len(recovery_bytes),
            "image_id": recovery_id,
            "platform": "linux/amd64",
            "revision": revision,
            "schema_version": 13,
            "assistant_enabled": False,
            "base_revision": base_revision,
            "base_image_id": base_id,
            "base_archive_sha256": base_archive,
            "base_source_context_sha256": base_context,
            "overlay_sha256": overlay_sha,
            "source_context_sha256": recovery_context,
            "migration_sha256": rehearsal.MIGRATION_013_SHA256,
        },
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    _private_write(pair_root / manifest_name, manifest_bytes)

    receipt: dict[str, object] = {
        "status": "pass",
        "same_disposable_volume": True,
        "production_or_remote_mutation": False,
        "candidate_source_context_sha256": source_context,
        "candidate_image": {
            "id": candidate_id,
            "revision_label": revision,
            "source_context_sha256": source_context,
            "architecture": "linux/amd64",
        },
        "recovery_image": {"id": recovery_id},
        "recovery_context_sha256": recovery_context,
        "recovery_overlay": {
            **overlay_identity,
            "overlay_sha256": overlay_sha,
        },
        "migration": {
            "schema_before": 12,
            "schema_after": 13,
            "pre_migration_backup": {"schema_version": 12, "verified": True},
            "read_only_backup_verification": {
                "schema_version": 12,
                "verified": True,
                "integrity_verified": True,
            },
        },
        "candidate": {
            "stage": "candidate",
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": False},
        },
        "recovery": {
            "stage": "recovery",
            "schema_after_recovery": 13,
            "schema_versions": list(range(1, 14)),
            "historical_schema12_backup_integrity_verified": True,
            "container_profile": {"assistant_enabled": False},
        },
        "cleanup": {
            "containers_removed": True,
            "volume_removed": True,
            "verification": "task containers and volume absent",
        },
        "schema12_base_revision": base_revision,
        "schema12_base_image": {
            "image": {"id": base_id},
            "source_context_sha256": base_context,
        },
        "observed_deployment_baseline": {
            "image_id": base_id,
            "release_archive_sha256": base_archive,
        },
        "release_pair": {
            "candidate_archive_name": candidate_name,
            "candidate_archive_sha256": candidate_sha,
            "candidate_archive_size": len(candidate_bytes),
            "recovery_archive_name": recovery_name,
            "recovery_archive_sha256": recovery_sha,
            "recovery_archive_size": len(recovery_bytes),
            "manifest_name": manifest_name,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    }
    _private_write(pair_root / receipt_name, json.dumps(receipt, sort_keys=True).encode())
    return pair_root, receipt, manifest


def _publisher_tools(
    directory: Path,
    revision: str,
    candidate_id: str,
    recovery_id: str,
) -> tuple[Path, Path]:
    directory.mkdir()
    log = directory / "commands.jsonl"
    store = directory / "published-assets"
    store.mkdir()
    prefix = f"#!{sys.executable}\n"
    tools = {
        "git": """import json, os, sys
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as output:
    output.write(json.dumps(["git", *args]) + "\\n")
if args[:2] == ["rev-parse", "--verify"]:
    print(os.environ["REVISION"])
elif args[:1] == ["ls-remote"]:
    print(os.environ["REVISION"] + "\\trefs/heads/main")
elif args[:1] == ["status"]:
    pass
else:
    raise SystemExit(3)
""",
        "gh": """import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as output:
    output.write(json.dumps(["gh", *args]) + "\\n")
store = Path(os.environ["GH_ASSETS"])
if args[:2] == ["release", "view"]:
    raise SystemExit(1)
if args[:2] == ["release", "create"]:
    assets = [Path(value) for value in args[2:] if Path(value).is_file()]
    if len(assets) != 3:
        raise SystemExit(4)
    for asset in assets:
        shutil.copyfile(asset, store / asset.name)
elif args[:2] == ["release", "download"]:
    destination = Path(args[args.index("--dir") + 1])
    for asset in store.iterdir():
        shutil.copyfile(asset, destination / asset.name)
else:
    raise SystemExit(5)
""",
        "docker": f"""import json, os, sys
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as output:
    output.write(json.dumps(["docker", *args]) + "\\n")
if args[:1] == ["load"]:
    raise SystemExit(0)
if args[:1] == ["run"]:
    print("13")
    raise SystemExit(0)
if args[:2] != ["image", "inspect"]:
    raise SystemExit(6)
template = args[args.index("--format") + 1]
reference = args[-1]
if "Id" in template:
    print({candidate_id!r} if reference == {candidate_id!r} else {recovery_id!r})
elif "org.opencontainers.image.revision" in template:
    print(os.environ["REVISION"])
elif "Architecture" in template and "Os" in template:
    print("linux/amd64")
elif "Config.Entrypoint" in template:
    entrypoint = json.dumps(
        ["python", "-m", "stock_probs.recovery_supervisor"], separators=(",", ":")
    )
    command = json.dumps(
        ["serve", "--host", "0.0.0.0", "--port", "8000", "--allow-non-loopback"],
        separators=(",", ":"),
    )
    print(entrypoint + "|" + command)
elif "Config.Env" in template:
    print("[] " + (os.environ.get("FAKE_SECRET_METADATA") or "{{}}"))
else:
    raise SystemExit(7)
""",
    }
    for name, source in tools.items():
        path = directory / name
        path.write_text(prefix + source, encoding="utf-8")
        path.chmod(0o700)
    return directory, log


def _run_publisher(
    tmp_path: Path,
    harness: tuple[Path, str, str, Path],
    *,
    secret_metadata: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], Path]:
    repository, revision, source_context, marker = harness
    tools, log = _publisher_tools(
        tmp_path / "fake-bin",
        revision,
        "sha256:" + "1" * 64,
        "sha256:" + "2" * 64,
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tools}:{os.defpath}",
            "SIGNAL_LEDGER_IMAGE_PUBLISH_MODE": "prebuilt-release",
            "REVISION": revision,
            "SOURCE_CONTEXT": source_context,
            "COMMAND_LOG": str(log),
            "GH_ASSETS": str(tools / "published-assets"),
            "TOOL_MARKER": str(marker),
            "TMPDIR": str(tmp_path),
        }
    )
    if secret_metadata is not None:
        env["FAKE_SECRET_METADATA"] = secret_metadata
    else:
        env.pop("FAKE_SECRET_METADATA", None)
    result = subprocess.run(  # noqa: S603, S607 - fixed script in disposable fixture tree.
        ["/bin/bash", str(repository / "scripts/publish-production-image.sh")],
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    return result, commands, marker


def test_release_archive_verifier_accepts_clean_bounded_single_image(tmp_path: Path) -> None:
    archive = _docker_archive(tmp_path, {"app.py": b"print('safe')"})

    result = verifier.verify_image_archive(archive)

    assert result["status"] == "pass"
    assert result["archive_size"] == archive.stat().st_size
    assert result["layer_count"] == 1
    assert len(result["archive_sha256"]) == 64


def _spdx_test_source() -> tuple[bytes, tuple[tuple[int, int], ...]]:
    first = b"sk-" + b"A" * 20
    second = b"sk-" + b"B" * 20
    contents = b"X" + first + b" middle X" + second + b" " + b"x" * 23
    first_start = contents.index(first)
    second_start = contents.index(second)
    return contents, (
        (first_start, first_start + len(first)),
        (second_start, second_start + len(second)),
    )


def _configure_spdx_test_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    contents: bytes,
    spans: tuple[tuple[int, int], ...],
) -> None:
    monkeypatch.setattr(
        verifier,
        "PINNED_PUBLIC_MATCH_SOURCES",
        {
            "vendor/licenses/_spdx.py": (
                len(contents),
                hashlib.sha256(contents).hexdigest(),
                spans,
            )
        },
    )


def test_release_archive_verifier_allows_only_pinned_spdx_match_spans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents, spans = _spdx_test_source()
    _configure_spdx_test_allowlist(monkeypatch, contents, spans)
    archive = _docker_archive(tmp_path, {"vendor/licenses/_spdx.py": contents})

    result = verifier.verify_image_archive(archive)

    assert result["status"] == "pass"


def test_release_archive_verifier_rejects_spdx_file_with_added_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents, spans = _spdx_test_source()
    _configure_spdx_test_allowlist(monkeypatch, contents, spans)
    extra_match = b"sk-" + b"C" * 20
    changed = contents[: -len(extra_match)] + extra_match
    assert len(changed) == len(contents)
    archive = _docker_archive(tmp_path, {"vendor/licenses/_spdx.py": changed})

    with pytest.raises(verifier.ArchiveError, match="credential_like_bytes"):
        verifier.verify_image_archive(archive)


def test_release_archive_verifier_rejects_spdx_digest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents, spans = _spdx_test_source()
    _configure_spdx_test_allowlist(monkeypatch, contents, spans)
    changed = contents[:-1] + b"z"
    assert len(changed) == len(contents)
    archive = _docker_archive(tmp_path, {"vendor/licenses/_spdx.py": changed})

    with pytest.raises(verifier.ArchiveError, match="credential_like_bytes"):
        verifier.verify_image_archive(archive)


def test_release_archive_verifier_rejects_added_match_with_updated_source_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents, spans = _spdx_test_source()
    extra_match = b"sk-" + b"C" * 20
    changed = contents[: -len(extra_match)] + extra_match
    assert len(changed) == len(contents)
    _configure_spdx_test_allowlist(monkeypatch, contents, spans)
    monkeypatch.setattr(
        verifier,
        "PINNED_PUBLIC_MATCH_SOURCES",
        {
            "vendor/licenses/_spdx.py": (
                len(changed),
                hashlib.sha256(changed).hexdigest(),
                spans,
            )
        },
    )
    archive = _docker_archive(tmp_path, {"vendor/licenses/_spdx.py": changed})

    with pytest.raises(verifier.ArchiveError, match="credential_like_bytes"):
        verifier.verify_image_archive(archive)


def test_release_archive_verifier_pinned_spans_cross_stream_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_match = b"sk-" + b"F" * 20
    second_match = b"sk-" + b"G" * 20
    first_start = verifier.CHUNK_BYTES - 100
    second_start = verifier.CHUNK_BYTES * 2 - 10
    size = verifier.CHUNK_BYTES * 2 + 64
    contents = bytearray(b"!" * size)
    contents[first_start : first_start + len(first_match)] = first_match
    contents[second_start : second_start + len(second_match)] = second_match
    source = bytes(contents)
    spans = (
        (first_start, first_start + len(first_match)),
        (second_start, second_start + len(second_match)),
    )
    monkeypatch.setattr(
        verifier,
        "PINNED_PUBLIC_MATCH_SOURCES",
        {
            "vendor/licenses/_spdx.py": (
                size,
                hashlib.sha256(source).hexdigest(),
                spans,
            )
        },
    )

    assert verifier._scan_member("vendor/licenses/_spdx.py", io.BytesIO(source), size) == size


def test_release_archive_verifier_does_not_exempt_spdx_path_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents, spans = _spdx_test_source()
    _configure_spdx_test_allowlist(monkeypatch, contents, spans)
    archive = _docker_archive(tmp_path, {"vendor/licenses/_spdx_copy.py": contents})

    with pytest.raises(verifier.ArchiveError, match="credential_like_bytes"):
        verifier.verify_image_archive(archive)


def test_release_archive_verifier_scans_other_bytes_in_allowlisted_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents, spans = _spdx_test_source()
    other_marker = b"ghp_" + b"D" * 20
    contents += b" " + other_marker
    _configure_spdx_test_allowlist(monkeypatch, contents, spans)
    archive = _docker_archive(tmp_path, {"vendor/licenses/_spdx.py": contents})

    with pytest.raises(verifier.ArchiveError, match="credential_like_bytes"):
        verifier.verify_image_archive(archive)


def test_release_archive_verifier_rejects_quoted_environment_and_adjacent_tokens(
    tmp_path: Path,
) -> None:
    token = b"sk-" + b"E" * 24
    for contents in (
        b'"OPENAI_API_KEY=' + token + b'"',
        b"OPENAI_API_KEY=" + token,
        b"x" + token + b"y",
    ):
        archive = _docker_archive(tmp_path, {"app.py": contents})
        with pytest.raises(verifier.ArchiveError, match="credential_like_bytes"):
            verifier.verify_image_archive(archive)


@pytest.mark.parametrize(
    ("layer_files", "reason"),
    [
        ({"data.sqlite3-wal": b"database sidecar"}, "persistent_data_path"),
        ({"auth/id_rsa": b"synthetic key"}, "credential_like_path"),
        ({"home/user/.aws/credentials": b"synthetic key"}, "credential_like_path"),
        ({"app/Auth.JSON": b"synthetic token file"}, "credential_like_path"),
        (
            {"app.py": b"x" * (verifier.CHUNK_BYTES - 4) + b"ghp_" + b"A" * 30},
            "credential_like_bytes",
        ),
        ({"app.py": b"sk-ant-api03-" + b"A" * 32}, "credential_like_bytes"),
        ({"app.py": b"AIza" + b"A" * 32}, "credential_like_bytes"),
    ],
)
def test_release_archive_verifier_rejects_persistent_or_credential_material(
    tmp_path: Path,
    layer_files: dict[str, bytes],
    reason: str,
) -> None:
    archive = _docker_archive(tmp_path, layer_files)

    with pytest.raises(verifier.ArchiveError, match=reason):
        verifier.verify_image_archive(archive)


def test_release_archive_verifier_rejects_path_traversal_without_extracting(
    tmp_path: Path,
) -> None:
    archive = _docker_archive(tmp_path, {"../outside.txt": b"no extraction"})

    with pytest.raises(verifier.ArchiveError, match="unsafe_layer_path"):
        verifier.verify_image_archive(archive)


def test_publisher_uses_shared_archive_scanner_and_keeps_metadata_screen() -> None:
    script = SCRIPT.with_name("publish-production-image.sh").read_text(encoding="utf-8")
    assert 'python3 scripts/verify-release-archive.py "$ARCHIVE_PATH"' in script
    assert "SECRET_BYTES_PATTERN" not in script

    for path in ("home/.aws/credentials", "home/.ssh/config", "app/Auth.JSON"):
        assert verifier.SECRET_PATH.search(path), path
    for value in (b"sk-ant-api03-" + b"A" * 32, b"AIza" + b"A" * 32):
        assert verifier.SECRET_BYTES.search(value)
    assert "IMAGE_SCHEMA >= 13" in script
    assert "candidate/recovery GitHub release pair" in script
    assert "SIGNAL_LEDGER_IMAGE_PUBLISH_MODE:-release" in script
    assert '"$PUBLISH_MODE" == "prebuilt-release"' in script
    assert 'docker load --input "$ARCHIVE_PATH"' in script
    assert "{{json .Config.Env}} {{json .Config.Labels}}" in script
    assert "IMAGE_METADATA" in script and "RECOVERY_METADATA" in script
    assert 'validate-prebuilt-pair.py" final' in script


def test_prebuilt_release_reuses_the_verified_pair_without_build_or_rehearsal(
    tmp_path: Path,
    _publisher_harness: tuple[Path, str, str, Path],
) -> None:
    repository, revision, source_context, marker = _publisher_harness
    pair_root, _, _ = _write_pair(repository, revision, source_context, tmp_path)

    result, commands, marker = _run_publisher(tmp_path, _publisher_harness)

    assert result.returncode == 0, result.stderr
    published = json.loads(result.stdout)
    assert published["revision"] == revision
    assert published["image_id"] == "sha256:" + "1" * 64
    assert published["recovery_image_id"] == "sha256:" + "2" * 64
    assert published["archive_name"] == f"signal-ledger-image-{revision}.tar.gz"
    assert not marker.exists()
    git_calls = [command[1:] for command in commands if command[0] == "git"]
    assert ["rev-parse", "--verify", "HEAD"] in git_calls
    assert ["ls-remote", "origin", "refs/heads/main"] in git_calls
    assert ["status", "--porcelain", "--untracked-files=normal"] in git_calls
    assert not any(call[:1] == ["branch"] for call in git_calls)
    docker_calls = [command[1:] for command in commands if command[0] == "docker"]
    assert not any(call[:1] in (["save"], ["push"]) for call in docker_calls)
    assert sum(call[:1] == ["load"] for call in docker_calls) == 4
    assert any(
        call[:3]
        == [
            "image",
            "inspect",
            "--format",
        ]
        and "Config.Env" in call[3]
        for call in docker_calls
    )
    gh_calls = [command[1:] for command in commands if command[0] == "gh"]
    assert any(call[:2] == ["release", "create"] for call in gh_calls)
    assert any(call[:2] == ["release", "download"] for call in gh_calls)
    assert (pair_root / f"signal-ledger-pair-{revision}.json").is_file()


@pytest.mark.parametrize("mutation", ["receipt-status", "unsafe-mode", "manifest-image-id"])
def test_prebuilt_release_rejects_invalid_fixed_pair_before_release_create(
    tmp_path: Path,
    _publisher_harness: tuple[Path, str, str, Path],
    mutation: str,
) -> None:
    repository, revision, source_context, marker = _publisher_harness
    pair_root, receipt, manifest = _write_pair(repository, revision, source_context, tmp_path)
    receipt_path = pair_root / f"signal-ledger-pair-receipt-{revision}.json"
    if mutation == "receipt-status":
        receipt["status"] = "fail"
        _private_write(receipt_path, json.dumps(receipt, sort_keys=True).encode())
    elif mutation == "unsafe-mode":
        (pair_root / f"signal-ledger-image-{revision}.tar.gz").chmod(0o644)
    else:
        manifest["candidate"]["image_id"] = "sha256:" + "9" * 64  # type: ignore[index]
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        _private_write(pair_root / f"signal-ledger-pair-{revision}.json", manifest_bytes)
        receipt["release_pair"]["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()  # type: ignore[index]
        _private_write(receipt_path, json.dumps(receipt, sort_keys=True).encode())

    result, commands, marker = _run_publisher(tmp_path, _publisher_harness)

    assert result.returncode != 0
    assert "fixed prebuilt pair" in result.stderr
    assert not marker.exists()
    gh_calls = [command[1:] for command in commands if command[0] == "gh"]
    assert not any(call[:2] == ["release", "create"] for call in gh_calls)


def test_prebuilt_release_keeps_image_metadata_secret_screen(
    tmp_path: Path,
    _publisher_harness: tuple[Path, str, str, Path],
) -> None:
    repository, revision, source_context, marker = _publisher_harness
    _write_pair(repository, revision, source_context, tmp_path)

    result, commands, marker = _run_publisher(
        tmp_path,
        _publisher_harness,
        secret_metadata='{"SYNTHETIC":"sk-' + "A" * 30 + '"}',
    )

    assert result.returncode != 0
    assert "image metadata contains credential-like material" in result.stderr
    assert not marker.exists()
    docker_calls = [command[1:] for command in commands if command[0] == "docker"]
    assert any("Config.Env" in " ".join(call) for call in docker_calls)
    gh_calls = [command[1:] for command in commands if command[0] == "gh"]
    assert not any(call[:2] == ["release", "create"] for call in gh_calls)
