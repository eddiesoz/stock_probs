"""Static checks keep the local container boundary secure and persistence-safe."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_is_pinned_wheel_installed_non_root_and_exec_form() -> None:
    """The runtime image retains only installed artifacts and an unprivileged process."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    pinned_image = (
        "python:3.11.15-slim@sha256:"
        "90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff"
    )

    assert dockerfile.count(f"FROM {pinned_image}") == 2
    assert "python -m pip wheel" in dockerfile
    assert "--constraint requirements.lock" in dockerfile
    assert "--no-index" in dockerfile and "stock-probs==0.1.0" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'CMD ["stock-probs", "serve", "--host", "0.0.0.0", "--port", "8000",' in dockerfile
    assert '"--allow-non-loopback"]' in dockerfile
    assert "urllib.request.urlopen" in dockerfile
    assert "http://127.0.0.1:8000/api/v1/health" in dockerfile


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
