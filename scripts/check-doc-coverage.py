#!/usr/bin/env python3
"""Check that mapped repository changes have the required documentation.

The check is deliberately read-only.  Without a base it verifies completeness:
every tracked mapped path has all of its documentation files.  With a base (or
explicit changed paths) it also verifies that a mapped documentation path is in
the same change set.  A map's ``rules`` use first-match semantics; ``additional``
rules, when present, all apply to matching paths.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXEMPT_PATTERN = re.compile(r"(?im)^[ \t]*doc-gate[ \t]*:[ \t]*exempt\b")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}


class ConfigError(Exception):
    """Raised when the map or requested Git comparison is unusable."""


def compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile a small repository-path glob (``*``, ``**``, and ``?``)."""
    pieces = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    index += 1
                    pieces.append("(?:.*/)?")
                else:
                    pieces.append(".*")
                continue
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        index += 1
    pieces.append("$")
    return re.compile("".join(pieces))


def normalize(path: str) -> str:
    """Normalize a Git or CLI path to a repository-relative slash path."""
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def compile_rules(entries: object, map_path: Path, *, allow_on_add: bool) -> list[dict]:
    if not isinstance(entries, list):
        raise ConfigError(f"{map_path} rule section must be a list")
    rules: list[dict] = []
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError(f"invalid rule in {map_path}: {entry!r}")
        name = entry.get("name")
        matches = entry.get("match")
        docs = entry.get("docs")
        on_add = entry.get("onAdd", [])
        if not isinstance(name, str) or not name:
            raise ConfigError(f"rule without a name in {map_path}")
        if name in names:
            raise ConfigError(f"duplicate rule name in {map_path}: {name}")
        if not isinstance(matches, list) or not matches or not all(
            isinstance(item, str) and item for item in matches
        ):
            raise ConfigError(f"rule {name} must list non-empty match patterns")
        if not isinstance(docs, list) or not docs or not all(
            isinstance(item, str) and item for item in docs
        ):
            raise ConfigError(f"rule {name} must list non-empty documentation paths")
        if not isinstance(on_add, list) or not all(isinstance(item, str) for item in on_add):
            raise ConfigError(f"rule {name} onAdd must be a list of paths")
        if on_add and not allow_on_add:
            raise ConfigError(f"rule {name} may not use onAdd in additional")
        names.add(name)
        rules.append(
            {
                "name": name,
                "match": [compile_glob(item) for item in matches],
                "docs": docs,
                "onAdd": on_add,
            }
        )
    return rules


