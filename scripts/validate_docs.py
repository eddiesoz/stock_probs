#!/usr/bin/env python3
"""Fail closed when the authored documentation or project skill drifts."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "documentation"
SKILL_MAX_LINES = 500
SKILL_TAGS = ["documentation", "markdown", "taxonomy", "audit", "stock-probability"]
SKILL_REFERENCES = ("audit.md", "authoring.md", "repository-sources.md")
CATEGORIES: dict[str, tuple[str, ...]] = {
    "concepts": ("architecture.md", "forecast-model.md"),
    "configure": ("local-configuration.md",),
    "develop": ("testing.md", "documentation.md"),
    "evidence": ("ponytail-reviews.md",),
    "operations": ("getting-started.md", "backup-restore.md"),
    "reference": ("api.md",),
    "security": ("threat-model.md",),
    "usage": ("dashboard.md",),
}
FRONTMATTER_VALUE = re.compile(r'^([a-zA-Z][a-zA-Z0-9_-]*):\s*"([^"\n]+)"\s*$')
TOPIC_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECRET_PATTERNS = {
    "private key block": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "Bearer credential": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.IGNORECASE),
    "credential URL": re.compile(r"https?://[^\s/:]+:[^\s/@]+@", re.IGNORECASE),
}
STALE_DOC_PATTERNS = {
    "pending authored-documentation taxonomy": re.compile(
        r"authored-documentation taxonomy(?: implementation)? remains(?: \*\*)?pending",
        re.IGNORECASE,
    ),
    "absent documentation skill": re.compile(
        r"no (?:project )?documentation skill (?:has been |was |is )?(?:created|present|available)",
        re.IGNORECASE,
    ),
    "absent authored documentation": re.compile(
        r"no (?:new )?(?:authored )?documentation "
        r"(?:has been |was |is )?(?:created|present|available)",
        re.IGNORECASE,
    ),
}


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str, list[str]]:
    """Parse the intentionally minimal quoted scalar frontmatter used by authored docs."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, text, [f"{path}: missing opening frontmatter delimiter"]
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return {}, text, [f"{path}: missing closing frontmatter delimiter"]
    values: dict[str, str] = {}
    issues: list[str] = []
    for line_number, line in enumerate(lines[1:closing], start=2):
        match = FRONTMATTER_VALUE.fullmatch(line)
        if not match:
            issues.append(f"{path}:{line_number}: frontmatter must be a quoted scalar")
            continue
        key, value = match.groups()
        if key in values:
            issues.append(f"{path}:{line_number}: duplicate frontmatter key {key}")
        values[key] = value.strip()
    return values, "\n".join(lines[closing + 1 :]), issues


def _link_target(raw_target: str) -> str:
    """Remove an optional Markdown title without accepting whitespace in ordinary paths."""

    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def _markdown_anchors(text: str) -> set[str]:
    """Return GitHub-style heading anchors, including duplicate-heading suffixes."""

    anchors: set[str] = set()
    occurrences: dict[str, int] = defaultdict(int)
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", stripped)
        if not match:
            continue
        heading = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", match.group(1))
        heading = re.sub(r"<[^>]+>|[`*_~]", "", heading).lower()
        base = re.sub(r"[^\w\- ]", "", heading)
        base = re.sub(r"\s+", "-", base.strip())
        suffix = occurrences[base]
        occurrences[base] += 1
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
    anchors.update(re.findall(r"<a\s+(?:[^>]*?\s)?(?:id|name)=[\"']([^\"']+)[\"']", text, re.I))
    return anchors


def _validate_links(path: Path, text: str, root: Path) -> list[str]:
    issues: list[str] = []
    for match in MARKDOWN_LINK.finditer(text):
        target = _link_target(match.group(1))
        if not target:
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            continue
        if target.startswith("/"):
            issues.append(f"{path}: local Markdown link must be relative: {target}")
            continue
        location, _, raw_fragment = target.partition("#")
        local_part = unquote(location.split("?", 1)[0])
        resolved = (path.parent / local_part).resolve() if local_part else path.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            issues.append(f"{path}: link leaves repository: {target}")
            continue
        if not resolved.exists():
            issues.append(f"{path}: unresolved Markdown link: {target}")
            continue
        if raw_fragment and resolved.suffix.lower() == ".md":
            fragment = unquote(raw_fragment).lower()
            anchors = _markdown_anchors(resolved.read_text(encoding="utf-8"))
            if fragment not in anchors:
                issues.append(f"{path}: unresolved Markdown anchor: {target}")
    return issues


