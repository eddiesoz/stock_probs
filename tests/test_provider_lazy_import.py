"""Keep optional Yahoo dependencies outside application startup and fixture imports."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_public_app_construction_defers_optional_yahoo_imports(tmp_path: Path) -> None:
    """Fixture and Yahoo app construction do not load Yahoo clients or use the network."""

    script = r"""
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

def forbidden_network(*_args, **_kwargs):
    raise AssertionError("network access is forbidden in this regression")

socket.socket.connect = forbidden_network
socket.socket.connect_ex = forbidden_network
socket.create_connection = forbidden_network
socket.getaddrinfo = forbidden_network

import stock_probs.provider as provider_module
from stock_probs.api import create_app
from stock_probs.config import Settings
from stock_probs.domain import DomainError
from stock_probs.provider import FixtureProvider, YahooProvider

optional_modules = ("yfinance", "pandas", "numpy", "curl_cffi")

def loaded_optional_modules():
    return sorted(
        name for name in sys.modules
        if any(name == root or name.startswith(root + ".") for root in optional_modules)
    )

def app_settings(root, provider):
    data = root / provider
    return Settings(
        data_dir=data,
        database_path=data / "stock_probs.sqlite3",
        backup_dir=data / "backups",
        provider=provider,
        assistant_enabled=False,
        portfolio_features_enabled=True,
        portfolio_features_canary_only=False,
    )

root = Path(sys.argv[1])
fixture_app = create_app(app_settings(root, "fixture"))
yahoo_app = create_app(app_settings(root, "yahoo"))
assert FixtureProvider().fetch_news("EMPTY").items == ()
assert fixture_app is not None and yahoo_app is not None
assert loaded_optional_modules() == [], loaded_optional_modules()

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
provider_module._load_yfinance.cache_clear()
provider_module._load_curl_requests.cache_clear()
now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
assert YahooProvider().lookup("sample corporation", 5, now) == ()
assert requested == ["yfinance"]
assert YahooProvider().fetch_news("SPY", now=now).items == ()
assert requested == ["yfinance", "curl_cffi.requests"]
assert loaded_optional_modules() == [], loaded_optional_modules()

def missing_import(name):
    raise ImportError("optional dependency intentionally unavailable")

provider_module.import_module = missing_import
provider_module._load_yfinance.cache_clear()
provider_module._load_curl_requests.cache_clear()
try:
    YahooProvider().lookup("sample corporation", 5, now)
except DomainError as error:
    assert error.code == "provider_unavailable" and error.status_code == 503
    assert isinstance(error.__cause__, ImportError)
else:
    raise AssertionError("Yahoo lookup must report a missing optional dependency on use")
try:
    YahooProvider().fetch_news("SPY", now=now)
except DomainError as error:
    assert error.code == "provider_unavailable" and error.status_code == 503
    assert isinstance(error.__cause__, ImportError)
else:
    raise AssertionError("Yahoo news must report a missing optional dependency on use")
print(json.dumps({"startup_imports": [], "on_demand_imports": requested,
                  "missing_dependency_status": 503}))
"""
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(source_root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(tmp_path),
    }
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
        "missing_dependency_status": 503,
    }
