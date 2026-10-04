import json
import re
import shutil
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from scripts.validate_docs import (
    APPROVED_SKILL_CATALOG,
    CATEGORIES,
    parse_frontmatter,
    validate_repository,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def documentation_repository(tmp_path: Path) -> Path:
    """Copy only the documentation contract and make its root link targets resolvable."""

    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    skill_parent = tmp_path / ".opencode" / "skills"
    skill_parent.mkdir(parents=True)
    for name in APPROVED_SKILL_CATALOG:
        shutil.copytree(ROOT / ".opencode" / "skills" / name, skill_parent / name)
    history_parent = tmp_path / ".opencode" / "skill-history"
    history_parent.mkdir(parents=True)
    shutil.copy2(
        ROOT / ".opencode" / "skill-history" / "learnings.md",
        history_parent / "learnings.md",
    )
    shutil.copy2(ROOT / ".opencode" / "SKILL-INDEX.md", tmp_path / ".opencode" / "SKILL-INDEX.md")
    shutil.copy2(ROOT / "model-routing.json", tmp_path / "model-routing.json")
    for name in ("README.md", "AGENTS.md", "MVP-PLAN.md", "MVP-ROADMAP.md", "SESSION-EXPORT.md"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    assert validate_repository(tmp_path) == []
    return tmp_path


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def test_repository_documentation_contract_passes() -> None:
    assert validate_repository(ROOT) == []


def test_skill_history_is_governance_archive_not_a_flat_skill() -> None:
    history = ROOT / ".opencode/skill-history/learnings.md"
    assert history.is_file()
    assert not list((ROOT / ".opencode/skills").glob("*.md"))


def test_missing_skill_history_governance_artifact_fails(documentation_repository: Path) -> None:
    history = documentation_repository / ".opencode/skill-history/learnings.md"
    history.unlink()

    assert any(
        "missing project skill governance artifact" in issue
        for issue in validate_repository(documentation_repository)
    )


def test_root_level_skill_markdown_mutation_fails(documentation_repository: Path) -> None:
    accidental = documentation_repository / ".opencode/skills/accidental-flat.md"
    accidental.write_text("# Accidental flat skill\n", encoding="utf-8")

    issues = validate_repository(documentation_repository)

    assert any("native V2 flat skill" in issue for issue in issues)


def test_documentation_taxonomy_has_expected_size() -> None:
    assert len(CATEGORIES) == 9
    assert sum(map(len, CATEGORIES.values())) == 13


def test_project_skill_governance_catalog_has_expected_entries() -> None:
    assert len(APPROVED_SKILL_CATALOG) == 8
    assert tuple(APPROVED_SKILL_CATALOG) == (
        "documentation",
        "development-conventions",
        "stock-probability-skill-maintenance",
        "local-gate-evidence",
        "browser-qa",
        "beta-testing-email-workflow",
        "database-conventions",
        "security-audit",
    )
    assert all("ponytail" not in name.casefold() for name in APPROVED_SKILL_CATALOG)
    assert all(
        "ponytail"
        not in " ".join(
            (definition.description, *definition.tags, *definition.references)
        ).casefold()
        for definition in APPROVED_SKILL_CATALOG.values()
    )
    for name in APPROVED_SKILL_CATALOG:
        link = ROOT / ".agents/skills" / name
        assert link.is_symlink()
        assert link.readlink() == Path(f"../../.opencode/skills/{name}")
        for path in (ROOT / ".opencode/skills" / name).rglob("*"):
            if path.is_file() and path.suffix.lower() in {".md", ".json"}:
                assert "ponytail" not in path.read_text(encoding="utf-8").casefold(), path


def test_agent_profile_skill_grants_are_narrow() -> None:
    expected = {
        "luna-build.md": (
            ("*", "deny"),
            ("browser-qa", "allow"),
            ("database-conventions", "allow"),
            ("development-conventions", "allow"),
            ("local-gate-evidence", "allow"),
            ("security-audit", "allow"),
            ("stock-probability-skill-maintenance", "allow"),
        ),
        "luna-qa.md": (
            ("*", "deny"),
            ("browser-qa", "allow"),
            ("development-conventions", "allow"),
            ("local-gate-evidence", "allow"),
            ("security-audit", "allow"),
        ),
        "luna-docs.md": (
            ("*", "deny"),
            ("development-conventions", "allow"),
            ("documentation", "allow"),
        ),
    }
    legacy = ROOT / ".opencode/agent"
    agents = ROOT / ".opencode/agents"
    profiles = {path.name: path.read_text(encoding="utf-8") for path in agents.glob("*.md")}
    routing = json.loads((ROOT / "model-routing.json").read_text(encoding="utf-8"))

    assert not any(legacy.glob("*.md"))
    assert set(profiles) == set(expected)
    for name, grants in expected.items():
        text = profiles[name]
        assert "mode: subagent" in text
        role_name = routing["opencode"]["agents"][name.removesuffix(".md")]
        role = routing["roles"][role_name]
        assert f"model: openai/{role['model']}#{role['reasoning_effort']}" in text
        assert not re.search(r"^(?:name|variant|permission|bash|task):", text, re.MULTILINE)
        matches = re.findall(
            r"^  - action: skill\n    resource: (.+)\n    effect: (.+)$",
            text,
            re.MULTILINE,
        )
        parsed = tuple((resource.strip('"'), effect) for resource, effect in matches)
        assert parsed == grants
        assert all("ponytail" not in resource.casefold() for resource, _ in parsed)

    docs = profiles["luna-docs.md"]
    assert (
        '  - action: shell\n    resource: ".dev-venv/bin/python scripts/validate_docs.py"\n'
        "    effect: allow"
    ) in docs


def test_native_agent_profiles_fail_closed_on_sensitive_reads() -> None:
    resources = (
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
    paths = (
        ".env",
        ".env.example",
        "nested/.env.production",
        "config/credentials.json",
        "secrets/api-token.txt",
        "certs/private-key.pem",
        "certs/server.key",
    )
    for path in (ROOT / ".opencode/agents").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        read_rules = [
            (resource.strip('"'), effect)
            for resource, effect in re.findall(
                r"^  - action: read\n    resource: (.+)\n    effect: (.+)$",
                text,
                re.MULTILINE,
            )
        ]
        broad_allow = max(
            index
            for index, rule in enumerate(read_rules)
            if rule == ("*", "allow")
        )
        assert all((resource, "deny") in read_rules for resource in resources)
        for sensitive_path in paths:
            matches = [
                (index, effect)
                for index, (resource, effect) in enumerate(read_rules)
                if fnmatchcase(sensitive_path, resource)
            ]
            assert matches, (path, sensitive_path)
            assert matches[-1][1] == "deny", (path, sensitive_path)
            assert matches[-1][0] > broad_allow, (path, sensitive_path)


def test_astra_matrix_has_214_unique_inventory_rows_and_dimension_keys() -> None:
    text = (ROOT / "docs/evidence/astra-final-matrix.md").read_text(encoding="utf-8")
    report = (ROOT / "docs/evidence/astra-final-report.md").read_text(encoding="utf-8")
    row_ids = re.findall(r"^\| `([ACSHTNVMWP]\d{3})` \|", text, re.MULTILINE)
    expected = {
        f"{prefix}{number:03d}"
        for prefix, count in {
            "A": 35,
            "C": 37,
            "S": 21,
            "H": 8,
            "T": 12,
            "N": 10,
            "V": 52,
            "M": 6,
            "W": 20,
            "P": 13,
        }.items()
        for number in range(1, count + 1)
    }

    assert len(row_ids) == len(set(row_ids)) == 214
    assert set(row_ids) == expected
    for label in (
        "Show up to 10 headlines",
        "Review detailed provenance",
        "View failed request",
    ):
        assert label in text
    for suffix in ("AE", "MO", "RE", "AX", "PE"):
        assert f"`<ID>-{suffix}`" in text
        assert f"(`-{suffix}`)" in report
    for prefix in "ACSHTNVMWP":
        assert f"| `{prefix}` |" in report


@pytest.mark.parametrize("topic", ["astra-final-matrix.md", "astra-final-report.md"])
def test_astra_evidence_index_link_mutation_fails(
    documentation_repository: Path, topic: str
) -> None:
    index = documentation_repository / "docs/evidence/index.md"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            f"({topic})", "(ponytail-reviews.md)"
        ),
        encoding="utf-8",
    )

    issues = validate_repository(documentation_repository)

    assert any(f"must link {topic} exactly once" in issue for issue in issues)


def test_unexpected_skill_governance_directory_mutation_fails(
    documentation_repository: Path,
) -> None:
    unexpected = documentation_repository / ".opencode/skills/unapproved"
    unexpected.mkdir()
    (unexpected / "SKILL.md").write_text(
        '---\nname: "unapproved"\ndescription: "Unapproved test skill."\n---\n',
        encoding="utf-8",
    )

    assert any(
        "unexpected project skill governance directory: unapproved" in issue
        for issue in validate_repository(documentation_repository)
    )


def test_project_governance_index_count_mutation_fails(documentation_repository: Path) -> None:
    index = documentation_repository / ".opencode/SKILL-INDEX.md"
    index.write_text(
        index.read_text(encoding="utf-8").replace("**8 skills**", "**0 skills**"),
        encoding="utf-8",
    )

    assert any(
        "project governance skill count must be exactly 8" in issue
        for issue in validate_repository(documentation_repository)
    )


@pytest.mark.parametrize("name", APPROVED_SKILL_CATALOG)
def test_missing_approved_project_skill_governance_mutation_fails(
    documentation_repository: Path, name: str
) -> None:
    shutil.rmtree(documentation_repository / f".opencode/skills/{name}")

    assert any(
        f"missing approved project skill governance directory: {name}" in issue
        for issue in validate_repository(documentation_repository)
    )


def test_unexpected_markdown_page_mutation_fails(documentation_repository: Path) -> None:
    unexpected = documentation_repository / "docs/evidence/unexpected.md"
    unexpected.write_text(
        '---\ntitle: "Unexpected"\ndescription: "Unexpected taxonomy page."\n---\n',
        encoding="utf-8",
    )

    issues = validate_repository(documentation_repository)

    assert any(f"unexpected documentation page: {unexpected}" in issue for issue in issues)


def test_frontmatter_parser_rejects_unquoted_values(tmp_path: Path) -> None:
    document = tmp_path / "example.md"
    document.write_text("---\ntitle: Unquoted\ndescription: \"Useful\"\n---\n\n# Example\n")

    _, _, issues = parse_frontmatter(document)

    assert any("frontmatter must be a quoted scalar" in issue for issue in issues)


@pytest.mark.parametrize(
    ("relative_path", "expected_issue"),
    [
        (
            ".opencode/skills/documentation/SKILL.md",
            "project governance metadata description must match SKILL.md frontmatter",
        ),
        (
            ".opencode/skills/documentation/metadata.json",
            "project governance metadata description must match SKILL.md frontmatter",
        ),
        (
            ".opencode/SKILL-INDEX.md",
            "project governance row must match SKILL.md frontmatter name and description",
        ),
    ],
)
def test_project_skill_governance_description_parity_mutations_fail(
    documentation_repository: Path, relative_path: str, expected_issue: str
) -> None:
    path = documentation_repository / relative_path
    skill_path = documentation_repository / ".opencode/skills/documentation/SKILL.md"
    description = parse_frontmatter(skill_path)[0]["description"]
    if path.suffix == ".json":
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["description"] += " Stale."
        path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(description, f"{description} Stale."),
            encoding="utf-8",
        )

    issues = validate_repository(documentation_repository)

    assert any(expected_issue in issue for issue in issues)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alwaysApply", True),
        ("tags", ["audit", "documentation"]),
        ("_comment", "An unexplained catalog entry."),
    ],
)
def test_project_skill_governance_metadata_policy_mutations_fail(
    documentation_repository: Path, field: str, value: object
) -> None:
    path = documentation_repository / ".opencode/skills/documentation/metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata[field] = value
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    assert any("metadata.json" in issue for issue in validate_repository(documentation_repository))


