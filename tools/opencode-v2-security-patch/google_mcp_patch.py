#!/usr/bin/env python3
"""Synchronize pinned MCP registry updates before each native session snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

PATCH_DIRECTORY = Path(__file__).parent
MANIFEST_PATH = PATCH_DIRECTORY / "manifest.json"

_OLD_RECONCILE = """    const reconcile = lock.withPermit(
      Effect.gen(function* () {
        discovered = yield* mcp.tools()
        yield* tools.reload()
      }),
    )"""
_OLD_INTERFACE_COMMENT = "  /** Wait for the initial MCP tool registration to settle. */"
_NEW_INTERFACE_COMMENT = "  /** Synchronize the live MCP registry before session context snapshots it. */"
_NEW_RECONCILE = """    const sameToolSnapshot = (left: readonly Mcp.Tool[], right: readonly Mcp.Tool[]) =>
      left.length === right.length && left.every((tool, index) => tool === right[index])

    const reconcile = lock.withPermit(
      Effect.gen(function* () {
        const current = yield* mcp.tools()
        if (sameToolSnapshot(discovered, current)) return
        discovered = current
        yield* tools.reload()
      }),
    )"""
_OLD_RETURN = "    return Service.of({ flush: Effect.asVoid(Fiber.await(initial)) })"
_NEW_RETURN = """    // The MCP handshake may finish before its debounced ToolsChanged observer updates Tool state.
    // Reconcile the live snapshot here so the first model request after registration sees all tools.
    const flush = Effect.asVoid(Fiber.await(initial)).pipe(Effect.andThen(reconcile))
    return Service.of({ flush })"""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _replace_once(source: str, old: str, new: str, *, name: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"pinned MCP patch anchor mismatch: {name}")
    return source.replace(old, new, 1)


def transform_mcp_tool(source: str) -> str:
    """Apply only the exact tool-registry snapshot repair to MCP tool service source."""

    source = _replace_once(
        source,
        _OLD_INTERFACE_COMMENT,
        _NEW_INTERFACE_COMMENT,
        name="interface-comment",
    )
    source = _replace_once(source, _OLD_RECONCILE, _NEW_RECONCILE, name="reconcile")
    return _replace_once(source, _OLD_RETURN, _NEW_RETURN, name="flush")


def patch_mcp_tool(source_root: Path) -> dict[str, str]:
    """Hash-check V2.0.7 MCP tool source before and after its fixed transformation."""

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pinned = manifest["opencode"]
    path = source_root / str(pinned["mcp_tool_path"])
    source = path.read_text(encoding="utf-8")
    source_sha256 = _sha256_text(source)
    if source_sha256 != pinned["mcp_tool_sha256"]:
        raise ValueError("pinned MCP tool source digest mismatch")
    transformed = transform_mcp_tool(source)
    patched_sha256 = _sha256_text(transformed)
    if patched_sha256 != pinned["mcp_tool_patched_sha256"]:
        raise ValueError("pinned MCP tool patch output digest mismatch")
    path.write_text(transformed, encoding="utf-8")
    return {
        "mcp_tool_source_sha256": source_sha256,
        "mcp_tool_patched_sha256": patched_sha256,
    }
