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


class ArchiveError(ValueError):
    """A safe image-archive verification failure."""


def _safe_member_name(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith("/")
        and "\\" not in name
        and all(part not in {"", ".."} for part in name.rstrip("/").split("/"))
    )


def _scan_stream(stream: object) -> int:
    tail = b""
    scanned = 0
    while True:
        chunk = stream.read(CHUNK_BYTES)  # type: ignore[attr-defined]
        if not chunk:
            return scanned
        scanned += len(chunk)
        if scanned > MAX_ARCHIVE_BYTES:
            raise ArchiveError("layer_too_large")
        candidate = tail + chunk
        if SECRET_BYTES.search(candidate):
            raise ArchiveError("credential_like_bytes")
        tail = candidate[-TAIL_BYTES:]


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
                    scanned_bytes += _scan_stream(stream)
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