def test_stale_root_link_wording_in_authored_docs_fails(
    documentation_repository: Path,
) -> None:
    _append(
        documentation_repository / "docs/index.md",
        "\n[No documentation skill is available](../README.md).\n",
    )

    issues = validate_repository(documentation_repository)

    assert any("stale root-state wording" in issue for issue in issues)


@pytest.mark.parametrize(
    "credential",
    [
        "AKIA" + "A" * 16,
        "ghp_" + "a" * 36,
        "Bearer " + "a" * 24,
        "https://operator:password@example.invalid/resource",
    ],
)
def test_secret_mutations_fail(documentation_repository: Path, credential: str) -> None:
    _append(documentation_repository / "docs/index.md", f"\nSynthetic leak: `{credential}`\n")

    issues = validate_repository(documentation_repository)

    assert any("possible" in issue for issue in issues)


def test_heading_anchor_mutation_fails(documentation_repository: Path) -> None:
    index = documentation_repository / "docs/index.md"
    _append(
        index,
        "\n[Architecture boundaries](concepts/architecture.md#boundary-responsibilities)\n",
    )
    assert validate_repository(documentation_repository) == []
    index.write_text(
        index.read_text(encoding="utf-8").replace("#boundary-responsibilities", "#missing-heading"),
        encoding="utf-8",
    )

    issues = validate_repository(documentation_repository)

    assert any("unresolved Markdown anchor" in issue for issue in issues)


