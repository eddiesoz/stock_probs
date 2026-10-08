"""Verify the fixed local PR pair and write its private review pins."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.deploy_mcp import pr_rehearsal  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Verify and persist pins only when the operator explicitly requests a write."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        required=True,
        help="verify the current clean PR-1 pair and write its private review metadata",
    )
    arguments = parser.parse_args(argv)
    if not arguments.write:
        parser.error("--write is required")
    try:
        result = pr_rehearsal.write_review_pins_from_current_pair()
    except pr_rehearsal.RehearsalError as exc:
        print(json.dumps({"status": "error", "code": exc.code}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": "written", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
