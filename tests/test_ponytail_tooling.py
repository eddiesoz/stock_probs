# ruff: noqa: E501, S603, S607
"""Focused immutable Ponytail and OpenCode configuration checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
PONYTAIL = ROOT / "tools/ponytail"
PLUGIN_SPEC = "file://{env:PWD}/tools/ponytail/.opencode/plugins/ponytail.mjs"

UPSTREAM_HASHES = {
    ".opencode/plugins/ponytail.mjs": "e9e2214149ace3e589a584a27136bf5bd9da558fbad948f8cf1d3bc2c50d3828",
    ".opencode/plugins/ponytail-frontmatter.cjs": "36073b0749a62bebadb22c01b7fc018d063fb20b337591269008051151a1513d",
    "hooks/ponytail-instructions.js": "23c050103f28dbe6bad953ae21d98cd06d720a20f33d4716e9de419f947d495e",
    "hooks/ponytail-config.js": "0a8daf96cf9ac703dc4cb7b5065253567e513c951d60b8eb94a0fe727514aeca",
    "skills/ponytail/SKILL.md": "1316a2f3f95741d2300b116fe0c2d81ce4a9568656ed0a62643f54aaf09957f2",
    "skills/ponytail-audit/SKILL.md": "5560b8e383dbe2ddfddc873a1e2bf2e586e23e0cd7d995537482b2315331f6d1",
    "skills/ponytail-debt/SKILL.md": "c84fba75f0ca12bfe83f9a78ea02fd125c5dd3f1fbb18124105a489937f284e6",
    "skills/ponytail-gain/SKILL.md": "24e01d1c9715cb136ba1c4f1e52a95940c0193558b876828e537736480d6408b",
    "skills/ponytail-help/SKILL.md": "2264d1615117b02b0fd5a69ec84cd2757006471a78e4d6c22eed6d581c1d37a4",
    "skills/ponytail-review/SKILL.md": "40df33b58fc6ef889b93585733feb9566b76e9586efa7f376785c1e995197ac0",
    ".opencode/command/ponytail.md": "800919b5c7b53f05e9adb96e5978818f3b5cd9137bc2df35b1575590d5464f14",
    ".opencode/command/ponytail-audit.md": "6278f820b117a6a57e4c0b013906e06fe4719652e6adc4b9a1b868d6bd1ba6f2",
    ".opencode/command/ponytail-debt.md": "ddbadb1f484a1ecc54ed577b80aa3f7b326ccd1ae2a35159652a52221eb31301",
    ".opencode/command/ponytail-gain.md": "33514a67319e30072e1daeef336b4f4af8de31ef25595a23353f0719004189b2",
    ".opencode/command/ponytail-help.md": "3052afd5cc1ea528d9405729b2620d1b81c36ca3287ec1ae964a68d6feb4c178",
    ".opencode/command/ponytail-review.md": "ff09bd42b1d23bd3e3919c6b7ab4710c0a71b04e23c0fc30fb3c1b1b50451485",
    "LICENSE": "fb1bc6909ac3ef82d5c22106e32ef682b0cff66788fa915fb9b53b15c9d2f3ab",
}


def test_vendored_closure_matches_recorded_upstream_hashes():
    provenance = (PONYTAIL / "PROVENANCE.md").read_text()
    assert "16f29800fd2681bdf24f3eb4ccffe38be3baec6b" in provenance
    assert "MIT" in provenance
    closure = {
        path.relative_to(PONYTAIL).as_posix()
        for path in PONYTAIL.rglob("*")
        if path.is_file() and path.name != "smoke.mjs"
    }
    assert closure == set(UPSTREAM_HASHES) | {"PROVENANCE.md", "package.json"}

    for relative, expected in UPSTREAM_HASHES.items():
        source = (PONYTAIL / relative).read_text()
        if relative == ".opencode/plugins/ponytail.mjs":
            guard = (
                "      // The system-transform hook has no agent field; the protected broker supplies this canonical prompt marker.\n"
                "      if (output.system.some((prompt) => prompt.includes('This agent is reserved for system use. Do not invoke directly.'))) return;\n"
            )
            assert guard in source
            source = source.replace(guard, "")
        assert hashlib.sha256(source.encode()).hexdigest() == expected
        assert expected in provenance


def test_project_registers_one_local_plugin_and_preserves_playwright():
    config = json.loads((ROOT / "opencode.json").read_text())
    assert config["plugin"] == [PLUGIN_SPEC]
    assert config["skills"]["paths"] == [".opencode/skills"]
    assert set(config["mcp"]) == {"playwright"}
    assert "ponytail" not in config["mcp"]
    assert "@dietrichgebert/ponytail" not in json.dumps(config)
    assert "/home/brajam/repos/ingenium" not in json.dumps(config)


def test_profiles_are_four_deny_default_roles_without_qa_repair_or_git_mutation():
    profiles = sorted((ROOT / ".opencode/agent").glob("*.md"))
    assert [path.name for path in profiles] == [
        "astra.md",
        "luna-docs.md",
        "luna-qa.md",
        "sol-build.md",
    ]
    for profile in profiles:
        text = profile.read_text()
        assert '  "*": deny' in text
        assert "task:\n    \"*\": deny" in text
        assert "git commit" not in text and "git push" not in text
    qa = (ROOT / ".opencode/agent/luna-qa.md").read_text()
    assert "Never delegate or repair findings" in qa
    assert "ponytail-review: allow" in qa


def test_node_plugin_smoke_has_no_credential_io():
    completed = subprocess.run(
        ["node", "tools/ponytail/smoke.mjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert completed.stdout.strip() == "ponytail plugin smoke: pass"


def test_opencode_11831_loads_valid_config_in_isolated_home(tmp_path):
    environment = os.environ.copy()
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        location = tmp_path / name.lower()
        location.mkdir()
        environment[name] = str(location)
    environment["PWD"] = str(ROOT)
    environment["PONYTAIL_DEFAULT_MODE"] = "full"
    launcher = (ROOT / "scripts/ponytail-review.sh").read_text()
    environment["OPENCODE_CONFIG_CONTENT"] = re.search(
        r"readonly_review_config='([^']+)'", launcher
    ).group(1)

    version = subprocess.run(
        ["opencode", "--version"], text=True, capture_output=True, check=True, timeout=10
    ).stdout.strip()
    assert version == "1.18.31"
    resolved = subprocess.run(
        ["opencode", "debug", "config"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    config = json.loads(resolved.stdout)
    assert sorted(name for name in config["command"] if name.startswith("ponytail")) == [
        "ponytail",
        "ponytail-audit",
        "ponytail-debt",
        "ponytail-gain",
        "ponytail-help",
        "ponytail-review",
    ]
    assert str(PONYTAIL / "skills") in config["skills"]["paths"]
    assert config["plugin"] == [PONYTAIL.joinpath(".opencode/plugins/ponytail.mjs").as_uri()]
    agents = config["agent"]
    assert {
        name: (agent["model"], agent.get("variant"), agent["mode"])
        for name, agent in agents.items()
    } == {
        "ASTRA": ("openai/gpt-6-astra", "max", "subagent"),
        "LUNA MAX QA": ("openai/gpt-5.6-luna", "max", "subagent"),
        "LUNA MAX docs": ("openai/gpt-5.6-luna", "max", "subagent"),
        "SOL HIGH build": ("openai/gpt-5.6-sol", "high", "subagent"),
        "Orchestrator": ("openai/gpt-5.6-sol", "medium", "primary"),
    }
    assert agents["Orchestrator"]["options"]["stock_probs_max_active_subagents"] == 6
    assert all(
        agent["permission"]["*"] == "deny"
        for name, agent in agents.items()
        if name != "Orchestrator"
    )
    assert agents["LUNA MAX QA"]["mode"] == "subagent"
    review_permission = agents["LUNA MAX QA"]["permission"]
    assert review_permission["edit"] == "deny" and review_permission["task"] == "deny"
    created_names = {path.name.lower() for path in tmp_path.rglob("*")}
    assert not ({"auth.json", "credentials", "credentials.json", ".env"} & created_names)


def test_review_launcher_retains_unexercised_resource_and_permission_guards():
    launcher = (ROOT / "scripts/ponytail-review.sh").read_text()
    assert "timeout --signal=TERM --kill-after=10s 300s" in launcher
    assert "ulimit -f 2048" in launcher
    assert "ulimit -f 65536" in launcher
    assert "OPENCODE_TEST_HOME OPENCODE_ZED_DB" in launcher
    assert "refusing to replace existing report" in launcher
    override = json.loads(re.search(r"readonly_review_config='([^']+)'", launcher).group(1))
    assert override["agent"]["LUNA MAX QA"]["permission"]["bash"] == {
        "*": "deny",
        "git diff*": "allow",
        "git rev-parse*": "allow",
        "git status*": "allow",
        "wc -l": "allow",
        "wc -l *": "allow",
    }


def test_review_launcher_uses_disposable_state_while_parent_database_is_live(tmp_path):
    parent = tmp_path / "parent"
    parent_data = parent / "data"
    parent_db = parent_data / "opencode/opencode.db"
    parent_db.parent.mkdir(parents=True)
    connection = sqlite3.connect(parent_db)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE parent_state (value TEXT)")
    connection.execute("INSERT INTO parent_state VALUES ('live-parent-session')")
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("INSERT INTO parent_state VALUES ('held-open')")

    parent_config = parent / "config"
    parent_mode = parent_config / "opencode/.ponytail-active"
    parent_mode.parent.mkdir(parents=True)
    parent_mode.write_text("full")
    parent_rg = parent / "cache/opencode/bin/rg"
    parent_rg.parent.mkdir(parents=True)
    parent_rg.write_text("parent-rg")
    parent_rg.chmod(0o700)
    secret = "synthetic-auth-" + hashlib.sha256(os.urandom(32)).hexdigest()
    parent_auth = parent_db.parent / "auth.json"
    parent_auth.write_text(json.dumps({"openai": {"type": "api", "key": secret}}))
    parent_auth.chmod(0o600)
    parent_auth_digest = hashlib.sha256(parent_auth.read_bytes()).hexdigest()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_opencode = fake_bin / "opencode"
    fake_opencode.write_text(
        """#!/usr/bin/env python3
