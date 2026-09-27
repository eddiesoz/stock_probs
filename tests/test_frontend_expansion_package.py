"""A partial expansion export cannot replace the last complete staged frontend."""

import pytest

from scripts import build_frontend


def test_partial_expansion_does_not_replace_staged_export(tmp_path, monkeypatch):
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
