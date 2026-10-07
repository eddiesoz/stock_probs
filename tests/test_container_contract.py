"""Static checks keep the local container boundary secure and persistence-safe."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_IMAGE = (
    "python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff"
)
NODE_IMAGE = (
    "node:22.19.0-bookworm-slim@sha256:"
    "4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90"
)


def test_image_is_pinned_wheel_installed_non_root_and_exec_form() -> None:
    """The runtime image retains only installed artifacts and an unprivileged process."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert dockerfile.startswith("ARG SOURCE_DATE_EPOCH=1757894400\n")
    assert dockerfile.count("ARG SOURCE_DATE_EPOCH") == 4
    assert dockerfile.count(f"FROM {PYTHON_IMAGE}") == 2
    assert (
        "ghcr.io/anomalyco/opencode:2.0.7@sha256:d2c7ddda8142b47942426972fcee07f56ecde762ac7f528c5e53c2f957aabc05"
        in dockerfile
    )
    assert (
        "ghcr.io/anomalyco/opencode:2.0.7@sha256:396bd94fe43d392fd7b12e3ec83d80c0e527715936bfcf6f9120a4385e541e42"
        in dockerfile
    )
    assert "python -m pip wheel" in dockerfile
    assert "--constraint requirements.lock" in dockerfile
    assert "--no-compile" in dockerfile and "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "--root /install" in dockerfile and "COPY --from=builder /install /" in dockerfile
    assert "--no-index" in dockerfile and "stock-probs==0.1.0" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "stock_probs.container_supervisor"]' in dockerfile
    assert (
        'CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--allow-non-loopback"]' in dockerfile
    )
    assert "/usr/local/bin/opencode" in dockerfile
    assert "urllib.request.urlopen" in dockerfile
    assert "http://127.0.0.1:8000/api/v1/health" in dockerfile


