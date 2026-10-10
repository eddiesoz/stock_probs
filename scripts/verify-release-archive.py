#!/usr/bin/env python3
"""Scan one bounded Docker image archive for credentials and persistent data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tarfile
from pathlib import Path

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
TAIL_BYTES = 256
MAX_ARCHIVE_MEMBERS = 100_000
SECRET_PATH = re.compile(
    r"(^|/)(\.env($|\.)|\.aws($|/)|\.ssh($|/)|auth\.json$|"
    r"credentials?(\.json)?$|.*(id_(rsa|dsa|ecdsa|ed25519)|private[-_.]?key|"
    r"secret[-_.]?key|client[-_.]?key|server[-_.]?key|token[-_.]?file|access[-_.]?token)([^/]*)$|"
    r".*\.(p12|pfx|key)$)",
    re.IGNORECASE,
)
SECRET_BYTES = re.compile(
    rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\t\n\r ]*[A-Za-z0-9+/=]{32,}|"
    rb"gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    rb"sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|"
    rb"AKIA[0-9A-Z]{16}|AWS_SECRET_ACCESS_KEY=|SIGNAL_LEDGER_.*SECRET="
)
DATA_PATH = re.compile(
    r"(^|/)[^/]*\.(?:db|sqlite3?|spbackup)(?:-(?:wal|shm|journal))?(?:/|$)",
    re.IGNORECASE,
)
LAYER_NAME = re.compile(r"(?:(?:[^/]+/)*layer\.tar|blobs/sha256/[0-9a-f]{64})")

# These fixed artifacts contain provenance-verified public strings that the broad credential
# heuristic classifies as `sk-` tokens. Each exemption is bound to one exact file path, size,
# SHA-256 and match span. The public wheel/member hashes and the Bun comparison are recorded in
# the task QA receipt; this table is not a path-, package-, or content-category-wide exemption.
PINNED_PUBLIC_MATCH_SOURCES: dict[str, tuple[int, str, tuple[tuple[int, int], ...]]] = {
    # Peewee 4.5.1's PyPI METADATA README link (official wheel SHA-256
    # dbbdc93e9be08d1df49ceed48dc5d609bfeda6112848086f1f6c1f1debe70975).
    "usr/local/lib/python3.11/site-packages/peewee-4.5.1.dist-info/METADATA": (
        10_627,
        "ec0d94c2e24185782acd93a9df566abc44ce8a9c60265a1d414de090e5421fba",
        ((9_835, 9_880),),
    ),
    # Setuptools 79.0.1 is part of the pinned Python builder base. Its official PyPI wheel
    # (SHA-256 e147c0549f27767ba362f9da434eab9c5dc0045d5304feb602a0af001089fc51) vendors this
    # SPDX exception source.
    "usr/local/lib/python3.11/site-packages/setuptools/_vendor/packaging/licenses/_spdx.py": (
        48_398,
        "a009b5ced3c5c25b2608a7bb94002cbff38839f4b57160eef5b34191ebbeda7b",
        ((42_650, 42_680), (42_697, 42_727)),
    ),
    # packaging 26.3's official PyPI wheel (SHA-256
    # d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c) contains two SPDX
    # exception identifiers at these exact spans.
    "usr/local/lib/python3.11/site-packages/packaging/licenses/_spdx.py": (
        51_122,
        "596ec35e2ca0ebcba9fd8343ff0a51625af548786257815f24b41f7e08613314",
        ((44_773, 44_803), (44_820, 44_850)),
    ),
    # The exact `sk-` match spans in the fixed OpenCode executable have identical offsets and
    # per-span digests in the official pinned Bun 1.4.2 binary. The compiled file's own digest is
    # separately pinned; all nonmatching bytes and any additional matches remain scanned.
    "usr/local/bin/opencode": (
        212_784_608,
        "c22fce743cf6ab15d056d5b589d1307fb5c05ed2129949bef5491af775c2c3ad",
        (
            (1_169_954, 1_169_988),
            (1_184_754, 1_184_859),
            (16_825_067, 16_825_502),
            (16_849_344, 16_852_808),
        ),
    ),
}


class ArchiveError(ValueError):
    """A safe image-archive verification failure."""


def _safe_member_name(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith("/")
        and "\\" not in name
        and all(part not in {"", ".."} for part in name.rstrip("/").split("/"))
    )


def _scan_stream(
    stream: object,
    *,
    exempt_spans: tuple[tuple[int, int], ...] = (),
    expected_sha256: str | None = None,
) -> int:
    tail = b""
    scanned = 0
    digest = hashlib.sha256() if expected_sha256 is not None else None
    seen_exempt_spans: set[tuple[int, int]] = set()
    expected_exempt_spans = set(exempt_spans)
    while True:
        chunk = stream.read(CHUNK_BYTES)  # type: ignore[attr-defined]
        if not chunk:
            if seen_exempt_spans != expected_exempt_spans:
                raise ArchiveError("allowlisted_source_match_missing")
            if digest is not None and digest.hexdigest() != expected_sha256:
                raise ArchiveError("credential_like_bytes")
            return scanned
        scanned += len(chunk)
        if scanned > MAX_ARCHIVE_BYTES:
            raise ArchiveError("layer_too_large")
        if digest is not None:
            digest.update(chunk)
        candidate = tail + chunk
        candidate_offset = scanned - len(chunk) - len(tail)
        for match in SECRET_BYTES.finditer(candidate):
            span = (
                candidate_offset + match.start(),
                candidate_offset + match.end(),
            )
            if span in expected_exempt_spans:
                seen_exempt_spans.add(span)
                continue
            raise ArchiveError("credential_like_bytes")
        tail = candidate[-TAIL_BYTES:]


def _scan_member(name: str, stream: object, size: int) -> int:
    source_pin = PINNED_PUBLIC_MATCH_SOURCES.get(name)
    if source_pin is None or size != source_pin[0]:
        return _scan_stream(stream)
    _, expected_sha256, exempt_spans = source_pin
    return _scan_stream(
        stream,
        exempt_spans=exempt_spans,
        expected_sha256=expected_sha256,
    )


def _scan_layer(layer_stream: object) -> int:
    scanned_bytes = 0
    try:
        with tarfile.open(fileobj=layer_stream, mode="r|*") as layer:
            for member in layer:
                if not _safe_member_name(member.name):
                    raise ArchiveError("unsafe_layer_path")
                if DATA_PATH.search(member.name):
                    raise ArchiveError("persistent_data_path")
                if SECRET_PATH.search(member.name):
                    raise ArchiveError("credential_like_path")
                if not member.isfile():
                    continue
                stream = layer.extractfile(member)
                if stream is None:
                    raise ArchiveError("unreadable_layer_member")
                with stream:
                    scanned_bytes += _scan_member(member.name, stream, member.size)
                    if scanned_bytes > MAX_ARCHIVE_BYTES:
                        raise ArchiveError("layer_too_large")
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise ArchiveError("unreadable_layer") from exc
    return scanned_bytes


def verify_image_archive(path: Path) -> dict[str, object]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ArchiveError("archive_unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ArchiveError("archive_unsafe")
    if not 1 <= metadata.st_size <= MAX_ARCHIVE_BYTES:
        raise ArchiveError("archive_size_invalid")
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise ArchiveError("archive_size_invalid")
                digest.update(chunk)
        manifest: object | None = None
        with tarfile.open(path, mode="r:gz") as archive:
            for member_count, member in enumerate(archive, start=1):
                if member_count > MAX_ARCHIVE_MEMBERS:
                    raise ArchiveError("archive_member_limit")
                if not _safe_member_name(member.name):
                    raise ArchiveError("archive_member_invalid")
                if member.name == "manifest.json":
                    if manifest is not None or not member.isfile():
                        raise ArchiveError("image_manifest_invalid")
                    if member.size > MAX_MANIFEST_BYTES:
                        raise ArchiveError("image_manifest_too_large")
                    manifest_stream = archive.extractfile(member)
                    if manifest_stream is None:
                        raise ArchiveError("image_manifest_unreadable")
                    with manifest_stream:
                        manifest = json.load(manifest_stream)
            if manifest is None:
                raise ArchiveError("image_manifest_missing")
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise ArchiveError("image_manifest_invalid")
            entry = manifest[0]
            if not isinstance(entry, dict):
                raise ArchiveError("image_manifest_invalid")
            layers = entry.get("Layers")
            if not isinstance(layers, list) or not layers:
                raise ArchiveError("image_layers_missing")
            if len(layers) > MAX_ARCHIVE_MEMBERS:
                raise ArchiveError("image_layer_limit")
            layer_names: set[str] = set()
            for layer_name in layers:
                if not isinstance(layer_name, str) or LAYER_NAME.fullmatch(layer_name) is None:
                    raise ArchiveError("image_layer_name_invalid")
                if layer_name in layer_names:
                    raise ArchiveError("image_layer_name_invalid")
                layer_names.add(layer_name)

        found_layers: set[str] = set()
        total_layer_bytes = 0
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                if member.name not in layer_names:
                    continue
                if member.name in found_layers or not member.isfile():
                    raise ArchiveError("image_layer_invalid")
                if member.size > MAX_ARCHIVE_BYTES:
                    raise ArchiveError("image_layer_too_large")
                layer_stream = archive.extractfile(member)
                if layer_stream is None:
                    raise ArchiveError("image_layer_unreadable")
                with layer_stream:
                    total_layer_bytes += _scan_layer(layer_stream)
                found_layers.add(member.name)
                if total_layer_bytes > MAX_ARCHIVE_BYTES:
                    raise ArchiveError("image_layers_too_large")
        if found_layers != layer_names:
            raise ArchiveError("image_layer_missing")
    except ArchiveError:
        raise
    except (
        OSError,
        EOFError,
        UnicodeDecodeError,
        RecursionError,
        json.JSONDecodeError,
        tarfile.TarError,
    ) as exc:
        raise ArchiveError("archive_unreadable") from exc
    if size != metadata.st_size:
        raise ArchiveError("archive_changed_during_scan")
    return {
        "status": "pass",
        "archive_sha256": digest.hexdigest(),
        "archive_size": size,
        "layer_count": len(layers),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        result = verify_image_archive(args.archive)
    except ArchiveError as exc:
        print(json.dumps({"status": "fail", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
