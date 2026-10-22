"""Keep the attached HTTP-only probe independent of application startup imports."""

from __future__ import annotations

import ast
import builtins
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DRIVER = Path(__file__).with_name("native_assistant_probe.py")


def test_attached_probe_rejects_bad_input_without_importing_application_auth(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "stock_probs" or name.startswith("stock_probs."):
            pytest.fail("attached HTTP-only probe imported application code")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = importlib.util.spec_from_file_location("attached_probe_import_contract", DRIVER)
    assert spec is not None and spec.loader is not None
    driver = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, driver)
    spec.loader.exec_module(driver)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}\n")))

    assert driver.run_attached_existing_app_probe() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["safe_error_code"] == "stdin_invalid"
    assert result["failure_stage"] == "input_validation"
    assert result["attached_candidate_acceptance"] is False


def test_attached_cookie_wire_names_match_application_auth() -> None:
    from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

    module = ast.parse(DRIVER.read_text(encoding="utf-8"))
    attached = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_attached_existing_app_probe"
    )
    names = {}
    for node in attached.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "SESSION_COOKIE_NAME",
                "CSRF_COOKIE_NAME",
            }:
                names[target.id] = ast.literal_eval(node.value)
    assert names == {
        "SESSION_COOKIE_NAME": SESSION_COOKIE_NAME,
        "CSRF_COOKIE_NAME": CSRF_COOKIE_NAME,
    }
