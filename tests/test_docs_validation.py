import json
import re
import shutil
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
    shutil.copy2(ROOT / ".opencode" / "skills" / "learnings.md", skill_parent / "learnings.md")
    shutil.copy2(ROOT / ".opencode" / "SKILL-INDEX.md", tmp_path / ".opencode" / "SKILL-INDEX.md")
    for name in ("README.md", "AGENTS.md", "MVP-PLAN.md", "MVP-ROADMAP.md", "SESSION-EXPORT.md"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    assert validate_repository(tmp_path) == []
    return tmp_path


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def test_repository_documentation_contract_passes() -> None:
    assert validate_repository(ROOT) == []


def test_documentation_taxonomy_has_expected_size() -> None:
    assert len(CATEGORIES) == 9
    assert sum(map(len, CATEGORIES.values())) == 13


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


def test_unexpected_skill_catalog_mutation_fails(documentation_repository: Path) -> None:
    unexpected = documentation_repository / ".opencode/skills/unapproved"
    unexpected.mkdir()
    (unexpected / "SKILL.md").write_text(
        '---\nname: "unapproved"\ndescription: "Unapproved test skill."\n---\n',
        encoding="utf-8",
    )

    assert any(
        "unexpected project skill: unapproved" in issue
        for issue in validate_repository(documentation_repository)
    )


def test_missing_admitted_skill_catalog_mutation_fails(documentation_repository: Path) -> None:
    shutil.rmtree(documentation_repository / ".opencode/skills/skill-maintenance")

    assert any(
        "missing admitted project skill: skill-maintenance" in issue
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
            "metadata description must match SKILL.md frontmatter",
        ),
        (
            ".opencode/skills/documentation/metadata.json",
            "metadata description must match SKILL.md frontmatter",
        ),
        (
            ".opencode/SKILL-INDEX.md",
            "skill row must match SKILL.md frontmatter name and description",
        ),
    ],
)
def test_skill_description_parity_mutations_fail(
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
def test_metadata_policy_mutations_fail(
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


def test_missing_skill_reference_link_mutation_fails(documentation_repository: Path) -> None:
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
def test_skill_name_catalog_mutation_fails(
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
def test_active_skill_500_line_boundary(
    documentation_repository: Path, line_count: int, fails: bool
) -> None:
    skill = documentation_repository / ".opencode/skills/documentation/SKILL.md"
    lines = skill.read_text(encoding="utf-8").splitlines()
    lines.extend(["<!-- deterministic line-limit mutation -->"] * (line_count - len(lines)))
    skill.write_text("\n".join(lines) + "\n", encoding="utf-8")

    issues = validate_repository(documentation_repository)
    line_limit_issues = [issue for issue in issues if "must not exceed 500 lines" in issue]

    assert bool(line_limit_issues) is fails


def test_indexed_skill_path_mutation_fails(documentation_repository: Path) -> None:
    index = documentation_repository / ".opencode/SKILL-INDEX.md"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "skills/documentation/SKILL.md", "skills/documentation/skill.md"
        ),
        encoding="utf-8",
    )

    issues = validate_repository(documentation_repository)

    assert any("SKILL.md frontmatter name and description" in issue for issue in issues)
