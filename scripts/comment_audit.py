"""Fail release checks when implementation files omit an intent-bearing comment."""

from __future__ import annotations

from pathlib import Path


def has_comment(path: Path) -> bool:
    """Recognize comments/docstrings plus JSON's explicit explanatory metadata convention."""

    text = path.read_text()
    if path.suffix == ".json":
        return '"_comment"' in text or '"instructions"' in text or '"$schema"' in text
    if path.suffix in {".html"}:
        return "<!--" in text
    if path.suffix in {".css", ".js"}:
        return "/*" in text or "//" in text
    return "#" in text or '"""' in text or "--" in text


def main() -> None:
    roots = [
        Path("src"),
        Path("tests"),
        Path("scripts"),
        Path("tools"),
        Path(".opencode"),
        Path(".github"),
    ]
    standalone = [Path("pyproject.toml"), Path("Makefile"), Path("opencode.json")]
    # Generated dependencies and browser artifacts are not authored implementation files.
    excluded_parts = {
        "node_modules",
        "test-results",
        "playwright-report",
        "__pycache__",
        "stock_probs.egg-info",
    }
    generated_opencode = {
        Path(".opencode/.gitignore"),
        Path(".opencode/package.json"),
        Path(".opencode/package-lock.json"),
    }
    candidates = standalone + [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if path.is_file()
        and path not in generated_opencode
        and not excluded_parts.intersection(path.parts)
    ]
    checked = [path for path in candidates if path.suffix not in {".lock", ".png", ".pyc"}]
    missing = [str(path) for path in checked if not has_comment(path)]
    if missing:
        raise SystemExit("Files missing useful comments: " + ", ".join(missing))
    print(f"comment audit passed: {len(checked)} implementation files")


if __name__ == "__main__":
    main()
