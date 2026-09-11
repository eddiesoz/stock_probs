"""M01/M06 configuration tests pin loopback, MCP, agent, and CI safety contracts."""

from __future__ import annotations

import json
import re
import stat
import sys
from pathlib import Path

import pytest

from stock_probs.cli import main
from stock_probs.config import Settings

ROOT = Path(__file__).parents[1]


def test_settings_reject_unbounded_or_ambiguous_environment(monkeypatch):
    monkeypatch.setenv("STOCK_PROBS_PROVIDER_TIMEOUT", "nan")
    with pytest.raises(ValueError, match="TIMEOUT"):
        Settings.from_env()

    monkeypatch.setenv("STOCK_PROBS_PROVIDER_TIMEOUT", "8")
    monkeypatch.setenv("STOCK_PROBS_PORT", "70000")
    with pytest.raises(ValueError, match="PORT"):
        Settings.from_env()

    monkeypatch.setenv("STOCK_PROBS_PORT", "8000")
    monkeypatch.setenv("STOCK_PROBS_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="PROVIDER"):
        Settings.from_env()


def test_settings_hardens_existing_directories_and_never_chmods_symlink_target(tmp_path):
    """Private runtime setup repairs modes but fails closed on a linked backup directory."""

    data_dir = tmp_path / "runtime"
    backup_dir = data_dir / "backups"
    settings = Settings(data_dir, data_dir / "stock_probs.sqlite3", backup_dir)
    settings.ensure_local_dirs()
    data_dir.chmod(0o777)
    backup_dir.chmod(0o777)
    settings.ensure_local_dirs()

    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700

    backup_dir.rmdir()
    target = tmp_path / "outside"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    backup_dir.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        settings.ensure_local_dirs()
    # The no-follow open must not harden an unrelated target chosen by a local attacker.
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_cli_requires_explicit_non_loopback_acknowledgement(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["stock-probs", "serve", "--host", "0.0.0.0", "--port", "8000"],  # noqa: S104
    )
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2


def test_official_playwright_mcp_is_pinned_headless_and_isolated():
    package = json.loads((ROOT / "tools/browser/package.json").read_text())
    config = json.loads((ROOT / "opencode.json").read_text())
    launcher = (ROOT / "scripts/playwright-mcp.sh").read_text()
    command = config["mcp"]["playwright"]["command"]

    assert package["devDependencies"]["@playwright/mcp"] == "0.0.80"
    assert command[0] == "./scripts/playwright-mcp.sh"
    assert command[1:6] == ["--headless", "--isolated", "--browser", "chromium", "--allowed-hosts"]
    assert "127.0.0.1,localhost,[::1]" in command
    assert "http://127.0.0.1:*;http://localhost:*" in " ".join(command)
    assert "--output-max-size" in command and "--timeout-navigation" in command
    assert config["tool_output"]["max_bytes"] == 32768
    assert "playwright-mcp" in launcher


def test_sol_and_luna_profiles_preserve_ownership_boundaries():
    sol = (ROOT / ".opencode/agent/sol-build.md").read_text()
    qa = (ROOT / ".opencode/agent/luna-qa.md").read_text()
    docs = (ROOT / ".opencode/agent/luna-docs.md").read_text()

    assert "model: openai/gpt-5.6-sol" in sol and "variant: high" in sol
    assert "model: openai/gpt-5.6-luna" in qa and "variant: max" in qa
    assert "# SOL HIGH build" in sol and "# LUNA MAX QA" in qa and "# LUNA MAX docs" in docs
    assert '"tests/**": allow' in qa
    assert '"MVP-PLAN.md": allow' in docs
    assert "burry_env/**\": deny" in sol


def test_ci_and_frontend_fail_closed_on_required_boundaries():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    javascript = (ROOT / "src/stock_probs/static/app.js").read_text().lower()

    assert "make check" in workflow and "make browser-test" in workflow
    assert "make browser-install" in workflow and "make mcp-smoke" in workflow
    assert "M06-browser-${{ github.sha }}" in workflow
    assert "comment_audit.py" in workflow
    assert 'const apiroot = "/api/v1"' in javascript
    assert "sqlite" not in javascript and "yahoo.com" not in javascript


def test_reproducible_arm64_toolchains_are_pinned_and_generated_files_ignored():
    """Lock source archives and ensure local dependency/output trees never become evidence."""

    node_installer = (ROOT / "scripts/install-node-arm64.sh").read_text()
    requirements = (ROOT / "requirements.lock").read_text()
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    browser_lock = json.loads((ROOT / "tools/browser/package-lock.json").read_text())

    assert 'NODE_VERSION="22.19.0"' in node_installer
    assert "NODE_SHA256=" in node_installer and "--max-time 120" in node_installer
    assert "mypy==1.17.1" in requirements and "setuptools==80.9.0" in requirements
    assert "node_modules/" in ignore and "test-results/" in ignore
    assert browser_lock["lockfileVersion"] == 3


def test_makefile_exposes_the_exact_supported_operational_targets():
    """Keep automation and operator entry points stable while recipes evolve internally."""

    makefile = (ROOT / "Makefile").read_text()
    targets = set(re.findall(r"^([a-z][a-z-]*):", makefile, flags=re.MULTILINE))
    assert {
        "setup",
        "dev",
        "check",
        "browser-install",
        "browser-test",
        "acceptance",
        "live-smoke",
        "release-check",
        "backup",
        "restore",
    } <= targets


def test_browser_gate_allocates_an_isolated_loopback_port_by_default():
    """Parallel or interrupted QA runs must not collide with a stale fixed-port server."""

    makefile = (ROOT / "Makefile").read_text()

    assert 's.bind(("127.0.0.1", 0))' in makefile
    assert 'STOCK_PROBS_BROWSER_PORT="$$PORT"' in makefile
    assert "reuseExistingServer: false" in (
        ROOT / "tools/browser/playwright.config.js"
    ).read_text()