def load_map(path: Path) -> tuple[list[dict], list[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"documentation map not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ConfigError(f"{path} must be an object with version 1")
    rules = compile_rules(data.get("rules"), path, allow_on_add=True)
    if not rules:
        raise ConfigError(f"{path} must define a non-empty rules list")
    additional = compile_rules(data.get("additional", []), path, allow_on_add=False)
    return rules, additional


def matches(rule: dict, path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in rule["match"])


def first_match(rules: list[dict], path: str) -> dict | None:
    return next((rule for rule in rules if matches(rule, path)), None)


def resolve_doc(spec: str, source: str) -> str:
    result = spec.replace("{stem}", Path(source).stem)
    if "{" in result or "}" in result:
        raise ConfigError(f"unresolved placeholder in documentation spec: {spec}")
    if os.path.isabs(result) or normalize(result).startswith("../"):
        raise ConfigError(f"documentation path must stay in the repository: {spec}")
    return normalize(result)


def rule_docs(rule: dict, source: str) -> list[str]:
    return [resolve_doc(spec, source) for spec in rule["docs"]]


def find_executable(name: str) -> str | None:
    """Resolve a trusted tool name to an absolute executable path."""
    executable = shutil.which(name)
    return str(Path(executable).resolve()) if executable else None


def git_executable() -> str:
    executable = find_executable("git")
    if executable is None:
        raise ConfigError("git executable not found")
    return executable


def list_files(root: Path) -> list[str]:
    """List tracked files, with a filesystem fallback for isolated self-tests."""
    git = find_executable("git")
    result = None
    if git is not None:
        try:
            result = subprocess.run(  # noqa: S603 - git is resolved; argv is fixed.
                [git, "-C", str(root), "ls-files", "-z"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            result = None
    if result is not None and result.returncode == 0:
        return [normalize(item) for item in result.stdout.split("\0") if item]

    files: list[str] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for filename in filenames:
            files.append(normalize(os.path.relpath(Path(directory) / filename, root)))
    return files


def git_changed(root: Path, base: str, head: str) -> dict[str, str]:
    result = subprocess.run(  # noqa: S603 - resolved git and validated ref arguments.
        [
            git_executable(),
            "-C",
            str(root),
            "diff",
            "--name-status",
            "-z",
            "-M",
            f"{base}...{head}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ConfigError(f"git diff {base}...{head} failed: {result.stderr.strip()}")

    tokens = result.stdout.split("\0")
    changed: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        status = tokens[index]
        if not status:
            index += 1
            continue
        code = status[0]
        if code in {"R", "C"}:
            if index + 2 >= len(tokens):
                raise ConfigError("malformed rename/copy result from git diff")
            old, new = normalize(tokens[index + 1]), normalize(tokens[index + 2])
            changed[old if code == "R" else new] = "D" if code == "R" else "A"
            if code == "R":
                changed[new] = "R"
            index += 3
        else:
            if index + 1 >= len(tokens):
                raise ConfigError("malformed result from git diff")
            changed[normalize(tokens[index + 1])] = code
            index += 2
    return changed


def git_exempt(root: Path, base: str, head: str) -> bool:
    result = subprocess.run(  # noqa: S603 - resolved git and validated ref arguments.
        [git_executable(), "-C", str(root), "log", "--format=%B", f"{base}..{head}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(EXEMPT_PATTERN.search(result.stdout))


def check_completeness(
    root: Path, rules: list[dict], additional: list[dict], files: list[str]
) -> tuple[list[tuple[str, str]], int]:
    violations: list[tuple[str, str]] = []
    checked = 0
    for path in files:
        rule = first_match(rules, path)
        if rule is not None:
            checked += 1
            for doc in rule_docs(rule, path):
                if not (root / doc).is_file():
                    violations.append((path, f"missing documentation {doc}"))
        for extra in additional:
            if matches(extra, path):
                for doc in rule_docs(extra, path):
                    if not (root / doc).is_file():
                        violations.append((path, f"missing documentation {doc} ({extra['name']})"))
    return violations, checked


def check_changes(
    rules: list[dict], additional: list[dict], changed: dict[str, str]
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    changed_paths = set(changed)
    added_by_rule: dict[str, list[str]] = {}
    for path in sorted(changed):
        rule = first_match(rules, path)
        if rule is not None:
            docs = rule_docs(rule, path)
            if not any(doc in changed_paths for doc in docs):
                violations.append((path, "requires an update to one of: " + ", ".join(docs)))
            if changed[path] == "A":
                added_by_rule.setdefault(rule["name"], []).append(path)
        for extra in additional:
            if matches(extra, path):
                docs = rule_docs(extra, path)
                if not any(doc in changed_paths for doc in docs):
                    violations.append(
                        (
                            path,
                            "requires an update to one of: "
                            + ", ".join(docs)
                            + f" ({extra['name']})",
                        )
                    )
    for rule_name, paths in added_by_rule.items():
        rule = next(rule for rule in rules if rule["name"] == rule_name)
        if rule["onAdd"] and not any(
            resolve_doc(spec, path) in changed_paths
            for path in paths
            for spec in rule["onAdd"]
        ):
            violations.append(
                (
                    f"new entry under rule '{rule_name}'",
                    "requires an update to one of: " + ", ".join(rule["onAdd"]),
                )
            )
    return violations


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enforce mapped documentation completeness and change coverage."
    )
    parser.add_argument("--root", help="repository root (default: Git toplevel of cwd)")
    parser.add_argument("--map", help="documentation map (default: <root>/documentation-map.json)")
    parser.add_argument("--base", help="Git base ref for change-aware checking")
    parser.add_argument("--head", default="HEAD", help="Git head ref (default: HEAD)")
    parser.add_argument(
        "--changed-file", action="append", default=[], help="treat path as modified"
    )
    parser.add_argument("--added-file", action="append", default=[], help="treat path as added")
    parser.add_argument("--exempt", action="store_true", help="skip only change-aware checking")
    parser.add_argument("--json", action="store_true", help="emit a JSON summary")
    parser.add_argument("--quiet", action="store_true", help="suppress the OK line")
    return parser.parse_args(argv)


def repository_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidate = Path.cwd().resolve()
    git = find_executable("git")
    result = None
    if git is not None:
        try:
            result = subprocess.run(  # noqa: S603 - resolved git and fixed argv.
                [git, "-C", str(candidate), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return candidate


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = repository_root(args.root)
    map_path = (
        Path(args.map).expanduser().resolve()
        if args.map
        else root / "documentation-map.json"
    )
    try:
        rules, additional = load_map(map_path)
        changed: dict[str, str] = {}
        for path in args.changed_file:
            changed[normalize(path)] = "M"
        for path in args.added_file:
            changed[normalize(path)] = "A"
        if not changed and args.base:
            changed = git_changed(root, args.base, args.head)
        exempt = args.exempt or os.environ.get("DOC_GATE_EXEMPT", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not exempt and args.base and changed:
            exempt = git_exempt(root, args.base, args.head)
        completeness, checked = check_completeness(root, rules, additional, list_files(root))
        changes = [] if exempt or not changed else check_changes(rules, additional, changed)
    except (ConfigError, OSError) as exc:
        print(f"check-doc-coverage: {exc}", file=sys.stderr)
        return 2

    violations = completeness + changes
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not violations,
                    "checked": checked,
                    "changed": len(changed),
                    "exempt": bool(exempt and changed),
                    "violations": [
                        {"path": path, "message": message} for path, message in violations
                    ],
                },
                indent=2,
            )
        )
    else:
        for path, message in violations:
            print(f"MISSING/STALE: {path}: {message}", file=sys.stderr)
        if exempt and changed:
            print(
                "NOTICE: change-aware documentation check exempted (Doc-Gate: exempt).",
                file=sys.stderr,
            )
        if not violations and not args.quiet:
            suffix = f", {len(changed)} changed" if changed else ""
            print(f"OK: documentation coverage valid ({checked} mapped files checked{suffix})")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
