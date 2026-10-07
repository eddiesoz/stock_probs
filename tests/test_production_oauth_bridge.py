"""Disposable Docker bridge coverage for the production OAuth caller boundary."""

from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/jtmb/signal-ledger:sha-566baab14c298fb52b5edb3138d64cd3e9123311"
IMAGE_SETTING = (
    '"${STOCK_PROBS_IMAGE:?STOCK_PROBS_IMAGE is supplied by the fixed deployment helper}"'
)
CURRENT_ENTRYPOINT = ["python", "-m", "stock_probs.container_supervisor"]
CURRENT_COMMAND = [
    "serve",
    "--host",
    "0.0.0.0",  # noqa: S104 - the Compose publication remains host-loopback only.
    "--port",
    "8000",
    "--allow-non-loopback",
]
NETWORK_NAME = "signal-ledger-production-ingress"
SUBNET = "172.30.219.0/28"
GATEWAY = "172.30.219.1"


def _docker_environment() -> dict[str, str]:
    """Keep only non-application host settings and supply fake local OAuth values."""

    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("STOCK_PROBS_")
    }
    environment.update(
        {
            "STOCK_PROBS_IMAGE": IMAGE,
            "STOCK_PROBS_PROVIDER": "fixture",
            "STOCK_PROBS_PUBLIC_ORIGIN": "https://bridge-qa.invalid",
            "STOCK_PROBS_AUTH_SESSION_SECRET": secrets.token_urlsafe(48),
            "STOCK_PROBS_GITHUB_CLIENT_ID": "bridge-qa-client-id",
            "STOCK_PROBS_GITHUB_CLIENT_SECRET": secrets.token_urlsafe(32),
            "STOCK_PROBS_GITHUB_REDIRECT_URI": (
                "https://bridge-qa.invalid/api/v1/auth/github/callback"
            ),
            "STOCK_PROBS_OWNER_GITHUB_ID": "123456789",
        }
    )
    return environment


