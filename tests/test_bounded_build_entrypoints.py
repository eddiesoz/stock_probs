"""Keep every repository-owned app image build on the bounded Buildx path."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_compose_has_no_direct_build_and_requires_the_bounded_launcher() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    app = compose.split("  app:\n", maxsplit=1)[1].split("\nvolumes:\n", maxsplit=1)[0]

    assert "    build:" not in app
    assert "pull_policy: never" in app
    assert "${STOCK_PROBS_LOCAL_IMAGE:?Use scripts/local-compose.sh" in app

    launcher = (ROOT / "scripts/local-compose.sh").read_text(encoding="utf-8")
    assert "bounded_docker_build.py" in launcher
    assert "--local-image-build" in launcher
    assert "--local-current-image" in launcher
    assert "STOCK_PROBS_LOCAL_IMAGE" in launcher
    assert 'if [[ "$ARG" == "--build" ]]' in launcher


def test_local_compose_down_uses_fallback_when_image_variable_is_unset(tmp_path: Path) -> None:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    docker_log = tmp_path / "docker-argv.txt"
    docker_stub = stub_bin / "docker"
    docker_stub.write_text(
        '#!/bin/sh\nprintf \'%s|%s\\n\' "${STOCK_PROBS_LOCAL_IMAGE-UNSET}" "$*" > "$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    environment = {
        "PATH": f"{stub_bin}:/usr/bin:/bin",
        "DOCKER_LOG": str(docker_log),
    }

    result = subprocess.run(  # noqa: S603 - Fixed local script and inert stub.
        ["/usr/bin/bash", str(ROOT / "scripts/local-compose.sh"), "down"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert docker_log.read_text(encoding="utf-8").splitlines() == [
        f"stock-probs:local|compose --project-directory {ROOT} --file {ROOT / 'compose.yaml'} down"
    ]


def test_arm64_smoke_routes_its_build_through_the_shared_helper() -> None:
    script = (ROOT / "scripts/arm64-smoke.sh").read_text(encoding="utf-8")

    assert "--arm64-compose-build" in script
    assert "bounded_docker_build.py" in script
    assert "--plan-arm64-cleanup" in script
    assert "--ack-arm64-cleanup" in script
    assert "ARM_BUILD_ATTEMPTED" in script
    assert 'docker image rm --no-prune "$image_id"' in script
    assert [line.strip() for line in script.splitlines() if "docker image rm" in line] == [
        'docker image rm --no-prune "$image_id" >/dev/null || return $?'
    ]
    assert 'COMPOSE_FILE" build --pull' not in script
    assert '--registered-image-id "$image_id"' in script
    assert '--frontend-image "$ARM64_FRONTEND_IMAGE"' in script


def test_arm64_app_startup_cannot_fall_back_to_compose_build_or_pull() -> None:
    script = (ROOT / "scripts/arm64-smoke.sh").read_text(encoding="utf-8")
    lines = script.splitlines()
    startup_index = next(index for index, line in enumerate(lines) if "up --detach" in line)

    assert sum("up --detach" in line for line in lines) == 1
    assert lines[startup_index].strip().endswith("--no-build --pull never \\")
    assert lines[startup_index + 1].strip() == "--no-deps arm64-app"
    assert "--arm64-compose-build" in script
    assert "$ROOT/scripts/bounded_docker_build.py" in script

    for setting in ("COMPOSE_BAKE", "BUILDX_BUILDER", "DOCKER_BUILDKIT"):
        assert f"export {setting}=" not in script
