from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rehearse_schema13.py"
_SPEC = importlib.util.spec_from_file_location("candidate_rehearse_schema13", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
rehearsal = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = rehearsal
_SPEC.loader.exec_module(rehearsal)


def _managed_receipt() -> dict[str, object]:
    return {
        "schema": "r120-bounded-image-build-v1",
        "status": "built",
        "stage": "complete",
        "candidate_role": "current",
        "source_branch": "local-managed-build",
        "source_head": rehearsal.HOTFIX_V3_IMAGE_SOURCE_REVISION,
        "revision_label": rehearsal.HOTFIX_V3_IMAGE_SOURCE_REVISION,
        "platform": "linux/amd64",
        "image_id": rehearsal.HOTFIX_V3_IMAGE_ID,
        "context_sha256": rehearsal.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
        "candidate_tag": rehearsal.HOTFIX_V3_CANDIDATE_TAG,
        "builder": "r120-bounded",
        "build_kind": "local",
        "finished_utc": "2026-10-18T04:44:39.343053+00:00",
    }


def _write_receipt(path: Path, receipt: dict[str, object]) -> tuple[Path, str]:
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return path, hashlib.sha256(raw).hexdigest()


def _read_v3(path: Path, digest: str) -> dict[str, object]:
    return rehearsal._read_fixed_hotfix_build_receipt(
        path,
        expected_sha256=digest,
        image_revision=rehearsal.HOTFIX_V3_IMAGE_SOURCE_REVISION,
        image_id=rehearsal.HOTFIX_V3_IMAGE_ID,
        context_sha256=rehearsal.HOTFIX_V3_IMAGE_CONTEXT_SHA256,
        receipt_profile="managed-v3",
    )


def test_managed_v3_receipt_accepts_exact_local_producer_shape(tmp_path: Path) -> None:
    path, digest = _write_receipt(tmp_path / "receipt.json", _managed_receipt())
    assert _read_v3(path, digest) == _managed_receipt()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "branch",
        "head",
        "image",
        "context",
        "tag",
        "platform",
        "builder",
        "build_kind",
        "status",
        "time",
    ],
)
def test_managed_v3_receipt_rejects_invalid_shape_or_identity_even_with_rehashed_bytes(
    tmp_path: Path, mutation: str
) -> None:
    receipt = _managed_receipt()
    if mutation == "missing":
        del receipt["builder"]
    elif mutation == "extra":
        receipt["legacy_build_exit_code"] = 0
    elif mutation == "branch":
        receipt["source_branch"] = "codex/signal-ledger-assistant-fix"
    elif mutation == "head":
        receipt["source_head"] = "0" * 40
    elif mutation == "image":
        receipt["image_id"] = "sha256:" + "0" * 64
    elif mutation == "context":
        receipt["context_sha256"] = "0" * 64
    elif mutation == "tag":
        receipt["candidate_tag"] = "stock-probs:unreviewed"
    elif mutation == "platform":
        receipt["platform"] = "linux/arm64"
    elif mutation == "builder":
        receipt["builder"] = "other-builder"
    elif mutation == "build_kind":
        receipt["build_kind"] = "remote"
    elif mutation == "status":
        receipt["status"] = "running"
    elif mutation == "time":
        receipt["finished_utc"] = "not-a-timestamp"
    else:
        raise AssertionError(mutation)
    path, digest = _write_receipt(tmp_path / "receipt.json", receipt)
    with pytest.raises(
        rehearsal.RehearsalError,
        match="accepted_hotfix_build_receipt_identity_mismatch",
    ):
        _read_v3(path, digest)


def test_managed_v3_receipt_rejects_wrong_fixed_digest(tmp_path: Path) -> None:
    path, _ = _write_receipt(tmp_path / "receipt.json", _managed_receipt())
    with pytest.raises(
        rehearsal.RehearsalError,
        match="accepted_hotfix_build_receipt_digest_mismatch",
    ):
        _read_v3(path, "0" * 64)


def test_build_receipt_rejects_unknown_profile_before_opening_file(tmp_path: Path) -> None:
    with pytest.raises(
        rehearsal.RehearsalError,
        match="accepted_hotfix_build_receipt_profile_invalid",
    ):
        rehearsal._read_fixed_hotfix_build_receipt(
            tmp_path / "missing.json", receipt_profile="unknown-v4"
        )