import json
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

root = Path(os.environ["EXPECTED_PROJECT"])
isolated_data = Path(os.environ["XDG_DATA_HOME"])
parent_db = Path(os.environ["EXPECTED_PARENT_DB"])
sandbox = isolated_data.parent
auth = isolated_data / "opencode/auth.json"
assert auth.is_file() and not auth.is_symlink()
assert auth.stat().st_mode & 0o777 == 0o600
assert hashlib.sha256(auth.read_bytes()).hexdigest() == os.environ["EXPECTED_AUTH_DIGEST"]
secret = json.loads(auth.read_text())["openai"]["key"]
assert all(secret not in argument for argument in sys.argv)
assert all(secret not in value for value in os.environ.values())
process = Path("/proc/self")
for _ in range(8):
    cmdline = (process / "cmdline").read_bytes()
    assert secret.encode() not in cmdline
    status = (process / "status").read_text()
    parent_pid = int(next(line for line in status.splitlines() if line.startswith("PPid:" )).split()[1])
    if parent_pid == 0:
        break
    process = Path("/proc") / str(parent_pid)
assert Path(os.environ["HOME"]) == sandbox / "home"
assert Path(os.environ["XDG_CONFIG_HOME"]) == sandbox / "config"
assert Path(os.environ["XDG_CACHE_HOME"]) == sandbox / "cache"
assert Path(os.environ["XDG_STATE_HOME"]) == sandbox / "state"
assert Path(os.environ["XDG_RUNTIME_DIR"]) == sandbox / "runtime"
assert Path(os.environ["TMPDIR"]) == sandbox / "tmp"
assert (sandbox / "cache/opencode/bin/rg").read_text() == "parent-rg"
db = isolated_data / "opencode/opencode.db"
assert db != parent_db
db.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(db) as connection:
    connection.execute("CREATE TABLE IF NOT EXISTS nested_state (value TEXT)")
    connection.execute("INSERT INTO nested_state VALUES ('isolated')")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
