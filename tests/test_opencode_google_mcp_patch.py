"""Tests for the hash-pinned MCP tool snapshot reconciliation patch."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIRECTORY = ROOT / "tools/opencode-v2-security-patch"
sys.path.insert(0, str(PATCH_DIRECTORY))

import google_mcp_patch  # noqa: E402


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fixture_source() -> str:
    return "\n".join(
        (
            google_mcp_patch._OLD_INTERFACE_COMMENT,
            "import { Context, Effect, Fiber, type JsonSchema, Layer, PubSub, Semaphore, Stream } "
            'from "effect"',
            google_mcp_patch._OLD_RECONCILE,
            google_mcp_patch._OLD_RETURN,
        )
    )


def test_transform_reconciles_the_current_registry_before_snapshot() -> None:
    patched = google_mcp_patch.transform_mcp_tool(_fixture_source())

    assert (
        "const sameToolSnapshot = (left: readonly Mcp.Tool[], right: readonly Mcp.Tool[])"
        in patched
    )
    assert "const current = yield* mcp.tools()" in patched
    assert "if (sameToolSnapshot(discovered, current)) return" in patched
    assert "discovered = current" in patched
    assert "yield* tools.reload()" in patched
    assert "Effect.andThen(reconcile)" in patched
    assert "Synchronize the live MCP registry before session context snapshots it." in patched


def test_transform_rejects_missing_or_ambiguous_pinned_anchors() -> None:
    with pytest.raises(ValueError, match="anchor mismatch: reconcile"):
        google_mcp_patch.transform_mcp_tool(
            _fixture_source().replace("const reconcile", "const other")
        )

    with pytest.raises(ValueError, match="anchor mismatch: reconcile"):
        google_mcp_patch.transform_mcp_tool(
            _fixture_source() + "\n" + google_mcp_patch._OLD_RECONCILE
        )


def test_pinned_patch_checks_input_and_output_hashes_before_writing(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source = source_root / "packages/core/src/tool/mcp.ts"
    source.parent.mkdir(parents=True)
    original = _fixture_source()
    transformed = google_mcp_patch.transform_mcp_tool(original)
    source.write_text(original, encoding="utf-8")
    manifest = {
        "opencode": {
            "mcp_tool_path": "packages/core/src/tool/mcp.ts",
            "mcp_tool_sha256": _sha256(original),
            "mcp_tool_patched_sha256": _sha256(transformed),
        }
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(google_mcp_patch, "MANIFEST_PATH", manifest_path)

    receipt = google_mcp_patch.patch_mcp_tool(source_root)

    assert receipt == {
        "mcp_tool_source_sha256": _sha256(original),
        "mcp_tool_patched_sha256": _sha256(transformed),
    }
    assert source.read_text(encoding="utf-8") == transformed


def test_pinned_patch_rejects_source_digest_mismatch_without_mutation(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "source"
    source = source_root / "packages/core/src/tool/mcp.ts"
    source.parent.mkdir(parents=True)
    original = _fixture_source()
    source.write_text(original, encoding="utf-8")
    manifest = {
        "opencode": {
            "mcp_tool_path": "packages/core/src/tool/mcp.ts",
            "mcp_tool_sha256": "0" * 64,
            "mcp_tool_patched_sha256": "1" * 64,
        }
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(google_mcp_patch, "MANIFEST_PATH", manifest_path)

    with pytest.raises(ValueError, match="source digest mismatch"):
        google_mcp_patch.patch_mcp_tool(source_root)

    assert source.read_text(encoding="utf-8") == original
