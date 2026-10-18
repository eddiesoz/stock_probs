from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import signal
import stat
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/hotfix_release_transport.py"
SPEC = importlib.util.spec_from_file_location("hotfix_release_transport_for_tests", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
transport = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transport
SPEC.loader.exec_module(transport)


def _write_private(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    path.chmod(0o600)


def _package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, bytes, bytes]:
    helper_revision = "a" * 40
    candidate = b"fixed candidate archive fixture"
    predecessor = b"fixed predecessor archive fixture"
    monkeypatch.setattr(
        transport, "HOTFIX_CANDIDATE_ARCHIVE_SHA256", hashlib.sha256(candidate).hexdigest()
    )
    monkeypatch.setattr(transport, "HOTFIX_CANDIDATE_ARCHIVE_SIZE", len(candidate))
    monkeypatch.setattr(
        transport, "PRODUCTION_PREDECESSOR_ARCHIVE_SHA256", hashlib.sha256(predecessor).hexdigest()
    )
    monkeypatch.setattr(transport, "PRODUCTION_PREDECESSOR_ARCHIVE_SIZE", len(predecessor))

    root = tmp_path / "package"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    scratch = tmp_path / "approved-scratch"
    scratch.mkdir(mode=0o700)
    scratch.chmod(0o700)
    monkeypatch.setattr(transport, "HOTFIX_SCRATCH_ROOT", scratch)
    _write_private(
        root / transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION), candidate
    )
    _write_private(
        root / transport._fixed_archive_name(transport.PRODUCTION_PREDECESSOR_REVISION), predecessor
    )

    manifest_name = f"signal-ledger-pair-{helper_revision}.json"
    manifest = transport._expected_manifest(helper_revision)
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    _write_private(root / manifest_name, manifest_bytes)
    receipt: dict[str, Any] = {
        "status": "prepared",
        "contract": transport.HOTFIX_PAIR_CONTRACT,
        "helper_source_revision": helper_revision,
        "hotfix_pull_number": 9,
        "candidate_archive_name": transport._fixed_archive_name(
            transport.HOTFIX_CANDIDATE_REVISION
        ),
        "candidate_archive_sha256": transport.HOTFIX_CANDIDATE_ARCHIVE_SHA256,
        "candidate_archive_size": transport.HOTFIX_CANDIDATE_ARCHIVE_SIZE,
        "candidate_image": {
            "architecture": "linux/amd64",
            "id": transport.HOTFIX_CANDIDATE_IMAGE_ID,
            "revision_label": transport.HOTFIX_CANDIDATE_REVISION,
            "source_context_sha256": transport.HOTFIX_CANDIDATE_CONTEXT_SHA256,
        },
        "recovery_archive_name": transport._fixed_archive_name(
            transport.PRODUCTION_PREDECESSOR_REVISION
        ),
        "recovery_archive_sha256": transport.PRODUCTION_PREDECESSOR_ARCHIVE_SHA256,
        "recovery_archive_size": transport.PRODUCTION_PREDECESSOR_ARCHIVE_SIZE,
        "recovery_image": {
            "architecture": "linux/amd64",
            "id": transport.PRODUCTION_PREDECESSOR_IMAGE_ID,
            "revision_label": transport.PRODUCTION_PREDECESSOR_REVISION,
            "source_context_sha256": transport.PRODUCTION_PREDECESSOR_CONTEXT_SHA256,
        },
        "prior_pair_manifest_sha256": transport.PRODUCTION_PREDECESSOR_PRIOR_PAIR_SHA256,
        "migration_commands": 0,
        "restore_commands": 0,
        "manifest_name": manifest_name,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    _write_private(
        root / "package-receipt.json",
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
    )
    return root, helper_revision, candidate, predecessor


class _GitHub:
    def __init__(self) -> None:
        self.releases: dict[str, dict[str, Any]] = {}
        self.events: list[tuple[str, str]] = []
        self.corrupt_download = False

    def command(self, argv: list[str], **_: object) -> Any:
        assert argv[0] == "gh"
        assert argv[1] == "release"
        operation = argv[2]
        tag = argv[3]
        if operation == "create":
            if tag in self.releases:
                return _result(argv, 1, "release already exists")
            repo_index = argv.index("--repo")
            assets = [Path(item) for item in argv[4:repo_index]]
            target = argv[argv.index("--target") + 1]
            self.releases[tag] = {
                "target": target,
                "assets": {asset.name: asset.read_bytes() for asset in assets},
                "upload_names": [asset.name for asset in assets],
            }
            self.events.append(("create", tag))
            return _result(argv)
        if operation == "view":
            release = self.releases.get(tag)
            if release is None:
                return _result(argv, 1, "release not found")
            query = argv[argv.index("--jq") + 1]
            needle = query.split('.name=="', 1)[1].split('"', 1)[0]
            matches = [
                {"name": name, "size": len(content)}
                for name, content in release["assets"].items()
                if name == needle
            ][:2]
            value = {
                "targetCommitish": release["target"],
                "assetCount": len(release["assets"]),
                "matches": matches,
            }
            self.events.append(("view", tag))
            return _result(argv, stdout=json.dumps(value))
        if operation == "download":
            release = self.releases.get(tag)
            if release is None:
                return _result(argv, 1, "release not found")
            asset_name = argv[argv.index("--pattern") + 1]
            content = release["assets"].get(asset_name)
            if content is None:
                return _result(argv, 1, "asset not found")
            directory = Path(argv[argv.index("--dir") + 1])
            output = directory / asset_name
            output.write_bytes(content)
            output.chmod(0o644)
            if self.corrupt_download:
                output.write_bytes(b"corrupted after download")
            self.events.append(("download", tag))
            return _result(argv)
        raise AssertionError(f"unexpected gh operation: {operation}")


def _result(argv: list[str], returncode: int = 0, stderr: str = "", stdout: str = "") -> Any:
    from subprocess import CompletedProcess

    return CompletedProcess(argv, returncode, stdout, stderr)


def _bind_publisher(
    monkeypatch: pytest.MonkeyPatch,
    github: _GitHub,
    events: list[tuple[str, str]],
) -> None:
    monkeypatch.setattr(
        transport, "_validate_current_source", lambda revision: events.append(("source", revision))
    )
    monkeypatch.setattr(
        transport, "_scan_archive", lambda archive: events.append(("scan", archive.name))
    )
    monkeypatch.setattr(transport, "_require_hotfix_scratch_mount", lambda: None)

    def invoke(argv: list[str], **kwargs: object) -> str:
        result = github.command(argv, **kwargs)
        if result.returncode != 0:
            raise transport.PublicationError("bounded_command_failed")
        return result.stdout

    monkeypatch.setattr(transport, "_command", invoke)


def test_package_binds_both_exact_archives_and_helper_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, _, _ = _package(tmp_path, monkeypatch)

    package = transport.validate_package(root, revision)

    assert package.helper_revision == revision
    assert package.manifest_name == f"signal-ledger-pair-{revision}.json"
    assert package.candidate.revision == transport.HOTFIX_CANDIDATE_REVISION
    assert package.predecessor.revision == transport.PRODUCTION_PREDECESSOR_REVISION


def test_package_rejects_changed_candidate_archive_before_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, _, _ = _package(tmp_path, monkeypatch)
    candidate_path = root / transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION)
    candidate_path.write_bytes(b"changed")

    with pytest.raises(transport.PublicationError, match="hotfix_archive_identity_mismatch"):
        transport.validate_package(root, revision)


