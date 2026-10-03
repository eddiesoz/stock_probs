"""M01/M06 configuration tests pin loopback, MCP, agent, and CI safety contracts."""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from scripts.sync_model_routing import projected_files, sync_projection
from stock_probs.cli import main
from stock_probs.config import Settings

ROOT = Path(__file__).parents[1]

SENSITIVE_READ_PATTERNS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.env",
    "**/*.env",
    "*.env.*",
    "**/*.env.*",
    ".env.example",
    "**/.env.example",
    "*.env.example",
    "**/*.env.example",
    "*credential*",
    "**/*credential*",
    "*secret*",
    "**/*secret*",
    "*token*",
    "**/*token*",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
    "*.p12",
    "**/*.p12",
    "*.pfx",
    "**/*.pfx",
    "*private*key*",
    "**/*private*key*",
)
SENSITIVE_READ_PATHS = (
    ".env",
    ".env.local",
    ".env.example",
    "nested/.env",
    "nested/.env.production",
    "config/credentials.json",
    "secrets/api-token.txt",
    "certs/private-key.pem",
    "certs/server.key",
    "certs/archive.p12",
)


def _frontmatter_read_rules(text: str) -> list[tuple[str, str]]:
    matches = re.findall(
        r"^  - action: read\n    resource: (.+)\n    effect: (.+)$",
        text,
        re.MULTILINE,
    )
    return [(resource.strip('"'), effect) for resource, effect in matches]


def _assert_sensitive_reads_are_terminally_denied(
    rules: list[tuple[str, str]],
) -> None:
    broad_allow = max(
        index
        for index, (resource, effect) in enumerate(rules)
        if resource == "*" and effect == "allow"
    )
    assert all((pattern, "deny") in rules for pattern in SENSITIVE_READ_PATTERNS)
    for path in SENSITIVE_READ_PATHS:
        matches = [
            (index, effect)
            for index, (pattern, effect) in enumerate(rules)
            if fnmatchcase(path, pattern)
        ]
        assert matches, path
        assert matches[-1][1] == "deny", path
        assert matches[-1][0] > broad_allow, path
    general_matches = [effect for pattern, effect in rules if fnmatchcase("src/module.py", pattern)]
    assert general_matches[-1] == "allow"


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

    monkeypatch.setenv("STOCK_PROBS_PROVIDER", "fixture")
    monkeypatch.setenv("STOCK_PROBS_PORT", "not-a-number")
    with pytest.raises(ValueError, match="STOCK_PROBS_PORT"):
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


