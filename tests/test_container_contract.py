"""Static checks keep the local container boundary secure and persistence-safe."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_IMAGE = (
    "python:3.11.15-slim@sha256:"
    "90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff"
)
NODE_IMAGE = (
    "node:22.19.0-bookworm-slim@sha256:"
    "4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90"
)


def test_image_is_pinned_wheel_installed_non_root_and_exec_form() -> None:
    """The runtime image retains only installed artifacts and an unprivileged process."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert dockerfile.count(f"FROM {PYTHON_IMAGE}") == 2
    assert "python -m pip wheel" in dockerfile
    assert "--constraint requirements.lock" in dockerfile
    assert "--no-index" in dockerfile and "stock-probs==0.1.0" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'CMD ["stock-probs", "serve", "--host", "0.0.0.0", "--port", "8000",' in dockerfile
    assert '"--allow-non-loopback"]' in dockerfile
    assert "urllib.request.urlopen" in dockerfile
    assert "http://127.0.0.1:8000/api/v1/health" in dockerfile


def test_next_export_is_built_with_pinned_node_but_runtime_is_python_only() -> None:
    """Node builds the export without crossing into the final Python stage."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    frontend_stage, python_stages = dockerfile.split(f"FROM {PYTHON_IMAGE}", maxsplit=1)
    _, runtime_stage = python_stages.split(f"FROM {PYTHON_IMAGE}", maxsplit=1)

    assert frontend_stage.startswith(f"FROM {NODE_IMAGE} AS frontend-builder\n")
    assert "COPY frontend/package.json frontend/package-lock.json ./" in frontend_stage
    assert "RUN npm ci" in frontend_stage
    assert "COPY frontend/ ./" in frontend_stage
    assert "RUN npm run typecheck && npm run build && npm run test" in frontend_stage
    retained_export = (
        "RUN mkdir /static-next \\\n"
        "    && cp out/index.html out/api-docs.html /static-next/ \\\n"
        "    && cp -R out/_next /static-next/"
    )
    assert retained_export in frontend_stage
    assert all(name not in frontend_stage for name in (".txt", "404", "_not-found"))
    export_copy = (
        "COPY --from=frontend-builder /static-next "
        "./src/stock_probs/static/next"
    )
    assert python_stages.index(export_copy) < python_stages.index("python -m pip wheel")
    assert "COPY --from=frontend-builder /build/frontend/out" not in dockerfile
    assert "node:" not in runtime_stage
    assert "npm " not in runtime_stage
    assert "frontend" not in runtime_stage
    assert "COPY src" not in runtime_stage


def test_compose_limits_access_resources_and_keeps_all_state_on_data_volume() -> None:
    """Compose publishes only loopback and mounts one durable state directory."""

    compose = (ROOT / "compose.yaml").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text()

    assert '"127.0.0.1:${STOCK_PROBS_PORT:-8000}:8000"' in compose
    assert "STOCK_PROBS_DATA_DIR: /data" in compose
    assert "${STOCK_PROBS_PROVIDER:-yahoo}" in compose
    assert "stock-probs-data:/data" in compose
    assert "read_only: true" in compose
    # This is an in-memory container mount, not a host temporary-file trust boundary.
    assert "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777" in compose  # noqa: S108
    assert all(
        setting in compose
        for setting in (
            "pids_limit: 128",
            "mem_limit: 768m",
            "cpus: 1.0",
            "max-size: 10m",
            'max-file: "3"',
            "restart: unless-stopped",
            "no-new-privileges:true",
        )
    )
    assert all(
        exclusion in dockerignore
        for exclusion in (
            ".git/",
            ".venv/",
            "burry_env/",
            "frontend/node_modules/",
            "frontend/.next/",
            "frontend/out/",
            "src/stock_probs/static/next/",
            "data/",
            "*.sqlite3-*",
            "*.spbackup",
            "SESSION-EXPORT.md",
            "tests/",
            "test-results/",
            ".env.*",
            "*.pem",
        )
    )
    assert "frontend/" not in dockerignore.splitlines()
    assert "frontend/package-lock.json" not in dockerignore


def test_arm64_compose_builds_actual_targets_and_contains_the_production_runtime() -> None:
    """The architecture smoke uses the production Dockerfile and a loopback-only app."""

    compose = (ROOT / "scripts/compose.arm64.yml").read_text()

    assert compose.count("platform: linux/arm64") >= 4
    assert "target: frontend-builder" in compose
    assert 'image: "${STOCK_PROBS_ARM64_FRONTEND_IMAGE:?}"' in compose
    assert 'image: "${STOCK_PROBS_ARM64_IMAGE:?}"' in compose
    assert '"127.0.0.1:${STOCK_PROBS_ARM64_PORT:?}:8000"' in compose
    assert "STOCK_PROBS_PROVIDER: fixture" in compose
    assert '"arm64-app-data:/data"' in compose
    assert all(
        value in compose
        for value in (
            "read_only: true",
            'cap_drop: ["ALL"]',
            'security_opt: ["no-new-privileges:true"]',
            "pids_limit: 128",
            "mem_limit: 768m",
            "max-size: 10m",
            'max-file: "3"',
        )
    )