def test_snapshot_rejects_source_mutation_during_stream_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.bin"
    original = b"fixed bytes while a concurrent writer changes the source"
    _write_private(source, original)
    source_identity = source.stat()
    destination = tmp_path / "snapshot.bin"
    real_read = os.read
    changed = False

    def mutate_after_source_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        chunk = real_read(descriptor, size)
        if not changed and os.fstat(descriptor).st_ino == source_identity.st_ino and chunk:
            with source.open("r+b", buffering=0) as writer:
                writer.write(b"X" * len(original))
                os.fsync(writer.fileno())
            changed = True
        return chunk

    monkeypatch.setattr(transport.os, "read", mutate_after_source_read)

    with pytest.raises(transport.PublicationError, match="package_file_changed"):
        transport._copy_verified_package_file(
            source,
            destination,
            expected_sha256=hashlib.sha256(original).hexdigest(),
            expected_size=len(original),
            maximum=1024,
            mismatch_error="hotfix_archive_identity_mismatch",
        )

    assert changed


def test_candidate_publication_uploads_only_the_reviewed_candidate_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, candidate, _ = _package(tmp_path, monkeypatch)
    github = _GitHub()
    events: list[tuple[str, str]] = []
    _bind_publisher(monkeypatch, github, events)

    result = transport.publish("hotfix-candidate", revision, root)

    tag = f"signal-ledger-{transport.HOTFIX_CANDIDATE_REVISION}"
    assert result["status"] == "published_candidate_asset_verified"
    assert github.releases[tag]["target"] == transport.HOTFIX_CANDIDATE_REVISION
    assert github.releases[tag]["upload_names"] == [
        transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION)
    ]
    assert github.releases[tag]["assets"][github.releases[tag]["upload_names"][0]] == candidate
    assert events == [
        ("source", revision),
        ("scan", transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION)),
        ("scan", transport._fixed_archive_name(transport.PRODUCTION_PREDECESSOR_REVISION)),
    ]
    assert [kind for kind, _ in github.events] == ["create", "view", "download"]


def test_candidate_upload_uses_the_verified_snapshot_after_originals_change_during_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, candidate, predecessor = _package(tmp_path, monkeypatch)
    github = _GitHub()
    events: list[tuple[str, str]] = []
    _bind_publisher(monkeypatch, github, events)
    original_scan_names: list[str] = []
    changed_originals = False

    def mutate_inputs_during_scan(archive: transport.Archive) -> None:
        nonlocal changed_originals
        original_scan_names.append(archive.name)
        assert archive.path.parent != root
        expected = (
            candidate if archive.revision == transport.HOTFIX_CANDIDATE_REVISION else predecessor
        )
        assert archive.path.read_bytes() == expected
        assert stat.S_IMODE(archive.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(archive.path.parent.stat().st_mode) == 0o700
        if not changed_originals:
            (root / archive.name).write_bytes(b"concurrent package rewrite")
            (
                root / transport._fixed_archive_name(transport.PRODUCTION_PREDECESSOR_REVISION)
            ).write_bytes(b"concurrent predecessor rewrite")
            (root / f"signal-ledger-pair-{revision}.json").write_bytes(
                b"concurrent manifest rewrite"
            )
            changed_originals = True

    monkeypatch.setattr(transport, "_scan_archive", mutate_inputs_during_scan)

    result = transport.publish("hotfix-candidate", revision, root)

    tag = f"signal-ledger-{transport.HOTFIX_CANDIDATE_REVISION}"
    asset_name = transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION)
    assert result["status"] == "published_candidate_asset_verified"
    assert changed_originals
    assert original_scan_names == [
        transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION),
        transport._fixed_archive_name(transport.PRODUCTION_PREDECESSOR_REVISION),
    ]
    assert github.releases[tag]["assets"][asset_name] == candidate