def _validate_taxonomy(root: Path) -> tuple[list[str], dict[Path, str]]:
    docs_root = root / "docs"
    expected = {docs_root / "index.md"}
    for category, topics in CATEGORIES.items():
        expected.add(docs_root / category / "index.md")
        expected.update(docs_root / category / topic for topic in topics)
    actual = set(docs_root.rglob("*.md")) if docs_root.exists() else set()
    issues = [f"missing documentation page: {path}" for path in sorted(expected - actual)]
    issues.extend(f"unexpected documentation page: {path}" for path in sorted(actual - expected))
    documents: dict[Path, str] = {}
    for path in sorted(actual):
        relative = path.relative_to(docs_root)
        if any(part != part.lower() for part in relative.parts):
            issues.append(f"{path}: documentation paths must be lowercase")
        if path.name != "index.md" and not TOPIC_NAME.fullmatch(path.name):
            issues.append(f"{path}: topic filename must be lowercase and hyphenated")
        text = path.read_text(encoding="utf-8")
        frontmatter, body, frontmatter_issues = parse_frontmatter(path)
        issues.extend(frontmatter_issues)
        if set(frontmatter) != {"title", "description"}:
            issues.append(f"{path}: frontmatter must contain only title and description")
        for key in ("title", "description"):
            if not frontmatter.get(key):
                issues.append(f"{path}: missing non-empty {key} frontmatter")
        documents[path] = body
        issues.extend(_validate_links(path, text, root))
        for label, pattern in STALE_DOC_PATTERNS.items():
            if pattern.search(text):
                issues.append(f"{path}: stale root-state wording: {label}")

    root_index = documents.get(docs_root / "index.md", "")
    for category in CATEGORIES:
        target = f"{category}/index.md"
        if len(re.findall(rf"\]\({re.escape(target)}\)", root_index)) != 1:
            issues.append(f"{docs_root / 'index.md'}: must link {target} exactly once")
    for category, topics in CATEGORIES.items():
        index = documents.get(docs_root / category / "index.md", "")
        for topic in topics:
            if len(re.findall(rf"\]\({re.escape(topic)}\)", index)) != 1:
                issues.append(
                    f"{docs_root / category / 'index.md'}: must link {topic} exactly once"
                )
    return issues, documents