def _run(
    arguments: list[str], environment: dict[str, str], *, check: bool = True, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603 - all commands and arguments are fixed by this test
        arguments,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check:
        assert result.returncode == 0, f"{arguments!r}: {result.stdout}\n{result.stderr}"
    return result


def _compose(
    prefix: list[str], environment: dict[str, str], *arguments: str, check: bool = True
) -> str:
    result = _run([*prefix, *arguments], environment, check=check)
    return result.stdout.strip()


def _apply_current_supervisor_runtime(compose_text: str) -> str:
    """Use the current Dockerfile's supervisor when a cached image supplies only packaging."""

    image_line = f"    image: {IMAGE_SETTING}\n"
    if compose_text.count(image_line) != 1:
        raise AssertionError("production Compose must contain one fixed application image line")
    runtime = (
        "    entrypoint:\n"
        "      - python\n"
        "      - -m\n"
        "      - stock_probs.container_supervisor\n"
        "    command:\n"
        "      - serve\n"
        "      - --host\n"
        "      - 0.0.0.0\n"
        "      - --port\n"
        "      - '8000'\n"
        "      - --allow-non-loopback\n"
    )
    return compose_text.replace(image_line, image_line + runtime, 1)


def _status(host: str, port: int, caller: str, forwarded_for: str) -> int:
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(
            "GET",
            "/api/v1/auth/github/start",
            headers={
                "Host": "bridge-qa.invalid",
                "Origin": "https://bridge-qa.invalid",
                "CF-Connecting-IP": caller,
                "X-Forwarded-For": forwarded_for,
                "X-Forwarded-Host": "bridge-qa.invalid",
                "X-Forwarded-Proto": "https",
            },
        )
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def _wait_ready(host: str, port: int) -> None:
    deadline = time.monotonic() + 45
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            connection = http.client.HTTPConnection(host, port, timeout=2)
            connection.request("GET", "/api/v1/readiness", headers={"Host": "bridge-qa.invalid"})
            response = connection.getresponse()
            response.read()
            connection.close()
            if response.status == 200:
                return
        except OSError as exc:
            last_error = exc
        time.sleep(0.25)
    raise AssertionError(f"disposable production app did not become ready: {last_error}")


def test_cached_image_fixture_uses_current_dockerfile_supervisor_runtime() -> None:
    """Keep the legacy image cache from bypassing the current privilege-dropping supervisor."""

    production_compose = (ROOT / "compose.production.yaml").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["python", "-m", "stock_probs.container_supervisor"]' in dockerfile
    assert (
        'CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--allow-non-loopback"]' in dockerfile
    )
    image_line = f"    image: {IMAGE_SETTING}\n"
    runtime = (
        "    entrypoint:\n"
        "      - python\n"
        "      - -m\n"
        "      - stock_probs.container_supervisor\n"
        "    command:\n"
        "      - serve\n"
        "      - --host\n"
        "      - 0.0.0.0\n"
        "      - --port\n"
        "      - '8000'\n"
        "      - --allow-non-loopback\n"
    )
    assert production_compose.count(image_line) == 1
    assert _apply_current_supervisor_runtime(production_compose) == production_compose.replace(
        image_line, image_line + runtime, 1
    )


def test_production_bridge_keeps_cloudflare_callers_separate_and_ignores_untrusted_headers(
    tmp_path: Path,
) -> None:
    """Exercise host publication and an untrusted bridge peer against the pinned gateway."""

    if shutil.which("docker") is None:
        pytest.skip("local Docker CLI is unavailable")
    environment = _docker_environment()
    daemon = _run(["docker", "info", "--format", "{{.ServerVersion}}"], environment, check=False)
    if daemon.returncode != 0:
        pytest.skip("local Docker daemon is unavailable")
    image = _run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], environment, check=False
    )
    if image.returncode != 0:
        pytest.skip(f"local {IMAGE} image is unavailable")

    docker_context = _run(["docker", "context", "show"], environment).stdout.strip()
    endpoint_result = _run(
        [
            "docker",
            "context",
            "inspect",
            docker_context,
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        ],
        environment,
        check=False,
    )
    if (
        endpoint_result.returncode != 0
        or not endpoint_result.stdout.strip().startswith("unix://")
        or environment.get("DOCKER_HOST", "").startswith(("tcp://", "ssh://"))
    ):
        pytest.skip("OAuth bridge protocol test requires a local Docker daemon")

    run_id = uuid.uuid4().hex[:12]
    project = f"oauth-bridge-{run_id}"
    test_network = f"signal-ledger-oauth-qa-{run_id}"
    test_compose = tmp_path / "compose.oauth-bridge.yaml"
    legacy_app_env = tmp_path / "legacy-app.env"
    legacy_app_env.write_text("STOCK_PROBS_TRUSTED_PROXY_HOSTS=127.0.0.1\n")
    production_compose = (ROOT / "compose.production.yaml").read_text()
    assert production_compose.count('"127.0.0.1:8000:8000"') == 1
    assert production_compose.count(IMAGE_SETTING) == 1
    assert production_compose.count('STOCK_PROBS_PROVIDER: "${STOCK_PROBS_PROVIDER:-yahoo}"') == 1
    assert production_compose.count("      - signal-ledger-data:/data\n") == 1
    assert production_compose.count("    name: signal-ledger-production-ingress\n") == 1
    production_compose = _apply_current_supervisor_runtime(production_compose)
    production_compose = production_compose.replace('"127.0.0.1:8000:8000"', '"127.0.0.1::8000"', 1)
    production_compose = production_compose.replace(
        "    name: signal-ledger-production-ingress\n",
        f"    name: {test_network}\n",
        1,
    )
    production_compose = production_compose.replace(
        'STOCK_PROBS_PROVIDER: "${STOCK_PROBS_PROVIDER:-yahoo}"',
        "STOCK_PROBS_PROVIDER: fixture",
        1,
    )
    production_compose = production_compose.replace(
        "      STOCK_PROBS_DATA_DIR: /data\n",
        "      STOCK_PROBS_DATA_DIR: /data\n      PYTHONPATH: /opt/stock-probs-src\n",
        1,
    )
    production_compose = production_compose.replace(
        "      - signal-ledger-data:/data\n",
        "      - signal-ledger-data:/data\n"
        "      - type: bind\n"
        f"        source: {json.dumps(str(ROOT / 'src'))}\n"
        "        target: /opt/stock-probs-src\n"
        "        read_only: true\n",
        1,
    )
    test_compose.write_text(production_compose)

    prefix = [
        "docker",
        "compose",
        "--env-file",
        str(legacy_app_env),
        "--project-directory",
        str(ROOT),
        "--project-name",
        project,
        "--file",
        str(test_compose),
    ]
    effective_compose = json.loads(_compose(prefix, environment, "config", "--format", "json"))
    assert (
        effective_compose["services"]["app"]["environment"]["STOCK_PROBS_TRUSTED_PROXY_HOSTS"]
        == "127.0.0.1,::1,localhost,172.30.219.1"
    )
    app_service = effective_compose["services"]["app"]
    assert app_service["image"] == IMAGE
    assert app_service["entrypoint"] == CURRENT_ENTRYPOINT
    assert app_service["command"] == CURRENT_COMMAND
    assert app_service["user"] == "0:0"
    assert app_service["read_only"] is True
    assert app_service["cap_drop"] == ["ALL"]
    assert set(app_service["cap_add"]) == {"SETGID", "SETUID"}
    assert "no-new-privileges:true" in app_service["security_opt"]
    assert app_service["ports"][0]["host_ip"] == "127.0.0.1"
    blocker = f"oauth-bridge-conflict-{run_id}"
    probe_name = f"oauth-bridge-probe-{run_id}"
    blocker_created = False
    compose_attempted = False
    probe_attempted = False
    try:
        blocker_result = _run(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--subnet",
                SUBNET,
                "--gateway",
                GATEWAY,
                blocker,
            ],
            environment,
            check=False,
        )
        if blocker_result.returncode == 0:
            blocker_created = True
            compose_attempted = True
            conflicted = _run(
                [*prefix, "up", "--detach", "--no-build", "--pull", "never"],
                environment,
                check=False,
            )
            assert conflicted.returncode != 0, "Compose silently selected a fallback bridge subnet"
            assert "overlap" in conflicted.stderr.lower(), conflicted.stderr
            _compose(prefix, environment, "down", "--volumes", "--remove-orphans", check=False)
            compose_attempted = False
            _run(["docker", "network", "rm", blocker], environment)
            blocker_created = False
        else:
            assert "overlap" in blocker_result.stderr.lower(), blocker_result.stderr
            # A pre-existing overlap should prevent this Compose bridge from starting too. Skip
            # only the protocol part after recording Docker's fail-closed network allocator.
            compose_attempted = True
            conflict = _run(
                [*prefix, "up", "--detach", "--no-build", "--pull", "never"],
                environment,
                check=False,
            )
            assert conflict.returncode != 0, "overlapping fixed bridge subnet was not rejected"
            _compose(prefix, environment, "down", "--volumes", "--remove-orphans", check=False)
            compose_attempted = False
            pytest.skip("fixed production OAuth subnet overlaps an existing local Docker network")

        compose_attempted = True
        _compose(prefix, environment, "up", "--detach", "--no-build", "--pull", "never")
        published = _compose(prefix, environment, "port", "app", "8000")
        published_host, published_port_text = published.rsplit(":", 1)
        assert published_host == "127.0.0.1"
        published_port = int(published_port_text)

        container_id = _compose(prefix, environment, "ps", "--quiet", "app")
        inspect = json.loads(
            _run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .NetworkSettings.Networks}}",
                    container_id,
                ],
                environment,
            ).stdout
        )
        assert list(inspect) == [test_network]
        app_network = inspect[test_network]
        app_ip = app_network["IPAddress"]
        assert app_network["Gateway"] == GATEWAY

        mounts = json.loads(
            _run(
                ["docker", "inspect", "--format", "{{json .Mounts}}", container_id], environment
            ).stdout
        )
        durable_mounts = [mount for mount in mounts if mount["Type"] != "tmpfs"]
        assert {mount["Destination"] for mount in durable_mounts} == {
            "/data",
            "/opt/stock-probs-src",
        }
        source_mount = next(
            mount for mount in mounts if mount["Destination"] == "/opt/stock-probs-src"
        )
        assert source_mount["Source"] == str(ROOT / "src")
        assert source_mount["RW"] is False
        assert (
            next(mount for mount in mounts if mount["Destination"] == "/data")["Type"] == "volume"
        )

        network = json.loads(
            _run(["docker", "network", "inspect", test_network], environment).stdout
        )[0]
        ipam = network["IPAM"]["Config"]
        assert len(ipam) == 1
        assert ipam[0]["Subnet"] == SUBNET
        assert ipam[0]["Gateway"] == GATEWAY
        assert not ipam[0].get("IPRange")

        _wait_ready("127.0.0.1", published_port)
        processes = (
            _run(["docker", "top", container_id, "-eo", "pid,uid,gid,comm"], environment)
            .stdout.strip()
            .splitlines()
        )
        process_identities = {
            tuple(fields[1:]) for line in processes[1:] if len(fields := line.split()) == 4
        }
        assert ("0", "0", "python") in process_identities, "the fixed supervisor must run as root"
        assert (
            "10001",
            "10001",
            "stock-probs",
        ) in process_identities, "the app must run under its fixed unprivileged identity"
        caller_a = "198.51.100.71"
        caller_b = "198.51.100.72"
        for index in range(8):
            assert _status("127.0.0.1", published_port, caller_a, f"203.0.113.{index + 1}") == 302
        assert _status("127.0.0.1", published_port, caller_a, "203.0.113.250") == 429
        for index in range(8):
            assert _status("127.0.0.1", published_port, caller_b, f"203.0.113.{index + 31}") == 302
        assert _status("127.0.0.1", published_port, caller_b, "203.0.113.251") == 429

        probe_script = """
import http.client
import sys

host = sys.argv[1]
statuses = []
for index in range(9):
    connection = http.client.HTTPConnection(host, 8000, timeout=5)
    headers = {
        "Host": "bridge-qa.invalid",
        "Origin": "https://bridge-qa.invalid",
        "CF-Connecting-IP": "198.51.100.72",
        "X-Forwarded-For": f"192.0.2.{index + 1}",
        "X-Forwarded-Host": "bridge-qa.invalid",
        "X-Forwarded-Proto": "https",
    }
    connection.request("GET", "/api/v1/auth/github/start", headers=headers)
    response = connection.getresponse()
    statuses.append(response.status)
    response.read()
    connection.close()
print(",".join(map(str, statuses)))
"""
        probe_attempted = True
        probe = _run(
            [
                "docker",
                "run",
                "--name",
                probe_name,
                "--network",
                test_network,
                "--ip",
                "172.30.219.14",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "32",
                "--memory",
                "128m",
                "--cpus",
                "0.5",
                "--user",
                "10001:10001",
                "--entrypoint",
                "python",
                IMAGE,
                "-c",
                probe_script,
                app_ip,
            ],
            environment,
            timeout=30,
        ).stdout.strip()
        assert probe == "302,302,302,302,302,302,302,302,429"
    finally:
        if probe_attempted:
            _run(["docker", "rm", "--force", probe_name], environment, check=False)
        if compose_attempted:
            teardown = _run(
                [
                    *prefix,
                    "down",
                    "--volumes",
                    "--remove-orphans",
                ],
                environment,
                check=False,
            )
            assert teardown.returncode == 0, f"Compose cleanup failed: {teardown.stderr}"
        if blocker_created:
            _run(["docker", "network", "rm", blocker], environment, check=False)

        project_containers = _run(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ],
            environment,
        ).stdout.strip()
        project_volumes = _run(
            [
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ],
            environment,
        ).stdout.strip()
        for resource_name in (test_network, blocker):
            remaining = _run(
                ["docker", "network", "inspect", resource_name], environment, check=False
            )
            assert remaining.returncode != 0, f"test network {resource_name} was not removed"
        remaining_probe = _run(
            ["docker", "ps", "--all", "--quiet", "--filter", f"name={probe_name}"], environment
        ).stdout.strip()
        assert not project_containers
        assert not project_volumes
        assert not remaining_probe
