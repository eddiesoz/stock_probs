"""Fail release checks when authored implementation files omit an intent-bearing comment."""

from __future__ import annotations

from pathlib import Path

ROOTS = ("src", "tests", "scripts", "tools", ".opencode", ".github")
STANDALONE = ("pyproject.toml", "Makefile", "opencode.json")
EXCLUDED_PARTS = {
    "node_modules",
    ".next",
    "out",
    "test-results",
    "playwright-report",
    "__pycache__",
    "stock_probs.egg-info",
}
# JSON has no comment syntax. Declarative config/budgets and .opencode skill metadata are exempt;
# authored fixtures and browser package declarations must retain their existing `_comment`.
DECLARATIVE_JSON = {
    Path("opencode.json"),
    Path(".opencode/package.json"),
    Path(".opencode/package-lock.json"),
    Path("tools/browser/performance-budgets.json"),
    Path("tools/ponytail/package.json"),
}
GENERATED_METADATA = {
    Path(".opencode/.gitignore"),
    Path("frontend/next-env.d.ts"),
}
PONYTAIL = Path("tools/ponytail")
PONYTAIL_LOCAL_SMOKE = PONYTAIL / "smoke.mjs"


def has_comment(path: Path) -> bool:
    """Recognize comments/docstrings without treating arbitrary JSON keys as comments."""

    text = path.read_text()
    if path.suffix == ".json":
        return '"_comment"' in text
    if path.suffix == ".html":
        return "<!--" in text
    if path.suffix in {".css", ".js", ".cjs", ".mjs", ".ts", ".tsx"}:
        return "/*" in text or "//" in text
    return "#" in text or '"""' in text or "--" in text


def checked_paths(root: Path) -> list[Path]:
    """Return authored files while keeping exclusions explicit and path-specific."""

    candidates = [root / item for item in STANDALONE] + [
        path
        for relative_root in ROOTS
        if (root / relative_root).exists()
        for path in (root / relative_root).rglob("*")
        if path.is_file()
    ] + [
        path
        for path in (root / "frontend").rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx"}
    ]
    checked = []
    for path in candidates:
        relative = path.relative_to(root)
        if relative in DECLARATIVE_JSON or (
            relative.parts[0] == ".opencode" and relative.name == "metadata.json"
        ):
            continue
        if (
            EXCLUDED_PARTS.intersection(relative.parts)
            or relative.is_relative_to(Path("src/stock_probs/static/next"))
            or (PONYTAIL in relative.parents and relative != PONYTAIL_LOCAL_SMOKE)
            or relative in GENERATED_METADATA
            or path.suffix in {".lock", ".png", ".pyc"}
        ):
            continue
        checked.append(path)
    return checked


def main() -> None:
    root = Path.cwd().resolve()
    try:
        checked = checked_paths(root)
        missing = [str(path.relative_to(root)) for path in checked if not has_comment(path)]
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"Comment audit scope validation failed: {exc}") from exc
    if missing:
        raise SystemExit("Files missing useful comments: " + ", ".join(missing))
    print(f"comment audit passed: {len(checked)} authored implementation files")


if __name__ == "__main__":
    main()