def test_native_opencode_is_source_built_in_a_separate_pinned_stage() -> None:
    """Only the verified patched V2 binary and its nonsecret receipt reach runtime."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    build_stage, runtime_stage = (
        dockerfile.split("FROM python:3.11.15-slim@sha256:", maxsplit=1)[0],
        dockerfile.rsplit("FROM python:3.11.15-slim@sha256:", maxsplit=1)[-1],
    )

    assert (
        "AS opencode-patched-builder\nARG TARGETARCH\nARG BUILDARCH\nWORKDIR /build" in build_stage
    )
    assert "COPY tools/opencode-v2-security-patch/ /patch/" in build_stage
    assert "RUN python /patch/build_native.py" in build_stage
    assert '    --target-arch "$TARGETARCH"' in build_stage
    assert '    --build-arch "$BUILDARCH"' in build_stage
    assert "    --output /out" in build_stage
    assert "COPY --from=opencode-amd64 /usr/local/bin/opencode" not in dockerfile
    assert "COPY --from=opencode-arm64 /usr/local/bin/opencode" not in dockerfile
    assert (
        "COPY --from=opencode-patched-builder /out/opencode /usr/local/bin/opencode"
        in runtime_stage
    )
    assert (
        "COPY --from=opencode-patched-builder /out/build.json "
        "/usr/local/share/stock-probs/opencode-build.json"
    ) in runtime_stage
    assert (
        "COPY --from=opencode-patched-builder /out/opencode-LICENSE "
        "/usr/local/share/stock-probs/opencode-LICENSE"
    ) in runtime_stage
    assert "/usr/local/share/stock-probs/opencode-LICENSE" in runtime_stage
    assert (
        "chmod 0444 /usr/local/share/stock-probs/opencode-build.json \\\n"
        "        /usr/local/share/stock-probs/opencode-LICENSE"
    ) in runtime_stage
    assert "bun install" not in runtime_stage
    assert "build_native.py" not in runtime_stage
    assert "COPY --from=opencode-assets /out/ /" in runtime_stage
    assert build_stage.count("AS opencode-patched-builder") == 1


def test_next_export_is_built_with_pinned_node_but_runtime_is_python_only() -> None:
    """Node builds the export without crossing into the final Python stage."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    frontend_stage, python_stages = dockerfile.split(f"FROM {PYTHON_IMAGE}", maxsplit=1)
    _, runtime_stage = python_stages.split(f"FROM {PYTHON_IMAGE}", maxsplit=1)

    assert f"FROM {NODE_IMAGE} AS frontend-builder\nARG SOURCE_DATE_EPOCH\n" in frontend_stage
    assert "COPY frontend/package.json frontend/package-lock.json ./" in frontend_stage
    assert "RUN npm ci" in frontend_stage
    assert "COPY frontend/ ./" in frontend_stage
    assert "RUN npm run typecheck && npm run build && npm run test" in frontend_stage
    retained_export = (
        "RUN mkdir -p /static-next/tools \\\n"
        "    && cp out/index.html out/api-docs.html out/overview.html out/research.html "
        "out/tools.html \\\n"
        "       out/sign-in.html out/invite.html out/passkey.html "
        "out/authenticator.html out/account.html "
        "out/admin.html /static-next/ \\\n"
        "    && cp out/tools/forecast.html out/tools/live-trading.html out/tools/markets.html "
        "/static-next/tools/ \\\n"
        "    && cp -R out/_next /static-next/"
    )
    assert retained_export in frontend_stage
    assert all(name not in frontend_stage for name in (".txt", "404", "_not-found"))
    export_copy = "COPY --from=frontend-builder /static-next ./src/stock_probs/static/next"
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
            ".agents/",
            ".codex/",
            ".venv/",
            "burry_env/",
            "infra/",
            ".terraform/",
            "*.tfstate",
            "*.tfstate.*",
            "*.tfvars",
            "*.tfvars.json",
            "tfplan",
            "*.tfplan",
            "*.plan",
            "**/*.tfstate",
            "**/*.tfstate.*",
            "**/*.tfvars",
            "**/*.tfvars.json",
            "**/tfplan",
            "**/*.tfplan",
            "**/*.plan",
            "frontend/node_modules/",
            "frontend/.next/",
            "frontend/out/",
            "src/stock_probs/static/next/",
            "data/",
            "*.sqlite3-*",
            "*.spbackup",
            "**/data/",
            "**/backups/",
            "**/*.db",
            "**/*.db-*",
            "**/*.sqlite",
            "**/*.sqlite-*",
            "**/*.sqlite3",
            "**/*.sqlite3-*",
            "**/*.spbackup",
            "**/*.spbackup-*",
            "SESSION-EXPORT.md",
            "tests/",
            "test-results/",
            ".env.*",
            "*.pem",
            "*.p12",
            "**/.env",
            "**/.env.*",
            "**/*.key",
            "**/*.pem",
            "**/*.p12",
            "id_rsa*",
            "id_dsa*",
            "id_ecdsa*",
            "id_ed25519*",
            "**/id_rsa*",
            "**/id_dsa*",
            "**/id_ecdsa*",
            "**/id_ed25519*",
            "**/.aws/",
            "**/.ssh/",
            "**/secrets/",
            "**/credentials/",
            "**/credentials.json",
            "**/auth.json",
            "**/.npmrc",
            "**/.pypirc",
        )
    )
    assert "frontend/" not in dockerignore.splitlines()
    assert "frontend/package-lock.json" not in dockerignore


def test_arm64_compose_builds_actual_targets_and_contains_the_production_runtime() -> None:
    """The architecture smoke uses the production Dockerfile and a loopback-only app."""

    compose = (ROOT / "scripts/compose.arm64.yml").read_text()

    assert compose.count("platform: linux/arm64") >= 4
    assert compose.count("BUILDPLATFORM: linux/amd64") == 2
    assert compose.count("TARGETARCH: arm64") == 2
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


def test_production_compose_uses_one_container_with_separate_child_privileges() -> None:
    """Production mounts the fixed supervisor paths and supplies only its drop capabilities."""

    compose = (ROOT / "compose.production.yaml").read_text()
    assert 'user: "0:0"' in compose
    assert 'STOCK_PROBS_ASSISTANT_ENABLED: "${STOCK_PROBS_ASSISTANT_ENABLED:-0}"' in compose
    assert "- SETUID" in compose and "- SETGID" in compose
    assert "cap_drop:" in compose and "no-new-privileges:true" in compose
    assert "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700" in compose  # noqa: S108
    assert "/run/assistant:rw,nosuid,nodev,noexec,size=16m,mode=0711" in compose
    assert (
        "/run/assistant-worker-home:rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700"
        in compose
    )
    assert "stop_grace_period: 30s" in compose
