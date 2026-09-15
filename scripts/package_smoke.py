"""Build, inspect, and run a clean non-editable wheel from outside the source tree."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RESOURCES = {
    "stock_probs/static/next/index.html",
    "stock_probs/static/app.css",
    "stock_probs/static/app.js",
    "stock_probs/static/theme.js",
    "stock_probs/static/next/api-docs.html",
    "stock_probs/static/favicon.svg",
    "stock_probs/migrations/001_initial.sql",
    "stock_probs/migrations/002_historical_analysis.sql",
    "stock_probs/migrations/003_restore_and_immutability_guards.sql",
    "stock_probs/migrations/004_history_facets.sql",
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


class _RuntimeResourceParser(HTMLParser):
    """Collect browser-executed scripts and stylesheets from one packaged page."""

    def __init__(self) -> None:
        super().__init__()
        self.references: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        reference: str | None = None
        if tag == "script":
            reference = attributes.get("src")
        elif tag == "link":
            rel = (attributes.get("rel") or "").lower().split()
            if "stylesheet" in rel or "modulepreload" in rel or (
                attributes.get("as") or ""
            ).lower() in {
                "script",
                "style",
            }:
                reference = attributes.get("href")
        if reference is not None:
            self.references.add(_validate_runtime_resource(reference))


def _validate_runtime_resource(reference: str) -> str:
    """Return a safe first-party resource path or reject the packaged page."""

    parsed = urlsplit(reference)
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or not parsed.path.startswith("/")
        or "\\" in decoded_path
        or ".." in decoded_path.split("/")
        or not decoded_path.startswith(("/assets/", "/_next/"))
    ):
        raise RuntimeError(f"packaged HTML references unsafe runtime resource: {reference!r}")
    return reference


def _runtime_resources(html: str) -> set[str]:
    """Parse all local script and stylesheet requests made by a packaged page."""

    parser = _RuntimeResourceParser()
    parser.feed(html)
    parser.close()
    return parser.references


def _packaged_resource_name(reference: str) -> str:
    """Map an HTTP resource path to its wheel member name."""

    path = urlsplit(reference).path
    if path.startswith("/_next/"):
        return f"stock_probs/static/next{path}"
    return f"stock_probs/static/{path.removeprefix('/assets/')}"


def _get(
    url: str,
    *,
    method: str = "GET",
    payload: object | None = None,
    status: int = 200,
    timeout: float = 2,
) -> tuple[bytes, dict[str, str]]:
    """Fetch one generated loopback URL and retain normalized response headers."""

    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
    ):
        raise ValueError(f"refusing non-loopback smoke URL: {url!r}")
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(  # noqa: S310 - URL was constrained to loopback above.
        url,
        data=data,
        headers={} if data is None else {"Content-Type": "application/json"},
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
    except urllib.error.HTTPError as error:
        response = error
    with response:
        observed = response.getcode()
        body = response.read(1024 * 1024 + 1)
        headers = {name.lower(): value for name, value in response.headers.items()}
    if len(body) > 1024 * 1024:
        raise RuntimeError(f"loopback response exceeded 1 MiB: {url}")
    if observed != status:
        raise RuntimeError(f"{url} returned HTTP {observed}, expected {status}: {body!r}")
    return body, headers


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)  # noqa: S603


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_json(
    url: str,
    expected_status: str,
    process: subprocess.Popen[bytes] | None,
    *,
    timeout: float = 20,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"wheel-installed server exited with {process.returncode}")
        try:
            payload = json.loads(_get(url, timeout=1)[0])
            if payload.get("status") == expected_status:
                return
        except (OSError, ValueError, RuntimeError) as exc:
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
            page_resources = {
                page: _runtime_resources(archive.read(page).decode())
                for page in (
                    "stock_probs/static/next/index.html",
                    "stock_probs/static/next/api-docs.html",
                )
            }
        missing = sorted(EXPECTED_RESOURCES - contents)
        if missing:
            raise RuntimeError("wheel omitted packaged resources: " + ", ".join(missing))
        # A .js suffix also admits fixed manifests; require a content-named runtime chunk.
        next_chunks = sorted(
            name
            for name in contents
            if name.startswith("stock_probs/static/next/_next/static/chunks/")
            and re.fullmatch(r"[a-z0-9][a-z0-9_-]{7,}\.js", Path(name).name)
        )
        if not next_chunks:
            raise RuntimeError("wheel omitted hashed Next JavaScript chunks")
        referenced_resources = set().union(*page_resources.values())
        missing_references = sorted(
            resource_name
            for reference in referenced_resources
            if (resource_name := _packaged_resource_name(reference)) not in contents
        )
        if missing_references:
            raise RuntimeError(
                "wheel omitted HTML-referenced resources: " + ", ".join(missing_references)
            )

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

        port = _free_port()
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
            served_resources: set[str] = set()
            for page_url, marker in (
                (dashboard_url, b"Signal Ledger"),
                (f"http://127.0.0.1:{port}/api/v1/docs", b"Signal Ledger API"),
            ):
                page, headers = _get(page_url)
                if marker not in page:
                    raise RuntimeError(
                        f"wheel-installed server returned the wrong HTML for {page_url}"
                    )
                policy = headers.get("content-security-policy", "")
                if (
                    "default-src 'self'" not in policy
                    or "script-src 'self'" not in policy
                    or "'unsafe-inline'" in policy
                    or "'unsafe-eval'" in policy
                ):
                    raise RuntimeError(
                        f"wheel-installed server returned an unsafe CSP for {page_url}"
                    )
                served_resources.update(_runtime_resources(page.decode()))
            if served_resources != referenced_resources:
                raise RuntimeError("served HTML resource references differ from the packaged wheel")
            expected_markers = {
                "/assets/theme.js": b"stock-probs.theme",
                "/assets/app.js": b"/api/v1",
            }
            for reference in sorted(served_resources):
                body, headers = _get(f"http://127.0.0.1:{port}{reference}")
                if not body or headers.get("x-content-type-options") != "nosniff":
                    raise RuntimeError(
                        f"wheel-installed server returned an invalid local asset: {reference}"
                    )
                marker = expected_markers.get(urlsplit(reference).path)
                if marker is not None and marker not in body:
                    raise RuntimeError(
                        f"wheel-installed server returned the wrong local asset: {reference}"
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
            "verified_resources": sorted(
                EXPECTED_RESOURCES
                | set(next_chunks)
                | {_packaged_resource_name(reference) for reference in referenced_resources}
            ),
            "html_resource_references": {
                page: sorted(references) for page, references in page_resources.items()
            },
            "checks": [
                "wheel-build",
                "wheel-contents",
                "non-editable-install",
                "registered-migration-resources",
                "migration",
                "loopback-runtime",
                "dashboard-html",
                "api-docs-html",
                "literal-theme-initializer",
                "app-js",
                "hashed-next-chunk",
                "strict-html-csp",
                "all-html-script-stylesheet-assets",
            ],
        }
        (artifact_dir / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
