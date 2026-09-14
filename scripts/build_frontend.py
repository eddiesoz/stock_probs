#!/usr/bin/env python3
"""Replace the packaged static tree with a validated Next export."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "frontend/out"
DESTINATION = ROOT / "src/stock_probs/static/next"


def main() -> None:
    if not all((SOURCE / name).is_file() for name in ("index.html", "api-docs.html")):
        raise SystemExit("frontend/out is not a complete Next export")
    if not (SOURCE / "_next").is_dir():
        raise SystemExit("frontend/out is not a complete Next export")
    if any(path.is_symlink() for path in SOURCE.rglob("*")):
        raise SystemExit("frontend/out must not contain symlinks")

    if DESTINATION.is_symlink():
        raise SystemExit("static/next must not be a symlink")
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    DESTINATION.mkdir()
    # FastAPI serves only these pages and /_next; omit Next route metadata and error files.
    for name in ("index.html", "api-docs.html"):
        shutil.copy2(SOURCE / name, DESTINATION / name)
    shutil.copytree(SOURCE / "_next", DESTINATION / "_next")


if __name__ == "__main__":
    main()