@pytest.mark.parametrize("category", ["concepts", "walkthrough"])
def test_duplicate_taxonomy_link_mutation_fails(
    documentation_repository: Path, category: str
) -> None:
    _append(
        documentation_repository / "docs/index.md",
        f"\n[{category.title()} again]({category}/index.md)\n",
    )

    issues = validate_repository(documentation_repository)

    assert any(f"must link {category}/index.md exactly once" in issue for issue in issues)


def test_missing_project_skill_governance_reference_link_mutation_fails(
    documentation_repository: Path,
) -> None:
    skill = documentation_repository / ".opencode/skills/documentation/SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8").replace(
            "references/authoring.md", "references/missing.md"
        ),
        encoding="utf-8",
    )

    issues = validate_repository(documentation_repository)

    assert any("missing reference link: references/authoring.md" in issue for issue in issues)


@pytest.mark.parametrize("name", APPROVED_SKILL_CATALOG)
def test_project_skill_governance_name_catalog_mutation_fails(
    documentation_repository: Path, name: str
) -> None:
    skill = documentation_repository / f".opencode/skills/{name}/SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8").replace(
            f'name: "{name}"', f'name: "{name}-stale"'
        ),
        encoding="utf-8",
    )

    issues = validate_repository(documentation_repository)

    assert any("skill name must match" in issue for issue in issues)