def test_cli_uses_bounded_environment_listener_without_startup_writes(monkeypatch, tmp_path):
    captured = {}
    data_dir = tmp_path / "server-state"
    monkeypatch.setenv("STOCK_PROBS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("STOCK_PROBS_PROVIDER", "fixture")
    monkeypatch.setenv("STOCK_PROBS_HOST", "localhost")
    monkeypatch.setenv("STOCK_PROBS_PORT", "8123")
    monkeypatch.setattr(sys, "argv", ["stock-probs", "serve"])
    monkeypatch.setattr(
        "stock_probs.cli.uvicorn.run", lambda app, **kwargs: captured.update(kwargs)
    )

    main()

    assert captured["host"] == "localhost"
    assert captured["port"] == 8123
    assert captured["workers"] == 1
    # Uvicorn owns lifespan startup; constructing its ASGI app must not touch user state.
    assert not data_dir.exists()


def test_importing_asgi_module_does_not_create_runtime_storage(tmp_path):
    import stock_probs.api as api_module

    data_dir = tmp_path / "import-state"
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("STOCK_PROBS_DATA_DIR", str(data_dir))
        environment.setenv("STOCK_PROBS_PROVIDER", "fixture")
        # Reload executes the module-level ASGI construction against isolated settings.
        importlib.reload(api_module)

    assert not data_dir.exists()
    # Restore the process-global module app to the caller's environment for later tests.
    importlib.reload(api_module)


def test_official_playwright_mcp_is_pinned_headless_and_isolated():
    package = json.loads((ROOT / "tools/browser/package.json").read_text())
    config = json.loads((ROOT / "opencode.json").read_text())
    launcher = (ROOT / "scripts/playwright-mcp.sh").read_text()
    server = config["mcp"]["servers"]["playwright"]
    command = server["command"]

    assert package["devDependencies"]["@playwright/mcp"] == "0.0.80"
    assert set(config["mcp"]) == {"servers"}
    assert set(config["mcp"]["servers"]) == {"playwright", "signal-ledger-deploy"}
    assert command == [
        "./scripts/playwright-mcp.sh",
        "--headless",
        "--isolated",
        "--browser",
        "chromium",
        "--allowed-hosts",
        "127.0.0.1,localhost,[::1]",
        "--allowed-origins",
        "http://127.0.0.1:*;http://localhost:*;http://[::1]:8000;http://[::1]:8765",
        "--block-service-workers",
        "--image-responses",
        "omit",
        "--output-dir",
        ".playwright-mcp",
        "--output-max-size",
        "10485760",
        "--timeout-action",
        "10000",
        "--timeout-navigation",
        "30000",
    ]
    assert server["disabled"] is False
    assert server["timeout"] == {"catalog": 30000, "execution": 30000}
    assert "./tools/ponytail/skills" not in json.dumps(config)
    assert "plugins" not in config
    assert "plugin" not in config
    assert not (ROOT / ".opencode/plugins").exists()
    assert "instructions" not in config
    assert config["tool_output"]["max_bytes"] == 32768
    assert "playwright-mcp" in launcher


def test_native_skill_source_is_automatic_without_duplicate_or_flat_skill_sources():
    config = json.loads((ROOT / "opencode.json").read_text())

    assert "skills" not in config
    assert "./.opencode/skills" not in json.dumps(config)
    assert not list((ROOT / ".opencode/skills").glob("*.md"))
    assert (ROOT / ".opencode/skill-history/learnings.md").is_file()


def test_native_agents_keep_builtins_for_sol_and_luna_for_custom_subagents():
    config = json.loads((ROOT / "opencode.json").read_text())
    routing = json.loads((ROOT / "model-routing.json").read_text())
    roles = routing["roles"]
    opencode_routing = routing["opencode"]
    legacy = ROOT / ".opencode/agent"
    agents = ROOT / ".opencode/agents"
    profiles = {path.stem: path.read_text() for path in agents.glob("*.md")}

    assert not any(legacy.glob("*.md"))
    assert set(profiles) == {"luna-build", "luna-qa", "luna-docs"}
    assert set(path.stem for path in agents.glob("*.md")) == set(profiles)
    assert set(config["agents"]) == {"build", "plan"}
    builtin_agents = config["agents"]
    for agent in builtin_agents.values():
        assert "permissions" in agent
        assert "permission" not in agent
        assert all(set(rule) == {"action", "resource", "effect"} for rule in agent["permissions"])
    assert all(
        builtin_agents[agent]["model"]
        == (
            f"openai/{roles[opencode_routing['builtin_agents'][agent]]['model']}#"
            f"{roles[opencode_routing['builtin_agents'][agent]]['reasoning_effort']}"
        )
        for agent in ("build", "plan")
    )
    assert all(
        opencode_routing["builtin_agents"][agent] == "orchestrator" for agent in ("build", "plan")
    )
    build_permissions = builtin_agents["build"]["permissions"]
    assert {"action": "edit", "resource": "*", "effect": "deny"} in build_permissions
    assert {"action": "subagent", "resource": "*", "effect": "deny"} in build_permissions
    assert {"action": "subagent", "resource": "luna-*", "effect": "allow"} in build_permissions
    assert "Orchestrator" not in config["agents"]
    assert "orchestrator" not in config["agents"]

    for profile_name, profile in profiles.items():
        assert "mode: subagent" in profile
        assigned_role = roles[opencode_routing["agents"][profile_name]]
        assert (
            f"model: openai/{assigned_role['model']}#{assigned_role['reasoning_effort']}" in profile
        )
        assert "permissions:\n" in profile
        assert not re.search(r"^(?:name|variant|permission|bash|task):", profile, re.MULTILINE)
    assert all(role == "worker" for role in opencode_routing["agents"].values())

    build = profiles["luna-build"]
    qa = profiles["luna-qa"]
    docs = profiles["luna-docs"]
    assert '- action: edit\n    resource: "*"\n    effect: allow' in build
    assert 'resource: "AGENTS.md"\n    effect: deny' in build
    assert 'resource: ".git/**"\n    effect: deny' in build
    assert 'resource: "**/node_modules/**"\n    effect: deny' in build
    assert 'resource: "**/test-results/**"\n    effect: deny' in build
    assert 'action: subagent\n    resource: "*"\n    effect: deny' in build
    assert 'action: shell\n    resource: "git *"\n    effect: deny' in build
    assert 'action: playwright_*\n    resource: "*"\n    effect: allow' in qa
    assert 'action: edit\n    resource: "*"\n    effect: deny' in qa
    assert 'action: subagent\n    resource: "*"\n    effect: deny' in qa
    assert 'resource: "MVP-PLAN.md"\n    effect: allow' in docs
    assert 'resource: "docs/**/*.md"\n    effect: allow' in docs
    assert 'action: subagent\n    resource: "*"\n    effect: deny' in docs
    assert 'action: shell\n    resource: "git *"\n    effect: deny' in docs
    assert all("ponytail" not in profile.lower() for profile in profiles.values())

    commands = ROOT / ".opencode/commands"
    assert {"qa.md", "handoff.md", "resume.md"} <= {path.name for path in commands.glob("*.md")}
    assert "agent: luna-qa" in (commands / "qa.md").read_text()
    assert "agent: build" in (commands / "handoff.md").read_text()
    assert "agent: build" in (commands / "resume.md").read_text()
    assert not any(commands.glob("ponytail*.md"))
    qa_command = (commands / "qa.md").read_text().lower()
    assert "agent: luna-qa" in qa_command
    assert "ponytail" not in qa_command


def test_canonical_model_manifest_matches_codex_model_fields():
    routing = json.loads((ROOT / "model-routing.json").read_text())
    roles = routing["roles"]
    codex_routing = routing["codex"]
    default_role = roles[codex_routing["default_role"]]
    project = tomllib.loads((ROOT / ".codex/config.toml").read_text())

    assert project["model"] == default_role["model"]
    assert project["model_reasoning_effort"] == default_role["reasoning_effort"]
    assert codex_routing["default_role"] == "orchestrator"

    for profile_name, role_name in codex_routing["agents"].items():
        profile = tomllib.loads((ROOT / f".codex/agents/{profile_name}.toml").read_text())
        assigned_role = roles[role_name]
        assert profile["model"] == assigned_role["model"]
        assert profile["model_reasoning_effort"] == assigned_role["reasoning_effort"]
        assert role_name == "worker"


def test_model_routing_sync_checks_drift_and_is_idempotent(tmp_path: Path):
    routing_file = ROOT / "model-routing.json"
    shutil.copy2(routing_file, tmp_path / routing_file.name)
    for relative in (".codex/config.toml", "opencode.json"):
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for relative_directory in (".codex/agents", ".opencode/agents"):
        source_directory = ROOT / relative_directory
        shutil.copytree(source_directory, tmp_path / relative_directory)

    root_config = tmp_path / ".codex/config.toml"
    before = root_config.read_text()
    model = json.loads(routing_file.read_text())["roles"]["orchestrator"]["model"]
    expected_line = f'model = "{model}"'
    assert expected_line in before
    root_config.write_text(before.replace(expected_line, 'model = "drift-marker"', 1))
    drifted_bytes = root_config.read_bytes()

    changed = sync_projection(tmp_path, write=False)
    assert changed == [".codex/config.toml"]
    assert root_config.read_bytes() == drifted_bytes
    assert sync_projection(tmp_path, write=True) == [".codex/config.toml"]
    assert sync_projection(tmp_path, write=False) == []

    synchronized_files = projected_files(tmp_path)
    synchronized_bytes = {path: path.read_bytes() for path in synchronized_files}
    assert sync_projection(tmp_path, write=True) == []
    assert {path: path.read_bytes() for path in synchronized_files} == synchronized_bytes


def test_sensitive_read_rules_are_final_and_fail_closed_for_build_and_luna():
    config = json.loads((ROOT / "opencode.json").read_text())
    build_rules = [
        (rule["resource"], rule["effect"])
        for rule in config["agents"]["build"]["permissions"]
        if rule["action"] == "read"
    ]
    _assert_sensitive_reads_are_terminally_denied(build_rules)

    for path in sorted((ROOT / ".opencode/agents").glob("*.md")):
        _assert_sensitive_reads_are_terminally_denied(_frontmatter_read_rules(path.read_text()))


def test_local_gate_and_frontend_fail_closed_on_required_boundaries():
    local_gate = (ROOT / "scripts/local-gate.sh").read_text()
    makefile = (ROOT / "Makefile").read_text()
    javascript = (ROOT / "src/stock_probs/static/app.js").read_text().lower()

    assert not (ROOT / ".github/workflows/ci.yml").exists()
    assert "set -euo pipefail" in local_gate and '"result": result' in local_gate
    assert "package-check check" in makefile and "./scripts/local-gate.sh release" in makefile
    assert "browser-test" in makefile and "comment_audit.py" in makefile
    assert 'const apiroot = "/api/v1"' in javascript
    assert "sqlite" not in javascript and "yahoo.com" not in javascript


def test_local_gate_accepts_canonical_task_ids():
    local_gate = (ROOT / "scripts/local-gate.sh").read_text()
    makefile = (ROOT / "Makefile").read_text()
    local_gate_match = re.search(r'"\$TASK_ID" =~ (\^\S+\$)', local_gate)

    assert local_gate_match
    local_gate_pattern = local_gate_match.group(1)
    assert re.fullmatch(local_gate_pattern, "M09")
    assert all(
        re.fullmatch(local_gate_pattern, task)
        for milestone in range(10)
        for task in (
            f"M{milestone:02}",
            f"EXP-M{milestone:02}",
            f"R-M{milestone:02}-1",
            f"R-ASTRA-{milestone + 1}",
        )
    )
    assert re.fullmatch(local_gate_pattern, "ASTRA-FINAL")
    assert re.fullmatch(local_gate_pattern, "EXP-FINAL")
    assert all(
        re.fullmatch(local_gate_pattern, task) is None
        for task in ("M10", "EXP-M10", "NOTIFY-FINAL", "R-M00-0", "R-ASTRA-1-extra")
    )
    assert "  m09)" in local_gate
    assert "TASK_ID=M09 ./scripts/local-gate.sh m09" in makefile


def test_arm64_smoke_accepts_canonical_task_ids_and_rejects_suffixes():
    arm64_smoke = (ROOT / "scripts/arm64-smoke.sh").read_text()
    match = re.search(r'"\$TASK_ID" =~ (\^\S+\$)', arm64_smoke)

    assert match
    pattern = match.group(1)
    accepted = ["ASTRA-FINAL", "EXP-FINAL", "R-ASTRA-0", "R-ASTRA-106"]
    accepted += [f"M{milestone:02}" for milestone in range(10)]
    accepted += [f"EXP-M{milestone:02}" for milestone in range(10)]
    accepted += [f"R-M{milestone:02}-1" for milestone in range(10)]
    assert all(re.fullmatch(pattern, task) for task in accepted)
    assert all(
        re.fullmatch(pattern, task) is None
        for task in (
            "M10",
            "EXP-M10",
            "NOTIFY-FINAL",
            "R-M00-0",
            "R-ASTRA-106-extra",
            "R-ASTRA-106.1",
        )
    )


def test_local_gate_and_arm64_smoke_preflight_reject_non_canonical_task_ids():
    """Bounded preflight only: an invalid TASK_ID exits 2 before any gate work starts."""

    cases = (
        ("scripts/local-gate.sh", ["m01"], "TASK_ID", "NOTIFY-FINAL"),
        ("scripts/local-gate.sh", ["m01"], "TASK_ID", "EXP-M10"),
        ("scripts/arm64-smoke.sh", [], "STOCK_PROBS_TASK_ID", "NOTIFY-FINAL"),
        ("scripts/arm64-smoke.sh", [], "STOCK_PROBS_TASK_ID", "R-M00-0"),
    )
    for script, args, variable, task in cases:
        environment = {**os.environ, variable: task}
        bash = shutil.which("bash")
        assert bash is not None
        # The interpreter is trusted via PATH resolution; argv is fixed and shell mode is disabled.
        completed = subprocess.run(  # noqa: S603
            [bash, str((ROOT / script).resolve()), *args],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 2, (script, task, completed.stderr)
        assert f"{variable} must be" in completed.stderr
        assert "ASTRA-FINAL" in completed.stderr and "EXP-FINAL" in completed.stderr


def test_reproducible_arm64_toolchains_are_pinned_and_generated_files_ignored():
    """Lock source archives and ensure local dependency/output trees never become evidence."""

    node_installer = (ROOT / "scripts/install-node.sh").read_text()
    requirements = (ROOT / "requirements.lock").read_text()
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    browser_lock = json.loads((ROOT / "tools/browser/package-lock.json").read_text())

    assert 'NODE_VERSION="22.19.0"' in node_installer
    assert node_installer.count("NODE_SHA256=") == 2 and "--max-time 120" in node_installer
    assert "arm64" in node_installer and "x64" in node_installer
    assert "mypy==1.17.1" in requirements and "setuptools==84.0.0" in requirements
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
    assert "reuseExistingServer: false" in (ROOT / "tools/browser/playwright.config.js").read_text()
