#!/usr/bin/env python3
"""Replace the packaged static tree with a validated Next export."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "frontend/out"
DESTINATION = ROOT / "src/stock_probs/static/next"
STATIC_ASSETS = ROOT / "src/stock_probs/static"
ASSET_NAMES = ("app.css", "app.js", "theme.js", "favicon.svg")
PAGES = (
    "index.html",
    "api-docs.html",
    "overview.html",
    "research.html",
    "tools.html",
    "tools/forecast.html",
    "tools/live-trading.html",
    "tools/markets.html",
    "sign-in.html",
    "invite.html",
    "passkey.html",
    "authenticator.html",
    "account.html",
    "admin.html",
)


def _validate_sources() -> None:
    """Validate all export and authored assets before replacing the staged tree."""
    if SOURCE.is_symlink() or not SOURCE.is_dir():
        raise SystemExit("frontend/out is not a complete Next export")
    if any(path.is_symlink() for path in SOURCE.rglob("*")):
        raise SystemExit("frontend/out must not contain symlinks")
    if not all((SOURCE / name).is_file() for name in PAGES):
        raise SystemExit("frontend/out is not a complete Next export")
    if not (SOURCE / "_next").is_dir():
        raise SystemExit("frontend/out is not a complete Next export")

    if DESTINATION.is_symlink():
        raise SystemExit("static/next must not be a symlink")
    if STATIC_ASSETS.is_symlink() or not STATIC_ASSETS.is_dir():
        raise SystemExit("FastAPI static assets are incomplete")
    for name in ASSET_NAMES:
        asset = STATIC_ASSETS / name
        if asset.is_symlink():
            raise SystemExit("FastAPI static assets must not contain symlinks")
        if not asset.is_file() or asset.stat().st_size == 0:
            raise SystemExit("FastAPI static assets are incomplete")

    export_assets = SOURCE / "assets"
    if export_assets.exists() and not export_assets.is_dir():
        raise SystemExit("frontend/out assets are incomplete")
    if any(
        (export_assets / name).exists() and not (export_assets / name).is_file()
        for name in ASSET_NAMES
    ):
        raise SystemExit("frontend/out assets are incomplete")


def _copy_authored_assets_to_export() -> None:
    """Include FastAPI's fixed authored assets in the generated Next export."""
    export_assets = SOURCE / "assets"
    export_assets.mkdir(exist_ok=True)
    for name in ASSET_NAMES:
        shutil.copy2(STATIC_ASSETS / name, export_assets / name)


def main() -> None:
    """Validate the export, reconcile served assets, and replace staged Next files."""
    _validate_sources()
    _copy_authored_assets_to_export()

    # All inputs are checked before deleting the previous packaged frontend.
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    DESTINATION.mkdir()
    # FastAPI serves only these pages and /_next; omit Next route metadata and error files.
    for name in PAGES:
        destination = DESTINATION / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / name, destination)
    shutil.copytree(SOURCE / "_next", DESTINATION / "_next")


if __name__ == "__main__":
    main()
