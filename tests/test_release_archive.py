from __future__ import annotations

import importlib.util
import io
import json
import re
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify-release-archive.py"
SPEC = importlib.util.spec_from_file_location("release_archive_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


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


def test_release_archive_verifier_accepts_clean_bounded_single_image(tmp_path: Path) -> None:
    archive = _docker_archive(tmp_path, {"app.py": b"print('safe')"})

    result = verifier.verify_image_archive(archive)

    assert result["status"] == "pass"
    assert result["archive_size"] == archive.stat().st_size
    assert result["layer_count"] == 1
    assert len(result["archive_sha256"]) == 64


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


def test_publisher_shell_scanner_matches_fixed_secret_name_and_token_rules() -> None:
    script = SCRIPT.with_name("publish-production-image.sh").read_text(encoding="utf-8")
    path_match = re.search(r"SECRET_PATH_PATTERN='([^']+)'", script)
    bytes_match = re.search(r"SECRET_BYTES_PATTERN='([^']+)'", script)
    assert path_match is not None
    assert bytes_match is not None
    path_pattern = re.compile(path_match.group(1), re.IGNORECASE)
    bytes_pattern = re.compile(bytes_match.group(1).encode())

    for path in ("home/.aws/credentials", "home/.ssh/config", "app/Auth.JSON"):
        assert path_pattern.search(path), path
    for value in (b"sk-ant-api03-" + b"A" * 32, b"AIza" + b"A" * 32):
        assert bytes_pattern.search(value), value[:8]
    assert "IMAGE_SCHEMA >= 13" in script
    assert "candidate/recovery GitHub release pair" in script
