"""Fresh-process contract for optional Yahoo dependencies at application startup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_fixture_and_application_start_without_yahoo_dependency_imports(tmp_path):
    script = r"""
import json
import socket
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

def forbidden_network(*_args, **_kwargs):
    raise AssertionError("network access is forbidden in this regression")

socket.socket.connect = forbidden_network
socket.socket.connect_ex = forbidden_network
socket.create_connection = forbidden_network
socket.getaddrinfo = forbidden_network

import stock_probs.provider as provider_module
from stock_probs.api import create_app
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider, YahooProvider

forbidden_modules = ("yfinance", "pandas", "numpy", "curl_cffi")

def loaded_forbidden_modules():
    return sorted(
        name for name in sys.modules
        if any(name == root or name.startswith(root + ".") for root in forbidden_modules)
    )

def app_settings(root, provider):
    data = root / provider
    return Settings(
        data_dir=data,
        database_path=data / "stock_probs.sqlite3",
        backup_dir=data / "backups",
        provider=provider,
    )

root = Path(tempfile.mkdtemp(prefix="lazy-import-", dir=sys.argv[1]))
fixture_app = create_app(app_settings(root, "fixture"))
yahoo_app = create_app(app_settings(root, "yahoo"))
with TestClient(fixture_app):
    pass
with TestClient(yahoo_app):
    pass
fixture_news = FixtureProvider().fetch_news("EMPTY")
assert fixture_news.items == ()
assert fixture_app is not None and yahoo_app is not None
assert loaded_forbidden_modules() == [], loaded_forbidden_modules()

requested = []

class EmptySearch:
    def __init__(self, *_args, **_kwargs):
        self.quotes = []

class EmptyYahooModule:
    Search = EmptySearch

class EmptyNewsSession:
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return None
    def get(self, _url, **kwargs):
        body = b'{"news": []}'
        assert kwargs["content_callback"](body) == len(body)
        return SimpleNamespace(status_code=200)

class EmptyCurlModule:
    Session = EmptyNewsSession

def synthetic_import(name):
    requested.append(name)
    if name == "yfinance":
        return EmptyYahooModule
    if name == "curl_cffi.requests":
        return EmptyCurlModule
    raise AssertionError("unexpected dynamic import")

provider_module.import_module = synthetic_import
now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
assert YahooProvider().lookup("sample corporation", 5, now) == ()
assert requested == ["yfinance"]
assert YahooProvider().fetch_news("SPY", now=now).items == ()
assert requested == ["yfinance", "curl_cffi.requests"]
assert loaded_forbidden_modules() == [], loaded_forbidden_modules()
print(json.dumps({"startup_imports": [], "on_demand_imports": requested}))
"""
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(tmp_path),
    }
    # S603: fixed interpreter/script, no shell, and a pytest-owned temporary path only.
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-s", "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=lambda: os.umask(0o22),
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise AssertionError("fresh interpreter exceeded its ten-second bound") from exc

    assert len(stdout.encode()) <= 4096
    assert len(stderr.encode()) <= 4096
    assert process.returncode == 0, stderr[-4096:]
    assert json.loads(stdout) == {
        "startup_imports": [],
        "on_demand_imports": ["yfinance", "curl_cffi.requests"],
    }