def test_pair_publication_reads_back_exact_public_archives_then_uploads_only_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, candidate, predecessor = _package(tmp_path, monkeypatch)
    package = transport.validate_package(root, revision)
    candidate_tag = f"signal-ledger-{transport.HOTFIX_CANDIDATE_REVISION}"
    predecessor_tag = f"signal-ledger-{transport.PRODUCTION_PREDECESSOR_REVISION}"
    github = _GitHub()
    github.releases[candidate_tag] = {
        "target": transport.HOTFIX_CANDIDATE_REVISION,
        "assets": {package.candidate.name: candidate},
        "upload_names": [package.candidate.name],
    }
    # The original 5ad release also carries a recovery asset; select only its candidate image.
    github.releases[predecessor_tag] = {
        "target": transport.PRODUCTION_PREDECESSOR_REVISION,
        "assets": {
            package.predecessor.name: predecessor,
            (
                f"signal-ledger-recovery-{transport.PRODUCTION_PREDECESSOR_REVISION}.tar.gz"
            ): b"older unrelated recovery archive",
        },
        "upload_names": [],
    }
    events: list[tuple[str, str]] = []
    _bind_publisher(monkeypatch, github, events)

    result = transport.publish("hotfix-pair", revision, root)

    pair_tag = f"signal-ledger-hotfix-pair-{revision}"
    assert result["status"] == "published_hotfix_pair_asset_verified"
    assert github.releases[pair_tag]["target"] == revision
    assert github.releases[pair_tag]["upload_names"] == [package.manifest_name]
    assert (
        github.releases[pair_tag]["assets"][package.manifest_name]
        == package.manifest_path.read_bytes()
    )
    assert [kind for kind, _ in github.events] == [
        "view",
        "view",
        "download",
        "download",
        "create",
        "view",
        "download",
    ]
    assert [value for kind, value in events if kind == "scan"] == [
        package.candidate.name,
        package.predecessor.name,
    ]


def test_pair_upload_uses_verified_manifest_snapshot_after_sources_change_during_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, candidate, predecessor = _package(tmp_path, monkeypatch)
    package = transport.validate_package(root, revision)
    expected_manifest = package.manifest_path.read_bytes()
    candidate_tag = f"signal-ledger-{transport.HOTFIX_CANDIDATE_REVISION}"
    predecessor_tag = f"signal-ledger-{transport.PRODUCTION_PREDECESSOR_REVISION}"
    github = _GitHub()
    github.releases[candidate_tag] = {
        "target": transport.HOTFIX_CANDIDATE_REVISION,
        "assets": {package.candidate.name: candidate},
        "upload_names": [package.candidate.name],
    }
    github.releases[predecessor_tag] = {
        "target": transport.PRODUCTION_PREDECESSOR_REVISION,
        "assets": {package.predecessor.name: predecessor},
        "upload_names": [],
    }
    events: list[tuple[str, str]] = []
    _bind_publisher(monkeypatch, github, events)
    changed_originals = False

    def mutate_inputs_during_scan(archive: transport.Archive) -> None:
        nonlocal changed_originals
        events.append(("scan", archive.name))
        assert archive.path.parent != root
        expected = (
            candidate if archive.revision == transport.HOTFIX_CANDIDATE_REVISION else predecessor
        )
        assert archive.path.read_bytes() == expected
        assert stat.S_IMODE(archive.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(archive.path.parent.stat().st_mode) == 0o700
        if not changed_originals:
            (root / package.candidate.name).write_bytes(b"concurrent candidate rewrite")
            (root / package.predecessor.name).write_bytes(b"concurrent predecessor rewrite")
            (root / package.manifest_name).write_bytes(b"concurrent manifest rewrite")
            changed_originals = True

    monkeypatch.setattr(transport, "_scan_archive", mutate_inputs_during_scan)

    result = transport.publish("hotfix-pair", revision, root)

    pair_tag = f"signal-ledger-hotfix-pair-{revision}"
    assert result["status"] == "published_hotfix_pair_asset_verified"
    assert changed_originals
    assert github.releases[pair_tag]["assets"][package.manifest_name] == expected_manifest
    assert github.releases[pair_tag]["upload_names"] == [package.manifest_name]


def test_pair_release_collision_fails_without_overwriting_existing_helper_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, candidate, predecessor = _package(tmp_path, monkeypatch)
    package = transport.validate_package(root, revision)
    candidate_tag = f"signal-ledger-{transport.HOTFIX_CANDIDATE_REVISION}"
    predecessor_tag = f"signal-ledger-{transport.PRODUCTION_PREDECESSOR_REVISION}"
    pair_tag = f"signal-ledger-hotfix-pair-{revision}"
    github = _GitHub()
    github.releases[candidate_tag] = {
        "target": transport.HOTFIX_CANDIDATE_REVISION,
        "assets": {package.candidate.name: candidate},
        "upload_names": [package.candidate.name],
    }
    github.releases[predecessor_tag] = {
        "target": transport.PRODUCTION_PREDECESSOR_REVISION,
        "assets": {package.predecessor.name: predecessor},
        "upload_names": [package.predecessor.name],
    }
    github.releases[pair_tag] = {
        "target": revision,
        "assets": {"unexpected.json": b"preserve existing release"},
        "upload_names": ["unexpected.json"],
    }
    before = copy.deepcopy(github.releases[pair_tag])
    events: list[tuple[str, str]] = []
    _bind_publisher(monkeypatch, github, events)

    with pytest.raises(transport.PublicationError, match="bounded_command_failed"):
        transport.publish("hotfix-pair", revision, root)

    assert github.releases[pair_tag] == before
    assert [kind for kind, _ in github.events].count("create") == 0


def test_candidate_release_collision_fails_without_overwrite_or_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, candidate, _ = _package(tmp_path, monkeypatch)
    tag = f"signal-ledger-{transport.HOTFIX_CANDIDATE_REVISION}"
    github = _GitHub()
    github.releases[tag] = {
        "target": transport.HOTFIX_CANDIDATE_REVISION,
        "assets": {transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION): candidate},
        "upload_names": [transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION)],
    }
    before = copy.deepcopy(github.releases)
    events: list[tuple[str, str]] = []
    _bind_publisher(monkeypatch, github, events)

    with pytest.raises(transport.PublicationError, match="bounded_command_failed"):
        transport.publish("hotfix-candidate", revision, root)

    assert github.releases == before
    assert [kind for kind, _ in github.events] == []