def _validate_skill(root: Path) -> tuple[list[str], list[Path]]:
    skill_root = root / ".opencode" / "skills" / SKILL_NAME
    skill_path = skill_root / "SKILL.md"
    metadata_path = skill_root / "metadata.json"
    index_path = root / ".opencode" / "SKILL-INDEX.md"
    learnings_path = root / ".opencode" / "skills" / "learnings.md"
    required = [skill_path, metadata_path, index_path, learnings_path]
    issues = [f"missing skill artifact: {path}" for path in required if not path.is_file()]
    if issues:
        return issues, [path for path in required if path.is_file()]

    discovered = sorted((root / ".opencode" / "skills").glob("*/SKILL.md"))
    if discovered != [skill_path]:
        issues.append(
            "project skill discovery must contain only "
            ".opencode/skills/documentation/SKILL.md"
        )
    for discovered_skill in discovered:
        line_count = len(discovered_skill.read_text(encoding="utf-8").splitlines())
        if line_count > SKILL_MAX_LINES:
            issues.append(
                f"{discovered_skill}: active project SKILL.md must not exceed "
                f"{SKILL_MAX_LINES} lines (found {line_count})"
            )

    frontmatter, _, frontmatter_issues = parse_frontmatter(skill_path)
    issues.extend(frontmatter_issues)
    if set(frontmatter) != {"name", "description"}:
        issues.append(f"{skill_path}: frontmatter must contain only name and description")
    if frontmatter.get("name") != skill_root.name or not SKILL_NAME_PATTERN.fullmatch(
        frontmatter.get("name", "")
    ):
        issues.append(f"{skill_path}: skill name must match its lowercase-hyphenated directory")
    description = frontmatter.get("description", "")

    try:
        loaded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(f"{metadata_path}: invalid JSON: {exc}")
        loaded_metadata = {}
    if not isinstance(loaded_metadata, dict):
        issues.append(f"{metadata_path}: metadata must be a JSON object")
        metadata: dict[str, object] = {}
    else:
        metadata = loaded_metadata
    expected_metadata_keys = {"_comment", "name", "description", "tags", "alwaysApply"}
    if set(metadata) != expected_metadata_keys:
        issues.append(f"{metadata_path}: metadata fields must match the supported project catalog")
    if metadata.get("name") != SKILL_NAME:
        issues.append(f"{metadata_path}: metadata name must match {SKILL_NAME}")
    if metadata.get("description") != description:
        issues.append(f"{metadata_path}: metadata description must match SKILL.md frontmatter")
    if metadata.get("tags") != SKILL_TAGS:
        issues.append(f"{metadata_path}: metadata tags must match the canonical ordered tags")
    if metadata.get("alwaysApply") is not False:
        issues.append(f"{metadata_path}: documentation must remain opt-in with alwaysApply false")
    comment = metadata.get("_comment")
    if not isinstance(comment, str) or "SKILL.md frontmatter" not in comment:
        issues.append(f"{metadata_path}: _comment must explain the stock loader boundary")

    index = index_path.read_text(encoding="utf-8")
    if "**1 skill**" not in index:
        issues.append(f"{index_path}: skill count must be exactly one")
    expected_link = "skills/documentation/SKILL.md"
    if len(re.findall(rf"\]\({re.escape(expected_link)}\)", index)) != 2:
        issues.append(f"{index_path}: expected table and directory links for {SKILL_NAME}")
    expected_row = (
        f"| `{SKILL_NAME}` | [`{expected_link}`]({expected_link}) | {description} |"
    )
    if index.count(expected_row) != 1:
        issues.append(
            f"{index_path}: skill row must match SKILL.md frontmatter name and description"
        )
    expected_listing = f"1. [`{SKILL_NAME}`]({expected_link})"
    if index.count(expected_listing) != 1:
        issues.append(f"{index_path}: directory listing must match the canonical name and path")

    references_root = skill_root / "references"
    expected_references = {references_root / name for name in SKILL_REFERENCES}
    actual_references = set(references_root.rglob("*.md")) if references_root.exists() else set()
    issues.extend(
        f"missing skill reference: {path}"
        for path in sorted(expected_references - actual_references)
    )
    issues.extend(
        f"unexpected skill reference: {path}"
        for path in sorted(actual_references - expected_references)
    )
    skill_text = skill_path.read_text(encoding="utf-8")
    linked_targets = [_link_target(match.group(1)) for match in MARKDOWN_LINK.finditer(skill_text)]
    for name in SKILL_REFERENCES:
        target = f"references/{name}"
        if target not in linked_targets:
            issues.append(f"{skill_path}: missing reference link: {target}")

    skill_files = [skill_path, index_path, learnings_path]
    skill_files.extend(sorted(actual_references))
    for path in skill_files:
        issues.extend(_validate_links(path, path.read_text(encoding="utf-8"), root))
    return issues, [*skill_files, metadata_path]


def _validate_secrets(paths: list[Path]) -> list[str]:
    issues: list[str] = []
    for path in sorted(set(paths)):
        text = path.read_text(encoding="utf-8")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                issues.append(f"{path}: possible {label}")
    return issues


def validate_repository(root: Path = ROOT) -> list[str]:
    """Return stable sorted validation issues; an empty list is a pass."""

    taxonomy_issues, documents = _validate_taxonomy(root)
    skill_issues, skill_files = _validate_skill(root)
    secret_paths = [*documents, *skill_files]
    return sorted({*taxonomy_issues, *skill_issues, *_validate_secrets(secret_paths)})


def main() -> int:
    issues = validate_repository()
    if issues:
        print("Documentation validation failed:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    topic_count = sum(len(topics) for topics in CATEGORIES.values())
    print(
        f"Documentation validation passed: {len(CATEGORIES)} categories, "
        f"{topic_count} topics, 1 project skill."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