@pytest.mark.parametrize(("line_count", "fails"), [(500, False), (501, True)])
def test_project_skill_governance_500_line_boundary(
    documentation_repository: Path, line_count: int, fails: bool
) -> None:
    skill = documentation_repository / ".opencode/skills/documentation/SKILL.md"
    lines = skill.read_text(encoding="utf-8").splitlines()
    lines.extend(["<!-- deterministic line-limit mutation -->"] * (line_count - len(lines)))
    skill.write_text("\n".join(lines) + "\n", encoding="utf-8")

    issues = validate_repository(documentation_repository)
    line_limit_issues = [issue for issue in issues if "must not exceed 500 lines" in issue]

    assert bool(line_limit_issues) is fails


@pytest.mark.parametrize("name", APPROVED_SKILL_CATALOG)
def test_project_skill_governance_indexed_path_mutation_fails(
    documentation_repository: Path, name: str
) -> None:
    index = documentation_repository / ".opencode/SKILL-INDEX.md"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            f"skills/{name}/SKILL.md", f"skills/{name}/skill.md"
        ),
        encoding="utf-8",
    )

    issues = validate_repository(documentation_repository)

    assert any(
        "project governance row must match SKILL.md frontmatter" in issue for issue in issues
    )


def test_skill_validation_reference_is_static_and_does_not_claim_runtime_discovery() -> None:
    text = (
        ROOT / ".opencode/skills/stock-probability-skill-maintenance/references/validation.md"
    ).read_text(encoding="utf-8")

    assert "opencode debug skill" not in text
    assert "debug agents" not in text
    assert ".dev-venv/bin/python scripts/validate_docs.py" in text
    assert ".dev-venv/bin/python -m pytest tests/test_docs_validation.py" in text
    assert "Static repository validation only" in text
    assert "native skill discovery" not in text
    assert "provider/session discovery" not in text
    assert "actual named skill load" not in text