def test_readback_digest_mismatch_fails_after_remote_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, _, _ = _package(tmp_path, monkeypatch)
    github = _GitHub()
    github.corrupt_download = True

    events: list[tuple[str, str]] = []
    _bind_publisher(monkeypatch, github, events)

    with pytest.raises(transport.PublicationError, match="published_asset_readback_mismatch"):
        transport.publish("hotfix-candidate", revision, root)

    assert f"signal-ledger-{transport.HOTFIX_CANDIDATE_REVISION}" in github.releases


def test_both_archive_scans_must_pass_before_candidate_release_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision, _, _ = _package(tmp_path, monkeypatch)
    github = _GitHub()
    scanned: list[str] = []

    def reject_predecessor(archive: transport.Archive) -> None:
        scanned.append(archive.name)
        if archive.revision == transport.PRODUCTION_PREDECESSOR_REVISION:
            raise transport.PublicationError("release_archive_scan_mismatch")

    monkeypatch.setattr(transport, "_validate_current_source", lambda _: None)
    monkeypatch.setattr(transport, "_require_hotfix_scratch_mount", lambda: None)
    monkeypatch.setattr(transport, "_scan_archive", reject_predecessor)
    monkeypatch.setattr(transport, "_command", github.command)

    with pytest.raises(transport.PublicationError, match="release_archive_scan_mismatch"):
        transport.publish("hotfix-candidate", revision, root)

    assert scanned == [
        transport._fixed_archive_name(transport.HOTFIX_CANDIDATE_REVISION),
        transport._fixed_archive_name(transport.PRODUCTION_PREDECESSOR_REVISION),
    ]
    assert github.releases == {}


def test_hotfix_dispatch_precedes_the_normal_build_and_release_path() -> None:
    script = (SCRIPT.parent / "publish-production-image.sh").read_text(encoding="utf-8")
    dispatch = script.index('if [[ "$PUBLISH_MODE" == "hotfix-candidate"')
    source_gate = script.index('REMOTE_MAIN="$(git ls-remote origin refs/heads/main')
    build_root = script.index('TEMP_ROOT="$(mktemp -d)"')

    assert source_gate < dispatch < build_root
    assert 'exec python3 scripts/hotfix_release_transport.py "$PUBLISH_MODE" "$REVISION"' in script
    assert (
        'if [[ "$PUBLISH_MODE" == "release" || "$PUBLISH_MODE" == "prebuilt-release" ]]' in script
    )


def test_normal_v1_release_locator_is_unchanged() -> None:
    revision = "b" * 40
    assert transport._fixed_archive_name(revision) == f"signal-ledger-image-{revision}.tar.gz"
    assert (
        transport._expected_manifest("a" * 40)["candidate"]["revision"]
        == transport.HOTFIX_CANDIDATE_REVISION
    )