(sandbox / "config/opencode").mkdir(parents=True, exist_ok=True)
(sandbox / "config/opencode/.ponytail-active").write_text("review")

if sys.argv[1:] == ["--version"]:
    print("1.18.31")
    raise SystemExit

if os.environ.get("FAKE_OPENCODE_FAIL"):
    print(json.dumps({"type": "tool_use", "part": {"state": {"output": "+API_KEY=" + secret}}}), flush=True)
    print(json.dumps({"type": "error", "error": {"name": "UnknownError", "message": secret}}), flush=True)
    sys.stderr.write("provider rejected secret " + secret + "\\n")
    sys.stderr.write(("+diff source must stay private\\n" * 24000))
    sys.stderr.flush()
    (sandbox / "tmp/provider-cache").write_bytes(b"x" * 256_000)
    raise SystemExit(70 if os.environ["FAKE_OPENCODE_FAIL"] == "exit" else 0)

assert sys.argv[1:] == [
    "run", "--dir", str(root), "--agent", "LUNA MAX QA",
    "--command", "ponytail-review", "--format", "json",
    "Return only canonical plain text: path:Lstart[-end]: tag: claim (tag is delete, stdlib, native, yagni, or shrink), or exactly Lean already. Ship. when there are no findings. Do not use Markdown or backticks anywhere, including around identifiers."
]
assert Path.cwd() == root
assert os.environ["PWD"] == str(root)
review = json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])["agent"]["LUNA MAX QA"]
assert "mode" not in review
assert review["model"] == "openai/gpt-5.6-luna"
assert review["variant"] == "max"
assert "OPENCODE_AUTH_CONTENT" not in os.environ
config = json.loads((root / "opencode.json").read_text())
plugin = config["plugin"][0].replace("{env:PWD}", os.environ["PWD"])
assert Path(plugin.removeprefix("file://")).is_file()
commands = sorted(path.stem for path in (root / "tools/ponytail/.opencode/command").glob("*.md"))
assert commands == [
    "ponytail", "ponytail-audit", "ponytail-debt", "ponytail-gain", "ponytail-help", "ponytail-review"
]
injected = [
    "src/leak.py:L1: shrink: api_key=" + secret,
    "src/leak.py:L2: shrink: https://hooks." + "slack.com/services/" + "T" * 12 + "/" + "B" * 12 + "/" + "x" * 24,
    "src/leak.py:L3: shrink: -----BEGIN " + "PRIVATE KEY-----",
    "src/leak.py:L4: shrink: AKIA" + "A" * 16,
    "src/leak.py:L5: shrink: ghp_" + "g" * 36,
    "src/leak.py:L6: shrink: Bearer " + "b" * 32,
    "src/leak.py:L7: shrink: https://operator:" + "password@example.invalid/private",
    'src/leak.py:L8: shrink: {"client_secret": "' + "s" * 32 + '"}',
    "src/leak.py:L9: shrink: diff --git a/src/leak.py b/src/leak.py",
    "src/leak.py:L10: shrink: @@ -1 +1 @@",
    "src/leak.py:L11: shrink: +print('raw source must stay private')",
    "src/malformed.py:not-a-line: yagni: reject malformed location",
    "- \x60src/prose.py:21-22: yagni: reject Markdown prose\x60",
]
if os.environ.get("FAKE_OPENCODE_MUTATION_ONLY"):
    events = [{"type": "text", "part": {"text": "\\n".join(injected)}}]
