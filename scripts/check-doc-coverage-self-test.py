#!/usr/bin/env python3
"""Run isolated negative and positive cases against the real doc checker."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

CHECKER = Path(__file__).resolve().with_name("check-doc-coverage.py")
FIXTURE_MAP = {
    "version": 1,
    "rules": [
        {
            "name": "scripts",
            "match": ["scripts/*.py"],
            "docs": ["docs/develop/{stem}.md"],
            "onAdd": ["docs/develop/index.md"],
        },
        {
            "name": "hooks",
            "match": [".githooks/**"],
            "docs": ["docs/develop/git-hooks.md"],
        },
        {
            "name": "commands",
            "match": [".opencode/commands/*.md"],
            "docs": ["docs/develop/commands.md"],
        },
        {
            "name": "opencode-workflow",
            "match": [
                "opencode.json",
                ".opencode/.gitignore",
                ".opencode/agents/*.md",
                ".opencode/skills/**",
                ".opencode/skill-history/**",
                ".opencode/plugins/**",
                ".opencode/package.json",
                ".opencode/package-lock.json",
            ],
            "docs": ["docs/develop/documentation.md"],
        },
    ],
    "additional": [
        {
            "name": "workflow-policy",
            "match": [
                "scripts/alpha.py",
                "opencode.json",
                ".opencode/.gitignore",
                ".opencode/agents/*.md",
                ".opencode/skills/**",
                ".opencode/skill-history/**",
                ".opencode/plugins/**",
                ".opencode/package.json",
                ".opencode/package-lock.json",
                ".opencode/commands/*.md",
            ],
            "docs": ["AGENTS.md"],
        }
    ],
}


def write(root: Path, relative: str, text: str = "fixture\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(root: Path, map_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - current Python and isolated fixture paths are trusted.
        [sys.executable, str(CHECKER), "--root", str(root), "--map", str(map_path), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def expect(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(f"unexpected result: {label}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="stock-probs-doc-coverage-") as temporary:
        root = Path(temporary)
        for relative in (
            "scripts/check-doc-coverage.py",
            "scripts/alpha.py",
            "docs/develop/check-doc-coverage.md",
            "docs/develop/alpha.md",
            "docs/develop/index.md",
            "AGENTS.md",
            ".githooks/pre-push",
            "docs/develop/git-hooks.md",
            ".opencode/commands/qa.md",
            "docs/develop/commands.md",
            "opencode.json",
            ".opencode/.gitignore",
            ".opencode/package.json",
            ".opencode/package-lock.json",
            ".opencode/agents/luna-qa.md",
            ".opencode/skills/demo/SKILL.md",
            ".opencode/skill-history/learnings.md",
            ".opencode/plugins/example/index.ts",
            "docs/develop/documentation.md",
        ):
            write(root, relative)
        map_path = root / "documentation-map.json"
        map_path.write_text(json.dumps(FIXTURE_MAP), encoding="utf-8")

        cases = 0
        result = run(root, map_path)
        expect(result.returncode == 0, f"complete fixture should pass: {result.stderr}")
        cases += 1

        (root / "docs/develop/alpha.md").unlink()
        result = run(root, map_path)
        expect(result.returncode == 1 and "missing documentation" in result.stderr,
               "missing documentation must fail completeness")
        cases += 1
        write(root, "docs/develop/alpha.md")

        result = run(root, map_path, "--changed-file", "scripts/alpha.py")
        expect(result.returncode == 1, "changed source without a doc change must fail")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            "scripts/alpha.py",
            "--changed-file",
            "docs/develop/alpha.md",
        )
        expect(result.returncode == 1 and "workflow-policy" in result.stderr,
               "an additional rule must also be satisfied")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            "scripts/alpha.py",
            "--changed-file",
            "docs/develop/alpha.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(result.returncode == 0, "source, docs, and additional docs should pass")
        cases += 1

        result = run(root, map_path, "--changed-file", "scripts/alpha.py", "--exempt")
        expect(result.returncode == 0 and "exempted" in result.stderr,
               "explicit exemption must skip only change-aware checking")
        cases += 1

        write(root, "scripts/beta.py")
        write(root, "docs/develop/beta.md")
        result = run(
            root,
            map_path,
            "--added-file",
            "scripts/beta.py",
            "--added-file",
            "docs/develop/beta.md",
        )
        expect(result.returncode == 1 and "new entry" in result.stderr,
               "new script must also update its index")
        cases += 1

        result = run(
            root,
            map_path,
            "--added-file",
            "scripts/beta.py",
            "--added-file",
            "docs/develop/beta.md",
            "--changed-file",
            "docs/develop/index.md",
        )
        expect(result.returncode == 0, "new script with documentation and index should pass")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/agents/luna-qa.md",
            "--changed-file",
            "docs/develop/documentation.md",
        )
        expect(result.returncode == 1 and "workflow-policy" in result.stderr,
               "an OpenCode profile change must also update AGENTS.md")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/plugins/example/index.ts",
            "--changed-file",
            "docs/develop/documentation.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(result.returncode == 0, "an OpenCode plugin change with policy docs should pass")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/commands/qa.md",
            "--changed-file",
            "docs/develop/commands.md",
        )
        expect(
            result.returncode == 1 and "workflow-policy" in result.stderr,
            "a project command change must also update AGENTS.md",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/commands/qa.md",
            "--changed-file",
            "docs/develop/commands.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(result.returncode == 0, "a project command change with policy docs should pass")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            "opencode.json",
            "--changed-file",
            "AGENTS.md",
        )
        expect(
            result.returncode == 1 and "docs/develop/documentation.md" in result.stderr,
            "configuration source must also update documentation.md",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            "opencode.json",
            "--changed-file",
            "docs/develop/documentation.md",
        )
        expect(
            result.returncode == 1 and "workflow-policy" in result.stderr,
            "configuration source must also update AGENTS.md",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            "opencode.json",
            "--changed-file",
            "docs/develop/documentation.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(result.returncode == 0, "configuration source with both docs should pass")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/package.json",
            "--changed-file",
            "AGENTS.md",
        )
        expect(
            result.returncode == 1 and "docs/develop/documentation.md" in result.stderr,
            "package manifest must also update documentation.md",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/package.json",
            "--changed-file",
            "docs/develop/documentation.md",
        )
        expect(
            result.returncode == 1 and "workflow-policy" in result.stderr,
            "package manifest must also update AGENTS.md",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/package.json",
            "--changed-file",
            "docs/develop/documentation.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(result.returncode == 0, "package manifest with both docs should pass")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/skills/demo/SKILL.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(
            result.returncode == 1 and "docs/develop/documentation.md" in result.stderr,
            "project skill must also update documentation.md",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/skills/demo/SKILL.md",
            "--changed-file",
            "docs/develop/documentation.md",
        )
        expect(
            result.returncode == 1 and "workflow-policy" in result.stderr,
            "project skill must also update AGENTS.md",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/skills/demo/SKILL.md",
            "--changed-file",
            "docs/develop/documentation.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(result.returncode == 0, "project skill with both docs should pass")
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/skill-history/learnings.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(
            result.returncode == 1 and "docs/develop/documentation.md" in result.stderr,
            "skill history must require the workflow documentation",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/skill-history/learnings.md",
            "--changed-file",
            "docs/develop/documentation.md",
        )
        expect(
            result.returncode == 1 and "workflow-policy" in result.stderr,
            "skill history must require the workflow policy documentation",
        )
        cases += 1

        result = run(
            root,
            map_path,
            "--changed-file",
            ".opencode/skill-history/learnings.md",
            "--changed-file",
            "docs/develop/documentation.md",
            "--changed-file",
            "AGENTS.md",
        )
        expect(result.returncode == 0, "skill history with both docs should pass")
        cases += 1

        (root / "docs/develop/commands.md").unlink()
        result = run(root, map_path)
        expect(result.returncode == 1 and "commands.md" in result.stderr,
               "new command without documentation must fail completeness")
        cases += 1

        write(root, "docs/develop/commands.md")
        result = run(root, map_path, "--json")
        expect(result.returncode == 0 and json.loads(result.stdout)["ok"] is True,
               "JSON success output should be machine-readable")
        cases += 1

    print(f"OK: documentation coverage self-test passed ({cases} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