def test_reviewed_candidate_and_original_5ad_recovery_pins_are_exact() -> None:
    assert transport.HOTFIX_CANDIDATE_REVISION == "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
    assert transport.HOTFIX_CANDIDATE_IMAGE_ID == (
        "sha256:52154c40d23c785f1d5522977c3add663ba6d3bffcc6c669cc2732c52cfdd196"
    )
    assert transport.HOTFIX_CANDIDATE_CONTEXT_SHA256 == (
        "a332dca5d27f4bb6fda4673e826096158c038e218f6291f01069951378c4fbae"
    )
    assert transport.HOTFIX_BUILD_RECEIPT_SHA256 == (
        "d3529f24499ea2f3b7921055a4308be019798b7be083fc6e75f1ad94b205b0b5"
    )
    assert transport.HOTFIX_CANDIDATE_ARCHIVE_SHA256 == (
        "c0e9d0fe89e53fef4c8f3173a5f2403d32a32f69b7591bc89e7d7ae129199f82"
    )
    assert transport.HOTFIX_CANDIDATE_ARCHIVE_SIZE == 202_160_947
    assert transport.RELEASE_SCANNER_SHA256 == (
        "75e3f8c07e62a36fb0e11ad8ef48996971148a890688bbb31bd9eb0d3d791670"
    )
    assert transport.PRODUCTION_PREDECESSOR_REVISION == "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"
    assert transport.PRODUCTION_PREDECESSOR_IMAGE_ID == (
        "sha256:78746f600815cac1941a9060f91bba41aca08f363714db466200c2d77e8ad7b1"
    )
    assert transport.PRODUCTION_PREDECESSOR_ARCHIVE_SHA256 == (
        "99b198f169958e63a4b1ee2380fa805c82a3bc75352d17f8feae2e4ad41185e5"
    )
    assert transport.PRODUCTION_PREDECESSOR_ARCHIVE_SIZE == 202_156_038
    assert hashlib.sha256(transport.SCANNER_PATH.read_bytes()).hexdigest() == (
        transport.RELEASE_SCANNER_SHA256
    )


def test_archive_scan_uses_the_exact_pinned_scanner_and_archive_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner = tmp_path / "verify-release-archive.py"
    scanner.write_bytes(b"approved scanner fixture")
    scanner.chmod(0o600)
    archive_path = tmp_path / "candidate.tar.gz"
    archive_path.write_bytes(b"reviewed archive bytes")
    archive = transport.Archive(
        name="signal-ledger-image-" + "c" * 40 + ".tar.gz",
        path=archive_path,
        sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        size=archive_path.stat().st_size,
        image_id=transport.HOTFIX_CANDIDATE_IMAGE_ID,
        revision=transport.HOTFIX_CANDIDATE_REVISION,
        source_context_sha256=transport.HOTFIX_CANDIDATE_CONTEXT_SHA256,
    )
    monkeypatch.setattr(transport, "SCANNER_PATH", scanner)
    monkeypatch.setattr(
        transport, "RELEASE_SCANNER_SHA256", hashlib.sha256(scanner.read_bytes()).hexdigest()
    )
    calls: list[list[str]] = []

    def scan_command(argv: list[str], **_: object) -> str:
        calls.append(argv)
        return json.dumps(
            {
                "status": "pass",
                "archive_sha256": archive.sha256,
                "archive_size": archive.size,
                "layer_count": 2,
            }
        )

    monkeypatch.setattr(transport, "_command", scan_command)
    transport._scan_archive(archive)

    assert calls == [[sys.executable, str(scanner), str(archive_path)]]
    monkeypatch.setattr(transport, "RELEASE_SCANNER_SHA256", "0" * 64)
    with pytest.raises(transport.PublicationError, match="reviewed_release_scanner_unavailable"):
        transport._scan_archive(archive)


def test_readback_scratch_requires_the_verified_uuid_and_private_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "approved-scratch"
    scratch.mkdir(mode=0o700)
    scratch.chmod(0o700)
    monkeypatch.setattr(transport, "HOTFIX_SCRATCH_ROOT", scratch)
    monkeypatch.setattr(transport, "_command", lambda argv: transport.HOTFIX_SCRATCH_UUID)

    with transport._temporary_readback() as directory:
        metadata = Path(directory).stat()
        assert Path(directory).parent == scratch
        assert stat.S_IMODE(metadata.st_mode) == 0o700

    monkeypatch.setattr(transport, "_command", lambda argv: "wrong-device")
    with pytest.raises(
        transport.PublicationError, match="release_readback_scratch_identity_mismatch"
    ):
        transport._require_hotfix_scratch_mount()


def test_archive_hashing_streams_without_loading_the_file_into_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.tar.gz"
    contents = b"archive-chunk" * 200_000
    path.write_bytes(contents)
    path.chmod(0o600)
    monkeypatch.setattr(
        transport,
        "_read_regular_file",
        lambda *args, **kwargs: pytest.fail("archive hashing must stream bytes"),
    )

    assert transport._hash_regular_file(path, len(contents)) == (
        hashlib.sha256(contents).hexdigest(),
        len(contents),
    )


@pytest.mark.parametrize(
    "code",
    [
        "import sys; sys.stdout.write('x' * 20000)",
        "import sys; sys.stderr.write('x' * 20000)",
    ],
)
def test_command_caps_both_output_streams_before_buffering(code: str) -> None:
    with pytest.raises(transport.PublicationError, match="bounded_command_output_exceeded"):
        transport._command([sys.executable, "-c", code], timeout=5)


def test_command_errors_do_not_expose_captured_stderr() -> None:
    with pytest.raises(transport.PublicationError, match="bounded_command_failed") as error:
        transport._command(
            [
                sys.executable,
                "-c",
                "import sys; print('private diagnostic marker', file=sys.stderr); sys.exit(1)",
            ],
            timeout=5,
        )
    assert "private diagnostic marker" not in str(error.value)