def test_project_skill_references_use_current_docs_and_authority_paths() -> None:
    guide = (
        ROOT / ".opencode/skills/development-conventions/references/write-docs/guide.md"
    ).read_text(encoding="utf-8")
    sources = (
        ROOT / ".opencode/skills/documentation/references/repository-sources.md"
    ).read_text(encoding="utf-8")
    checklist = (
        ROOT / ".opencode/skills/database-conventions/references/sqlite-change-checklist.md"
    ).read_text(encoding="utf-8")

    for path in (
        "docs/configure/local-configuration.md",
        "AGENTS.md",
        "docs/develop/documentation.md",
        "docs/develop/testing.md",
        "docs/concepts/architecture.md",
        "documentation-map.json",
    ):
        assert path in guide
    for stale_path in (
        "docs/develop/variables.md",
        "docs/adr/",
        "docs/concepts/skill-system.md",
        "docs/configure/agents.md",
        "docs/concepts/tech-stack.md",
        "docs/concepts/self-learning.md",
        ".opencode/skills/self-learning/SKILL.md",
    ):
        assert stale_path not in guide

    for path in (
        "src/stock_probs/api.py",
        "src/stock_probs/schemas.py",
        "src/stock_probs/repository.py",
        "src/stock_probs/migrations/*.sql",
        "src/stock_probs/backup.py",
        "src/stock_probs/cli.py",
        "frontend/**",
        "src/stock_probs/static/**",
    ):
        assert path in sources
    assert "and `schemas.py`" not in sources
    assert "`repository.py` plus packaged migrations" not in sources
    assert "`backup.py` and `cli.py`" not in sources
    assert "| Dashboard controls and states | static HTML/JS/CSS" not in sources
    assert "`src/stock_probs/repository.py`" in checklist
    assert "`repository.py` without" not in checklist


def test_active_skill_instructions_use_native_role_ids() -> None:
    skill_root = ROOT / ".opencode/skills"
    active_files = {
        path: path.read_text(encoding="utf-8")
        for path in skill_root.rglob("*.md")
    }

    for path, text in active_files.items():
        assert not re.search(r"\bSOL HIGH\b", text, re.IGNORECASE), path
        assert "LUNA MAX docs" not in text, path
        assert "@ingenium-qa" not in text, path
        assert not re.search(r"\borchestrator\b", text, re.IGNORECASE), path

    expected_roles = {
        "development-conventions/references/sources/visual-standards-conventions/source-index.md": (
            "luna-qa",
            "self-repair",
            "delegate",
        ),
        "documentation/references/audit.md": ("luna-build", "luna-docs"),
        "stock-probability-skill-maintenance/references/creation.md": (
            "luna-build",
            "luna-docs",
        ),
    }
    for relative_path, roles in expected_roles.items():
        text = (skill_root / relative_path).read_text(encoding="utf-8")
        assert all(role in text for role in roles), relative_path


def test_retired_ponytail_is_absent_from_index_and_current_status_is_superseding() -> None:
    index = (ROOT / ".opencode/SKILL-INDEX.md").read_text(encoding="utf-8")
    learnings = (ROOT / ".opencode/skill-history/learnings.md").read_text(encoding="utf-8")
    current_status = learnings.split("## 2026-09-11", maxsplit=1)[0]

    assert "**8 skills**" in index
    assert "ponytail-boundary-review" not in index
    assert "ponytail-boundary-review" in current_status
    assert "retired" in current_status.casefold()
    assert "Do not invoke, require, or recommend" in current_status
    assert "historical records only" in current_status