elif os.environ.get("FAKE_OPENCODE_CLEAN_ONLY"):
    events = [{"type": "text", "part": {"text": "\x60Lean already. Ship.\x60"}}]
elif os.environ.get("FAKE_OPENCODE_NET_ONLY"):
    events = [{"type": "text", "part": {"text": "\x60net: -2 lines possible.\x60\\n\x60Net removable: ~2 lines.\x60"}}]
else:
    events = [
        {"type": "step_start", "part": {"type": "step-start"}},
        {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed", "output": "+API_KEY=" + secret + "private diff " * 70000}}},
        {"type": "text", "part": {"text": "nested progress: reading diff"}},
        {"type": "text", "part": {"text": "src/example.py:L12-14: shrink: duplicate wrapper. Call helper directly.\\nL15-16: native: use the platform helper.\\nsrc/example.py:15 \u2014 delete: redundant wrapper. Call helper directly.\\n\x60scripts/example.py:16-18\x60 \u2014 shrink: remove the duplicate wrapper; call the helper.\\n\x60safe/path:167-177: yagni: remove the speculative wrapper.\x60\\nsafe/path:178-179: shrink: reuse \x60identifier\x60 directly.\\nLean already. Ship.\\nnet: -2 lines possible.\\nNet removable: ~2 lines.\\n" + "\\n".join(injected)}},
    ]
for event in events:
    print(json.dumps(event), flush=True)
"""
    )
    fake_opencode.chmod(0o700)

    run_key = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    reports = ROOT / "test-results" / f"ponytail-{run_key}"
    reports.mkdir(parents=True)
    report = reports / "review.txt"
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "EXPECTED_PARENT_DB": str(parent_db),
            "EXPECTED_PROJECT": str(ROOT),
            "EXPECTED_AUTH_DIGEST": parent_auth_digest,
            "HOME": str(parent / "home"),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TMPDIR": str(temporary),
            "XDG_CACHE_HOME": str(parent / "cache"),
            "XDG_CONFIG_HOME": str(parent_config),
            "XDG_DATA_HOME": str(parent_data),
            "XDG_STATE_HOME": str(parent / "state"),
        }
    )
    environment.pop("OPENCODE_AUTH_CONTENT", None)

    try:
        try:
            completed = subprocess.run(
                [str(ROOT / "scripts/ponytail-review.sh"), "R-M06-20", str(report)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
        finally:
            connection.rollback()
            connection.close()

        assert "retained sanitized report" in completed.stdout
        assert secret not in completed.stdout
        assert secret not in completed.stderr
        assert report.read_text() == (
            "scope: overengineering only\n"
            "command: /ponytail-review\n"
            "boundary: R-M06-20\n"
            "src/example.py:L12-14: shrink: duplicate wrapper. Call helper directly.\n"
            "L15-16: native: use the platform helper.\n"
            "src/example.py:15: delete: redundant wrapper. Call helper directly.\n"
            "scripts/example.py:16-18: shrink: remove the duplicate wrapper; call the helper.\n"
            "safe/path:167-177: yagni: remove the speculative wrapper.\n"
            "safe/path:178-179: shrink: reuse identifier directly.\n"
            "Lean already. Ship.\n"
            "net: -2 lines possible.\n"
            "Net removable: ~2 lines.\n"
        )
        assert "nested progress" not in report.read_text()
        assert "diff source" not in report.read_text()
        assert "raw source" not in report.read_text()
        assert "src/leak.py" not in report.read_text()
        assert secret not in report.read_text()
        assert not list(temporary.iterdir())
        assert not list(reports.glob(".ponytail-review.*"))
        assert hashlib.sha256(parent_auth.read_bytes()).hexdigest() == parent_auth_digest
        assert parent_auth.stat().st_mode & 0o777 == 0o600
        assert parent_mode.read_text() == "full"
        with sqlite3.connect(parent_db) as parent_check:
            assert parent_check.execute("SELECT value FROM parent_state").fetchall() == [
                ("live-parent-session",)
            ]

        clean_report = reports / "clean-review.txt"
        environment["FAKE_OPENCODE_CLEAN_ONLY"] = "1"
        clean = subprocess.run(
            [str(ROOT / "scripts/ponytail-review.sh"), "R-ASTRA-29", str(clean_report)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        assert "retained sanitized report" in clean.stdout
        assert clean.stderr == ""
        assert clean_report.read_text() == (
            "scope: overengineering only\n"
            "command: /ponytail-review\n"
            "boundary: R-ASTRA-29\n"
            "Lean already. Ship.\n"
        )
        environment.pop("FAKE_OPENCODE_CLEAN_ONLY")

        net_report = reports / "net-review.txt"
        environment["FAKE_OPENCODE_NET_ONLY"] = "1"
        net_failed = subprocess.run(
            [str(ROOT / "scripts/ponytail-review.sh"), "R-ASTRA-28", str(net_report)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert net_failed.returncode == 65
        assert net_failed.stdout == ""
        assert net_failed.stderr == (
            "review returned no allowlisted Ponytail result lines; no report retained\n"
        )
        assert not net_report.exists()
        environment.pop("FAKE_OPENCODE_NET_ONLY")

        mutation_report = reports / "mutation-review.txt"
        environment["FAKE_OPENCODE_MUTATION_ONLY"] = "1"
        mutation_failed = subprocess.run(
            [str(ROOT / "scripts/ponytail-review.sh"), "R-M06-20", str(mutation_report)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert mutation_failed.returncode == 65
        assert mutation_failed.stdout == ""
        assert mutation_failed.stderr == (
            "review returned no allowlisted Ponytail result lines; no report retained\n"
        )
        assert secret not in mutation_failed.stderr
        assert not mutation_report.exists()
        environment.pop("FAKE_OPENCODE_MUTATION_ONLY")

        failed_report = reports / "failed-review.txt"
        environment["FAKE_OPENCODE_FAIL"] = "exit"
        failed = subprocess.run(
            [str(ROOT / "scripts/ponytail-review.sh"), "R-M06-15", str(failed_report)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert failed.returncode == 70
        assert failed.stdout == ""
        assert failed.stderr == (
            "ponytail review provider failed (ref=provider-unknown-error-exit-70); "
            "no report retained\n"
        )
        assert len(failed.stderr) < 128
        assert secret not in failed.stdout
        assert secret not in failed.stderr
        assert "diff source" not in failed.stderr
        assert "provider rejected" not in failed.stderr
        assert not failed_report.exists()
        assert not list(temporary.iterdir())
        assert not list(reports.glob(".ponytail-review.*"))

        event_report = reports / "event-review.txt"
        environment["FAKE_OPENCODE_FAIL"] = "event"
        event_failed = subprocess.run(
            [str(ROOT / "scripts/ponytail-review.sh"), "R-M06-15", str(event_report)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert event_failed.returncode == 69
        assert event_failed.stdout == ""
        assert event_failed.stderr == (
            "ponytail review provider failed (ref=provider-unknown-error-exit-0); "
            "no report retained\n"
        )
        assert secret not in event_failed.stderr
        assert "diff source" not in event_failed.stderr
        assert not event_report.exists()
        assert not list(temporary.iterdir())
        assert not list(reports.glob(".ponytail-review.*"))
        leak_scan = subprocess.run(
            ["git", "grep", "--untracked", "-F", secret, "--", "."],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert leak_scan.returncode == 1
    finally:
        shutil.rmtree(reports)


def test_review_launcher_rejects_invalid_json_without_disclosing_it(tmp_path):
    parent_data = tmp_path / "parent-data"
    auth_dir = parent_data / "opencode"
    auth_dir.mkdir(parents=True)
    secret = "structured-secret-" + hashlib.sha256(os.urandom(32)).hexdigest()
    auth = auth_dir / "auth.json"
    auth.write_text(json.dumps({"openai": {"type": "api", "key": secret}}))
    auth.chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_opencode = fake_bin / "opencode"
    fake_opencode.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then printf '1.18.31\\n'; exit 0; fi\n"
        f"printf '%s\\n' 'not-json-{secret}'\n"
    )
    fake_opencode.chmod(0o700)

    temporary = tmp_path / "temporary"
    temporary.mkdir()
    reports = ROOT / "test-results" / (
        "ponytail-json-" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    )
    reports.mkdir(parents=True)
    report = reports / "review.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TMPDIR": str(temporary),
            "XDG_DATA_HOME": str(parent_data),
        }
    )

    try:
        completed = subprocess.run(
            [str(ROOT / "scripts/ponytail-review.sh"), "R-M06-15", str(report)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 65
        assert completed.stdout == ""
        assert completed.stderr == (
            "review returned invalid structured output; no report retained\n"
        )
        assert secret not in completed.stderr
        assert not report.exists()
        assert not list(temporary.iterdir())
    finally:
        shutil.rmtree(reports)


def test_review_launcher_rejects_missing_unsafe_mode_and_symlink_auth(tmp_path):
    parent_data = tmp_path / "parent-data"
    auth_dir = parent_data / "opencode"
    auth_dir.mkdir(parents=True)
    secret = "unsafe-auth-" + hashlib.sha256(os.urandom(32)).hexdigest()
    target = tmp_path / "auth-target.json"
    target.write_text(json.dumps({"openai": {"type": "api", "key": secret}}))
    target.chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invoked = tmp_path / "opencode-invoked"
    fake_opencode = fake_bin / "opencode"
    fake_opencode.write_text("#!/bin/sh\ntouch \"$FAKE_OPENCODE_INVOKED\"\nexit 99\n")
    fake_opencode.chmod(0o700)

    temporary = tmp_path / "temporary"
    temporary.mkdir()
    reports = ROOT / "test-results" / (
        "ponytail-unsafe-" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    )
    reports.mkdir(parents=True)
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_OPENCODE_INVOKED": str(invoked),
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TMPDIR": str(temporary),
            "XDG_DATA_HOME": str(parent_data),
        }
    )

    auth = auth_dir / "auth.json"
    cases = ("missing", "mode", "symlink")
    try:
        for case in cases:
            auth.unlink(missing_ok=True)
            if case == "mode":
                auth.write_text(target.read_text())
                auth.chmod(0o644)
            elif case == "symlink":
                auth.symlink_to(target)
            report = reports / f"{case}.txt"
            completed = subprocess.run(
                [str(ROOT / "scripts/ponytail-review.sh"), "R-M06-15", str(report)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            assert completed.returncode == 77
            assert secret not in completed.stdout
            assert secret not in completed.stderr
            assert not report.exists()
            assert not invoked.exists()
            assert not list(temporary.iterdir())
    finally:
        shutil.rmtree(reports)
