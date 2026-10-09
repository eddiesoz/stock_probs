"""Focused Docker-free tests for the centralized bounded image-build policy."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import multiprocessing
import os
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/bounded_docker_build.py"
SPEC = importlib.util.spec_from_file_location("bounded_docker_build", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bounded = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bounded)


def _ledger_slot_worker(
    lock_path: str,
    ledger_path: str,
    start_event: Any,
    result_queue: Any,
) -> None:
    state = Path(ledger_path).parent
    bounded.USER = SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(state))
    bounded.STATE = state
    bounded.LEDGER_LOCK_FILE = Path(lock_path)
    bounded.LEDGER_FILE = Path(ledger_path)
    bounded._image_inventory = lambda: {}

    def pause_before_write(*_args: object, **_kwargs: object) -> None:
        time.sleep(0.05)

    bounded._verify_ledger_inventory = pause_before_write
    if not start_event.wait(timeout=5):
        result_queue.put("start_timeout")
        return
    try:
        process_id = os.getpid()
        tag = f"stock-probs:pr-candidate-{process_id:012x}-{process_id + 1:012x}"
        bounded._reserve_managed_tags(
            {},
            (tag,),
            f"{process_id:040x}",
            hashlib.sha256(str(process_id).encode()).hexdigest(),
            "current",
        )
        result_queue.put("reserved")
    except bounded.BuildError as exc:
        result_queue.put(exc.code)


def _test_ledger_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    ledger_path = state / "candidate-ledger.json"
    lock_path = state / "candidate-ledger.lock"
    monkeypatch.setattr(bounded, "USER", SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(tmp_path)))
    monkeypatch.setattr(bounded, "STATE", state)
    monkeypatch.setattr(bounded, "LEDGER_FILE", ledger_path)
    monkeypatch.setattr(bounded, "LEDGER_LOCK_FILE", lock_path)
    return state, ledger_path


def _entry(index: int, role: str = "current") -> dict[str, str]:
    return {
        "image_id": "sha256:" + f"{index:064x}",
        "tag": f"stock-probs:pr-candidate-{index:012x}-{index + 1:012x}",
        "revision": f"{index:040x}",
        "context_sha256": f"{index + 2:064x}",
        "role": role,
        "status": "complete",
        "receipt_path": str(bounded.RUNS / f"{index:064x}/build-receipt.json"),
        "receipt_sha256": f"{index + 3:064x}",
    }


def test_active_buildkit_config_accepts_reformatted_exact_semantics() -> None:
    expected = MODULE_PATH.with_name("r120-buildkitd.toml").read_bytes()
    transformed = (
        b"\n[worker]\n\n  [worker.oci]\n"
        b"    gc = true\n"
        b"    max-parallelism = 1\n"
        b"    maxUsedSpace = 4294967296\n"
        b"    minFreeSpace = 4294967296\n"
        b"    reservedSpace = 1073741824\n"
    )

    assert (
        bounded.verify_active_buildkit_config(transformed, expected)
        == hashlib.sha256(transformed).hexdigest()
    )


@pytest.mark.parametrize(
    "active_config",
    [
        MODULE_PATH.with_name("r120-buildkitd.toml").read_bytes() + b"unexpected = true\n",
        MODULE_PATH.with_name("r120-buildkitd.toml")
        .read_bytes()
        .replace(b"max-parallelism = 1", b"max-parallelism = true"),
        MODULE_PATH.with_name("r120-buildkitd.toml")
        .read_bytes()
        .replace(b"reservedSpace = 1073741824", b"reservedSpace = 1"),
        b"[worker.oci\ngc = true\n",
    ],
)
def test_active_buildkit_config_rejects_extra_or_changed_semantics(active_config: bytes) -> None:
    expected = MODULE_PATH.with_name("r120-buildkitd.toml").read_bytes()

    with pytest.raises(bounded.BuildError, match="active_buildkit_config_changed"):
        bounded.verify_active_buildkit_config(active_config, expected)


@pytest.mark.parametrize(
    "output",
    [
        "github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1\n",
        "github.com/docker/buildx v0.30.1\n",
    ],
)
def test_bounded_build_accepts_exact_buildx_version_output(output: str) -> None:
    bounded.verify_buildx_version_output(output)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "github.com/docker/buildx",
        "github.com/docker/buildx 0.29.1 0.29.1-0ubuntu1",
        "github.com/docker/buildx v0.30.10",
        "github.com/docker/buildx-other 0.30.1 0.30.1-0ubuntu1",
        "github.com/docker/buildx 0.30.1 9.99.9-0ubuntu1",
        "github.com/docker/buildx v0.30.1 unexpected",
        "github.com/docker/buildx v0.30.1 9.99.9-0ubuntu1",
        "github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1+commit",
        "github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1 extra",
    ],
)
def test_bounded_build_rejects_missing_mismatched_or_ambiguous_buildx_version(
    output: str,
) -> None:
    with pytest.raises(bounded.BuildError, match="buildx_version_changed"):
        bounded.verify_buildx_version_output(output)


def test_bounded_helper_reads_driver_from_supported_buildx_json_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    listing = b'{"Current":true,"Driver":"docker","Name":"default","Nodes":[]}\n'
    listing += b'{"Current":false,"Driver":"docker-container","Name":"r120-bounded","Nodes":[]}\n'

    def fake_capture(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
        calls.append(argv)
        assert max_bytes == bounded.BUILDX_LISTING_MAX_BYTES
        assert timeout == bounded.BUILDX_LISTING_TIMEOUT
        return listing

    monkeypatch.setattr(bounded, "_capture_bounded_stdout", fake_capture)

    assert bounded.buildx_driver() == "docker-container"
    assert calls == [[bounded.DOCKER, "buildx", "ls", "--format", "json"]]


@pytest.mark.parametrize(
    ("listing", "error"),
    [
        (b"", "builder_driver_listing_invalid"),
        (b"not-json\n", "builder_driver_listing_invalid"),
        (b'{"Driver":"docker-container"}\n', "builder_driver_listing_invalid"),
        (b'{"Name":"r120-bounded","Driver":3}\n', "builder_driver_listing_invalid"),
        (
            b'{"Name":"r120-bounded","Name":"r120-bounded","Driver":"docker-container"}\n',
            "builder_driver_listing_invalid",
        ),
        (
            b'{"Name":"r120-bounded","Driver":"docker-container"}\n'
            b'{"Name":"r120-bounded","Driver":"docker-container"}\n',
            "builder_driver_listing_invalid",
        ),
        (b'{"Name":"default","Driver":"docker"}\n', "builder_driver_changed"),
        (b'{"Name":"r120-bounded","Driver":"docker"}\n', "builder_driver_changed"),
    ],
)
def test_bounded_helper_rejects_invalid_or_unexpected_buildx_driver_listing(
    listing: bytes, error: str
) -> None:
    with pytest.raises(bounded.BuildError, match=error):
        bounded.verify_buildx_driver_list(listing)


def test_bounded_driver_capture_accepts_output_at_exact_limit() -> None:
    output = bounded._capture_bounded_stdout(
        [sys.executable, "-c", "import os; os.write(1, b'12345678')"],
        max_bytes=8,
        timeout=2,
    )

    assert output == b"12345678"


def test_bounded_driver_capture_rejects_oversize_and_reaps_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = bounded.subprocess.Popen
    real_killpg = bounded.os.killpg
    processes: list[bounded.subprocess.Popen[bytes]] = []
    signals: list[int] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> bounded.subprocess.Popen[bytes]:
        assert kwargs["stdin"] == bounded.subprocess.DEVNULL
        assert kwargs["stdout"] == bounded.subprocess.PIPE
        assert kwargs["stderr"] == bounded.subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        assert kwargs["shell"] is False
        process = real_popen(argv, **kwargs)
        processes.append(process)
        return process

    def tracked_killpg(process_id: int, signum: int) -> None:
        signals.append(signum)
        real_killpg(process_id, signum)

    monkeypatch.setattr(bounded.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(bounded.os, "killpg", tracked_killpg)

    with pytest.raises(bounded.BuildError, match="builder_driver_listing_too_large"):
        bounded._capture_bounded_stdout(
            [sys.executable, "-c", "import os; os.write(1, b'x' * 64)"],
            max_bytes=8,
            timeout=2,
        )

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals


def test_bounded_driver_capture_times_out_after_stdout_eof_and_reaps_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = bounded.subprocess.Popen
    real_killpg = bounded.os.killpg
    processes: list[bounded.subprocess.Popen[bytes]] = []
    signals: list[int] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> bounded.subprocess.Popen[bytes]:
        process = real_popen(argv, **kwargs)
        processes.append(process)
        return process

    def tracked_killpg(process_id: int, signum: int) -> None:
        signals.append(signum)
        real_killpg(process_id, signum)

    monkeypatch.setattr(bounded.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(bounded.os, "killpg", tracked_killpg)

    with pytest.raises(bounded.BuildError, match="fixed_command_unavailable_or_timeout"):
        bounded._capture_bounded_stdout(
            [sys.executable, "-c", "import os,time; os.close(1); time.sleep(10)"],
            max_bytes=8,
            timeout=0.2,
        )

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals


def test_bounded_driver_capture_cancels_on_reader_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = bounded.subprocess.Popen
    real_read = bounded.os.read
    real_killpg = bounded.os.killpg
    processes: list[bounded.subprocess.Popen[bytes]] = []
    output_fds: set[int] = set()
    signals: list[int] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> bounded.subprocess.Popen[bytes]:
        process = real_popen(argv, **kwargs)
        processes.append(process)
        assert process.stdout is not None
        output_fds.add(process.stdout.fileno())
        return process

    def failed_output_read(file_descriptor: int, size: int) -> bytes:
        if file_descriptor in output_fds:
            raise OSError("synthetic reader failure")
        return real_read(file_descriptor, size)

    def tracked_killpg(process_id: int, signum: int) -> None:
        signals.append(signum)
        real_killpg(process_id, signum)

    monkeypatch.setattr(bounded.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(bounded.os, "read", failed_output_read)
    monkeypatch.setattr(bounded.os, "killpg", tracked_killpg)

    with pytest.raises(bounded.BuildError, match="fixed_command_unavailable_or_timeout"):
        bounded._capture_bounded_stdout(
            [sys.executable, "-c", "import os,time; os.write(1, b'x'); time.sleep(10)"],
            max_bytes=8,
            timeout=2,
        )

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals


def _arm_cleanup_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[tuple[str, str], str, dict[str, str], dict[str, str]]:
    state, ledger_path = _test_ledger_paths(tmp_path, monkeypatch)
    runs = state / "runs"
    runs.mkdir(mode=0o700)
    monkeypatch.setattr(bounded, "RUNS", runs)

    revision = "a" * 40
    context_hash = "b" * 64
    tags = (
        "stock-probs-r-astra-120-arm64-runtime:20261009T123456Z",
        "stock-probs-r-astra-120-arm64-frontend:20261009T123456Z",
    )
    image_ids = {
        tags[0]: "sha256:" + "c" * 64,
        tags[1]: "sha256:" + "d" * 64,
    }
    rows: list[dict[str, object]] = []
    for index, tag in enumerate(tags):
        receipt_path = runs / revision / str(index) / "build-receipt.json"
        receipt_path.parent.mkdir(parents=True, mode=0o700)
        image_id = image_ids[tag]
        receipt = {
            "schema": "r120-bounded-image-build-v1",
            "status": "built",
            "build_kind": "arm64-compose",
            "candidate_role": "transient",
            "candidate_tag": tag,
            "image_id": image_id,
            "revision_label": revision,
            "context_sha256": context_hash,
            "platform": "linux/arm64",
        }
        raw_receipt = (json.dumps(receipt, sort_keys=True) + "\n").encode()
        receipt_path.write_bytes(raw_receipt)
        receipt_path.chmod(0o600)
        rows.append(
            {
                "image_id": image_id,
                "tag": tag,
                "revision": revision,
                "context_sha256": context_hash,
                "role": "transient",
                "status": "complete",
                "receipt_path": str(receipt_path),
                "receipt_sha256": hashlib.sha256(raw_receipt).hexdigest(),
            }
        )
    ledger_path.write_text(
        json.dumps({"schema": bounded.LEDGER_SCHEMA, "entries": rows}), encoding="utf-8"
    )
    ledger_path.chmod(0o600)
    inventory = image_ids.copy()
    monkeypatch.setattr(bounded, "setup_receipt", lambda: {"legacy_task_image_inventory": {}})
    monkeypatch.setattr(bounded, "_image_inventory", lambda: inventory.copy())
    monkeypatch.setattr(bounded, "_all_image_ids", lambda: set(inventory.values()))
    monkeypatch.setattr(bounded, "_container_uses_image_id", lambda _image_id: False)

    def inspect(argv: list[str], timeout: int = 30) -> bytes:
        assert argv[:3] == [bounded.DOCKER, "image", "inspect"]
        tag = argv[-1]
        return f"{image_ids[tag]}|linux/arm64|{json.dumps([tag])}".encode()

    monkeypatch.setattr(bounded, "checked", inspect)
    return tags, revision, image_ids, inventory


def _schema13_rehearsal_cleanup_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "recovery",
) -> dict[str, object]:
    state, ledger_path = _test_ledger_paths(tmp_path, monkeypatch)
    runs = state / "build-runs"
    runs.mkdir(mode=0o700)
    monkeypatch.setattr(bounded, "RUNS", runs)

    tag = "stock-probs:schema13-recovery-012345abcdef"
    image_id = "sha256:" + "1" * 64
    parent_id = "sha256:" + "2" * 64
    revision = "schema13-recovery-" + "3" * 64
    context_hash = "4" * 64
    receipt_path = runs / ("a" * 40) / ("b" * 64) / "build-receipt.json"
    receipt_path.parent.mkdir(parents=True, mode=0o700)
    receipt = {
        "schema": "r120-bounded-image-build-v1",
        "status": "built",
        "source_head": "5" * 40,
        "source_branch": "codex/r120",
        "revision_label": revision,
        "context_sha256": context_hash,
        "candidate_tag": tag,
        "candidate_role": role,
        "image_id": image_id,
    }
    raw_receipt = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    receipt_path.write_bytes(raw_receipt)
    receipt_path.chmod(0o600)
    row = {
        "image_id": image_id,
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": role,
        "status": "complete",
        "receipt_path": str(receipt_path),
        "receipt_sha256": hashlib.sha256(raw_receipt).hexdigest(),
    }
    ledger_path.write_text(
        json.dumps({"schema": bounded.LEDGER_SCHEMA, "entries": [row]}), encoding="utf-8"
    )
    ledger_path.chmod(0o600)
    inventory = {tag: image_id}
    image_ids = {image_id, parent_id}
    first_layer = "sha256:" + "a" * 64
    second_layer = "sha256:" + "b" * 64
    rootfs_layers_by_id = {
        image_id: [first_layer, second_layer],
        parent_id: [first_layer],
    }
    repo_tags = {image_id: [tag], parent_id: []}
    references: set[str] = set()
    state_flags = {
        "remove_fails": False,
        "remove_leaves_id": False,
        "rootfs_inventory_override": None,
        "rootfs_capture_outcome": None,
    }
    calls: list[list[str]] = []
    capture_calls: list[tuple[list[str], int, float]] = []
    monkeypatch.setattr(bounded, "setup_receipt", lambda: {"legacy_task_image_inventory": {}})
    monkeypatch.setattr(bounded, "_image_inventory", lambda: inventory.copy())
    monkeypatch.setattr(bounded, "_all_image_ids", lambda: set(image_ids))
    monkeypatch.setattr(
        bounded, "_container_uses_image_id", lambda candidate_id: candidate_id in references
    )

    def inspect(argv: list[str], timeout: int = 30) -> bytes:
        calls.append(argv)
        assert argv[:3] == [bounded.DOCKER, "image", "inspect"]
        fmt = argv[4]
        candidates = argv[5:]
        if fmt == '{{.Id}}|{{index .Config.Labels "org.opencontainers.image.revision"}}':
            assert candidates == [image_id]
            return f"{image_id}|{revision}".encode()
        if fmt == (
            "{{.Id}}|{{.Os}}/{{.Architecture}}|{{json .RepoTags}}|"
            '{{index .Config.Labels "org.opencontainers.image.revision"}}'
        ):
            assert candidates == [image_id]
            return (f"{image_id}|linux/amd64|{json.dumps(repo_tags[image_id])}|{revision}").encode()
        if fmt == "{{.Id}}|{{.RootFS.Type}}|{{json .RootFS.Layers}}":
            override = state_flags["rootfs_inventory_override"]
            if override is not None:
                return override
            return "\n".join(
                f"{candidate_id}|layers|{json.dumps(rootfs_layers_by_id[candidate_id])}"
                for candidate_id in candidates
            ).encode()
        raise AssertionError(f"unexpected Docker inspect format: {fmt}")

    def docker_check(argv: list[str], timeout: int = 30) -> bytes:
        calls.append(argv)
        if argv[:3] == [bounded.DOCKER, "image", "inspect"]:
            return inspect(argv, timeout)
        if argv[:4] == [bounded.DOCKER, "image", "rm", "--no-prune"]:
            assert argv[4] == image_id
            if state_flags["remove_fails"]:
                raise bounded.BuildError("fixed_command_failed")
            inventory.pop(tag, None)
            repo_tags[image_id] = []
            if not state_flags["remove_leaves_id"]:
                image_ids.remove(image_id)
            return b"removed"
        if argv[:3] == [bounded.DOCKER, "image", "tag"]:
            assert argv[3:] == [image_id, tag]
            inventory[tag] = image_id
            repo_tags[image_id] = [tag]
            return b"tagged"
        raise AssertionError(f"unexpected Docker command: {argv}")

    def bounded_capture(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
        capture_calls.append((argv.copy(), max_bytes, timeout))
        outcome = state_flags["rootfs_capture_outcome"]
        if outcome == "too_large":
            raise bounded.BuildError("builder_driver_listing_too_large")
        if outcome == "unavailable":
            raise bounded.BuildError("fixed_command_failed")
        if outcome == "timeout":
            raise bounded.BuildError("fixed_command_unavailable_or_timeout")
        return inspect(argv, int(timeout))

    monkeypatch.setattr(bounded, "checked", docker_check)
    monkeypatch.setattr(bounded, "_capture_bounded_stdout", bounded_capture)
    return {
        "tag": tag,
        "image_id": image_id,
        "parent_id": parent_id,
        "revision": revision,
        "context_hash": context_hash,
        "row": row,
        "ledger_path": ledger_path,
        "inventory": inventory,
        "image_ids": image_ids,
        "rootfs_layers_by_id": rootfs_layers_by_id,
        "repo_tags": repo_tags,
        "references": references,
        "state_flags": state_flags,
        "calls": calls,
        "capture_calls": capture_calls,
    }


def _encode_buildkit_history_jsonl(rows: list[dict[str, object]]) -> bytes:
    encoded = [json.dumps(row, separators=(",", ":")) for row in rows]
    return ("\n".join(encoded) + "\n").encode()


def _failed_inflight_reservation_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    state, ledger_path = _test_ledger_paths(tmp_path, monkeypatch)
    runs = state / "build-runs"
    runs.mkdir(mode=0o700)
    runs.chmod(0o700)
    monkeypatch.setattr(bounded, "RUNS", runs)
    root_state = state / "root-state"
    root_state.mkdir(mode=0o700)
    root_state.chmod(0o700)
    setup_path = root_state / "setup-receipt.json"
    setup_bytes = b'{"fixture":"current setup receipt"}\n'
    setup_path.write_bytes(setup_bytes)
    setup_path.chmod(0o600)
    monkeypatch.setattr(bounded, "ROOT_STATE", root_state)
    monkeypatch.setattr(bounded, "SETUP_RECEIPT", setup_path)

    revision = "ae140dd011ee" + "1" * 28
    context_hash = "9" * 64
    tag = f"stock-probs:pr-candidate-{revision[:12]}-905bb33256c5"
    role = "current"
    run_key = hashlib.sha256((tag + "\0" + context_hash).encode()).hexdigest()
    run_dir = runs / revision / run_key
    run_dir.mkdir(mode=0o700, parents=True)
    (runs / revision).chmod(0o700)
    run_dir.chmod(0o700)
    started = datetime.now(UTC) - timedelta(seconds=20)
    build_started = started + timedelta(seconds=5)
    finished = build_started + timedelta(seconds=10)
    history_created = build_started + timedelta(seconds=2)
    history_completed = finished + timedelta(seconds=1)
    failure_receipt: dict[str, object] = {
        "schema": "r120-bounded-image-build-v1",
        "status": "failed",
        "stage": "fixed_command_unavailable_or_timeout",
        "source_head": revision,
        "source_branch": "codex/signal-ledger-assistant-r120",
        "revision_label": revision,
        "context_sha256": context_hash,
        "candidate_tag": tag,
        "candidate_role": role,
        "builder": bounded.BUILDER,
        "setup_receipt_sha256": hashlib.sha256(setup_bytes).hexdigest(),
        "started_utc": started.isoformat(),
        "build_started_utc": build_started.isoformat(),
        "finished_utc": finished.isoformat(),
        "process_group_cancel_verified": True,
        "ledger_reservation_retained": True,
    }
    raw_failure_receipt = (json.dumps(failure_receipt, sort_keys=True) + "\n").encode()
    failure_path = run_dir / "build-receipt.json"
    failure_path.write_bytes(raw_failure_receipt)
    failure_path.chmod(0o600)
    failure_sha256 = hashlib.sha256(raw_failure_receipt).hexdigest()
    reservation = {
        "image_id": bounded._reservation_image_id(tag),
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": role,
        "status": "inflight",
    }

    kept_tag = "stock-probs:pr-candidate-aaaaaaaaaaaa-bbbbbbbbbbbb"
    kept_revision = "b" * 40
    kept_context = "c" * 64
    kept_image_id = "sha256:" + "d" * 64
    kept_run_key = hashlib.sha256((kept_tag + "\0" + kept_context).encode()).hexdigest()
    kept_run_dir = runs / kept_revision / kept_run_key
    kept_run_dir.mkdir(mode=0o700, parents=True)
    (runs / kept_revision).chmod(0o700)
    kept_run_dir.chmod(0o700)
    kept_receipt = {
        "schema": "r120-bounded-image-build-v1",
        "status": "built",
        "candidate_tag": kept_tag,
        "candidate_role": "current",
        "image_id": kept_image_id,
        "revision_label": kept_revision,
        "context_sha256": kept_context,
    }
    kept_receipt_bytes = (json.dumps(kept_receipt, sort_keys=True) + "\n").encode()
    kept_receipt_path = kept_run_dir / "build-receipt.json"
    kept_receipt_path.write_bytes(kept_receipt_bytes)
    kept_receipt_path.chmod(0o600)
    kept_row = {
        "image_id": kept_image_id,
        "tag": kept_tag,
        "revision": kept_revision,
        "context_sha256": kept_context,
        "role": "current",
        "status": "complete",
        "receipt_path": str(kept_receipt_path),
        "receipt_sha256": hashlib.sha256(kept_receipt_bytes).hexdigest(),
    }
    legacy_tag = "stock-probs:schema12-base-ffffffffffff"
    legacy_image_id = "sha256:" + "e" * 64
    legacy_inventory = {legacy_tag: legacy_image_id}
    inventory = {kept_tag: kept_image_id, **legacy_inventory}
    ledger = {"schema": bounded.LEDGER_SCHEMA, "entries": [reservation, kept_row]}
    ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
    ledger_path.chmod(0o600)
    history_ref = "r120-bounded/r120-bounded0/" + "a" * 25
    history = [
        {
            "cached_steps": 3,
            "completed_at": history_completed.isoformat().replace("+00:00", "Z"),
            "completed_steps": 21,
            "created_at": history_created.isoformat().replace("+00:00", "Z"),
            "name": "context",
            "ref": history_ref,
            "status": "Error",
            "total_steps": 46,
        },
        {
            "cached_steps": 0,
            "completed_at": (started - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "completed_steps": 2,
            "created_at": (started - timedelta(seconds=3)).isoformat().replace("+00:00", "Z"),
            "name": "context",
            "ref": "r120-bounded/r120-bounded0/" + "b" * 25,
            "status": "Completed",
            "total_steps": 4,
        },
        {
            "cached_steps": 2,
            "completed_at": (started - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
            "completed_steps": 3,
            "created_at": (started - timedelta(seconds=4)).isoformat().replace("+00:00", "Z"),
            "name": "worker-probe",
            "ref": "r120-bounded/r120-bounded0/" + "c" * 25,
            "status": "Completed",
            "total_steps": 5,
        },
        {
            "cached_steps": 0,
            "completed_at": (started - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
            "completed_steps": 1,
            "created_at": (started - timedelta(seconds=6)).isoformat().replace("+00:00", "Z"),
            "name": "context-check",
            "ref": "r120-bounded/r120-bounded0/" + "d" * 25,
            "status": "Canceled",
            "total_steps": 2,
        },
    ]
    history_state = {"bytes": _encode_buildkit_history_jsonl(history)}
    capture_calls: list[tuple[list[str], int, float]] = []

    def capture(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
        capture_calls.append((argv, max_bytes, timeout))
        return history_state["bytes"]

    checked_calls: list[list[str]] = []

    def checked(argv: list[str], timeout: int = 30) -> bytes:
        checked_calls.append(argv)
        assert argv[:3] == [bounded.DOCKER, "image", "inspect"]
        assert argv[-1] == kept_image_id
        return f"{kept_image_id}|{kept_revision}".encode()

    monkeypatch.setattr(
        bounded,
        "setup_receipt",
        lambda: {"legacy_task_image_inventory": legacy_inventory},
    )
    monkeypatch.setattr(bounded, "_image_inventory", lambda: inventory.copy())
    monkeypatch.setattr(bounded, "checked", checked)
    monkeypatch.setattr(bounded, "_capture_bounded_stdout", capture)
    return {
        "tag": tag,
        "revision": revision,
        "context_hash": context_hash,
        "role": role,
        "failure_sha256": failure_sha256,
        "failure_path": failure_path,
        "failure_bytes": raw_failure_receipt,
        "ledger_path": ledger_path,
        "ledger_before": ledger_path.read_bytes(),
        "reservation": reservation,
        "kept_row": kept_row,
        "kept_receipt": kept_receipt_path,
        "inventory": inventory,
        "legacy_inventory": legacy_inventory,
        "history": history,
        "history_state": history_state,
        "history_ref": history_ref,
        "capture_calls": capture_calls,
        "checked_calls": checked_calls,
        "recovery_path": run_dir / f"failed-reservation-release-{failure_sha256}.json",
        "setup_sha256": hashlib.sha256(setup_bytes).hexdigest(),
    }


def _set_terminal_buildx_failure(state: dict[str, object]) -> dict[str, object]:
    failure_path = Path(state["failure_path"])
    receipt = json.loads(failure_path.read_bytes())
    build_finished = datetime.fromisoformat(receipt["finished_utc"])
    receipt["stage"] = "buildx_exit_nonzero"
    receipt["build_exit_code"] = 1
    receipt["build_finished_utc"] = build_finished.isoformat()
    receipt["finished_utc"] = (build_finished + timedelta(seconds=2)).isoformat()
    receipt.pop("process_group_cancel_verified")
    raw = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    failure_path.write_bytes(raw)
    failure_path.chmod(0o600)
    failure_sha256 = hashlib.sha256(raw).hexdigest()
    state["failure_sha256"] = failure_sha256
    state["failure_bytes"] = raw
    state["recovery_path"] = (
        failure_path.parent / f"failed-reservation-release-{failure_sha256}.json"
    )
    return receipt


def _rewrite_failed_receipt(state: dict[str, object], receipt: dict[str, object]) -> bytes:
    raw = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    failure_path = Path(state["failure_path"])
    failure_path.write_bytes(raw)
    failure_path.chmod(0o600)
    failure_sha256 = hashlib.sha256(raw).hexdigest()
    state["failure_sha256"] = failure_sha256
    state["failure_bytes"] = raw
    state["recovery_path"] = (
        failure_path.parent / f"failed-reservation-release-{failure_sha256}.json"
    )
    return raw


def test_failed_inflight_reservation_release_requires_terminal_history_and_preserves_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    before_inventory = dict(state["inventory"])
    before_ledger = Path(state["ledger_path"]).read_bytes()
    before_failure = Path(state["failure_path"]).read_bytes()

    result = bounded._release_failed_inflight_reservation(
        str(state["tag"]),
        str(state["revision"]),
        str(state["context_hash"]),
        str(state["role"]),
        str(state["failure_sha256"]),
    )

    ledger = json.loads(Path(state["ledger_path"]).read_bytes())
    assert result["status"] == "failed_build_reservation_released"
    assert ledger["entries"] == [state["kept_row"]]
    assert dict(state["inventory"]) == before_inventory
    assert Path(state["failure_path"]).read_bytes() == before_failure
    assert Path(state["recovery_path"]).is_file()
    recovery_raw = Path(state["recovery_path"]).read_bytes()
    assert hashlib.sha256(recovery_raw).hexdigest() == result["recovery_receipt_sha256"]
    recovery = json.loads(recovery_raw)
    assert recovery["status"] == "failed_build_reservation_released"
    assert recovery["failure_receipt_sha256"] == state["failure_sha256"]
    assert recovery["tag"] == state["tag"]
    assert recovery["revision"] == state["revision"]
    assert recovery["context_sha256"] == state["context_hash"]
    assert recovery["role"] == "current"
    assert recovery["buildkit_history"]["ref"] == state["history_ref"]
    assert recovery["buildkit_history"]["status"] == "error"
    assert result["recovery_receipt"] == str(state["recovery_path"])
    assert Path(state["ledger_path"]).read_bytes() != before_ledger
    assert len(state["capture_calls"]) == 1
    argv, max_bytes, timeout = state["capture_calls"][0]
    assert argv == [
        bounded.DOCKER,
        "buildx",
        "history",
        "ls",
        "--builder",
        bounded.BUILDER,
        "--no-trunc",
        "--format",
        "json",
    ]
    assert max_bytes == bounded.BUILDX_LISTING_MAX_BYTES
    assert timeout == bounded.BUILDX_LISTING_TIMEOUT
    assert state["checked_calls"] == [
        [
            bounded.DOCKER,
            "image",
            "inspect",
            "--format",
            '{{.Id}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
            state["kept_row"]["image_id"],
        ]
    ]


def test_failed_inflight_reservation_release_accepts_terminal_buildx_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    receipt = _set_terminal_buildx_failure(state)
    before_failure = Path(state["failure_path"]).read_bytes()
    before_inventory = dict(state["inventory"])

    result = bounded._release_failed_inflight_reservation(
        str(state["tag"]),
        str(state["revision"]),
        str(state["context_hash"]),
        str(state["role"]),
        str(state["failure_sha256"]),
    )

    assert receipt["stage"] == "buildx_exit_nonzero"
    assert receipt["build_exit_code"] == 1
    assert result["status"] == "failed_build_reservation_released"
    assert json.loads(Path(state["ledger_path"]).read_bytes())["entries"] == [state["kept_row"]]
    assert dict(state["inventory"]) == before_inventory
    assert Path(state["failure_path"]).read_bytes() == before_failure
    recovery = json.loads(Path(state["recovery_path"]).read_bytes())
    assert recovery["status"] == "failed_build_reservation_released"
    assert recovery["failure_receipt_sha256"] == state["failure_sha256"]
    assert recovery["buildkit_history"]["status"] == "error"
    assert recovery["buildkit_history"]["completed_steps"] == 21
    assert recovery["buildkit_history"]["total_steps"] == 46
    assert len(state["capture_calls"]) == 1


@pytest.mark.parametrize(
    "invalid_case",
    (
        "exit_zero",
        "exit_bool",
        "exit_string",
        "unknown_stage",
        "missing_build_finished",
        "build_finished_before_start",
        "receipt_finished_before_build_finished",
        "cancel_marker_present",
        "self_reported_built",
        "image_id_present",
        "history_without_error",
        "history_still_active",
    ),
)
def test_failed_inflight_terminal_buildx_receipt_requires_exact_failed_terminal_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_case: str,
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    receipt = _set_terminal_buildx_failure(state)
    if invalid_case == "exit_zero":
        receipt["build_exit_code"] = 0
    elif invalid_case == "exit_bool":
        receipt["build_exit_code"] = True
    elif invalid_case == "exit_string":
        receipt["build_exit_code"] = "1"
    elif invalid_case == "unknown_stage":
        receipt["stage"] = "buildx_exit_unverified"
    elif invalid_case == "missing_build_finished":
        receipt.pop("build_finished_utc")
    elif invalid_case == "build_finished_before_start":
        receipt["build_finished_utc"] = (
            datetime.fromisoformat(receipt["build_started_utc"]) - timedelta(seconds=1)
        ).isoformat()
    elif invalid_case == "receipt_finished_before_build_finished":
        receipt["finished_utc"] = (
            datetime.fromisoformat(receipt["build_finished_utc"]) - timedelta(seconds=1)
        ).isoformat()
    elif invalid_case == "cancel_marker_present":
        receipt["process_group_cancel_verified"] = True
    elif invalid_case == "self_reported_built":
        receipt["status"] = "built"
    elif invalid_case == "image_id_present":
        receipt["image_id"] = "sha256:" + "a" * 64
    elif invalid_case == "history_without_error":
        state["history"][0]["status"] = "Completed"
        state["history_state"]["bytes"] = _encode_buildkit_history_jsonl(state["history"])
    elif invalid_case == "history_still_active":
        state["history"][1]["status"] = "Running"
        state["history_state"]["bytes"] = _encode_buildkit_history_jsonl(state["history"])

    _rewrite_failed_receipt(state, receipt)
    ledger_path = Path(state["ledger_path"])
    before_ledger = ledger_path.read_bytes()
    before_failure = Path(state["failure_path"]).read_bytes()
    before_inventory = dict(state["inventory"])

    with pytest.raises(bounded.BuildError):
        bounded._release_failed_inflight_reservation(
            str(state["tag"]),
            str(state["revision"]),
            str(state["context_hash"]),
            str(state["role"]),
            str(state["failure_sha256"]),
        )

    assert ledger_path.read_bytes() == before_ledger
    assert Path(state["failure_path"]).read_bytes() == before_failure
    assert dict(state["inventory"]) == before_inventory
    assert state["checked_calls"] == []
    assert not Path(state["recovery_path"]).exists()
    if invalid_case in {"history_without_error", "history_still_active"}:
        assert len(state["capture_calls"]) == 1
    else:
        assert state["capture_calls"] == []


@pytest.mark.parametrize("failure_point", ("write", "chmod", "publish"))
def test_failed_inflight_release_write_failure_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    ledger_path = Path(state["ledger_path"])
    failure_path = Path(state["failure_path"])
    recovery_path = Path(state["recovery_path"])
    before_ledger = ledger_path.read_bytes()
    before_failure = failure_path.read_bytes()
    before_inventory = dict(state["inventory"])
    triggered = False

    if failure_point == "write":
        original_write = os.write
        calls = 0

        def fail_after_partial_write(fd: int, data: bytes | memoryview) -> int:
            nonlocal calls, triggered
            calls += 1
            if calls == 1:
                written = original_write(fd, data[:45])
                triggered = True
                return written
            if calls == 2:
                raise OSError("injected receipt write failure")
            return original_write(fd, data)

        monkeypatch.setattr(bounded.os, "write", fail_after_partial_write)
    elif failure_point == "chmod":
        original_fchmod = os.fchmod

        def fail_chmod(fd: int, mode: int) -> None:
            nonlocal triggered
            triggered = True
            raise OSError("injected receipt chmod failure")

        monkeypatch.setattr(bounded.os, "fchmod", fail_chmod)
    else:
        original_link = os.link

        def fail_publish(*args: object, **kwargs: object) -> None:
            nonlocal triggered
            triggered = True
            raise OSError("injected atomic publication failure")

        monkeypatch.setattr(bounded.os, "link", fail_publish)

    with pytest.raises(
        bounded.BuildError, match="failed_reservation_recovery_receipt_write_failed"
    ):
        bounded._release_failed_inflight_reservation(
            str(state["tag"]),
            str(state["revision"]),
            str(state["context_hash"]),
            str(state["role"]),
            str(state["failure_sha256"]),
        )

    assert triggered
    if failure_point == "publish":
        assert json.loads(ledger_path.read_bytes()) == json.loads(before_ledger)
    else:
        assert ledger_path.read_bytes() == before_ledger
    assert dict(state["inventory"]) == before_inventory
    assert failure_path.read_bytes() == before_failure
    assert not recovery_path.exists()
    assert list(recovery_path.parent.glob(f".{recovery_path.name}.*.tmp")) == []

    if failure_point == "write":
        monkeypatch.setattr(bounded.os, "write", original_write)
    elif failure_point == "chmod":
        monkeypatch.setattr(bounded.os, "fchmod", original_fchmod)
    else:
        monkeypatch.setattr(bounded.os, "link", original_link)

    result = bounded._release_failed_inflight_reservation(
        str(state["tag"]),
        str(state["revision"]),
        str(state["context_hash"]),
        str(state["role"]),
        str(state["failure_sha256"]),
    )

    assert result["status"] == "failed_build_reservation_released"
    assert json.loads(ledger_path.read_bytes())["entries"] == [state["kept_row"]]
    assert dict(state["inventory"]) == before_inventory
    assert failure_path.read_bytes() == before_failure
    assert recovery_path.is_file()
    assert list(recovery_path.parent.glob(f".{recovery_path.name}.*.tmp")) == []


@pytest.mark.parametrize(
    ("binding", "replacement"),
    (
        ("tag", "stock-probs:pr-candidate-ae140dd011ee-111111111111"),
        ("revision", "f" * 40),
        ("context_hash", "e" * 64),
        ("role", "recovery"),
        ("failure_sha256", "0" * 64),
    ),
)
def test_failed_inflight_reservation_mismatched_binding_precedes_docker_or_ledger_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding: str,
    replacement: str,
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    ledger_path = Path(state["ledger_path"])
    before_ledger = ledger_path.read_bytes()
    args = {
        "tag": str(state["tag"]),
        "revision": str(state["revision"]),
        "context_hash": str(state["context_hash"]),
        "role": str(state["role"]),
        "failure_receipt_sha256": str(state["failure_sha256"]),
    }
    if binding == "failure_sha256":
        args["failure_receipt_sha256"] = replacement
    else:
        args[binding] = replacement

    with pytest.raises(bounded.BuildError):
        bounded._release_failed_inflight_reservation(**args)

    assert ledger_path.read_bytes() == before_ledger
    assert state["capture_calls"] == []
    assert state["checked_calls"] == []
    assert dict(state["inventory"]) == {
        state["kept_row"]["tag"]: state["kept_row"]["image_id"],
        **state["legacy_inventory"],
    }
    assert not Path(state["recovery_path"]).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("stage", "buildx_exit_nonzero"),
        ("process_group_cancel_verified", False),
        ("ledger_reservation_retained", False),
        ("setup_receipt_sha256", "0" * 64),
        ("image_id", "sha256:" + "a" * 64),
    ),
)
def test_failed_inflight_receipt_contract_mismatch_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    receipt_path = Path(state["failure_path"])
    receipt = json.loads(receipt_path.read_bytes())
    receipt[field] = value
    raw = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    receipt_path.write_bytes(raw)
    before_ledger = Path(state["ledger_path"]).read_bytes()

    with pytest.raises(bounded.BuildError):
        bounded._release_failed_inflight_reservation(
            str(state["tag"]),
            str(state["revision"]),
            str(state["context_hash"]),
            str(state["role"]),
            hashlib.sha256(raw).hexdigest(),
        )

    assert Path(state["ledger_path"]).read_bytes() == before_ledger
    assert state["capture_calls"] == []
    assert state["checked_calls"] == []
    assert dict(state["inventory"]) == {
        state["kept_row"]["tag"]: state["kept_row"]["image_id"],
        **state["legacy_inventory"],
    }
    assert not Path(state["recovery_path"]).exists()


@pytest.mark.parametrize(
    ("history_change", "expected_error"),
    (
        ("duplicate", "failed_reservation_buildkit_record_not_unique_error"),
        ("active", "failed_reservation_buildkit_history_invalid"),
        ("wrong_name", "failed_reservation_buildkit_record_not_unique_error"),
        ("wrong_status", "failed_reservation_buildkit_record_not_unique_error"),
        ("invalid_ref", "failed_reservation_buildkit_history_invalid"),
        ("invalid_counter", "failed_reservation_buildkit_history_invalid"),
        ("blank_line", "failed_reservation_buildkit_history_invalid"),
        ("array_envelope", "failed_reservation_buildkit_history_invalid"),
        ("duplicate_key", "failed_reservation_buildkit_history_invalid"),
        ("trailing_text", "failed_reservation_buildkit_history_invalid"),
    ),
)
def test_failed_inflight_history_must_have_one_bounded_terminal_error_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    history_change: str,
    expected_error: str,
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    history = [json.loads(line) for line in state["history_state"]["bytes"].splitlines()]
    if history_change == "duplicate":
        duplicate = dict(history[0])
        duplicate["ref"] = "r120-bounded/r120-bounded0/" + "e" * 25
        history.append(duplicate)
    elif history_change == "active":
        history[1]["status"] = "running"
    elif history_change == "wrong_name":
        history[0]["name"] = "other"
    elif history_change == "wrong_status":
        history[0]["status"] = "Completed"
    elif history_change == "invalid_ref":
        history[0]["ref"] = "other-builder/node0/" + "a" * 25
    elif history_change == "invalid_counter":
        history[0]["total_steps"] = bounded.BUILDX_HISTORY_STEP_LIMIT + 1
    if history_change in {
        "duplicate",
        "active",
        "wrong_name",
        "wrong_status",
        "invalid_ref",
        "invalid_counter",
    }:
        state["history_state"]["bytes"] = _encode_buildkit_history_jsonl(history)
    elif history_change == "blank_line":
        state["history_state"]["bytes"] += b"\n"
    elif history_change == "array_envelope":
        state["history_state"]["bytes"] = json.dumps(history).encode() + b"\n"
    elif history_change == "duplicate_key":
        first_line = state["history_state"]["bytes"].splitlines()[0]
        state["history_state"]["bytes"] = first_line[:-1] + b',"status":"Error"}\n'
    elif history_change == "trailing_text":
        state["history_state"]["bytes"] += b"unparsed\n"
    ledger_path = Path(state["ledger_path"])
    before_ledger = ledger_path.read_bytes()

    with pytest.raises(bounded.BuildError, match=expected_error):
        bounded._release_failed_inflight_reservation(
            str(state["tag"]),
            str(state["revision"]),
            str(state["context_hash"]),
            str(state["role"]),
            str(state["failure_sha256"]),
        )

    assert ledger_path.read_bytes() == before_ledger
    assert state["checked_calls"] == []
    assert not Path(state["recovery_path"]).exists()


def test_failed_inflight_reservation_requires_absent_iidfile_and_task_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    ledger_path = Path(state["ledger_path"])
    before_ledger = ledger_path.read_bytes()
    run_dir = Path(state["failure_path"]).parent
    iidfile = run_dir / "image.iid"
    iidfile.write_text("sha256:" + "a" * 64, encoding="ascii")

    with pytest.raises(bounded.BuildError, match="artifact_or_time_invalid"):
        bounded._release_failed_inflight_reservation(
            str(state["tag"]),
            str(state["revision"]),
            str(state["context_hash"]),
            str(state["role"]),
            str(state["failure_sha256"]),
        )
    assert state["capture_calls"] == []
    assert ledger_path.read_bytes() == before_ledger

    iidfile.unlink()
    tag_image = "sha256:" + "a" * 64
    state["inventory"][str(state["tag"])] = tag_image
    with pytest.raises(bounded.BuildError, match="candidate_tag_still_present"):
        bounded._release_failed_inflight_reservation(
            str(state["tag"]),
            str(state["revision"]),
            str(state["context_hash"]),
            str(state["role"]),
            str(state["failure_sha256"]),
        )
    assert ledger_path.read_bytes() == before_ledger
    assert state["inventory"][str(state["tag"])] == tag_image
    assert not Path(state["recovery_path"]).exists()


def test_failed_inflight_release_cli_requires_fixed_identity_and_passes_only_bindings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tag = "stock-probs:pr-candidate-aaaaaaaaaaaa-bbbbbbbbbbbb"
    revision = "a" * 40
    context_hash = "c" * 64
    failure_sha256 = "d" * 64
    result = {"status": "failed_build_reservation_released", "tag": tag}
    calls: list[tuple[str, str, str, str, str]] = []

    def release(
        received_tag: str,
        received_revision: str,
        received_context_hash: str,
        received_role: str,
        received_failure_sha256: str,
    ) -> dict[str, object]:
        calls.append(
            (
                received_tag,
                received_revision,
                received_context_hash,
                received_role,
                received_failure_sha256,
            )
        )
        return result

    monkeypatch.setattr(bounded.os, "geteuid", lambda: bounded.USER.pw_uid)
    monkeypatch.setattr(bounded, "validate_user_state", lambda: None)
    monkeypatch.setattr(bounded.os, "access", lambda *_args: True)
    monkeypatch.setattr(bounded, "_release_failed_inflight_reservation", release)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bounded_docker_build.py",
            "--release-failed-inflight-reservation",
            "--failure-receipt-sha256",
            failure_sha256,
            "--tag",
            tag,
            "--revision",
            revision,
            "--context-sha256",
            context_hash,
            "--role",
            "current",
        ],
    )

    assert bounded.main() == 0
    assert json.loads(capsys.readouterr().out) == result
    assert calls == [(tag, revision, context_hash, "current", failure_sha256)]

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bounded_docker_build.py",
            "--release-failed-inflight-reservation",
            "--failure-receipt-sha256",
            failure_sha256,
            "--tag",
            tag,
        ],
    )
    with pytest.raises(SystemExit):
        bounded.main()
    assert "requires only its receipt SHA and bound identity" in capsys.readouterr().err

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bounded_docker_build.py",
            "--release-failed-inflight-reservation",
            "--failure-receipt-sha256",
            failure_sha256,
            "--tag",
            tag,
            "--revision",
            revision,
            "--context-sha256",
            context_hash,
            "--role",
            "current",
            "--retire-schema13-rehearsal-tag",
            "stock-probs:schema13-recovery-012345abcdef",
            "--retire-schema13-rehearsal-image-id",
            "sha256:" + "e" * 64,
        ],
    )
    with pytest.raises(SystemExit):
        bounded.main()
    assert "requires only its receipt SHA and bound identity" in capsys.readouterr().err
    assert calls == [(tag, revision, context_hash, "current", failure_sha256)]


def test_bounded_buildx_command_uses_only_supported_fixed_flags(tmp_path: Path) -> None:
    command = bounded._buildx_argv(
        "stock-probs:pr-candidate-aaaaaaaaaaaa-bbbbbbbbbbbb",
        "a" * 40,
        tmp_path / "context",
        tmp_path / "image.iid",
    )

    assert command[:5] == [
        bounded.DOCKER,
        "buildx",
        "build",
        "--builder",
        bounded.BUILDER,
    ]
    assert "--load" in command
    assert "--platform=linux/amd64" in command
    assert "--resource" not in command
    assert command[-1] == str(tmp_path / "context")


def test_local_buildx_command_uses_fixed_builder_load_and_native_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bounded.platform, "machine", lambda: "aarch64")
    command = bounded._local_buildx_argv(
        "stock-probs:local-" + "a" * 12 + "-" + "b" * 12 + "-" + "c" * 12,
        "a" * 40,
        bounded._native_platform(),
        tmp_path / "context",
        tmp_path / "image.iid",
    )

    assert command[:5] == [
        bounded.DOCKER,
        "buildx",
        "build",
        "--builder",
        bounded.BUILDER,
    ]
    assert "--platform=linux/arm64" in command
    assert "--load" in command
    assert "--resource" not in command
    assert command[command.index("--tag") + 1].startswith("stock-probs:local-")


def test_build_mount_monitor_checks_only_the_bound_mount_uuid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_uuid = "12345678-1234-1234-1234-123456789abc"
    calls: list[tuple[list[str], float]] = []

    def checked(argv: list[str], timeout: float = 30) -> bytes:
        calls.append((argv, timeout))
        return (expected_uuid + "\n").encode()

    monkeypatch.setattr(bounded, "checked", checked)

    bounded.verify_build_mount(
        expected_uuid,
        str(tmp_path.resolve()),
        deadline=time.monotonic() + 10,
    )

    assert calls == [
        (
            [bounded.FINDMNT, "-n", "-o", "UUID", "--target", str(tmp_path.resolve())],
            pytest.approx(10, abs=0.1),
        )
    ]


def test_build_mount_monitor_rejects_path_or_uuid_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_uuid = "12345678-1234-1234-1234-123456789abc"
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(bounded.BuildError, match="build_mount_path_changed"):
        bounded.verify_build_mount(
            expected_uuid,
            str(alias),
            deadline=time.monotonic() + 10,
        )

    monkeypatch.setattr(bounded, "checked", lambda *_args, **_kwargs: b"different-uuid\n")
    with pytest.raises(bounded.BuildError, match="build_mount_uuid_mismatch"):
        bounded.verify_build_mount(
            expected_uuid,
            str(tmp_path.resolve()),
            deadline=time.monotonic() + 10,
        )


def test_build_mount_monitor_reports_lookup_failure_without_command_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_lookup(*_args: object, **_kwargs: object) -> bytes:
        raise bounded.BuildError("fixed_command_unavailable_or_timeout")

    monkeypatch.setattr(bounded, "checked", failed_lookup)

    with pytest.raises(bounded.BuildError, match="build_mount_lookup_failed"):
        bounded.verify_build_mount(
            "12345678-1234-1234-1234-123456789abc",
            str(tmp_path.resolve()),
            deadline=time.monotonic() + 10,
        )


def test_arm64_compose_command_selects_only_the_bounded_builder_and_fixed_services(
    tmp_path: Path,
) -> None:
    command = bounded._arm64_compose_argv(
        "stock-probs-r-astra-120-arm64-1000", tmp_path / "compose.yml"
    )

    assert command[0:3] == [bounded.DOCKER, "compose", "--project-directory"]
    assert command[command.index("build") + 1 :] == [
        "--builder",
        bounded.BUILDER,
        "--pull",
        "arm64-frontend-builder",
        "arm64-app",
    ]
    assert "--memory" not in command
    assert "--resource" not in command


def test_arm64_compose_context_rewrite_is_fixed_and_fail_closed(tmp_path: Path) -> None:
    source = (
        "services:\n  app:\n    build:\n      context: ..\n  web:\n    build:\n      context: ..\n"
    )
    rendered = bounded._render_arm64_compose(source, tmp_path / "context")

    assert rendered.count(f'context: "{tmp_path / "context"}"') == 2
    assert "context: .." not in rendered
    with pytest.raises(bounded.BuildError, match="arm64_compose_build_context_shape_invalid"):
        bounded._render_arm64_compose(
            "services:\n  app:\n    build:\n      context: ..\n", tmp_path
        )
    with pytest.raises(bounded.BuildError, match="arm64_build_context_path_invalid"):
        bounded._render_arm64_compose(source, tmp_path / 'context"bad')


def test_bounded_compose_build_rejects_success_observed_after_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeClock:
        now = 0.0

        def monotonic(self) -> float:
            return self.now

    clock = FakeClock()

    class LateProcess:
        pid = 501

        def poll(self) -> int:
            clock.now = 2.0
            return 0

    monkeypatch.setattr(bounded.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(bounded.subprocess, "Popen", lambda *_args, **_kwargs: LateProcess())

    def no_process_group(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(bounded.os, "killpg", no_process_group)

    with pytest.raises(bounded.BuildError, match="bounded_build_timeout"):
        bounded._run_bounded_build(
            ["/usr/bin/docker", "compose", "build"],
            expected_uuid="00000000-0000-0000-0000-000000000000",
            docker_root=tmp_path,
            space_paths=(tmp_path,),
            env={},
            timeout=1,
        )


def test_bounded_build_monitors_mount_and_checks_docker_root_after_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class BuildProcess:
        pid = 502

        def __init__(self) -> None:
            self.poll_count = 0

        def poll(self) -> int | None:
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

    process = BuildProcess()
    events: list[str] = []

    def no_process_group(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    def mount_check(
        _uuid: str,
        _path: str,
        *,
        deadline: float,
    ) -> None:
        assert deadline > time.monotonic()
        events.append("mount")

    def docker_root_check(
        _uuid: str,
        _path: str,
        *,
        deadline: float | None = None,
    ) -> tuple[Path, int]:
        assert process.poll_count >= 2
        assert deadline is not None and deadline > time.monotonic()
        events.append("docker-root")
        return tmp_path, bounded.MIN_FREE

    monkeypatch.setattr(bounded.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(bounded.os, "killpg", no_process_group)
    monkeypatch.setattr(bounded, "verify_build_mount", mount_check)
    monkeypatch.setattr(bounded, "data_root", docker_root_check)
    monkeypatch.setattr(bounded, "check_space", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(bounded.time, "sleep", lambda _seconds: None)

    bounded._run_bounded_build(
        [bounded.DOCKER, "buildx", "build"],
        expected_uuid="12345678-1234-1234-1234-123456789abc",
        docker_root=tmp_path,
        space_paths=(tmp_path,),
        env={},
        timeout=10,
    )

    assert events == ["mount", "docker-root"]


def test_bounded_build_rejects_success_when_post_build_docker_root_check_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class CompleteProcess:
        pid = 503

        def poll(self) -> int:
            return 0

    def no_process_group(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    def docker_root_failure(*_args: object, **_kwargs: object) -> tuple[Path, int]:
        raise bounded.BuildError("docker_root_path_changed")

    monkeypatch.setattr(bounded.subprocess, "Popen", lambda *_args, **_kwargs: CompleteProcess())
    monkeypatch.setattr(bounded.os, "killpg", no_process_group)
    monkeypatch.setattr(bounded, "data_root", docker_root_failure)

    with pytest.raises(bounded.BuildError, match="bounded_build_post_root_identity_failed"):
        bounded._run_bounded_build(
            [bounded.DOCKER, "buildx", "build"],
            expected_uuid="12345678-1234-1234-1234-123456789abc",
            docker_root=tmp_path,
            space_paths=(tmp_path,),
            env={},
            timeout=10,
        )


def test_build_filesystem_floor_rejects_below_threshold_and_accepts_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    free = {"bytes": bounded.MIN_FREE - 1}
    monkeypatch.setattr(
        bounded.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=free["bytes"]),
    )
    with pytest.raises(bounded.BuildError, match="build_disk_floor_breached"):
        bounded.check_space((tmp_path,), bounded.MIN_FREE)

    free["bytes"] = bounded.MIN_FREE
    assert bounded.check_space((tmp_path,), bounded.MIN_FREE) == {str(tmp_path): bounded.MIN_FREE}

    free["bytes"] = bounded.STOP_FREE - 1
    with pytest.raises(bounded.BuildError, match="build_disk_floor_breached"):
        bounded.check_space((tmp_path,), bounded.STOP_FREE)


def test_build_cancel_stops_owned_process_group_and_verifies_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExitedProcess:
        pid = 42001
        waited: list[int] = []

        def wait(self, *, timeout: int) -> int:
            self.waited.append(timeout)
            return 0

    process = ExitedProcess()
    calls: list[tuple[int, int]] = []

    def killpg(pid: int, sig: int) -> None:
        calls.append((pid, sig))
        if sig == 0:
            raise ProcessLookupError()

    monkeypatch.setattr(bounded.os, "killpg", killpg)
    assert bounded.cancel(process) is True
    assert calls == [(42001, signal.SIGINT), (42001, 0)]
    assert process.waited == [5, 2]


def _worker_step_proof() -> dict[str, object]:
    return {
        "schema": "r120-buildkit-run-cgroup-v1",
        "status": "passed",
        "memory_max_bytes": bounded.MEMORY,
        "cpu_quota": bounded.CPU_QUOTA,
        "cpu_period": bounded.CPU_PERIOD,
        "network_none": True,
        "worker_cgroup_descendant": True,
        "controller_cgroup_scope_verified": True,
        "probe_image_id": "sha256:" + "a" * 64,
        "probe_sha256": "b" * 64,
        "probe_output_sha256": bounded.PROBE_MARKER_SHA256,
        "worker_cgroup_path_sha256": "c" * 64,
        "controller_cgroup_path_sha256": "d" * 64,
        "controller_process_cgroup_path_sha256": "e" * 64,
        "builder_network": {
            "name": bounded.BUILDER_NETWORK,
            "id": "f" * 64,
            "driver": "bridge",
            "scope": "local",
            "enable_ipv6": False,
            "internal": False,
            "owner_label": {
                bounded.BUILDER_NETWORK_OWNER_LABEL: bounded.BUILDER_NETWORK_OWNER_VALUE
            },
        },
        "builder_container_networks": {bounded.BUILDER_NETWORK: "f" * 64},
    }


def test_worker_step_cgroup_proof_accepts_only_verified_bounded_run() -> None:
    assert bounded._worker_step_proof_valid(_worker_step_proof())

    for field, invalid in (
        ("worker_cgroup_descendant", False),
        ("memory_max_bytes", bounded.MEMORY + 1),
        ("cpu_quota", bounded.CPU_QUOTA + 1),
        ("network_none", False),
        ("probe_output_sha256", "0" * 64),
        ("worker_cgroup_path_sha256", "bad"),
        ("controller_cgroup_scope_verified", False),
        ("controller_cgroup_path_sha256", "bad"),
        ("controller_process_cgroup_path_sha256", "bad"),
    ):
        proof = _worker_step_proof()
        proof[field] = invalid
        assert not bounded._worker_step_proof_valid(proof), field

    for field in (
        "controller_cgroup_scope_verified",
        "controller_process_cgroup_path_sha256",
    ):
        proof = _worker_step_proof()
        proof.pop(field)
        assert not bounded._worker_step_proof_valid(proof), field

    assert not bounded._worker_step_proof_valid(None)


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("name", "foreign-network"),
        ("id", "short-id"),
        ("driver", "host"),
        ("scope", "swarm"),
        ("enable_ipv6", True),
        ("internal", True),
        ("owner_label", {bounded.BUILDER_NETWORK_OWNER_LABEL: "foreign"}),
        ("unexpected", "value"),
    ],
)
def test_worker_step_proof_rejects_invalid_builder_network(field: str, invalid: object) -> None:
    proof = _worker_step_proof()
    network = proof["builder_network"]
    assert isinstance(network, dict)
    network[field] = invalid
    assert not bounded._worker_step_proof_valid(proof)


def test_worker_step_proof_rejects_extra_or_mismatched_builder_attachments() -> None:
    proof = _worker_step_proof()
    proof["builder_container_networks"] = {
        bounded.BUILDER_NETWORK: "f" * 64,
        "foreign-network": "a" * 64,
    }
    assert not bounded._worker_step_proof_valid(proof)

    proof = _worker_step_proof()
    proof["builder_container_networks"] = {bounded.BUILDER_NETWORK: "a" * 64}
    assert not bounded._worker_step_proof_valid(proof)

    proof = _worker_step_proof()
    proof.pop("builder_network")
    assert not bounded._worker_step_proof_valid(proof)


@pytest.mark.parametrize("network_mode", ["bridge", bounded.BUILDER_NETWORK])
def test_builder_network_validation_checks_exact_attachment_and_live_identity(
    monkeypatch: pytest.MonkeyPatch, network_mode: str
) -> None:
    proof = _worker_step_proof()
    network_id = "f" * 64
    container_id = "a" * 64
    calls: list[list[str]] = []

    def fake_checked(argv: list[str], timeout: int = 30) -> bytes:
        calls.append(argv)
        if argv[:3] == [bounded.DOCKER, "container", "inspect"]:
            return f"{network_mode}|empty\n{bounded.BUILDER_NETWORK}|{network_id}\n".encode()
        if argv[:3] == [bounded.DOCKER, "network", "inspect"]:
            return (
                f"{bounded.BUILDER_NETWORK}|{network_id}|bridge|local|false|false|"
                f'{{"{bounded.BUILDER_NETWORK_OWNER_LABEL}":"{bounded.BUILDER_NETWORK_OWNER_VALUE}"}}\n'
            ).encode()
        raise AssertionError("unexpected fixed command")

    monkeypatch.setattr(bounded, "checked", fake_checked)
    bounded.verify_builder_network({"worker_step_cgroup_proof": proof}, container_id)

    assert calls == [
        [
            bounded.DOCKER,
            "container",
            "inspect",
            "--format",
            "{{.HostConfig.NetworkMode}}|"
            '{{if .HostConfig.PortBindings}}present{{else}}empty{{end}}{{"\\n"}}'
            "{{range $name, $network := .NetworkSettings.Networks}}"
            '{{$name}}|{{$network.NetworkID}}{{"\\n"}}{{end}}',
            container_id,
        ],
        [
            bounded.DOCKER,
            "network",
            "inspect",
            "--format",
            "{{.Name}}|{{.Id}}|{{.Driver}}|{{.Scope}}|{{.EnableIPv6}}|"
            "{{.Internal}}|{{json .Labels}}",
            bounded.BUILDER_NETWORK,
        ],
    ]


@pytest.mark.parametrize(
    "attachment_output",
    [
        b"bridge|empty\nforeign-network|" + b"f" * 64 + b"\n",
        b"bridge|empty\nr120-bounded-build|" + b"f" * 64 + b"\nother|" + b"a" * 64 + b"\n",
        b"bridge|empty\nr120-bounded-build|" + b"a" * 64 + b"\n",
        b"bridge|present\nr120-bounded-build|" + b"f" * 64 + b"\n",
        b"host|empty\nr120-bounded-build|" + b"f" * 64 + b"\n",
        b"malformed\n",
    ],
)
def test_builder_network_validation_rejects_foreign_or_unsafe_attachments(
    monkeypatch: pytest.MonkeyPatch, attachment_output: bytes
) -> None:
    proof = _worker_step_proof()

    def fake_checked(argv: list[str], timeout: int = 30) -> bytes:
        assert argv[:3] == [bounded.DOCKER, "container", "inspect"]
        return attachment_output

    monkeypatch.setattr(bounded, "checked", fake_checked)
    with pytest.raises(bounded.BuildError, match="builder_network_attachment_mismatch"):
        bounded.verify_builder_network({"worker_step_cgroup_proof": proof}, "a" * 64)


@pytest.mark.parametrize(
    "network_output",
    [
        b"foreign-name|"
        + b"f" * 64
        + b'|bridge|local|false|false|{"io.signal-ledger.r120-bounded-builder":"r120-bounded"}\n',
        b"r120-bounded-build|"
        + b"a" * 64
        + b'|bridge|local|false|false|{"io.signal-ledger.r120-bounded-builder":"r120-bounded"}\n',
        b"r120-bounded-build|"
        + b"f" * 64
        + b'|host|local|false|false|{"io.signal-ledger.r120-bounded-builder":"r120-bounded"}\n',
        b"r120-bounded-build|"
        + b"f" * 64
        + b'|bridge|swarm|false|false|{"io.signal-ledger.r120-bounded-builder":"r120-bounded"}\n',
        b"r120-bounded-build|"
        + b"f" * 64
        + b'|bridge|local|true|false|{"io.signal-ledger.r120-bounded-builder":"r120-bounded"}\n',
        b"r120-bounded-build|"
        + b"f" * 64
        + b'|bridge|local|false|true|{"io.signal-ledger.r120-bounded-builder":"r120-bounded"}\n',
        b"r120-bounded-build|" + b"f" * 64 + b"|bridge|local|false|false|{}\n",
        b"r120-bounded-build|"
        + b"f" * 64
        + b'|bridge|local|false|false|{"io.signal-ledger.r120-bounded-builder":"r120-bounded",'
        + b'"extra":"label"}\n',
    ],
)
def test_builder_network_validation_rejects_live_network_identity_changes(
    monkeypatch: pytest.MonkeyPatch, network_output: bytes
) -> None:
    proof = _worker_step_proof()

    def fake_checked(argv: list[str], timeout: int = 30) -> bytes:
        if argv[:3] == [bounded.DOCKER, "container", "inspect"]:
            return f"bridge|empty\n{bounded.BUILDER_NETWORK}|{'f' * 64}\n".encode()
        assert argv[:3] == [bounded.DOCKER, "network", "inspect"]
        return network_output

    monkeypatch.setattr(bounded, "checked", fake_checked)
    with pytest.raises(bounded.BuildError, match="builder_network_identity_mismatch"):
        bounded.verify_builder_network({"worker_step_cgroup_proof": proof}, "a" * 64)


@pytest.mark.parametrize(
    "labels",
    [
        b"not-json",
        b'{"io.signal-ledger.r120-bounded-builder":"r120-bounded",'
        b'"io.signal-ledger.r120-bounded-builder":"r120-bounded"}',
    ],
)
def test_builder_network_validation_rejects_malformed_or_duplicate_labels(
    monkeypatch: pytest.MonkeyPatch, labels: bytes
) -> None:
    proof = _worker_step_proof()

    def fake_checked(argv: list[str], timeout: int = 30) -> bytes:
        if argv[:3] == [bounded.DOCKER, "container", "inspect"]:
            return f"bridge|empty\n{bounded.BUILDER_NETWORK}|{'f' * 64}\n".encode()
        assert argv[:3] == [bounded.DOCKER, "network", "inspect"]
        return (
            f"{bounded.BUILDER_NETWORK}|{'f' * 64}|bridge|local|false|false|".encode()
            + labels
            + b"\n"
        )

    monkeypatch.setattr(bounded, "checked", fake_checked)
    with pytest.raises(bounded.BuildError, match="builder_network_inspection_invalid"):
        bounded.verify_builder_network({"worker_step_cgroup_proof": proof}, "a" * 64)


def test_inspect_builder_invokes_network_validation_before_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container_id = "a" * 64
    config_path = tmp_path / "buildkitd.toml"
    config_path.write_bytes(b"configuration")
    calls: list[str] = []

    def fake_checked(argv: list[str], timeout: int = 30) -> bytes:
        if argv == [bounded.DOCKER, "buildx", "version"]:
            return b"github.com/docker/buildx 0.30.1\n"
        if argv[:3] == [bounded.DOCKER, "container", "inspect"]:
            return (
                f"{container_id}|{bounded.CONTAINER_NAME}|sha256:{'b' * 64}|"
                f"{bounded.MEMORY}|{bounded.SWAP}|{bounded.CPU_QUOTA}|"
                f"{bounded.CPU_PERIOD}|{bounded.PIDS_LIMIT}|true"
            ).encode()
        if argv[:2] == [bounded.DOCKER, "exec"]:
            return b"active configuration"
        raise AssertionError("unexpected fixed command")

    monkeypatch.setattr(bounded, "checked", fake_checked)
    monkeypatch.setattr(bounded, "buildx_driver", lambda: "docker-container")
    monkeypatch.setattr(bounded, "CONFIG_FILE", config_path)
    monkeypatch.setattr(bounded, "verify_installed_config", lambda: "installed")
    monkeypatch.setattr(bounded, "verify_active_buildkit_config", lambda *_args: "c" * 64)
    monkeypatch.setattr(
        bounded,
        "verify_cache_volume",
        lambda *_args: calls.append("cache"),
    )
    monkeypatch.setattr(
        bounded,
        "verify_builder_network",
        lambda _data, observed_id: calls.append(f"network:{observed_id}"),
    )

    bounded.inspect_builder(
        {
            "builder_container_id": container_id,
            "buildkit_image_id": f"sha256:{'b' * 64}",
            "active_buildkit_config_sha256": "c" * 64,
        }
    )

    assert calls == [f"network:{container_id}", "cache"]


def test_retention_ledger_accepts_three_proven_roles_and_rejects_a_fourth() -> None:
    bounded._validate_ledger_document(
        {
            "schema": bounded.LEDGER_SCHEMA,
            "entries": [_entry(1), _entry(2, "recovery"), _entry(3, "recovery")],
        }
    )

    with pytest.raises(bounded.BuildError, match="limit_or_shape"):
        bounded._validate_ledger_document(
            {
                "schema": bounded.LEDGER_SCHEMA,
                "entries": [_entry(i) for i in range(1, 5)],
            }
        )


def test_retention_ledger_rejects_unresolved_or_duplicate_entries() -> None:
    pending = _entry(1)
    pending["status"] = "inflight"
    with pytest.raises(bounded.BuildError, match="unresolved_inflight"):
        bounded._validate_ledger_document({"schema": bounded.LEDGER_SCHEMA, "entries": [pending]})

    duplicate = _entry(1)
    duplicate["tag"] = _entry(2)["tag"]
    with pytest.raises(bounded.BuildError, match="entry_invalid"):
        bounded._validate_ledger_document(
            {"schema": bounded.LEDGER_SCHEMA, "entries": [_entry(1), duplicate]}
        )


def test_reservation_fills_only_the_third_slot_and_refuses_a_fourth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _test_ledger_paths(tmp_path, monkeypatch)
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(bounded, "_atomic_json", lambda _path, data: writes.append(data.copy()))
    ledger: dict[str, object] = {
        "schema": bounded.LEDGER_SCHEMA,
        "entries": [_entry(1), _entry(2)],
    }

    bounded._reserve(
        ledger,
        "stock-probs:schema13-recovery-aaaaaaaaaaaa",
        "schema13-recovery-" + "a" * 64,
        "b" * 64,
        "recovery",
    )
    assert len(writes) == 1
    assert len(ledger["entries"]) == 3  # type: ignore[arg-type]
    with pytest.raises(bounded.BuildError, match="retention_limit_reached"):
        bounded._reserve(
            ledger,
            "stock-probs:schema12-base-bbbbbbbbbbbb",
            "c" * 40,
            "d" * 64,
            "recovery",
        )
    assert len(writes) == 1


def test_concurrent_candidate_reservations_cannot_exceed_three_slots(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    ledger_path = state / "candidate-ledger.json"
    ledger = {"schema": bounded.LEDGER_SCHEMA, "entries": [_entry(1), _entry(2)]}
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    ledger_path.chmod(0o600)

    context = multiprocessing.get_context("fork")
    start_event = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_ledger_slot_worker,
            args=(str(state / "candidate-ledger.lock"), str(ledger_path), start_event, results),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    start_event.set()
    for worker in workers:
        worker.join(timeout=10)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=2)
            pytest.fail("ledger reservation worker did not exit")

    outcomes = sorted(results.get(timeout=2) for _ in workers)
    final_ledger = json.loads(ledger_path.read_bytes())
    assert outcomes.count("reserved") == 1
    rejected = next(outcome for outcome in outcomes if outcome != "reserved")
    assert rejected in {
        "candidate_retention_limit_reached",
        "candidate_ledger_unresolved_inflight",
    }
    assert len(final_ledger["entries"]) == 3
    assert all(worker.exitcode == 0 for worker in workers)


def test_candidate_ledger_lock_rejects_symlink_lock_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ledger_path = _test_ledger_paths(tmp_path, monkeypatch)
    target = state / "other"
    target.write_text("", encoding="utf-8")
    (state / "candidate-ledger.lock").symlink_to(target)

    with (
        pytest.raises(bounded.BuildError, match="candidate_ledger_lock_unavailable"),
        bounded._candidate_ledger_lock(),
    ):
        pytest.fail("symlink lock must not be opened")


@pytest.mark.parametrize(
    ("failure_kind", "expected_error"),
    (
        ("invalid_lock_file", "candidate_ledger_lock_file_invalid"),
        ("flock_error", "candidate_ledger_lock_unavailable"),
    ),
)
def test_candidate_ledger_lock_closes_descriptor_once_after_open_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_error: str,
) -> None:
    state, _ledger_path = _test_ledger_paths(tmp_path, monkeypatch)
    lock_path = state / "candidate-ledger.lock"
    if failure_kind == "invalid_lock_file":
        lock_path.write_text("", encoding="utf-8")
        lock_path.chmod(0o644)
    else:
        original_fcntl = bounded.fcntl

        def fail_exclusive_lock(_fd: int, _operation: int) -> None:
            raise OSError("synthetic flock failure")

        monkeypatch.setattr(
            bounded,
            "fcntl",
            SimpleNamespace(LOCK_EX=original_fcntl.LOCK_EX, flock=fail_exclusive_lock),
        )

    real_os = bounded.os
    sentinel = state / "descriptor-reuse-sentinel"
    closed_fds: list[int] = []
    reused_fds: list[int] = []

    def close_and_reuse(fd: int) -> None:
        closed_fds.append(fd)
        real_os.close(fd)
        if len(closed_fds) == 1:
            reopened = real_os.open(
                sentinel, real_os.O_CREAT | real_os.O_EXCL | real_os.O_RDWR, 0o600
            )
            if reopened != fd:
                real_os.close(reopened)
                raise AssertionError("the sentinel did not reuse the closed lock descriptor")
            reused_fds.append(reopened)

    monkeypatch.setattr(
        bounded,
        "os",
        SimpleNamespace(
            O_CREAT=real_os.O_CREAT,
            O_RDWR=real_os.O_RDWR,
            O_CLOEXEC=getattr(real_os, "O_CLOEXEC", 0),
            O_NOFOLLOW=getattr(real_os, "O_NOFOLLOW", 0),
            open=real_os.open,
            fstat=real_os.fstat,
            close=close_and_reuse,
        ),
    )

    with (
        pytest.raises(bounded.BuildError, match=expected_error),
        bounded._candidate_ledger_lock(),
    ):
        pytest.fail("the invalid lock must fail before entering the critical section")

    assert len(closed_fds) == 1
    assert len(reused_fds) == 1
    real_os.fstat(reused_fds[0])
    real_os.close(reused_fds[0])
    sentinel.unlink()


def test_arm_cleanup_plans_registered_full_ids_and_acknowledges_only_after_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tags, revision, image_ids, inventory = _arm_cleanup_fixture(tmp_path, monkeypatch)

    plan = bounded._plan_arm64_cleanup(tags, revision)
    assert plan["registered_image_ids"] == sorted(image_ids.values())
    assert plan["remove_image_ids"] == sorted(image_ids.values())

    with pytest.raises(bounded.BuildError, match="arm64_cleanup_image_still_present"):
        bounded._ack_arm64_cleanup(tags, revision, tuple(sorted(image_ids.values())))

    inventory.clear()
    result = bounded._ack_arm64_cleanup(tags, revision, tuple(sorted(image_ids.values())))
    assert result["status"] == "retired"
    assert result["removed_image_ids"] == sorted(image_ids.values())
    assert json.loads(bounded.LEDGER_FILE.read_bytes())["entries"] == []


def test_arm_cleanup_refuses_rebound_tag_and_container_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tags, revision, image_ids, inventory = _arm_cleanup_fixture(tmp_path, monkeypatch)
    inventory[tags[0]] = "sha256:" + "e" * 64

    with pytest.raises(bounded.BuildError, match="arm64_cleanup_tag_rebound"):
        bounded._plan_arm64_cleanup(tags, revision)

    inventory[tags[0]] = image_ids[tags[0]]
    monkeypatch.setattr(
        bounded, "_container_uses_image_id", lambda image_id: image_id == image_ids[tags[1]]
    )
    with pytest.raises(bounded.BuildError, match="arm64_cleanup_image_in_use"):
        bounded._plan_arm64_cleanup(tags, revision)


def test_schema13_rehearsal_retirement_removes_exact_id_and_frees_next_build_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)

    result = bounded._retire_schema13_rehearsal_tag(str(state["tag"]), str(state["image_id"]))

    assert result == {
        "status": "retired",
        "tag": state["tag"],
        "image_id": state["image_id"],
    }
    assert state["image_id"] not in state["image_ids"]
    assert state["inventory"] == {}
    assert json.loads(Path(state["ledger_path"]).read_bytes())["entries"] == []
    assert [
        command[:5]
        for command in state["calls"]
        if command[:4] == [bounded.DOCKER, "image", "rm", "--no-prune"]
    ] == [[bounded.DOCKER, "image", "rm", "--no-prune", state["image_id"]]]

    next_tag = "stock-probs:schema13-recovery-fedcba987654"
    next_ledger = bounded._reserve_managed_tags(
        {"legacy_task_image_inventory": {}},
        (next_tag,),
        "6" * 40,
        "7" * 64,
        "recovery",
    )
    assert len(next_ledger["entries"]) == 1
    assert next_ledger["entries"][0]["tag"] == next_tag


def test_managed_run_dir_creates_private_revision_and_leaf_with_permissive_umask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "build-runs"
    monkeypatch.setattr(bounded, "RUNS", runs)
    monkeypatch.setattr(bounded, "USER", SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(tmp_path)))
    revision = "a" * 40
    tag = f"stock-probs:pr-candidate-{revision[:12]}-bbbbbbbbbbbb"
    context_hash = "c" * 64
    previous_umask = os.umask(0o002)
    try:
        run_dir = bounded._managed_run_dir(revision, tag, context_hash)
    finally:
        os.umask(previous_umask)

    revision_dir = runs / revision
    assert (
        run_dir == revision_dir / hashlib.sha256((tag + "\0" + context_hash).encode()).hexdigest()
    )
    assert not runs.is_symlink()
    assert not revision_dir.is_symlink()
    assert not run_dir.is_symlink()
    assert runs.lstat().st_mode & 0o777 == 0o700
    assert revision_dir.lstat().st_mode & 0o777 == 0o700
    assert run_dir.lstat().st_mode & 0o777 == 0o700
    assert list(runs.iterdir()) == [revision_dir]
    assert list(revision_dir.iterdir()) == [run_dir]


def test_managed_run_dir_rejects_existing_unsafe_or_symlinked_revision_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "build-runs"
    runs.mkdir(mode=0o700)
    runs.chmod(0o700)
    monkeypatch.setattr(bounded, "RUNS", runs)
    monkeypatch.setattr(bounded, "USER", SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(tmp_path)))
    revision = "d" * 40
    tag = f"stock-probs:pr-candidate-{revision[:12]}-eeeeeeeeeeee"
    context_hash = "f" * 64
    run_key = hashlib.sha256((tag + "\0" + context_hash).encode()).hexdigest()
    revision_dir = runs / revision

    revision_dir.mkdir(mode=0o700)
    revision_dir.chmod(0o775)
    with pytest.raises(bounded.BuildError, match="build_receipt_directory_owner_or_mode_invalid"):
        bounded._managed_run_dir(revision, tag, context_hash)
    assert revision_dir.lstat().st_mode & 0o777 == 0o775
    assert not (revision_dir / run_key).exists()

    revision_dir.chmod(0o700)
    revision_dir.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    revision_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(bounded.BuildError, match="build_receipt_directory_owner_or_mode_invalid"):
        bounded._managed_run_dir(revision, tag, context_hash)
    assert revision_dir.is_symlink()
    assert list(outside.iterdir()) == []
    assert list(runs.iterdir()) == [revision_dir]


@pytest.mark.parametrize("image_is_present", [True, False])
def test_schema13_retirement_image_id_mismatch_precedes_docker_and_ledger_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_is_present: bool,
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)
    tag = str(state["tag"])
    ledger_path = Path(state["ledger_path"])
    expected_image_id = "sha256:" + "9" * 64
    before_ledger = ledger_path.read_bytes()
    if not image_is_present:
        state["inventory"].clear()
        state["image_ids"].remove(str(state["image_id"]))
    before_inventory = state["inventory"].copy()
    before_image_ids = state["image_ids"].copy()

    with pytest.raises(
        bounded.BuildError,
        match="schema13_rehearsal_expected_image_id_mismatch",
    ):
        bounded._retire_schema13_rehearsal_tag(tag, expected_image_id)

    assert state["calls"] == []
    assert state["inventory"] == before_inventory
    assert state["image_ids"] == before_image_ids
    assert ledger_path.read_bytes() == before_ledger


@pytest.mark.parametrize(
    "expected_image_id",
    ["1" * 64, "sha256:" + "A" * 64, "sha256:" + "1" * 63],
)
def test_schema13_retirement_rejects_noncanonical_expected_image_id_before_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expected_image_id: str,
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)
    ledger_path = Path(state["ledger_path"])
    before_ledger = ledger_path.read_bytes()
    before_inventory = state["inventory"].copy()
    before_image_ids = state["image_ids"].copy()

    with pytest.raises(
        bounded.BuildError,
        match="schema13_rehearsal_expected_image_id_invalid",
    ):
        bounded._retire_schema13_rehearsal_tag(str(state["tag"]), expected_image_id)

    assert state["calls"] == []
    assert state["inventory"] == before_inventory
    assert state["image_ids"] == before_image_ids
    assert ledger_path.read_bytes() == before_ledger


@pytest.mark.parametrize(
    ("case", "expected_error"),
    (
        ("current", "schema13_rehearsal_image_role_or_status_invalid"),
        ("transient", "schema13_rehearsal_image_role_or_status_invalid"),
        ("protected", "schema13_rehearsal_protected_image"),
        ("unregistered", "schema13_rehearsal_image_unregistered"),
        ("shared_tag", "schema13_rehearsal_image_identity_mismatch"),
        ("container", "schema13_rehearsal_image_in_use"),
        ("child", "schema13_rehearsal_image_has_child"),
        ("deep_child", "schema13_rehearsal_image_has_child"),
        ("same_rootfs", "schema13_rehearsal_image_rootfs_ancestry_ambiguous"),
        ("docker_failure", "schema13_rehearsal_image_remove_failed"),
        ("receipt_mismatch", "candidate_ledger_build_receipt_mismatch"),
    ),
)
def test_schema13_rehearsal_retirement_fails_closed_and_retains_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_error: str,
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(
        tmp_path,
        monkeypatch,
        role=case if case in {"current", "transient"} else "recovery",
    )
    tag = str(state["tag"])
    image_id = str(state["image_id"])
    row = state["row"]
    assert isinstance(row, dict)
    if case == "protected":
        monkeypatch.setattr(
            bounded,
            "setup_receipt",
            lambda: {"legacy_task_image_inventory": {tag: image_id}},
        )
    elif case == "unregistered":
        tag = "stock-probs:schema13-recovery-ffffffffffff"
    elif case == "shared_tag":
        state["repo_tags"][image_id] = [tag, "private-registry.example/kept:stable"]
    elif case == "container":
        state["references"].add(image_id)
    elif case == "child":
        child_id = "sha256:" + "8" * 64
        state["image_ids"].add(child_id)
        state["rootfs_layers_by_id"][child_id] = state["rootfs_layers_by_id"][image_id] + [
            "sha256:" + "9" * 64
        ]
        state["repo_tags"][child_id] = []
    elif case == "deep_child":
        child_id = "sha256:" + "8" * 64
        state["image_ids"].add(child_id)
        state["rootfs_layers_by_id"][child_id] = state["rootfs_layers_by_id"][image_id] + [
            "sha256:" + "9" * 64,
            "sha256:" + "c" * 64,
        ]
        state["repo_tags"][child_id] = []
    elif case == "same_rootfs":
        state["rootfs_layers_by_id"][state["parent_id"]] = state["rootfs_layers_by_id"][
            image_id
        ].copy()
    elif case == "docker_failure":
        state["state_flags"]["remove_fails"] = True
    elif case == "receipt_mismatch":
        Path(row["receipt_path"]).write_text("{}", encoding="utf-8")

    with pytest.raises(bounded.BuildError, match=expected_error):
        bounded._retire_schema13_rehearsal_tag(tag, str(state["image_id"]))

    assert json.loads(Path(state["ledger_path"]).read_bytes())["entries"] == [row]
    if case in {"current", "transient", "protected", "unregistered", "docker_failure"}:
        assert state["inventory"].get(str(state["tag"])) == image_id
    if case in {"child", "deep_child"}:
        assert state["image_id"] in state["image_ids"]
    if case == "same_rootfs":
        assert state["image_id"] in state["image_ids"]
    if case == "container":
        assert state["image_id"] in state["references"]


@pytest.mark.parametrize(
    ("fault", "expected_error"),
    (
        ("duplicate_image_id", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("missing_image_id", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("unknown_image_id", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("wrong_rootfs_type", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("empty_layers", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("duplicate_layer", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("malformed_layer_digest", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("malformed_json", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("too_many_layers", "schema13_rehearsal_image_inventory_too_large"),
        ("capture_too_large", "schema13_rehearsal_image_inventory_too_large"),
        ("capture_unavailable", "fixed_command_failed"),
        ("capture_timeout", "fixed_command_unavailable_or_timeout"),
    ),
)
def test_schema13_rehearsal_retirement_rejects_incomplete_rootfs_inventory_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    expected_error: str,
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)
    image_id = str(state["image_id"])
    parent_id = str(state["parent_id"])
    layers_by_id = state["rootfs_layers_by_id"]
    assert isinstance(layers_by_id, dict)
    rows = [
        f"{candidate_id}|layers|{json.dumps(layers_by_id[candidate_id])}"
        for candidate_id in sorted(state["image_ids"])
    ]
    if fault == "duplicate_image_id":
        rows[1] = rows[0]
    elif fault == "missing_image_id":
        rows.pop()
    elif fault == "unknown_image_id":
        rows[1] = f"{'sha256:' + '7' * 64}|layers|{json.dumps(layers_by_id[parent_id])}"
    elif fault == "wrong_rootfs_type":
        rows[1] = rows[1].replace("|layers|", "|unknown|")
    elif fault == "empty_layers":
        rows[1] = f"{parent_id}|layers|[]"
    elif fault == "duplicate_layer":
        duplicate = layers_by_id[image_id][0]
        rows[0] = f"{image_id}|layers|{json.dumps([duplicate, duplicate])}"
    elif fault == "malformed_layer_digest":
        rows[1] = f"{parent_id}|layers|{json.dumps(['sha256:' + 'Z' * 64])}"
    elif fault == "malformed_json":
        rows[1] = f"{parent_id}|layers|not-json"
    elif fault == "too_many_layers":
        many_layers = [f"sha256:{index:064x}" for index in range(129)]
        rows[1] = f"{parent_id}|layers|{json.dumps(many_layers)}"
    elif fault == "capture_too_large":
        state["state_flags"]["rootfs_capture_outcome"] = "too_large"
    elif fault == "capture_unavailable":
        state["state_flags"]["rootfs_capture_outcome"] = "unavailable"
    elif fault == "capture_timeout":
        state["state_flags"]["rootfs_capture_outcome"] = "timeout"
    if state["state_flags"]["rootfs_capture_outcome"] is None:
        state["state_flags"]["rootfs_inventory_override"] = "\n".join(rows).encode()
    before_ledger = Path(state["ledger_path"]).read_bytes()
    before_inventory = state["inventory"].copy()
    before_image_ids = state["image_ids"].copy()

    with pytest.raises(bounded.BuildError, match=expected_error):
        bounded._retire_schema13_rehearsal_tag(str(state["tag"]), image_id)

    assert before_ledger == Path(state["ledger_path"]).read_bytes()
    assert state["inventory"] == before_inventory
    assert state["image_ids"] == before_image_ids
    assert not any(
        command[:4] == [bounded.DOCKER, "image", "rm", "--no-prune"] for command in state["calls"]
    )
    assert state["capture_calls"]
    assert state["capture_calls"][0][1] == bounded._SCHEMA13_ROOTFS_INVENTORY_MAX_BYTES
    assert state["capture_calls"][0][2] == bounded.BUILDX_LISTING_TIMEOUT


def test_schema13_rehearsal_retirement_allows_unrelated_complete_rootfs_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)
    state["rootfs_layers_by_id"][state["parent_id"]] = [
        "sha256:" + "c" * 64,
        "sha256:" + "d" * 64,
    ]

    result = bounded._retire_schema13_rehearsal_tag(str(state["tag"]), str(state["image_id"]))

    assert result["status"] == "retired"
    assert state["image_id"] not in state["image_ids"]
    assert state["inventory"] == {}
    assert state["capture_calls"][0][1] == bounded._SCHEMA13_ROOTFS_INVENTORY_MAX_BYTES


def test_schema13_rehearsal_partial_removal_restores_registered_tag_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)
    state["state_flags"]["remove_leaves_id"] = True

    with pytest.raises(bounded.BuildError, match="schema13_rehearsal_image_removal_unverified"):
        bounded._retire_schema13_rehearsal_tag(str(state["tag"]), str(state["image_id"]))

    assert state["image_id"] in state["image_ids"]
    assert state["inventory"] == {state["tag"]: state["image_id"]}
    assert json.loads(Path(state["ledger_path"]).read_bytes())["entries"]

    state["state_flags"]["remove_leaves_id"] = False
    result = bounded._retire_schema13_rehearsal_tag(str(state["tag"]), str(state["image_id"]))
    assert result["status"] == "retired"
    assert json.loads(Path(state["ledger_path"]).read_bytes())["entries"] == []


def test_schema13_rehearsal_retirement_reconciles_a_previously_removed_image_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)
    state["inventory"].clear()
    state["image_ids"].remove(str(state["image_id"]))

    result = bounded._retire_schema13_rehearsal_tag(str(state["tag"]), str(state["image_id"]))

    assert result["status"] == "retired"
    assert json.loads(Path(state["ledger_path"]).read_bytes())["entries"] == []


def test_schema13_rehearsal_retirement_cli_requires_and_passes_fixed_tag_and_image_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tag = "stock-probs:schema13-recovery-012345abcdef"
    image_id = "sha256:" + "1" * 64
    result = {"status": "retired", "tag": tag, "image_id": image_id}
    calls: list[tuple[str, str]] = []

    def retire(received_tag: str, received_image_id: str) -> dict[str, object]:
        calls.append((received_tag, received_image_id))
        return result

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bounded_docker_build.py",
            "--retire-schema13-rehearsal-tag",
            tag,
            "--retire-schema13-rehearsal-image-id",
            image_id,
        ],
    )
    monkeypatch.setattr(bounded.os, "geteuid", lambda: bounded.USER.pw_uid)
    monkeypatch.setattr(bounded, "validate_user_state", lambda: None)
    monkeypatch.setattr(bounded.os, "access", lambda *_args: True)
    monkeypatch.setattr(bounded, "_retire_schema13_rehearsal_tag", retire)

    assert bounded.main() == 0
    assert json.loads(capsys.readouterr().out) == result
    assert calls == [(tag, image_id)]

    monkeypatch.setattr(
        sys, "argv", ["bounded_docker_build.py", "--retire-schema13-rehearsal-tag", tag]
    )
    with pytest.raises(SystemExit):
        bounded.main()
    assert "expected image ID" in capsys.readouterr().err

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bounded_docker_build.py",
            "--retire-schema13-rehearsal-tag",
            tag,
            "--retire-schema13-rehearsal-image-id",
            image_id,
            "--tag",
            "stock-probs:pr-candidate-aaaaaaaaaaaa-bbbbbbbbbbbb",
        ],
    )
    with pytest.raises(SystemExit):
        bounded.main()
    assert "fixed tag and image ID" in capsys.readouterr().err


def test_schema13_rehearsal_retirement_cli_mismatch_is_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _schema13_rehearsal_cleanup_fixture(tmp_path, monkeypatch)
    tag = str(state["tag"])
    expected_image_id = "sha256:" + "9" * 64
    ledger_path = Path(state["ledger_path"])
    before_ledger = ledger_path.read_bytes()
    before_inventory = state["inventory"].copy()
    before_image_ids = state["image_ids"].copy()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bounded_docker_build.py",
            "--retire-schema13-rehearsal-tag",
            tag,
            "--retire-schema13-rehearsal-image-id",
            expected_image_id,
        ],
    )
    monkeypatch.setattr(bounded.os, "geteuid", lambda: bounded.USER.pw_uid)
    monkeypatch.setattr(bounded, "validate_user_state", lambda: None)
    monkeypatch.setattr(bounded.os, "access", lambda *_args: True)

    assert bounded.main() == 1

    assert json.loads(capsys.readouterr().err) == {
        "stage": "schema13_rehearsal_expected_image_id_mismatch",
        "status": "failed",
    }
    assert state["calls"] == []
    assert state["inventory"] == before_inventory
    assert state["image_ids"] == before_image_ids
    assert ledger_path.read_bytes() == before_ledger


def test_local_and_arm_outputs_share_the_three_managed_image_slots() -> None:
    ledger: dict[str, object] = {
        "schema": bounded.LEDGER_SCHEMA,
        "entries": [
            _entry(1),
            _entry(2, "transient"),
        ],
    }

    bounded._check_retention_capacity(ledger, 1)
    with pytest.raises(bounded.BuildError, match="retention_limit_reached"):
        # One local image or the two-image ARM smoke pair cannot exceed the same cap.
        bounded._check_retention_capacity(ledger, 2)

    full: dict[str, object] = {
        "schema": bounded.LEDGER_SCHEMA,
        "entries": [_entry(3), _entry(4), _entry(5, "transient")],
    }
    with pytest.raises(bounded.BuildError, match="retention_limit_reached"):
        bounded._check_retention_capacity(full, 1)


def test_local_and_arm_output_tags_are_unique_managed_tag_families() -> None:
    local_tag = "stock-probs:local-" + "a" * 12 + "-" + "b" * 12 + "-" + "c" * 12
    arm_runtime = "stock-probs-r-astra-120-arm64-runtime:20261009T123456Z"
    arm_frontend = "stock-probs-r-astra-120-arm64-frontend:20261009T123456Z"

    assert bounded._safe_tag(local_tag)
    assert bounded._safe_tag(arm_runtime)
    assert bounded._safe_tag(arm_frontend)
    assert not bounded._safe_tag("stock-probs:local")


def test_repeated_local_build_reuses_exact_registered_image_before_slot_check(
    tmp_path: Path,
) -> None:
    revision = "a" * 40
    context_hash = "b" * 64
    tag = "stock-probs:local-" + "a" * 12 + "-" + "b" * 12 + "-" + "c" * 12
    image_id = "sha256:" + "d" * 64
    receipt = {
        "image_id": image_id,
        "revision_label": revision,
        "context_sha256": context_hash,
        "candidate_role": "current",
        "platform": "linux/amd64",
    }
    receipt_path = tmp_path / "build-receipt.json"
    raw = (json.dumps(receipt) + "\n").encode()
    receipt_path.write_bytes(raw)
    receipt_path.chmod(0o600)
    ledger: dict[str, object] = {
        "schema": bounded.LEDGER_SCHEMA,
        "entries": [
            {
                "image_id": image_id,
                "tag": tag,
                "revision": revision,
                "context_sha256": context_hash,
                "role": "current",
                "status": "complete",
                "receipt_path": str(receipt_path),
                "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            },
            _entry(2),
            _entry(3, "recovery"),
        ],
    }

    reused = bounded._find_reusable_local_image(ledger, revision, context_hash, "linux/amd64")

    assert reused == {"tag": tag, "image_id": image_id}
    # An identical local build is reused even when all three retention slots are occupied.


def test_cache_volume_validation_uses_api_identity_without_child_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "docker-root"
    root.mkdir()
    expected = str(root / "volumes" / bounded.CACHE_VOLUME / "_data")
    mount = {
        "Type": "volume",
        "Name": bounded.CACHE_VOLUME,
        "Source": expected,
        "Destination": "/var/lib/buildkit",
        "RW": True,
    }
    real_resolve = Path.resolve

    def guarded_resolve(self: Path, strict: bool = False) -> Path:
        if str(self) == expected:
            raise PermissionError("synthetic root-only Docker volume")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", guarded_resolve)

    def fake_checked(argv: list[str], timeout: int = 30) -> bytes:
        if argv[:3] == [bounded.DOCKER, "container", "inspect"]:
            return json.dumps([mount]).encode()
        if argv[:3] == [bounded.DOCKER, "volume", "inspect"]:
            return f"local|{expected}".encode()
        if argv[0] == bounded.FINDMNT:
            assert argv[-1] == str(root)
            return b"mount-uuid\n"
        raise AssertionError("unexpected fixed command")

    monkeypatch.setattr(bounded, "checked", fake_checked)
    bounded.verify_cache_volume(
        {
            "docker_root": str(root),
            "expected_docker_root_uuid": "mount-uuid",
            "buildkit_state_volume": {"mountpoint": expected},
        },
        "sha256:" + "a" * 64,
    )


def test_context_fingerprint_streams_exact_safe_paths_and_rejects_secret_names(
    tmp_path: Path,
) -> None:
    context = tmp_path / "context"
    context.mkdir()
    (context / "Dockerfile").write_bytes(b"FROM scratch\n")
    source = context / "src/stock_probs"
    source.mkdir(parents=True)
    (source / "api.py").write_bytes(b"API = True\n")

    digest = hashlib.sha256()
    for relative, content in (
        ("Dockerfile", b"FROM scratch\n"),
        ("src/stock_probs/api.py", b"API = True\n"),
    ):
        encoded = relative.encode()
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    assert bounded._context_sha256(context, os.getuid()) == digest.hexdigest()

    (context / ".env.local").write_text("fixture only\n", encoding="utf-8")
    with pytest.raises(bounded.BuildError, match="excluded_path"):
        bounded._context_sha256(context, os.getuid())


def test_build_state_requires_private_user_owned_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    state = home / ".local/state/stock-probs/r120-buildkit-v1"
    docker_config = state / "docker-config"
    docker_config.mkdir(parents=True, mode=0o700)
    for path in (home, home / ".local", home / ".local/state", home / ".local/state/stock-probs"):
        path.chmod(0o755)
    state.chmod(0o700)
    docker_config.chmod(0o700)
    monkeypatch.setattr(bounded, "USER", SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(home)))
    monkeypatch.setattr(bounded, "STATE", state)
    monkeypatch.setattr(bounded, "DOCKER_CONFIG", docker_config)
    bounded.validate_user_state()

    docker_config.chmod(0o755)
    with pytest.raises(bounded.BuildError, match="owner_or_mode_invalid"):
        bounded.validate_user_state()


def test_legacy_image_baseline_is_held_outside_three_managed_slots() -> None:
    legacy = {
        f"stock-probs:pr-candidate-{index:012x}-{index + 1:012x}": "sha256:" + f"{index + 10:064x}"
        for index in range(1, 506)
    }
    ledger = {
        "schema": bounded.LEDGER_SCHEMA,
        "entries": [_entry(700), _entry(701), _entry(702, "recovery")],
    }

    expected = bounded._expected_managed_inventory(ledger, legacy)

    assert len(legacy) == 505
    assert len(ledger["entries"]) == 3
    assert len(expected) == 508
    assert all(expected[tag] == image_id for tag, image_id in legacy.items())

    conflicting = dict(legacy)
    conflicting[_entry(700)["tag"]] = "sha256:" + "f" * 64
    with pytest.raises(bounded.BuildError, match="conflicts_with_held_baseline"):
        bounded._expected_managed_inventory(ledger, conflicting)
