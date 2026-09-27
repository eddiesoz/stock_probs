"""The comment audit keeps narrowly justified exclusions from masking authored source."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("comment_audit", ROOT / "scripts/comment_audit.py")
assert SPEC is not None and SPEC.loader is not None
comment_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comment_audit)


def test_removed_ponytail_tree_is_absent_from_the_inventory():
    checked = {path.relative_to(ROOT) for path in comment_audit.checked_paths(ROOT)}

    assert not any(path.parts[:2] == ("tools", "ponytail") for path in checked)
    assert not hasattr(comment_audit, "PONYTAIL")
    assert not hasattr(comment_audit, "PONYTAIL_LOCAL_SMOKE")


def test_declarative_json_exclusions_are_path_specific():
    checked = {path.relative_to(ROOT) for path in comment_audit.checked_paths(ROOT)}

    assert {
        Path("opencode.json"),
        Path(".opencode/package.json"),
        Path(".opencode/package-lock.json"),
        Path("tools/browser/performance-budgets.json"),
    } == comment_audit.DECLARATIVE_JSON
    assert not comment_audit.DECLARATIVE_JSON.intersection(checked)
    assert Path("tools/browser/tests/performance.spec.js") in checked
    assert Path("scripts/performance_harness.py") in checked


def test_declarative_json_exclusions_are_not_parsed(tmp_path):
    (tmp_path / "opencode.json").write_text("not json\n")

    assert tmp_path / "opencode.json" not in comment_audit.checked_paths(tmp_path)


def test_arbitrary_json_metadata_does_not_bypass_comment_requirement(tmp_path):
    candidate = tmp_path / "metadata.json"
    candidate.write_text('{"$schema": "example", "instructions": []}\n')

    assert not comment_audit.has_comment(candidate)
    candidate.write_text('{"_comment": "why this exists", "value": 1}\n')
    assert comment_audit.has_comment(candidate)


def test_main_scans_once_and_fails_for_missing_comment(tmp_path, monkeypatch, capsys):
    candidate = tmp_path / "unauthorized.py"
    candidate.write_text("value = 1\n")
    calls = 0

    def checked_paths(root):
        nonlocal calls
        calls += 1
        return [candidate]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(comment_audit, "checked_paths", checked_paths)

    with pytest.raises(SystemExit, match="Files missing useful comments: unauthorized.py"):
        comment_audit.main()
    assert calls == 1

    candidate.write_text('"""Explain why this exists."""\n')
    comment_audit.main()
    assert calls == 2
    assert capsys.readouterr().out == "comment audit passed: 1 authored implementation files\n"
