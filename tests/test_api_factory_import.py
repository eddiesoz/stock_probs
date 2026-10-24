"""Keep factory imports free of an unused default application."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_factory_import_defers_default_asgi_app_and_loads_it_once(tmp_path):
    script = r"""
import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI

def forbidden_network(*_args, **_kwargs):
    raise AssertionError("network access is forbidden in this regression")

socket.socket.connect = forbidden_network
socket.socket.connect_ex = forbidden_network
socket.create_connection = forbidden_network
socket.getaddrinfo = forbidden_network

construction_count = 0
original_init = FastAPI.__init__

def counted_init(self, *args, **kwargs):
    global construction_count
    construction_count += 1
    original_init(self, *args, **kwargs)

FastAPI.__init__ = counted_init

import stock_probs.api as api
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from uvicorn.importer import import_from_string

assert construction_count == 0, construction_count
factory = api.create_app
root = Path(sys.argv[1])
settings = Settings(
    data_dir=root,
    database_path=root / "stock_probs.sqlite3",
    backup_dir=root / "backups",
    provider="fixture",
)
explicit = factory(settings, FixtureProvider())
assert construction_count == 1

factory_calls = 0

def configured_factory():
    global factory_calls
    factory_calls += 1
    return factory(settings, FixtureProvider())

api.create_app = configured_factory
with ThreadPoolExecutor(max_workers=4) as executor:
    apps = list(executor.map(lambda _: import_from_string("stock_probs.api:app"), range(8)))
assert factory_calls == 1, factory_calls
assert construction_count == 2, construction_count
assert all(app is apps[0] for app in apps)
assert apps[0] is not explicit
assert {"/api/v1/health", "/api/v1/readiness"}.issubset(
    apps[0].openapi()["paths"]
)
try:
    getattr(api, "missing_api_attribute")
except AttributeError:
    pass
else:
    raise AssertionError("unknown module attributes must stay absent")
print(json.dumps({"explicit_apps": 1, "default_apps": factory_calls, "shared_loads": len(apps)}))
"""
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(tmp_path),
    }
    # S603: fixed interpreter and script with a pytest-owned temporary path; no shell.
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
    assert json.loads(stdout) == {"explicit_apps": 1, "default_apps": 1, "shared_loads": 8}
