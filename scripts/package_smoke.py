"""Build, inspect, and run a clean non-editable wheel from outside the source tree."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RESOURCES = {
    "stock_probs/static/index.html",
    "stock_probs/static/app.css",
    "stock_probs/static/app.js",
    "stock_probs/static/api-docs.html",
    "stock_probs/static/favicon.svg",
    "stock_probs/migrations/001_initial.sql",
    "stock_probs/migrations/002_historical_analysis.sql",
    "stock_probs/migrations/003_restore_and_immutability_guards.sql",
    "stock_probs/fixtures/acdc.json",
    "stock_probs/fixtures/spy.json",
}

REGISTERED_MIGRATION_CHECK = """\
from importlib.resources import files
from stock_probs.repository import MIGRATION_NAME, MIGRATION_SHA256

names = sorted(
    item.name for item in files("stock_probs.migrations").iterdir()
    if item.name.endswith(".sql")
)
matches = [MIGRATION_NAME.fullmatch(name) for name in names]
invalid = [name for name, match in zip(names, matches, strict=True) if match is None]
if invalid:
    raise RuntimeError(f"wheel contains invalid migration names: {invalid}")
packaged_versions = [int(match.group("version")) for match in matches if match is not None]
registered_versions = sorted(MIGRATION_SHA256)
if packaged_versions != registered_versions:
    raise RuntimeError(
        f"wheel migration versions {packaged_versions} do not match registry {registered_versions}"
    )
print(names)
"""


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)  # noqa: S603


def _free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_json(url: str, expected_status: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"wheel-installed server exited with {process.returncode}")
        try:
            # Only a generated loopback URL is accepted; this smoke never contacts a provider.
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                payload = json.load(response)
            if payload.get("status") == expected_status:
                return
        except (OSError, ValueError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"wheel-installed server was not ready: {last_error}")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _copy_build_input(destination: Path) -> None:
    shutil.copy2(ROOT / "pyproject.toml", destination / "pyproject.toml")
    shutil.copytree(ROOT / "src", destination / "src")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(os.getenv("STOCK_PROBS_PACKAGE_ARTIFACT_DIR", "test-results/package")),
    )
    parser.add_argument("--expected-machine")
    args = parser.parse_args()

    machine = platform.machine().lower()
    if args.expected_machine and machine not in {args.expected_machine.lower(), "arm64"}:
        raise SystemExit(f"expected machine {args.expected_machine}, observed {machine}")
    execution_label = os.getenv("STOCK_PROBS_EXECUTION_LABEL", f"native {machine}")
    print(f"execution_label={execution_label}", flush=True)

    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stock-probs-package-") as temporary:
        temp = Path(temporary)
        build_source = temp / "source"
        wheelhouse = temp / "wheelhouse"
        install_root = temp / "install"
        runtime_data = temp / "runtime"
        build_source.mkdir()
        wheelhouse.mkdir()
        _copy_build_input(build_source)

        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheelhouse),
                str(build_source),
            ],
            cwd=temp,
        )
        wheels = list(wheelhouse.glob("stock_probs-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected one application wheel, found {len(wheels)}")
        wheel = wheels[0]
        with zipfile.ZipFile(wheel) as archive:
            contents = set(archive.namelist())
        missing = sorted(EXPECTED_RESOURCES - contents)
        if missing:
            raise RuntimeError("wheel omitted packaged resources: " + ", ".join(missing))

        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-index",
                "--target",
                str(install_root),
                str(wheel),
            ],
            cwd=temp,
        )
        direct_urls = list(install_root.glob("*.dist-info/direct_url.json"))
        for direct_url in direct_urls:
            metadata = json.loads(direct_url.read_text())
            if metadata.get("dir_info", {}).get("editable"):
                raise RuntimeError("wheel smoke unexpectedly produced an editable installation")

        env = os.environ.copy()
        # The package path replaces any caller path; OCI dependencies may live in a separate target.
        dependency_path = os.getenv("STOCK_PROBS_DEPENDENCY_PATH")
        env["PYTHONPATH"] = os.pathsep.join(
            path for path in (str(install_root), dependency_path) if path
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["STOCK_PROBS_DATA_DIR"] = str(runtime_data)
        env["STOCK_PROBS_PROVIDER"] = "fixture"
        env["STOCK_PROBS_FIXTURE_NOW"] = "2025-01-10T17:03:00+00:00"
        import_check = (
            "import pathlib, stock_probs; "
            f"root=pathlib.Path({str(install_root)!r}).resolve(); "
            "loaded=pathlib.Path(stock_probs.__file__).resolve(); "
            "assert loaded.is_relative_to(root), (loaded, root); print(loaded)"
        )
        _run([sys.executable, "-c", import_check], cwd=temp, env=env)
        # Read the registry from the wheel installation so a checkout cannot mask omitted data.
        _run([sys.executable, "-c", REGISTERED_MIGRATION_CHECK], cwd=temp, env=env)
        _run([sys.executable, "-m", "stock_probs.cli", "migrate"], cwd=temp, env=env)

        port = _free_loopback_port()
        command = [
            sys.executable,
            "-m",
            "stock_probs.cli",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        print("+", " ".join(command), flush=True)
        process = subprocess.Popen(command, cwd=temp, env=env)  # noqa: S603
        try:
            _wait_for_json(f"http://127.0.0.1:{port}/api/v1/health", "ok", process)
            dashboard_url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(dashboard_url, timeout=2) as response:  # noqa: S310
                if b"Signal Ledger" not in response.read():
                    raise RuntimeError(
                        "wheel-installed server did not serve the packaged dashboard"
                    )
        finally:
            _stop(process)

        artifact_wheel = artifact_dir / wheel.name
        shutil.copy2(wheel, artifact_wheel)
        report = {
            "task": os.getenv("STOCK_PROBS_TASK_ID", "M01"),
            "revision": os.getenv("STOCK_PROBS_REVISION", "working-tree"),
            "machine": machine,
            "execution_label": execution_label,
            "result": "Pass",
            "wheel": artifact_wheel.name,
            "wheel_bytes": artifact_wheel.stat().st_size,
            "verified_resources": sorted(EXPECTED_RESOURCES),
            "checks": [
                "wheel-build",
                "wheel-contents",
                "non-editable-install",
                "registered-migration-resources",
                "migration",
                "loopback-runtime",
            ],
        }
        (artifact_dir / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