def test_command_fails_closed_when_killed_process_cannot_be_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DescriptorStream:
        def __init__(self) -> None:
            self._descriptor = os.open(os.devnull, os.O_RDONLY)
            self.closed = False

        def fileno(self) -> int:
            return self._descriptor

        def close(self) -> None:
            os.close(self._descriptor)
            self.closed = True

    class _NoWaitSelector:
        def register(self, *_args: object, **_kwargs: object) -> None:
            return None

        def get_map(self) -> dict[object, object]:
            return {}

        def close(self) -> None:
            return None

    class _UnreapableProcess:
        pid = 12345

        def __init__(self) -> None:
            self.stdout = _DescriptorStream()
            self.stderr = _DescriptorStream()
            self.wait_timeouts: list[float | None] = []
            self.kill_calls = 0

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            self.wait_timeouts.append(timeout)
            raise transport.subprocess.TimeoutExpired(["fixed-test-command"], timeout)

        def kill(self) -> None:
            self.kill_calls += 1

    process = _UnreapableProcess()
    monkeypatch.setattr(transport.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(transport.selectors, "DefaultSelector", _NoWaitSelector)
    monkeypatch.setattr(transport.os, "killpg", lambda *_args, **_kwargs: None)
    started = time.monotonic()

    with pytest.raises(transport.PublicationError, match="bounded_command_cleanup_unavailable"):
        transport._command(["fixed-test-command"], timeout=1)

    assert time.monotonic() - started < 1
    assert len(process.wait_timeouts) == 3
    assert all(timeout is not None and 0 < timeout <= 5 for timeout in process.wait_timeouts)
    assert process.kill_calls == 1


def test_command_timeout_kills_process_group_holding_its_output_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child_pid_path = tmp_path / "child.pid"
    child_code = (
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
        "print('child started',flush=True)"
    )

    real_popen = transport.subprocess.Popen

    def start_after_child_ready(*args: Any, **kwargs: Any) -> Any:
        process = real_popen(*args, **kwargs)
        readiness_deadline = time.monotonic() + 5
        while time.monotonic() < readiness_deadline:
            if child_pid_path.exists():
                return process
            # The parent is expected to exit after fork; only the descendant is the ready signal.
            time.sleep(0.01)

        try:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            try:
                process.wait(timeout=5)
            except transport.subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        finally:
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        pytest.fail("timed-out command fixture child did not become ready")

    monkeypatch.setattr(transport.subprocess, "Popen", start_after_child_ready)
    with pytest.raises(transport.PublicationError, match="bounded_command_timeout"):
        transport._command(
            [sys.executable, "-c", parent_code, child_code, str(child_pid_path)],
            timeout=1,
        )

    child_pid = int(child_pid_path.read_text())
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
        except FileNotFoundError:
            break
        if state == "Z":
            break
        time.sleep(0.01)
    else:
        pytest.fail("timed-out command left its child running")


def test_v3_manifest_keeps_reviewed_test_head_separate_from_image_revision() -> None:
    manifest = transport._expected_manifest_v3(
        "a" * 40,
        transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
        candidate_archive_sha256="c" * 64,
        candidate_archive_size=17,
    )

    assert manifest["format_version"] == 3
    assert manifest["contract"] == transport.HOTFIX_PAIR_CONTRACT_V3
    assert manifest["revision"] == "a" * 40
    assert manifest["reviewed_pr_head_sha"] == transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
    assert manifest["image_source_revision"] == transport.HOTFIX_V3_IMAGE_SOURCE_REVISION
    assert manifest["candidate"]["revision"] == transport.HOTFIX_V3_IMAGE_SOURCE_REVISION
    assert manifest["candidate"]["image_id"] == transport.HOTFIX_V3_IMAGE_ID
    assert (
        manifest["candidate"]["source_context_sha256"] == transport.HOTFIX_V3_IMAGE_CONTEXT_SHA256
    )
    assert manifest["candidate"]["build_receipt_sha256"] == transport.HOTFIX_V3_BUILD_RECEIPT_SHA256
    assert manifest["candidate"]["revision"] != manifest["reviewed_pr_head_sha"]


def test_v3_package_validation_binds_the_explicit_pr9_head_and_fixed_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper_revision = "a" * 40
    reviewed_pr_head_sha = transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA
    candidate = b"synthetic fixed 68c archive"
    predecessor = b"synthetic retained 5ad archive"
    monkeypatch.setattr(
        transport,
        "PRODUCTION_PREDECESSOR_ARCHIVE_SHA256",
        hashlib.sha256(predecessor).hexdigest(),
    )
    monkeypatch.setattr(transport, "PRODUCTION_PREDECESSOR_ARCHIVE_SIZE", len(predecessor))
    root = tmp_path / "package-v3"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    scratch = tmp_path / "approved-scratch"
    scratch.mkdir(mode=0o700)
    scratch.chmod(0o700)
    monkeypatch.setattr(transport, "HOTFIX_SCRATCH_ROOT", scratch)

    candidate_name = transport._fixed_archive_name(transport.HOTFIX_V3_IMAGE_SOURCE_REVISION)
    predecessor_name = transport._fixed_archive_name(transport.PRODUCTION_PREDECESSOR_REVISION)
    _write_private(root / candidate_name, candidate)
    _write_private(root / predecessor_name, predecessor)
    manifest_name = f"signal-ledger-pair-{helper_revision}.json"
    manifest = transport._expected_manifest_v3(
        helper_revision,
        reviewed_pr_head_sha,
        candidate_archive_sha256=hashlib.sha256(candidate).hexdigest(),
        candidate_archive_size=len(candidate),
    )
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    _write_private(root / manifest_name, manifest_bytes)
    receipt = {
        "status": "prepared",
        "contract": transport.HOTFIX_PAIR_CONTRACT_V3,
        "helper_source_revision": helper_revision,
        "reviewed_pr_head_sha": reviewed_pr_head_sha,
        "hotfix_pull_number": 9,
        "candidate_archive_name": candidate_name,
        "candidate_archive_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_archive_size": len(candidate),
        "candidate_image": {
            "architecture": "linux/amd64",
            "id": transport.HOTFIX_V3_IMAGE_ID,
            "revision_label": transport.HOTFIX_V3_IMAGE_SOURCE_REVISION,
            "source_context_sha256": transport.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
        },
        "candidate_build_receipt_sha256": transport.HOTFIX_V3_BUILD_RECEIPT_SHA256,
        "recovery_archive_name": predecessor_name,
        "recovery_archive_sha256": hashlib.sha256(predecessor).hexdigest(),
        "recovery_archive_size": len(predecessor),
        "recovery_image": {
            "architecture": "linux/amd64",
            "id": transport.PRODUCTION_PREDECESSOR_IMAGE_ID,
            "revision_label": transport.PRODUCTION_PREDECESSOR_REVISION,
            "source_context_sha256": transport.PRODUCTION_PREDECESSOR_CONTEXT_SHA256,
        },
        "prior_pair_manifest_sha256": transport.PRODUCTION_PREDECESSOR_PRIOR_PAIR_SHA256,
        "migration_commands": 0,
        "restore_commands": 0,
        "manifest_name": manifest_name,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    _write_private(
        root / "package-receipt.json",
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
    )

    package = transport.validate_package(
        root, helper_revision, reviewed_pr_head_sha=reviewed_pr_head_sha
    )

    assert package.reviewed_pr_head_sha == reviewed_pr_head_sha
    assert package.candidate.revision == transport.HOTFIX_V3_IMAGE_SOURCE_REVISION
    assert package.candidate.image_id == transport.HOTFIX_V3_IMAGE_ID

    manifest["reviewed_pr_head_sha"] = "d" * 40
    changed_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    _write_private(root / manifest_name, changed_bytes)
    receipt["manifest_sha256"] = hashlib.sha256(changed_bytes).hexdigest()
    _write_private(
        root / "package-receipt.json",
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode(),
    )
    with pytest.raises(transport.PublicationError, match="hotfix_manifest_identity_mismatch"):
        transport.validate_package(root, helper_revision, reviewed_pr_head_sha=reviewed_pr_head_sha)


@pytest.mark.parametrize(
    ("helper_revision", "reviewed_pr_head_sha", "archive_digest", "archive_size", "error"),
    [
        (
            "A" * 40,
            transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "c" * 64,
            17,
            "helper_revision_invalid",
        ),
        ("a" * 40, "", "c" * 64, 17, "reviewed_pr_head_invalid"),
        (
            "a" * 40,
            transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "C" * 64,
            17,
            "candidate_archive_identity_invalid",
        ),
        (
            "a" * 40,
            transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "c" * 64,
            True,
            "candidate_archive_identity_invalid",
        ),
        (
            "a" * 40,
            transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "c" * 64,
            0,
            "candidate_archive_identity_invalid",
        ),
    ],
)
def test_v3_manifest_rejects_missing_or_malformed_explicit_identity(
    helper_revision: str,
    reviewed_pr_head_sha: str,
    archive_digest: str,
    archive_size: int,
    error: str,
) -> None:
    with pytest.raises(transport.PublicationError, match=error):
        transport._expected_manifest_v3(
            helper_revision,
            reviewed_pr_head_sha,
            candidate_archive_sha256=archive_digest,
            candidate_archive_size=archive_size,
        )


def _hotfix_v3_delta_text(mutation: str | None = None) -> tuple[str, str]:
    """Build deterministic raw-diff and numstat fixtures from the pinned PR #9 map."""

    raw_records: list[str] = []
    stat_records: list[str] = []
    target = "tests/test_assistant_final_boundary_coverage.py"
    for (
        filename,
        base_blob,
        head_blob,
        additions,
        deletions,
    ) in transport.HOTFIX_V3_REVIEWED_PR9_FILE_DELTA:
        old_mode, new_mode = "100644", "100644"
        if mutation == "base_mode" and filename == target:
            old_mode = "120000"
        elif mutation == "head_mode" and filename == target:
            new_mode = "100755"
        elif mutation == "same_blob" and filename == target:
            head_blob = base_blob
        elif mutation == "wrong_blob" and filename == target:
            head_blob = "3" * 40
        raw_records.append(f":{old_mode} {new_mode} {base_blob} {head_blob} M\0{filename}\0")
        if mutation == "wrong_numstat" and filename == target:
            additions += 1
        stat_records.append(f"{additions}\t{deletions}\t{filename}\0")
    raw_diff = "".join(raw_records)
    numstat = "".join(stat_records)
    if mutation == "extra_file":
        raw_diff += f":100644 100644 {'1' * 40} {'2' * 40} M\0unexpected.py\0"
        numstat += "1\t0\tunexpected.py\0"
    elif mutation == "truncated_raw":
        raw_diff = raw_diff[:-1]
    return raw_diff, numstat


def test_v3_test_head_proof_requires_only_the_approved_one_line_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    path = "tests/test_assistant_final_boundary_coverage.py"
    old_line = '    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"'
    new_line = (
        '    assert captured["url"] == "https://opencode.ai/inference/openai/v1/chat/completions"'
    )
    raw_diff, numstat = _hotfix_v3_delta_text()
    outputs = [
        "",
        "",
        "\n".join(transport.HOTFIX_V3_REVIEWED_PR9_COMMITS) + "\n",
        raw_diff,
        numstat,
        (f"diff --git a/{path} b/{path}\n@@ -41 +41 @@\n-{old_line}\n+{new_line}\n"),
    ]

    def command(argv: list[str], *, timeout: int = 30) -> str:
        assert timeout == 10
        commands.append(argv)
        return outputs[len(commands) - 1]

    monkeypatch.setattr(transport, "_command", command)
    transport._prove_reviewed_pr9_head(transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA, "c" * 40)

    assert len(commands) == 6
    assert commands[0][1:4] == [
        "merge-base",
        "--is-ancestor",
        transport.HOTFIX_V3_IMAGE_SOURCE_REVISION,
    ]
    assert commands[1][1:4] == [
        "merge-base",
        "--is-ancestor",
        transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
    ]
    assert commands[2][1:3] == ["rev-list", "--reverse"]
    assert commands[3][1:3] == ["diff", "--raw"]
    assert commands[3][2:4] == ["--raw", "--no-abbrev"]
    assert commands[4][1:3] == ["diff", "--numstat"]
    assert commands[5][-2:] == ["--", path]


def test_v3_test_head_proof_rejects_an_unpinned_head_before_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        transport,
        "_command",
        lambda *_args, **_kwargs: pytest.fail("unreviewed head must be rejected before Git"),
    )
    with pytest.raises(transport.PublicationError, match="reviewed_pr_head_unreviewed"):
        transport._prove_reviewed_pr9_head("b" * 40, "c" * 40)


@pytest.mark.parametrize(
    "patch_lines",
    [
        (
            '-    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"\n'
            '+    assert captured["url"] == '
            '"https://opencode.ai/inference/openai/v1/chat/completions" # accepted?\n'
        ),
        (
            '-    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"\n'
            '+    assert captured["url"] == "https://opencode.ai/inference/openai/v1/chat/completions"\n'
            "+assert unrelated is True\n"
        ),
    ],
)
def test_v3_test_head_proof_rejects_other_diff_shapes(
    monkeypatch: pytest.MonkeyPatch,
    patch_lines: str,
) -> None:
    path = "tests/test_assistant_final_boundary_coverage.py"
    raw_diff, numstat = _hotfix_v3_delta_text()
    outputs = [
        "",
        "",
        "\n".join(transport.HOTFIX_V3_REVIEWED_PR9_COMMITS) + "\n",
        raw_diff,
        numstat,
        f"diff --git a/{path} b/{path}\n@@ -41 +41 @@\n{patch_lines}",
    ]
    calls = 0

    def command(_argv: list[str], *, timeout: int = 30) -> str:
        nonlocal calls
        assert timeout == 10
        result = outputs[calls]
        calls += 1
        return result

    monkeypatch.setattr(transport, "_command", command)
    with pytest.raises(transport.PublicationError, match="reviewed_pr_test_diff_mismatch"):
        transport._prove_reviewed_pr9_head(transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA, "c" * 40)


@pytest.mark.parametrize(
    "mutation",
    [
        "base_mode",
        "head_mode",
        "same_blob",
        "wrong_blob",
        "extra_file",
        "wrong_numstat",
        "truncated_raw",
    ],
)
def test_v3_test_head_proof_requires_the_exact_regular_six_file_delta(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    path = "tests/test_assistant_final_boundary_coverage.py"
    old_line = '    assert captured["url"] == "https://opencode.ai/zen/v1/chat/completions"'
    new_line = (
        '    assert captured["url"] == "https://opencode.ai/inference/openai/v1/chat/completions"'
    )
    raw_diff, numstat = _hotfix_v3_delta_text(mutation)
    outputs = [
        "",
        "",
        "\n".join(transport.HOTFIX_V3_REVIEWED_PR9_COMMITS) + "\n",
        raw_diff,
        numstat,
        f"diff --git a/{path} b/{path}\n@@ -41 +41 @@\n-{old_line}\n+{new_line}\n",
    ]
    calls = 0

    def command(argv: list[str], *, timeout: int = 30) -> str:
        nonlocal calls
        assert timeout == 10
        result = outputs[calls]
        calls += 1
        return result

    monkeypatch.setattr(transport, "_command", command)
    with pytest.raises(transport.PublicationError, match="reviewed_pr_test_diff_mismatch"):
        transport._prove_reviewed_pr9_head(
            transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA,
            "c" * 40,
        )
    assert calls == 6


def test_v3_test_head_proof_requires_the_exact_three_commit_pr9_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = [
        "",
        "",
        "c2fe99cbd486b93958c6d5c398da9fc25ddd7075\n"
        "0b214bb47886cc7e9db73edccc8648b9af38b678\n" + "9" * 40 + "\n",
    ]
    calls = 0

    def command(argv: list[str], *, timeout: int = 30) -> str:
        nonlocal calls
        assert timeout == 10
        result = outputs[calls]
        calls += 1
        return result

    monkeypatch.setattr(transport, "_command", command)
    with pytest.raises(transport.PublicationError, match="reviewed_pr_lineage_mismatch"):
        transport._prove_reviewed_pr9_head(transport.HOTFIX_V3_REVIEWED_PR_HEAD_SHA, "c" * 40)
    assert calls == 3
