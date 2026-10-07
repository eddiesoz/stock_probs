"""A partial expansion export cannot replace the last complete staged frontend."""

from pathlib import Path

import pytest

from scripts import build_frontend

ASSET_BYTES = {
    "app.css": b"fixture stylesheet",
    "app.js": b"fixture application",
    "theme.js": b"fixture theme",
    "favicon.svg": b"<svg />",
}


def _write_complete_export(source: Path) -> None:
    """Create the required export pages and one static Next chunk."""
    for name in build_frontend.PAGES:
        page = source / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(name)
    chunk = source / "_next/static/chunks/app.js"
    chunk.parent.mkdir(parents=True, exist_ok=True)
    chunk.write_text("chunk")


def _write_authored_assets(directory: Path) -> None:
    """Create the fixed files that FastAPI serves outside the Next stage."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, contents in ASSET_BYTES.items():
        (directory / name).write_bytes(contents)


def _prepare_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """Prepare isolated export, stage, and authored-asset trees."""
    source = tmp_path / "out"
    destination = tmp_path / "static/next"
    authored_assets = tmp_path / "authored-static"
    _write_complete_export(source)
    _write_authored_assets(authored_assets)
    destination.mkdir(parents=True)
    (destination / "keep-until-valid.txt").write_text("old")
    monkeypatch.setattr(build_frontend, "SOURCE", source)
    monkeypatch.setattr(build_frontend, "DESTINATION", destination)
    monkeypatch.setattr(build_frontend, "STATIC_ASSETS", authored_assets)
    return source, destination, authored_assets


def test_partial_expansion_does_not_replace_staged_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the previous stage intact when required Next pages are missing."""
    source = tmp_path / "out"
    destination = tmp_path / "static/next"
    source.mkdir()
    destination.mkdir(parents=True)
    (destination / "keep-until-valid.txt").write_text("old")
    for name in build_frontend.PAGES[:3]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    (source / "_next/static/chunks").mkdir(parents=True)
    (source / "_next/static/chunks/app.js").write_text("chunk")
    monkeypatch.setattr(build_frontend, "SOURCE", source)
    monkeypatch.setattr(build_frontend, "DESTINATION", destination)

    with pytest.raises(SystemExit, match="not a complete Next export"):
        build_frontend.main()
    assert (destination / "keep-until-valid.txt").read_text() == "old"


def test_reconciles_fastapi_assets_to_export_without_changing_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copy served assets into out while preserving originals and staged pages."""
    source, destination, authored_assets = _prepare_layout(tmp_path, monkeypatch)

    build_frontend.main()

    for name, contents in ASSET_BYTES.items():
        assert (source / "assets" / name).read_bytes() == contents
        assert (authored_assets / name).read_bytes() == contents
    assert (destination / "index.html").is_file()
    assert (destination / "_next/static/chunks/app.js").read_text() == "chunk"
    assert not (destination / "assets").exists()
    assert not (destination / "keep-until-valid.txt").exists()

    (source / "assets/app.css").write_bytes(b"stale export copy")
    build_frontend.main()
    assert (source / "assets/app.css").read_bytes() == ASSET_BYTES["app.css"]
    assert (authored_assets / "app.css").read_bytes() == ASSET_BYTES["app.css"]
    staged_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert staged_files == set(build_frontend.PAGES) | {"_next/static/chunks/app.js"}


@pytest.mark.parametrize("invalid_asset", ["missing", "empty", "directory"])
def test_incomplete_authored_asset_preserves_staged_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_asset: str
) -> None:
    """Reject missing, empty, or non-file authored assets before replacing stage."""
    _, destination, authored_assets = _prepare_layout(tmp_path, monkeypatch)
    asset = authored_assets / "app.css"
    asset.unlink()
    if invalid_asset == "empty":
        asset.write_bytes(b"")
    elif invalid_asset == "directory":
        asset.mkdir()

    with pytest.raises(SystemExit, match="FastAPI static assets are incomplete"):
        build_frontend.main()
    assert (destination / "keep-until-valid.txt").read_text() == "old"


@pytest.mark.parametrize(
    "symlink_case",
    [
        "export-root",
        "export-assets",
        "dangling-export-assets",
        "nested-export",
        "authored-root",
        "authored-file",
    ],
)
def test_source_symlinks_preserve_staged_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symlink_case: str
) -> None:
    """Reject linked export and authored paths without removing the prior stage."""
    source, destination, authored_assets = _prepare_layout(tmp_path, monkeypatch)
    target = tmp_path / "symlink-target"
    target.mkdir()

    if symlink_case == "export-root":
        export_link = tmp_path / "linked-out"
        export_link.symlink_to(source, target_is_directory=True)
        monkeypatch.setattr(build_frontend, "SOURCE", export_link)
        message = "frontend/out is not a complete Next export"
    elif symlink_case in {"export-assets", "dangling-export-assets"}:
        if symlink_case == "dangling-export-assets":
            target = tmp_path / "missing-assets-target"
        (source / "assets").symlink_to(target, target_is_directory=True)
        message = "frontend/out must not contain symlinks"
    elif symlink_case == "nested-export":
        link = source / "_next/static/chunks/linked.js"
        link.symlink_to(target / "app.js")
        message = "frontend/out must not contain symlinks"
    elif symlink_case == "authored-root":
        static_link = tmp_path / "linked-authored-static"
        static_link.symlink_to(authored_assets, target_is_directory=True)
        monkeypatch.setattr(build_frontend, "STATIC_ASSETS", static_link)
        message = "FastAPI static assets are incomplete"
    else:
        asset = authored_assets / "app.css"
        asset.unlink()
        asset.symlink_to(target / "app.css")
        message = "FastAPI static assets must not contain symlinks"

    with pytest.raises(SystemExit, match=message):
        build_frontend.main()
    assert (destination / "keep-until-valid.txt").read_text() == "old"


def test_export_asset_directory_conflict_preserves_staged_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a generated asset path that is a directory before replacing stage."""
    source, destination, _ = _prepare_layout(tmp_path, monkeypatch)
    export_asset = source / "assets/app.css"
    export_asset.mkdir(parents=True)

    with pytest.raises(SystemExit, match="frontend/out assets are incomplete"):
        build_frontend.main()
    assert (destination / "keep-until-valid.txt").read_text() == "old"
