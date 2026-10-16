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
FRONTEND_CHECKS_VERTEX = (
    "[frontend-builder 4/8] RUN npm run typecheck && npm run build "
    "&& npm run test -- --test-concurrency=1"
)
NATIVE_BUILDER_VERTEX = (
    "[opencode-patched-builder 8/8] RUN python /patch/build_native.py "
    '--target-arch "$TARGETARCH" --build-arch "$BUILDARCH" --output /out'
)


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


def _set_terminal_build_timeout(
    state: dict[str, object], *, elapsed_seconds: int = 901
) -> dict[str, object]:
    failure_path = Path(state["failure_path"])
    receipt = json.loads(failure_path.read_bytes())
    finished = datetime.now(UTC) - timedelta(seconds=1)
    build_started = finished - timedelta(seconds=elapsed_seconds)
    receipt.update(
        {
            "stage": "build_timeout_after_900s",
            "timeout_seconds": 900,
            "started_utc": (build_started - timedelta(seconds=1)).isoformat(),
            "build_started_utc": build_started.isoformat(),
            "finished_utc": finished.isoformat(),
        }
    )
    for field in (
        "process_group_cancel_verified",
        "build_deadline_cancel_verified",
        "timeout_cancellation_contract",
        "build_exit_code",
        "build_finished_utc",
    ):
        receipt.pop(field, None)
    rows = [dict(row) for row in state["history"]]
    for index, row in enumerate(rows):
        if row["ref"] == state["history_ref"]:
            created = build_started + timedelta(seconds=1)
            completed = finished + timedelta(milliseconds=500)
            row.update(
                {
                    "name": "context",
                    "status": "Error",
                    "created_at": created.isoformat().replace("+00:00", "Z"),
                    "completed_at": completed.isoformat().replace("+00:00", "Z"),
                    "completed_steps": 36,
                    "cached_steps": 19,
                    "total_steps": 47,
                }
            )
        else:
            created = build_started - timedelta(seconds=10 + index)
            completed = created + timedelta(seconds=1)
            row["created_at"] = created.isoformat().replace("+00:00", "Z")
            row["completed_at"] = completed.isoformat().replace("+00:00", "Z")
    state["history"] = rows
    state["history_state"]["bytes"] = _encode_buildkit_history_jsonl(rows)
    _rewrite_failed_receipt(state, receipt)
    return receipt


@pytest.mark.parametrize(
    ("cancellation", "expected"),
    (
        ({}, False),
        ({"process_group_cancel_verified": False}, False),
        ({"build_deadline_cancel_verified": 1}, False),
        ({"build_deadline_cancel_verified": True}, True),
    ),
)
def test_timeout_cancellation_contract_requires_literal_verified_process_group_state(
    cancellation: dict[str, object], expected: bool
) -> None:
    data = dict(cancellation)

    bounded._record_timeout_cancellation_contract(data)

    assert ("timeout_cancellation_contract" in data) is expected
    if expected:
        assert data["timeout_cancellation_contract"] == "bounded-cancel-v1"


def test_failed_inflight_timeout_release_uses_fresh_terminal_history_and_preserves_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    receipt = _set_terminal_build_timeout(state)
    before_failure = Path(state["failure_path"]).read_bytes()
    before_inventory = dict(state["inventory"])

    result = bounded._release_failed_inflight_reservation(
        str(state["tag"]),
        str(state["revision"]),
        str(state["context_hash"]),
        str(state["role"]),
        str(state["failure_sha256"]),
    )

    assert receipt["timeout_seconds"] == 900
    assert "process_group_cancel_verified" not in receipt
    assert result["status"] == "failed_build_reservation_released"
    assert Path(state["failure_path"]).read_bytes() == before_failure
    assert dict(state["inventory"]) == before_inventory
    assert state["tag"] not in state["inventory"]
    assert json.loads(Path(state["ledger_path"]).read_bytes())["entries"] == [state["kept_row"]]
    recovery = json.loads(Path(state["recovery_path"]).read_bytes())
    assert recovery["buildkit_history"]["status"] == "error"
    assert recovery["buildkit_history"]["completed_steps"] == 36
    assert recovery["client_process_group_cancellation"] == "unavailable"
    observed = datetime.fromisoformat(recovery["backend_terminal_error_observed_utc"])
    assert observed >= datetime.fromisoformat(recovery["buildkit_history"]["completed_at"])
    assert observed <= datetime.fromisoformat(recovery["released_utc"])


def test_failed_inflight_late_nonzero_exit_uses_terminal_exit_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    receipt = _set_terminal_build_timeout(state)
    receipt.update(
        {
            "stage": "buildx_exit_nonzero",
            "build_exit_code": 1,
            "build_finished_utc": receipt["finished_utc"],
        }
    )
    receipt.pop("timeout_seconds")
    _rewrite_failed_receipt(state, receipt)

    result = bounded._release_failed_inflight_reservation(
        str(state["tag"]),
        str(state["revision"]),
        str(state["context_hash"]),
        str(state["role"]),
        str(state["failure_sha256"]),
    )

    assert result["status"] == "failed_build_reservation_released"
    recovery = json.loads(Path(state["recovery_path"]).read_bytes())
    assert recovery["buildkit_history"]["status"] == "error"


def test_failed_inflight_timeout_release_records_verified_current_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    receipt = _set_terminal_build_timeout(state)
    receipt.update(
        {
            "timeout_cancellation_contract": "bounded-cancel-v1",
            "build_deadline_cancel_verified": True,
        }
    )
    _rewrite_failed_receipt(state, receipt)

    bounded._release_failed_inflight_reservation(
        str(state["tag"]),
        str(state["revision"]),
        str(state["context_hash"]),
        str(state["role"]),
        str(state["failure_sha256"]),
    )

    recovery = json.loads(Path(state["recovery_path"]).read_bytes())
    assert recovery["client_process_group_cancellation"] == "verified"


@pytest.mark.parametrize(
    "invalid_case",
    (
        "short_elapsed",
        "wrong_timeout",
        "noninteger_timeout",
        "false_cancel",
        "cancel_contract_without_proof",
        "exit_code",
        "build_finished",
    ),
)
def test_failed_inflight_timeout_release_rejects_unproven_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_case: str
) -> None:
    state = _failed_inflight_reservation_fixture(tmp_path, monkeypatch)
    receipt = _set_terminal_build_timeout(
        state, elapsed_seconds=899 if invalid_case == "short_elapsed" else 901
    )
    if invalid_case == "wrong_timeout":
        receipt["timeout_seconds"] = 901
    elif invalid_case == "noninteger_timeout":
        receipt["timeout_seconds"] = 900.0
    elif invalid_case == "false_cancel":
        receipt["build_deadline_cancel_verified"] = False
    elif invalid_case == "cancel_contract_without_proof":
        receipt["timeout_cancellation_contract"] = "bounded-cancel-v1"
    elif invalid_case == "exit_code":
        receipt["build_exit_code"] = 1
    elif invalid_case == "build_finished":
        receipt["build_finished_utc"] = receipt["finished_utc"]
    _rewrite_failed_receipt(state, receipt)
    before_ledger = Path(state["ledger_path"]).read_bytes()
    before_inventory = dict(state["inventory"])

    with pytest.raises(bounded.BuildError, match="failed_reservation_receipt_contract_mismatch"):
        bounded._release_failed_inflight_reservation(
            str(state["tag"]),
            str(state["revision"]),
            str(state["context_hash"]),
            str(state["role"]),
            str(state["failure_sha256"]),
        )

    assert Path(state["ledger_path"]).read_bytes() == before_ledger
    assert dict(state["inventory"]) == before_inventory
    assert state["capture_calls"] == []
    assert state["checked_calls"] == []
    assert not Path(state["recovery_path"]).exists()


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


def test_local_buildx_progress_observation_is_opt_in_and_does_not_change_arm_command(
    tmp_path: Path,
) -> None:
    args = (
        "stock-probs:local-" + "a" * 12 + "-" + "b" * 12 + "-" + "c" * 12,
        "a" * 40,
        "linux/amd64",
        tmp_path / "context",
        tmp_path / "image.iid",
    )

    legacy = bounded._local_buildx_argv(*args)
    observed = bounded._local_buildx_argv(*args, True)
    assert "--progress=rawjson" not in legacy
    assert observed == [
        *legacy[: legacy.index("--load")],
        "--progress=rawjson",
        *legacy[legacy.index("--load") :],
    ]
    assert bounded._arm64_compose_argv(
        "stock-probs-r-astra-120-arm64-1000", tmp_path / "compose.yml"
    ) == [
        bounded.DOCKER,
        "compose",
        "--project-directory",
        str(bounded.ROOT),
        "--project-name",
        "stock-probs-r-astra-120-arm64-1000",
        "--file",
        str(tmp_path / "compose.yml"),
        "build",
        "--builder",
        bounded.BUILDER,
        "--pull",
        "arm64-frontend-builder",
        "arm64-app",
    ]


def _phase_vertex(
    name: str,
    digest_number: int = 1,
    *,
    started: str | None = "2026-10-15T12:00:00.000000000Z",
    completed: str | None = "2026-10-15T12:00:05Z",
    cached: bool = False,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "digest": "sha256:" + f"{digest_number:064x}",
        "name": name,
        "started": started,
        "completed": completed,
        "cached": cached,
        "error": error,
    }


def _observe_phase_bytes(
    payload: bytes, observer: Any | None = None, *, chunk_size: int = 4096
) -> tuple[Any, dict[str, object]]:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb", buffering=0)
    phase_observer = bounded._LocalBuildPhaseObserver() if observer is None else observer
    phase_observer.attach(stream)
    try:
        for offset in range(0, len(payload), chunk_size):
            os.write(write_fd, payload[offset : offset + chunk_size])
    finally:
        os.close(write_fd)
    phase_observer.finish()
    projection = phase_observer.snapshot()
    assert isinstance(projection, dict)
    return phase_observer, projection


def test_local_phase_observer_keeps_only_coarse_redacted_vertex_facts() -> None:
    digest = "sha256:" + "d" * 64
    private_name = FRONTEND_CHECKS_VERTEX
    payload = (
        json.dumps(
            {
                "vertexes": [
                    _phase_vertex(
                        private_name,
                        started="2026-10-15T12:00:00.123456789Z",
                        error="private-error-detail",
                    )
                ],
                "statuses": [
                    {"vertex": digest, "name": "private-status-name", "current": 2, "total": 3}
                ],
                "logs": [
                    {
                        "vertex": digest,
                        "stream": 2,
                        "data": "cHJpdmF0ZS1sb2ctY29udGVudA==",
                    }
                ],
                "warnings": [
                    {
                        "vertex": digest,
                        "level": 1,
                        "short": "cHJpdmF0ZS13YXJuaW5n",
                        "detail": ["cHJpdmF0ZS1kZXRhaWw="],
                        "url": "https://private.example/path",
                        "sourceInfo": {"filename": "private-file"},
                        "range": [{"start": 7}],
                    }
                ],
            }
        ).encode()
        + b"\n"
    )
    observer, projection = _observe_phase_bytes(payload)

    assert projection["status"] == "available"
    assert projection["reason_code"] is None
    assert projection["phases"] == [
        {
            "phase": "frontend_checks_run",
            "ordinal": 1,
            "started": True,
            "completed": True,
            "cached": False,
            "error": True,
            "elapsed_ms": 4876,
        }
    ]
    serialized = json.dumps(projection)
    for private_value in (
        digest,
        private_name,
        "private-error-detail",
        "private-status-name",
        "cHJpdmF0ZS1sb2ctY29udGVudA==",
        "cHJpdmF0ZS13YXJuaW5n",
        "cHJpdmF0ZS1kZXRhaWw=",
        "private-file",
        "https://private.example/path",
    ):
        assert private_value not in serialized
    assert observer._thread is not None and not observer._thread.is_alive()
    assert observer._stream is not None and observer._stream.closed
    before_late_frame = json.dumps(observer.snapshot(), sort_keys=True)
    observer._consume_frame(
        json.dumps({"vertexes": [_phase_vertex(NATIVE_BUILDER_VERTEX)]}).encode()
    )
    assert json.dumps(observer.snapshot(), sort_keys=True) == before_late_frame


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        ({"future_field": "private"}, "unknown_or_invalid_frame"),
        (
            {
                "vertexes": [
                    {
                        **_phase_vertex(FRONTEND_CHECKS_VERTEX),
                        "future": "private",
                    }
                ]
            },
            "unknown_or_invalid_vertex",
        ),
        (
            {
                "vertexes": [
                    _phase_vertex(
                        FRONTEND_CHECKS_VERTEX,
                        started="2026-10-15T12:00:06Z",
                    )
                ]
            },
            "invalid_vertex_clock",
        ),
        (
            {
                "vertexes": [
                    {
                        **_phase_vertex(FRONTEND_CHECKS_VERTEX),
                        "progressGroup": {"id": "private-id", "weak": "true"},
                    }
                ]
            },
            "invalid_vertex_progress_group",
        ),
    ],
)
def test_local_phase_observer_fails_closed_on_unknown_or_invalid_late_frames(
    frame: dict[str, object], reason: str
) -> None:
    valid = {"vertexes": [_phase_vertex(NATIVE_BUILDER_VERTEX)]}
    payload = (json.dumps(valid) + "\n" + json.dumps(frame) + "\nprivate-late-output\n").encode()
    observer, projection = _observe_phase_bytes(payload)

    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == reason
    assert "private-late-output" not in json.dumps(projection)
    assert observer._thread is not None and not observer._thread.is_alive()


@pytest.mark.parametrize("weak", [False, True])
def test_local_phase_observer_accepts_optional_boolean_progress_group_weak(weak: bool) -> None:
    frame = {
        "vertexes": [
            {
                **_phase_vertex(FRONTEND_CHECKS_VERTEX),
                "progressGroup": {
                    "id": "private-progress-id",
                    "name": "private-name",
                    "weak": weak,
                },
            }
        ]
    }
    _observer, projection = _observe_phase_bytes((json.dumps(frame) + "\n").encode())

    assert projection["status"] == "available"
    assert projection["reason_code"] is None
    assert [phase["phase"] for phase in projection["phases"]] == ["frontend_checks_run"]
    serialized = json.dumps(projection)
    assert "private-progress-id" not in serialized
    assert "private-name" not in serialized
    assert "progressGroup" not in serialized
    assert '"weak"' not in serialized


def test_local_phase_observer_skips_routine_unknown_vertex_and_keeps_later_known_phase() -> None:
    routine_auth = "[auth] library/base:pull token for registry.example"
    payload = (
        json.dumps({"vertexes": [_phase_vertex(routine_auth, 1)]})
        + "\n"
        + json.dumps({"vertexes": [_phase_vertex(NATIVE_BUILDER_VERTEX, 2)]})
        + "\n"
    ).encode()
    observer, projection = _observe_phase_bytes(payload)

    assert projection["status"] == "partial"
    assert projection["reason_code"] == "unknown_vertices_skipped"
    assert projection["unknown_vertices_skipped"] == 1
    assert projection["unknown_vertices_truncated"] is False
    assert projection["phases"] == [
        {
            "phase": "native_builder_run",
            "ordinal": 1,
            "started": True,
            "completed": True,
            "cached": False,
            "error": False,
            "elapsed_ms": 5000,
        }
    ]
    assert routine_auth not in json.dumps(projection)
    assert observer._thread is not None and not observer._thread.is_alive()


def test_local_phase_observer_with_only_unknown_vertices_is_unavailable_without_names() -> None:
    unknown_name = "[internal] resolve image config for docker-image://private/base:latest"
    _observer, projection = _observe_phase_bytes(
        (json.dumps({"vertexes": [_phase_vertex(unknown_name)]}) + "\n").encode()
    )

    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == "unknown_vertices_skipped"
    assert projection["unknown_vertices_skipped"] == 1
    assert projection["vertices_observed"] == 0
    assert projection["phases"] == []
    assert unknown_name not in json.dumps(projection)


def test_local_phase_observer_caps_unknown_vertex_count_without_losing_known_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bounded, "LOCAL_BUILD_PHASE_MAX_SKIPPED_VERTICES", 1)
    unknown = "[auth] library/base:pull token for registry.example"
    payload = (
        json.dumps({"vertexes": [_phase_vertex(unknown, 1)]})
        + "\n"
        + json.dumps({"vertexes": [_phase_vertex(unknown, 2)]})
        + "\n"
        + json.dumps({"vertexes": [_phase_vertex(NATIVE_BUILDER_VERTEX, 3)]})
        + "\n"
    ).encode()
    _observer, projection = _observe_phase_bytes(payload)

    assert projection["status"] == "partial"
    assert projection["unknown_vertices_skipped"] == 1
    assert projection["unknown_vertices_truncated"] is True
    assert [phase["phase"] for phase in projection["phases"]] == ["native_builder_run"]
    assert unknown not in json.dumps(projection)


@pytest.mark.parametrize(
    ("limits", "payload", "reason"),
    [
        (
            {"LOCAL_BUILD_PHASE_MAX_RAW_BYTES": 100},
            ((json.dumps({"statuses": [{"name": "x" * 64}]}) + "\n") * 3).encode(),
            "raw_byte_limit",
        ),
        (
            {"LOCAL_BUILD_PHASE_MAX_LINE_BYTES": 32},
            b"x" * 33 + b"\n",
            "line_byte_limit",
        ),
        (
            {"LOCAL_BUILD_PHASE_MAX_FRAMES": 1},
            (json.dumps({"statuses": []}) + "\n") * 2,
            "frame_limit",
        ),
        (
            {"LOCAL_BUILD_PHASE_MAX_VERTICES": 1},
            json.dumps(
                {
                    "vertexes": [
                        _phase_vertex(
                            FRONTEND_CHECKS_VERTEX,
                            1,
                        ),
                        _phase_vertex("[opencode-assets 2/3] RUN mkdir -p /assets/amd64/lib", 2),
                    ]
                }
            ).encode()
            + b"\n",
            "vertex_limit",
        ),
        (
            {"LOCAL_BUILD_PHASE_MAX_ARTIFACT_BYTES": 256},
            (json.dumps({"vertexes": [_phase_vertex(FRONTEND_CHECKS_VERTEX)]}) + "\n").encode(),
            "artifact_size_limit",
        ),
    ],
)
def test_local_phase_observer_enforces_fixed_projection_caps(
    monkeypatch: pytest.MonkeyPatch,
    limits: dict[str, int],
    payload: bytes | str,
    reason: str,
) -> None:
    for name, value in limits.items():
        monkeypatch.setattr(bounded, name, value)
    raw = payload.encode() if isinstance(payload, str) else payload
    _observer, projection = _observe_phase_bytes(raw)

    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == reason
    assert projection["raw_bytes_read"] <= bounded.LOCAL_BUILD_PHASE_MAX_RAW_BYTES
    assert projection["vertices_observed"] <= bounded.LOCAL_BUILD_PHASE_MAX_VERTICES
    assert projection["unknown_vertices_skipped"] <= bounded.LOCAL_BUILD_PHASE_MAX_SKIPPED_VERTICES
    assert (
        len(json.dumps(projection, sort_keys=True, separators=(",", ":")).encode())
        <= bounded.LOCAL_BUILD_PHASE_MAX_ARTIFACT_BYTES
    )


def test_bounded_build_drains_noisy_child_beyond_pipe_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(bounded, "verify_build_mount", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bounded, "check_space", lambda *_args, **_kwargs: bounded.MIN_FREE)
    monkeypatch.setattr(
        bounded,
        "data_root",
        lambda *_args, **_kwargs: (tmp_path, bounded.MIN_FREE),
    )
    observer = bounded._LocalBuildPhaseObserver()
    command = [
        sys.executable,
        "-c",
        "import os; chunk=b'x'*8192; [os.write(2, chunk) for _ in range(1024)]",
    ]

    bounded._run_bounded_build(
        command,
        expected_uuid="12345678-1234-1234-1234-123456789abc",
        docker_root=tmp_path,
        space_paths=(tmp_path,),
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        timeout=10,
        phase_observer=observer,
    )

    projection = observer.snapshot()
    assert projection is not None
    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == "line_byte_limit"
    assert projection["raw_bytes_read"] <= bounded.LOCAL_BUILD_PHASE_MAX_RAW_BYTES
    assert observer._thread is not None and not observer._thread.is_alive()
    assert observer._stream is not None and observer._stream.closed


def test_bounded_build_without_observer_keeps_legacy_devnull_popen_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(bounded, "verify_build_mount", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bounded, "check_space", lambda *_args, **_kwargs: bounded.MIN_FREE)
    monkeypatch.setattr(
        bounded,
        "data_root",
        lambda *_args, **_kwargs: (tmp_path, bounded.MIN_FREE),
    )
    real_popen = bounded.subprocess.Popen
    observed_kwargs: list[dict[str, object]] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> bounded.subprocess.Popen[bytes]:
        observed_kwargs.append(dict(kwargs))
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(bounded.subprocess, "Popen", tracked_popen)
    bounded._run_bounded_build(
        [sys.executable, "-c", "import os; os.write(2, b'discarded')"],
        expected_uuid="12345678-1234-1234-1234-123456789abc",
        docker_root=tmp_path,
        space_paths=(tmp_path,),
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        timeout=5,
    )

    assert observed_kwargs == [
        {
            "cwd": bounded.ROOT,
            "env": {"PYTHONDONTWRITEBYTECODE": "1"},
            "stdin": bounded.subprocess.DEVNULL,
            "stdout": bounded.subprocess.DEVNULL,
            "stderr": bounded.subprocess.DEVNULL,
            "shell": False,
            "start_new_session": True,
        }
    ]


def test_bounded_build_timeout_cancels_noisy_child_and_bounds_reader_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(bounded, "verify_build_mount", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bounded, "check_space", lambda *_args, **_kwargs: bounded.MIN_FREE)
    real_popen = bounded.subprocess.Popen
    processes: list[bounded.subprocess.Popen[bytes]] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> bounded.subprocess.Popen[bytes]:
        process = real_popen(argv, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(bounded.subprocess, "Popen", tracked_popen)
    observer = bounded._LocalBuildPhaseObserver()
    command = [
        sys.executable,
        "-c",
        "import os; chunk=b'x'*8192\nwhile True: os.write(2, chunk)",
    ]

    with pytest.raises(bounded.BuildError, match="bounded_build_timeout"):
        bounded._run_bounded_build(
            command,
            expected_uuid="12345678-1234-1234-1234-123456789abc",
            docker_root=tmp_path,
            space_paths=(tmp_path,),
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            timeout=1,
            phase_observer=observer,
        )

    assert len(processes) == 1 and processes[0].poll() is not None
    projection = observer.snapshot()
    assert projection is not None
    assert projection["status"] == "unavailable"
    assert observer._finalized
    assert observer._thread is not None and not observer._thread.is_alive()
    assert observer._stream is not None and observer._stream.closed


def test_phase_reader_failure_drains_pipe_and_preserves_primary_build_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(bounded, "verify_build_mount", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bounded, "check_space", lambda *_args, **_kwargs: bounded.MIN_FREE)
    observer = bounded._LocalBuildPhaseObserver()

    def fail_parse(_line: bytes) -> None:
        raise RuntimeError("private observer exception")

    monkeypatch.setattr(observer, "_consume_frame", fail_parse)
    command = [
        sys.executable,
        "-c",
        "import os, sys\n"
        "data = b'{\"vertexes\": []}\\n' + b'x' * 262144\n"
        "view = memoryview(data)\n"
        "while view:\n"
        "    count = os.write(2, view)\n"
        "    view = view[count:]\n"
        "sys.exit(7)\n",
    ]

    with pytest.raises(bounded.BuildError, match="bounded_build_exit_nonzero") as caught:
        bounded._run_bounded_build(
            command,
            expected_uuid="12345678-1234-1234-1234-123456789abc",
            docker_root=tmp_path,
            space_paths=(tmp_path,),
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            timeout=5,
            phase_observer=observer,
        )

    assert caught.value.code == "bounded_build_exit_nonzero"
    projection = observer.snapshot()
    assert projection is not None
    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == "reader_failed"
    assert observer._thread is not None and not observer._thread.is_alive()
    assert observer._stream is not None and observer._stream.closed


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
    assert state["capture_calls"][0][1] <= bounded._SCHEMA13_ROOTFS_CHUNK_MAX_BYTES
    assert 0 < state["capture_calls"][0][2] <= bounded.BUILDX_LISTING_TIMEOUT


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
    assert state["capture_calls"][0][1] <= bounded._SCHEMA13_ROOTFS_CHUNK_MAX_BYTES


def _rootfs_test_image_ids(count: int) -> set[str]:
    return {f"sha256:{number:064x}" for number in range(1, count + 1)}


def _rootfs_test_row(image_id: str, layers: list[str] | None = None) -> bytes:
    actual_layers = layers or ["sha256:" + "a" * 64, "sha256:" + "b" * 64]
    return f"{image_id}|layers|{json.dumps(actual_layers)}\n".encode("ascii")


def test_schema13_rootfs_inventory_reads_exact_507_ids_in_bounded_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_ids = _rootfs_test_image_ids(507)
    calls: list[tuple[list[str], int, float]] = []

    def capture(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
        requested = argv[5:]
        assert 0 < len(requested) <= bounded._SCHEMA13_ROOTFS_CHUNK_SIZE
        assert max_bytes <= bounded._SCHEMA13_ROOTFS_CHUNK_MAX_BYTES
        assert 0 < timeout <= bounded.BUILDX_LISTING_TIMEOUT
        calls.append((requested, max_bytes, timeout))
        return b"".join(_rootfs_test_row(image_id) for image_id in requested)

    monkeypatch.setattr(bounded, "_capture_bounded_stdout", capture)
    inventory = bounded._schema13_rehearsal_rootfs_layers(image_ids)

    assert set(inventory) == image_ids
    assert len(inventory) == 507
    assert len(calls) == 16
    assert [len(requested) for requested, _max_bytes, _timeout in calls] == [
        32,
    ] * 15 + [27]
    flattened = [image_id for requested, _max_bytes, _timeout in calls for image_id in requested]
    assert len(flattened) == len(set(flattened)) == 507
    assert set(flattened) == image_ids


@pytest.mark.parametrize(
    ("fault", "expected_error"),
    (
        ("duplicate_within_chunk", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("omitted_within_chunk", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("omitted_second_chunk", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("foreign_from_prior_chunk", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("non_ascii", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("invalid_type", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("empty_layers", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("invalid_layer_digest", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("duplicate_layer_digest", "schema13_rehearsal_ancestry_metadata_invalid"),
        ("129_layers", "schema13_rehearsal_image_inventory_too_large"),
    ),
)
def test_schema13_rootfs_inventory_rejects_malformed_chunk_rows(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    expected_error: str,
) -> None:
    ids = sorted(
        _rootfs_test_image_ids(
            33 if fault in {"omitted_second_chunk", "foreign_from_prior_chunk"} else 2
        )
    )
    requested_chunks: list[list[str]] = []

    def capture(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
        requested = argv[5:]
        requested_chunks.append(requested)
        if fault == "omitted_second_chunk" and len(requested_chunks) == 2:
            return b""
        if fault == "foreign_from_prior_chunk" and len(requested_chunks) == 2:
            return _rootfs_test_row(requested_chunks[0][0])
        if fault == "duplicate_within_chunk":
            return _rootfs_test_row(requested[0]) + _rootfs_test_row(requested[0])
        if fault == "omitted_within_chunk":
            return _rootfs_test_row(requested[0])
        if fault == "non_ascii":
            return requested[0].encode("ascii") + b'|layers|["sha256:\xff"]\n'
        if fault == "invalid_type":
            return f"{requested[0]}|unknown|[]\n".encode("ascii")
        if fault == "empty_layers":
            return f"{requested[0]}|layers|[]\n".encode("ascii")
        if fault == "invalid_layer_digest":
            return f'{requested[0]}|layers|["sha256:{"G" * 64}"]\n'.encode("ascii")
        if fault == "duplicate_layer_digest":
            digest = "sha256:" + "a" * 64
            return f"{requested[0]}|layers|{json.dumps([digest, digest])}\n".encode("ascii")
        if fault == "129_layers":
            layers = [f"sha256:{number:064x}" for number in range(129)]
            return b"".join(
                _rootfs_test_row(image_id, layers if image_id == requested[0] else None)
                for image_id in requested
            )
        return b"".join(_rootfs_test_row(image_id) for image_id in requested)

    monkeypatch.setattr(bounded, "_capture_bounded_stdout", capture)
    with pytest.raises(bounded.BuildError, match=expected_error):
        bounded._schema13_rehearsal_rootfs_layers(set(ids))

    if fault in {"omitted_second_chunk", "foreign_from_prior_chunk"}:
        assert len(requested_chunks) == 2


def test_schema13_rootfs_inventory_accepts_exact_128_layer_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = next(iter(_rootfs_test_image_ids(1)))
    layers = [f"sha256:{number:064x}" for number in range(128)]
    monkeypatch.setattr(
        bounded,
        "_capture_bounded_stdout",
        lambda argv, **_kwargs: _rootfs_test_row(argv[5], layers),
    )

    assert bounded._schema13_rehearsal_rootfs_layers({image_id}) == {image_id: tuple(layers)}


def test_schema13_rootfs_inventory_enforces_exact_deadline_and_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _rootfs_test_image_ids(2)
    ticks = iter([0.0, 0.0, bounded._SCHEMA13_ROOTFS_GLOBAL_TIMEOUT])
    monkeypatch.setattr(
        bounded,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks)),
    )
    calls: list[list[str]] = []

    def capture(argv: list[str], **_kwargs: object) -> bytes:
        calls.append(argv[5:])
        return b"".join(_rootfs_test_row(image_id) for image_id in argv[5:])

    monkeypatch.setattr(bounded, "_capture_bounded_stdout", capture)
    with pytest.raises(
        bounded.BuildError,
        match="schema13_rehearsal_ancestry_metadata_timeout",
    ):
        bounded._schema13_rehearsal_rootfs_layers(ids)
    assert len(calls) == 1

    monkeypatch.setattr(bounded, "time", __import__("time"))

    def subprocess_timeout(*_args: object, **_kwargs: object) -> bytes:
        raise bounded.BuildError("fixed_command_unavailable_or_timeout")

    monkeypatch.setattr(bounded, "_capture_bounded_stdout", subprocess_timeout)
    with pytest.raises(bounded.BuildError, match="fixed_command_unavailable_or_timeout"):
        bounded._schema13_rehearsal_rootfs_layers(ids)


def test_schema13_rootfs_inventory_enforces_aggregate_bytes_and_image_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _rootfs_test_image_ids(3)
    monkeypatch.setattr(bounded, "_SCHEMA13_ROOTFS_CHUNK_SIZE", 1)
    monkeypatch.setattr(bounded, "_SCHEMA13_ROOTFS_INVENTORY_MAX_BYTES", 250)
    calls: list[int] = []

    def overflow_on_remaining_budget(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
        calls.append(max_bytes)
        output = _rootfs_test_row(argv[5], ["sha256:" + "a" * 64])
        if len(output) > max_bytes:
            raise bounded.BuildError("builder_driver_listing_too_large")
        return output

    monkeypatch.setattr(bounded, "_capture_bounded_stdout", overflow_on_remaining_budget)
    with pytest.raises(
        bounded.BuildError,
        match="schema13_rehearsal_image_inventory_too_large",
    ):
        bounded._schema13_rehearsal_rootfs_layers(ids)
    assert len(calls) == 2
    assert calls[0] == 250
    assert 0 < calls[1] < calls[0]

    monkeypatch.setattr(bounded, "_SCHEMA13_ROOTFS_CHUNK_SIZE", 32)
    calls.clear()
    with pytest.raises(
        bounded.BuildError,
        match="schema13_rehearsal_image_inventory_too_large",
    ):
        bounded._schema13_rehearsal_rootfs_layers(_rootfs_test_image_ids(8193))
    assert calls == []


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


def _local_transition_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state, _ = _test_ledger_paths(tmp_path, monkeypatch)
    pointer = state / "local-current.json"
    monkeypatch.setattr(bounded, "LOCAL_CURRENT_FILE", pointer)
    rows = [_entry(1), _entry(2)]
    monkeypatch.setattr(bounded, "setup_receipt", lambda: {})
    monkeypatch.setattr(bounded, "_ledger_read", lambda: {"entries": rows})
    monkeypatch.setattr(bounded, "_verify_ledger_inventory", lambda *_: None)
    monkeypatch.setattr(bounded, "_native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(
        bounded,
        "checked",
        lambda *_: f"{rows[0]['image_id']}|linux/amd64|{rows[0]['revision']}".encode(),
    )
    checks: list[str] = []
    monkeypatch.setattr(
        bounded, "_managed_build_receipt", lambda row: checks.append(str(row["image_id"]))
    )
    monkeypatch.setattr(bounded, "_schema13_rehearsal_image_facts", lambda *_: None)
    bounded._write_local_current(
        rows[0]["tag"], rows[0]["image_id"], rows[0]["revision"], rows[0]["context_sha256"]
    )
    return {"rows": rows, "pointer": pointer, "checks": checks, "before": pointer.read_bytes()}


def test_local_current_transition_checks_both_receipts_and_preserves_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_transition_fixture(tmp_path, monkeypatch)
    original = json.dumps(state["rows"], sort_keys=True)
    first, second = state["rows"]
    result = bounded.select_local_current(first["image_id"], second["image_id"])
    assert result["images_removed"] == [] and result["ledger_changed"] is False
    assert state["checks"] == [first["image_id"], second["image_id"]]
    assert json.loads(state["pointer"].read_text())["image_id"] == second["image_id"]
    assert json.dumps(state["rows"], sort_keys=True) == original


@pytest.mark.parametrize(
    "failure",
    [
        "stale",
        "same",
        "malformed",
        "missing",
        "duplicate",
        "recovery",
        "reserved",
        "receipt",
        "metadata",
        "write",
    ],
)
def test_local_current_transition_fails_without_pointer_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = _local_transition_fixture(tmp_path, monkeypatch)
    first, second = state["rows"]
    expected, replacement = first["image_id"], second["image_id"]
    if failure == "stale":
        expected = "sha256:" + "3" * 64
    elif failure == "same":
        replacement = expected
    elif failure == "malformed":
        replacement = "short-id"
    elif failure == "missing":
        state["rows"].pop()
    elif failure == "duplicate":
        state["rows"].append(dict(second))
    elif failure == "recovery":
        second["role"] = "recovery"
    elif failure == "reserved":
        second["status"] = "reserved"
    else:
        name = {
            "receipt": "_managed_build_receipt",
            "metadata": "_schema13_rehearsal_image_facts",
            "write": "_write_local_current",
        }[failure]

        def fail(*_: object) -> None:
            raise bounded.BuildError("injected_failure")

        monkeypatch.setattr(bounded, name, fail)
    with pytest.raises(bounded.BuildError):
        bounded.select_local_current(expected, replacement)
    assert state["pointer"].read_bytes() == state["before"]


def _local_generation(
    *, running: bool = True, container_id: str | None = None
) -> dict[str, object]:
    return {
        "container_id": container_id or "a" * 64,
        "name": bounded.CONTAINER_NAME,
        "image_id": "sha256:" + "b" * 64,
        "created": "2026-10-15T16:00:00Z",
        "started": "2026-10-15T16:01:00Z",
        "restart_count": 0,
        "running": running,
        "pid": 321 if running else 0,
    }


@pytest.mark.parametrize("stop_error_code", [None, "fixed_command_failed"])
def test_local_failure_stops_only_the_pinned_builder_after_cli_process_group_is_gone(
    monkeypatch: pytest.MonkeyPatch, stop_error_code: str | None
) -> None:
    setup = {"builder_container_id": "a" * 64, "buildkit_image_id": "sha256:" + "b" * 64}
    before = _local_generation()
    stopped = _local_generation(running=False)
    generations = iter((before, before, stopped))
    commands: list[tuple[list[str], float]] = []
    target_checks: list[tuple[dict[str, object], dict[str, object]]] = []

    def checked(argv: list[str], timeout: float = 30) -> bytes:
        commands.append((argv, timeout))
        if stop_error_code is not None:
            raise bounded.BuildError(stop_error_code)
        return b"stopped"

    monkeypatch.setattr(bounded, "_builder_generation", lambda _setup, **_kwargs: next(generations))
    monkeypatch.setattr(
        bounded,
        "_verify_builder_stop_target",
        lambda received_setup, received_generation, _deadline: target_checks.append(
            (received_setup, received_generation)
        ),
    )
    monkeypatch.setattr(
        bounded,
        "_local_buildkit_cgroup_proof",
        lambda container_id: {
            "status": "empty",
            "scope_path": f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope",
            "directories_scanned": 1,
            "entries_scanned": 2,
            "process_ids_observed": 0,
        },
    )
    monkeypatch.setattr(
        bounded, "inspect_builder", lambda _setup: pytest.fail("cleanup must not bootstrap")
    )
    monkeypatch.setattr(bounded, "checked", checked)

    result = bounded._stop_owned_builder_after_local_failure(setup, before)

    assert result["status"] == "verified_stopped_same_generation"
    assert result.get("stop_error_code") == stop_error_code
    assert result["stop_command_result"] == (
        "unavailable_but_state_verified" if stop_error_code is not None else "completed"
    )
    assert result["worker_cgroup"]["status"] == "empty"
    assert target_checks == [(setup, before)]
    assert len(commands) == 1
    stop_argv, stop_timeout = commands[0]
    assert stop_argv == [
        bounded.DOCKER,
        "container",
        "stop",
        "--time",
        str(bounded.LOCAL_BUILDKIT_STOP_GRACE_SECONDS),
        "a" * 64,
    ]
    assert 0 < stop_timeout <= bounded.LOCAL_BUILDKIT_STOP_TIMEOUT_SECONDS


def test_local_failure_refuses_rebound_builder_generation_before_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = {"builder_container_id": "a" * 64, "buildkit_image_id": "sha256:" + "b" * 64}
    before = _local_generation()
    rebound = _local_generation(container_id="c" * 64)
    commands: list[list[str]] = []
    monkeypatch.setattr(bounded, "_builder_generation", lambda _setup, **_kwargs: rebound)
    monkeypatch.setattr(
        bounded,
        "_verify_builder_stop_target",
        lambda *_args: pytest.fail("rebound generation must fail before profile checks"),
    )
    monkeypatch.setattr(bounded, "inspect_builder", lambda _setup: pytest.fail("must not inspect"))
    monkeypatch.setattr(bounded, "checked", lambda argv, **_kwargs: commands.append(argv))

    with pytest.raises(bounded.BuildError, match="local_builder_generation_changed"):
        bounded._stop_owned_builder_after_local_failure(setup, before)

    assert commands == []


def _local_reconciliation_fixture_path(state: dict[str, object], key: str) -> Path:
    value = state.get(key)
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)
    raise AssertionError(f"fixture path {key!r} must be a Path or text")


def test_local_reconciliation_stop_proof_rejects_builder_id_rebind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = {"builder_container_id": "a" * 64, "buildkit_image_id": "sha256:" + "b" * 64}
    original = _local_generation(running=False)
    rebound = _local_generation(running=False, container_id="c" * 64)
    monkeypatch.setattr(bounded, "_builder_generation", lambda _setup, **_kwargs: rebound)
    monkeypatch.setattr(
        bounded,
        "_verify_builder_stop_target",
        lambda *_args: pytest.fail("rebound generation must fail before profile proof"),
    )

    with pytest.raises(
        bounded.BuildError, match="local_reconciliation_builder_generation_unverified"
    ):
        bounded._verify_local_stopped_builder(setup, original)


def test_local_reconciliation_stop_proof_reads_same_stopped_generation_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = _local_generation(running=False)
    setup = {
        "builder_container_id": stopped["container_id"],
        "buildkit_image_id": stopped["image_id"],
    }
    generations = iter((stopped, stopped))
    profile_checks: list[dict[str, object]] = []
    monkeypatch.setattr(bounded, "_builder_generation", lambda _setup, **_kwargs: next(generations))
    monkeypatch.setattr(
        bounded,
        "_verify_builder_stop_target",
        lambda _setup, observed, _deadline: profile_checks.append(observed),
    )
    monkeypatch.setattr(
        bounded,
        "_local_buildkit_cgroup_proof",
        lambda container_id: {
            "status": "absent",
            "scope_path": f"/sys/fs/cgroup/docker-{container_id}.scope",
        },
    )

    proof = bounded._verify_local_stopped_builder(setup, stopped)

    assert proof["status"] == "verified_stopped_same_generation"
    assert proof["current_generation"] == stopped
    assert proof["worker_cgroup"]["status"] == "absent"
    assert profile_checks == [stopped]


def test_builder_stop_preflight_checks_exact_profile_and_pinned_inputs_without_exec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    generation = _local_generation()
    container_id = str(generation["container_id"])
    setup = {
        "builder_container_id": container_id,
        "buildkit_image_id": generation["image_id"],
        "buildkit_config_sha256": bounded.CONFIG_SHA,
        "active_buildkit_config_sha256": "c" * 64,
        "active_buildkit_config_semantically_verified": True,
    }
    fields = (
        container_id,
        bounded.CONTAINER_NAME,
        str(generation["image_id"]),
        str(bounded.MEMORY),
        str(bounded.SWAP),
        str(bounded.CPU_QUOTA),
        str(bounded.CPU_PERIOD),
        str(bounded.PIDS_LIMIT),
        "true",
        str(generation["pid"]),
        str(generation["created"]),
        str(generation["started"]),
        str(generation["restart_count"]),
    )
    commands: list[list[str]] = []
    config_path = tmp_path / "buildkitd.toml"
    config_path.write_bytes(b"pinned config")

    def checked(argv: list[str], timeout: float = 30) -> bytes:
        assert 0 < timeout <= bounded.LOCAL_BUILDKIT_STOP_QUERY_TIMEOUT_SECONDS
        commands.append(argv)
        return ("|".join(fields) + "\n").encode()

    def verify_network(
        received_setup: dict[str, object], received_id: str, *, check: object = None
    ) -> None:
        assert received_setup is setup
        assert received_id == container_id
        assert callable(check)

    def verify_cache(
        received_setup: dict[str, object], received_id: str, *, check: object = None
    ) -> None:
        assert received_setup is setup
        assert received_id == container_id
        assert callable(check)

    monkeypatch.setattr(bounded, "checked", checked)
    monkeypatch.setattr(bounded, "CONFIG_FILE", config_path)
    monkeypatch.setattr(bounded, "sha", lambda _path: bounded.CONFIG_SHA)
    monkeypatch.setattr(bounded, "verify_installed_config", lambda: bounded.CONFIG_SHA)
    monkeypatch.setattr(bounded, "verify_active_buildkit_config", lambda *_args: "c" * 64)
    monkeypatch.setattr(bounded, "verify_builder_network", verify_network)
    monkeypatch.setattr(bounded, "verify_cache_volume", verify_cache)

    bounded._verify_builder_stop_target(setup, generation, time.monotonic() + 5)

    assert commands == [
        [
            bounded.DOCKER,
            "container",
            "inspect",
            "--format",
            "|".join(
                (
                    "{{.Id}}",
                    "{{.Name}}",
                    "{{.Image}}",
                    "{{.HostConfig.Memory}}",
                    "{{.HostConfig.MemorySwap}}",
                    "{{.HostConfig.CpuQuota}}",
                    "{{.HostConfig.CpuPeriod}}",
                    "{{.HostConfig.PidsLimit}}",
                    "{{.State.Running}}",
                    "{{.State.Pid}}",
                    "{{.Created}}",
                    "{{.State.StartedAt}}",
                    "{{.RestartCount}}",
                )
            ),
            container_id,
        ]
    ]


def test_builder_stop_preflight_rejects_changed_resource_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    generation = _local_generation()
    container_id = str(generation["container_id"])
    fields = (
        container_id,
        bounded.CONTAINER_NAME,
        str(generation["image_id"]),
        str(bounded.MEMORY - 1),
        str(bounded.SWAP),
        str(bounded.CPU_QUOTA),
        str(bounded.CPU_PERIOD),
        str(bounded.PIDS_LIMIT),
        "true",
        str(generation["pid"]),
        str(generation["created"]),
        str(generation["started"]),
        str(generation["restart_count"]),
    )
    config_path = tmp_path / "buildkitd.toml"
    config_path.write_bytes(b"pinned config")
    network_checked = False

    def checked(argv: list[str], **_kwargs: object) -> bytes:
        assert argv[:3] == [bounded.DOCKER, "container", "inspect"]
        return ("|".join(fields) + "\n").encode()

    def verify_network(*_args: object, **_kwargs: object) -> None:
        nonlocal network_checked
        network_checked = True

    monkeypatch.setattr(bounded, "checked", checked)
    monkeypatch.setattr(bounded, "CONFIG_FILE", config_path)
    monkeypatch.setattr(bounded, "verify_builder_network", verify_network)
    monkeypatch.setattr(
        bounded, "verify_cache_volume", lambda *_args, **_kwargs: pytest.fail("must fail first")
    )

    with pytest.raises(bounded.BuildError, match="local_builder_profile_changed"):
        bounded._verify_builder_stop_target(
            {"buildkit_image_id": generation["image_id"]},
            generation,
            time.monotonic() + 5,
        )

    assert network_checked is False


def _empty_cgroup_tree(scope: Path) -> None:
    scope.mkdir(parents=True)
    (scope / "cgroup.procs").write_bytes(b"")
    (scope / "cgroup.threads").write_bytes(b"")


def test_local_builder_cgroup_proof_accepts_only_empty_or_absent_exact_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system_slice = tmp_path / "sys/fs/cgroup/system.slice"
    system_slice.mkdir(parents=True)
    monkeypatch.setattr(bounded, "LOCAL_BUILDKIT_CGROUP_SYSTEM_SLICE", system_slice)
    container_id = "a" * 64

    absent = bounded._local_buildkit_cgroup_proof(container_id)
    assert absent["status"] == "absent"
    assert absent["scope_path"] == str(system_slice / f"docker-{container_id}.scope")

    scope = system_slice / f"docker-{container_id}.scope"
    _empty_cgroup_tree(scope)
    buildkit = scope / "buildkit"
    _empty_cgroup_tree(buildkit)
    child = buildkit / "worker"
    _empty_cgroup_tree(child)
    proof = bounded._local_buildkit_cgroup_proof(container_id)
    assert proof["status"] == "empty"
    assert proof["directories_scanned"] == 3
    assert proof["process_ids_observed"] == 0


@pytest.mark.parametrize(
    "bad_tree", ["active_pid", "symlink", "missing_task_file", "deep", "entries", "too_many_pids"]
)
def test_local_builder_cgroup_proof_fails_closed_on_live_or_unknown_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_tree: str
) -> None:
    system_slice = tmp_path / "sys/fs/cgroup/system.slice"
    system_slice.mkdir(parents=True)
    monkeypatch.setattr(bounded, "LOCAL_BUILDKIT_CGROUP_SYSTEM_SLICE", system_slice)
    container_id = "b" * 64
    scope = system_slice / f"docker-{container_id}.scope"
    _empty_cgroup_tree(scope)
    if bad_tree == "active_pid":
        (scope / "cgroup.threads").write_bytes(b"321\n")
    elif bad_tree == "symlink":
        outside = tmp_path / "outside"
        _empty_cgroup_tree(outside)
        (scope / "worker").symlink_to(outside, target_is_directory=True)
    elif bad_tree == "missing_task_file":
        (scope / "cgroup.procs").unlink()
    elif bad_tree == "deep":
        nested = scope / "nested"
        _empty_cgroup_tree(nested)
        monkeypatch.setattr(bounded, "LOCAL_BUILDKIT_CGROUP_MAX_DEPTH", 0)
    elif bad_tree == "entries":
        monkeypatch.setattr(bounded, "LOCAL_BUILDKIT_CGROUP_MAX_ENTRIES", 1)
    else:
        monkeypatch.setattr(bounded, "LOCAL_BUILDKIT_CGROUP_MAX_PIDS", 1)
        (scope / "cgroup.procs").write_bytes(b"321\n322\n")

    expected = (
        "local_reconciliation_buildkit_worker_active"
        if bad_tree == "active_pid"
        else "local_reconciliation_cgroup_entries_exceeded"
        if bad_tree in {"entries", "too_many_pids"}
        else "local_reconciliation_cgroup_depth_exceeded"
        if bad_tree == "deep"
        else "local_reconciliation_cgroup_metadata_invalid"
        if bad_tree == "symlink"
        else "local_reconciliation_cgroup_metadata_unavailable"
    )
    with pytest.raises(bounded.BuildError, match=expected):
        bounded._local_buildkit_cgroup_proof(container_id)


def test_local_failure_refuses_a_second_inflight_reservation() -> None:
    revision = "1" * 40
    context_hash = "2" * 64
    tag = f"stock-probs:local-{revision[:12]}-{context_hash[:12]}-{'3' * 12}"
    first = {
        "image_id": bounded._reservation_image_id(tag),
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": "current",
        "status": "inflight",
    }
    second_tag = f"stock-probs:local-{'4' * 12}-{'5' * 12}-{'6' * 12}"
    second = {
        "image_id": bounded._reservation_image_id(second_tag),
        "tag": second_tag,
        "revision": "4" * 40,
        "context_sha256": "5" * 64,
        "role": "current",
        "status": "inflight",
    }

    with pytest.raises(bounded.BuildError, match="local_inflight_ledger_binding_mismatch"):
        bounded._validate_local_inflight_identity(
            {"entries": [first, second]},
            tag=tag,
            revision=revision,
            context_hash=context_hash,
        )


@pytest.mark.parametrize(
    ("stop_result", "expected_secondary"),
    [
        (None, "local_builder_stop_unverified"),
        (
            {
                "status": "verified_stopped_same_generation",
                "stop_error_code": "fixed_command_failed",
            },
            "fixed_command_failed",
        ),
    ],
)
def test_local_failure_retains_reservation_and_primary_error_when_backend_stop_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop_result: dict[str, object] | None,
    expected_secondary: str,
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    runs = state / "build-runs"
    runs.mkdir(mode=0o700)
    runs.chmod(0o700)
    ledger_path = state / "candidate-ledger.json"
    ledger_path.write_text(json.dumps({"schema": bounded.LEDGER_SCHEMA, "entries": []}))
    ledger_path.chmod(0o600)
    lock_path = state / "candidate-ledger.lock"
    setup = {
        "legacy_task_image_inventory": {},
        "builder_container_id": "a" * 64,
        "buildkit_image_id": "sha256:" + "b" * 64,
    }
    setup_sha = hashlib.sha256(b"pinned setup receipt").hexdigest()
    context_hash = "c" * 64
    revision = "d" * 40
    generation = _local_generation()
    flags = {"process_group_reaped": False, "backend_stop_attempted": False}

    monkeypatch.setattr(bounded, "USER", SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(tmp_path)))
    monkeypatch.setattr(bounded, "STATE", state)
    monkeypatch.setattr(bounded, "RUNS", runs)
    monkeypatch.setattr(bounded, "LEDGER_FILE", ledger_path)
    monkeypatch.setattr(bounded, "LEDGER_LOCK_FILE", lock_path)
    monkeypatch.setattr(bounded, "_builder_preflight", lambda: (setup, tmp_path, "0" * 36))
    monkeypatch.setattr(bounded, "checked", lambda _argv, **_kwargs: revision.encode())

    def build_context(destination: Path) -> str:
        destination.mkdir(mode=0o700)
        return context_hash

    monkeypatch.setattr(bounded, "_build_context", build_context)
    monkeypatch.setattr(bounded, "_context_sha256", lambda *_args: context_hash)
    monkeypatch.setattr(bounded, "_native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(bounded, "_verify_ledger_inventory", lambda *_args: None)
    monkeypatch.setattr(bounded, "_image_inventory", lambda: {})
    monkeypatch.setattr(bounded, "_all_image_ids", lambda: set())
    monkeypatch.setattr(bounded, "setup_receipt", lambda: setup)
    monkeypatch.setattr(bounded, "_current_setup_receipt_sha256", lambda: (setup, setup_sha))
    monkeypatch.setattr(bounded, "inspect_builder", lambda _setup: None)
    monkeypatch.setattr(bounded, "_builder_generation", lambda _setup: generation)
    monkeypatch.setattr(bounded, "_local_buildx_argv", lambda *_args: [bounded.DOCKER, "buildx"])

    def cli_build(*_args: object, **_kwargs: object) -> None:
        flags["process_group_reaped"] = True
        observer = _kwargs.get("phase_observer")
        assert isinstance(observer, bounded._LocalBuildPhaseObserver)
        safe_frame = {
            "vertexes": [
                _phase_vertex(
                    FRONTEND_CHECKS_VERTEX,
                    error="private-buildkit-error",
                )
            ]
        }
        read_fd, write_fd = os.pipe()
        observer.attach(os.fdopen(read_fd, "rb", buffering=0))
        os.write(write_fd, (json.dumps(safe_frame) + "\n").encode())
        os.close(write_fd)
        observer.finish()
        raise bounded.BuildError("fixed_command_unavailable_or_timeout")

    def stop(*_args: object) -> dict[str, object]:
        flags["backend_stop_attempted"] = True
        if stop_result is None:
            raise bounded.BuildError("local_builder_stop_unverified")
        return stop_result

    monkeypatch.setattr(bounded, "_run_bounded_build", cli_build)
    monkeypatch.setattr(bounded, "_stop_owned_builder_after_local_failure", stop)

    with pytest.raises(bounded.BuildError, match="fixed_command_unavailable_or_timeout") as caught:
        bounded.build_local_image()

    assert flags == {"process_group_reaped": True, "backend_stop_attempted": True}
    assert caught.value.code == "fixed_command_unavailable_or_timeout"
    assert caught.value.secondary_errors == [expected_secondary]
    ledger = json.loads(ledger_path.read_bytes())
    assert len(ledger["entries"]) == 1
    assert ledger["entries"][0]["status"] == "inflight"
    failure_path = Path(caught.value.local_failure_receipt_path)
    failure = json.loads(failure_path.read_bytes())
    assert failure["primary_error_code"] == "fixed_command_unavailable_or_timeout"
    assert failure["secondary_error_codes"] == [expected_secondary]
    assert failure["ledger_reservation_retained"] is True
    assert failure["failure_cause"] == "unproven"
    phase_observation = failure["build_phase_observation"]
    assert phase_observation["status"] == "available"
    assert phase_observation["phases"][0]["phase"] == "frontend_checks_run"
    assert phase_observation["phases"][0]["error"] is True
    assert "private-buildkit-error" not in json.dumps(failure)


def test_local_failure_receipt_write_error_does_not_mask_build_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    runs = state / "build-runs"
    runs.mkdir(mode=0o700)
    runs.chmod(0o700)
    ledger_path = state / "candidate-ledger.json"
    ledger_path.write_text(json.dumps({"schema": bounded.LEDGER_SCHEMA, "entries": []}))
    ledger_path.chmod(0o600)
    setup = {"legacy_task_image_inventory": {}}
    revision = "e" * 40
    context_hash = "f" * 64

    monkeypatch.setattr(bounded, "USER", SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(tmp_path)))
    monkeypatch.setattr(bounded, "STATE", state)
    monkeypatch.setattr(bounded, "RUNS", runs)
    monkeypatch.setattr(bounded, "LEDGER_FILE", ledger_path)
    monkeypatch.setattr(bounded, "LEDGER_LOCK_FILE", state / "candidate-ledger.lock")
    monkeypatch.setattr(bounded, "_builder_preflight", lambda: (setup, tmp_path, "0" * 36))
    monkeypatch.setattr(bounded, "checked", lambda _argv, **_kwargs: revision.encode())

    def build_context(destination: Path) -> str:
        destination.mkdir(mode=0o700)
        return context_hash

    monkeypatch.setattr(bounded, "_build_context", build_context)
    monkeypatch.setattr(bounded, "_context_sha256", lambda *_args: context_hash)
    monkeypatch.setattr(bounded, "check_space", lambda *_args, **_kwargs: 10 * 1024**3)
    monkeypatch.setattr(bounded, "_native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(bounded, "_verify_ledger_inventory", lambda *_args: None)
    monkeypatch.setattr(bounded, "_image_inventory", lambda: {})
    monkeypatch.setattr(bounded, "_all_image_ids", lambda: set())
    monkeypatch.setattr(bounded, "_current_setup_receipt_sha256", lambda: (setup, "a" * 64))
    monkeypatch.setattr(bounded, "inspect_builder", lambda _setup: None)
    monkeypatch.setattr(bounded, "_builder_generation", lambda _setup: _local_generation())
    monkeypatch.setattr(bounded, "_local_buildx_argv", lambda *_args: [bounded.DOCKER, "buildx"])
    monkeypatch.setattr(
        bounded,
        "_stop_owned_builder_after_local_failure",
        lambda *_args: {"status": "verified_stopped_same_generation"},
    )

    def reserve(
        received_setup: dict[str, object], tags: tuple[str, ...], rev: str, ctx: str, role: str
    ) -> dict[str, object]:
        assert received_setup is setup
        assert role == "current"
        entries = [
            {
                "image_id": bounded._reservation_image_id(tags[0]),
                "tag": tags[0],
                "revision": rev,
                "context_sha256": ctx,
                "role": role,
                "status": "inflight",
            }
        ]
        ledger = {"schema": bounded.LEDGER_SCHEMA, "entries": entries}
        bounded._atomic_json(ledger_path, ledger)
        return ledger

    monkeypatch.setattr(bounded, "_reserve_managed_tags", reserve)
    monkeypatch.setattr(
        bounded,
        "_run_bounded_build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(bounded.BuildError("buildx_exit_nonzero")),
    )
    monkeypatch.setattr(
        bounded,
        "_record_local_build_failure",
        lambda **_kwargs: (_ for _ in ()).throw(
            bounded.BuildError("local_failure_receipt_write_failed")
        ),
    )

    with pytest.raises(bounded.BuildError, match="buildx_exit_nonzero") as caught:
        bounded.build_local_image()

    assert caught.value.code == "buildx_exit_nonzero"
    assert caught.value.secondary_errors == ["local_failure_receipt_write_failed"]
    assert json.loads(ledger_path.read_bytes())["entries"][0]["status"] == "inflight"


def _write_private_json(path: Path, document: dict[str, object]) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    raw = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return hashlib.sha256(raw).hexdigest()


def _local_reconciliation_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    state = tmp_path / "state"
    runs = state / "build-runs"
    revision = "a" * 40
    context_hash = "b" * 64
    tag = f"stock-probs:local-{revision[:12]}-{context_hash[:12]}-{'c' * 12}"
    run_key = hashlib.sha256((tag + "\0" + context_hash).encode()).hexdigest()
    run_dir = runs / revision / run_key
    for directory in (state, runs, runs / revision, run_dir):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    ledger_path = state / "candidate-ledger.json"
    inflight = {
        "image_id": bounded._reservation_image_id(tag),
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": "current",
        "status": "inflight",
    }
    ledger = {"schema": bounded.LEDGER_SCHEMA, "entries": [inflight]}
    ledger_path.write_text(json.dumps(ledger, sort_keys=True, indent=2) + "\n")
    ledger_path.chmod(0o600)
    ledger_raw = ledger_path.read_bytes()
    setup = {
        "legacy_task_image_inventory": {},
        "builder_container_id": "a" * 64,
        "buildkit_image_id": "sha256:" + "b" * 64,
    }
    setup_sha = "f" * 64
    observations_root = tmp_path / "observations"
    observations_root.mkdir(mode=0o700)
    observations_root.chmod(0o700)
    monkeypatch.setattr(bounded, "USER", SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(tmp_path)))
    monkeypatch.setattr(bounded, "STATE", state)
    monkeypatch.setattr(bounded, "RUNS", runs)
    monkeypatch.setattr(bounded, "LEDGER_FILE", ledger_path)
    monkeypatch.setattr(bounded, "LEDGER_LOCK_FILE", state / "candidate-ledger.lock")
    monkeypatch.setattr(bounded, "LOCAL_OBSERVATION_ROOT", observations_root)
    monkeypatch.setattr(bounded, "_current_setup_receipt_sha256", lambda: (setup, setup_sha))
    monkeypatch.setattr(bounded, "_builder_generation", lambda _setup: _local_generation())
    monkeypatch.setattr(bounded, "_verify_local_observation_mount", lambda _root: None)
    monkeypatch.setattr(
        bounded,
        "_assert_no_running_buildkit_history",
        lambda: {"row_count": 1, "sha256": "1" * 64},
    )
    monkeypatch.setattr(bounded, "_image_inventory", lambda: {})
    monkeypatch.setattr(bounded, "_all_image_ids", lambda: set())

    started = datetime.now(UTC) - timedelta(minutes=5)
    finished = started + timedelta(seconds=4)
    preflight_at = finished + timedelta(seconds=1)
    cancellation_at = preflight_at + timedelta(seconds=1)
    cancellation_finished = cancellation_at + timedelta(seconds=2)
    settled_at = cancellation_finished + timedelta(minutes=1)
    builder_started = "2026-10-15T15:00:00Z"
    builder_id = str(setup["builder_container_id"])
    builder_image = str(setup["buildkit_image_id"])
    worker_pid = 4321
    terminal = {
        "command": ["./scripts/local-compose.sh", "build"],
        "started": started.isoformat(),
        "finished": finished.isoformat(),
        "exit_code": 1,
        "source_unchanged": True,
        "reason": None,
        "log_sha256": "2" * 64,
        "log_bytes": 70,
        "source_after": {"context_sha256": context_hash, "files": {"Dockerfile": "3" * 64}},
    }
    terminal_path = observations_root / "terminal.json"
    terminal_sha = _write_private_json(terminal_path, terminal)
    preflight = {
        "kind": "read_only_failed_build_worker_preflight",
        "mutation": "none",
        "build_terminal_sha256": terminal_sha,
        "source_context_sha256": context_hash,
        "source_inputs": 1,
        "recorded_at": preflight_at.isoformat(),
        "build_result": {
            key: terminal[key]
            for key in (
                "started",
                "finished",
                "exit_code",
                "source_unchanged",
                "log_sha256",
                "log_bytes",
            )
        },
        "ledger_sha256": hashlib.sha256(ledger_raw).hexdigest(),
        "ledger": ledger,
        "builder_inspect": {
            "exit_code": 0,
            "stdout": f"{builder_id}|running|123|false|0|{builder_started}\n",
        },
        "processes": [
            {
                "pid": worker_pid,
                "status": {"Name": "next-build"},
                "cgroup": f"0::/system.slice/docker-{builder_id}.scope/buildkit/worker",
            }
        ],
    }
    preflight_path = observations_root / "preflight.json"
    preflight_sha = _write_private_json(preflight_path, preflight)
    cancellation = {
        "kind": "exact_owned_failed_build_cancellation",
        "started": cancellation_at.isoformat(),
        "finished": cancellation_finished.isoformat(),
        "preflight_sha256": preflight_sha,
        "builder_id": builder_id,
        f"owned_worker_{worker_pid}_absent": True,
        "unrelated_app_unchanged": True,
        "ledger_unchanged": True,
        "no_image_cache_or_ledger_mutation": True,
        "unrelated_app_before": {"id": "app"},
        "unrelated_app_after": {"id": "app"},
        "builder_before": {
            "exit_code": 0,
            "stdout": (f"{builder_id}|running|123|false|0|{builder_started}|{builder_image}\n"),
        },
        "builder_after": {
            "exit_code": 0,
            "stdout": (f"{builder_id}|exited|0|false|0|{builder_started}|{builder_image}\n"),
        },
        "stop_result": {"exit_code": 0},
    }
    cancellation_path = observations_root / "cancellation.json"
    cancellation_sha = _write_private_json(cancellation_path, cancellation)
    history = {
        "cached_steps": 0,
        "completed_at": (started - timedelta(days=1) + timedelta(seconds=1)).isoformat(),
        "completed_steps": 1,
        "created_at": (started - timedelta(days=1)).isoformat(),
        "name": "older-build",
        "ref": f"r120-bounded/r120-bounded0/{'a' * 25}",
        "status": "completed",
        "total_steps": 1,
    }
    history_path = observations_root / "history.jsonl"
    history_raw = _encode_buildkit_history_jsonl([history])
    history_path.write_bytes(history_raw)
    history_path.chmod(0o600)
    settled = {
        "kind": "post_cancellation_read_only_history_and_exact_tag",
        "mutation": "none",
        "recorded_at": settled_at.isoformat(),
        "ledger_sha256": hashlib.sha256(ledger_raw).hexdigest(),
        "ledger_entries": 1,
        "history": {
            "path": str(history_path),
            "sha256": hashlib.sha256(history_raw).hexdigest(),
            "bytes": len(history_raw),
            "row_count": 1,
            "current_window_rows": [],
            "running_rows": [],
        },
        "exact_tag_inventory": {"tag": tag, "stdout": "", "absent": True},
    }
    settled_path = observations_root / "settled.json"
    settled_sha = _write_private_json(settled_path, settled)
    return {
        "state": state,
        "runs": runs,
        "run_dir": run_dir,
        "ledger_path": ledger_path,
        "ledger_bytes": ledger_raw,
        "setup": setup,
        "tag": tag,
        "revision": revision,
        "context_hash": context_hash,
        "paths": (terminal_path, preflight_path, cancellation_path, settled_path),
        "hashes": (terminal_sha, preflight_sha, cancellation_sha, settled_sha),
        "documents": (terminal, preflight, cancellation, settled),
        "observations_root": observations_root,
    }


def test_typed_local_reconciliation_releases_only_the_proven_inflight_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    terminal_path, preflight_path, cancellation_path, settled_path = state["paths"]
    terminal_sha, preflight_sha, cancellation_sha, settled_sha = state["hashes"]

    result = bounded._reconcile_local_inflight_reservation(
        tag=str(state["tag"]),
        revision=str(state["revision"]),
        context_hash=str(state["context_hash"]),
        role="current",
        terminal_observation=terminal_path,
        terminal_sha256=terminal_sha,
        preflight_observation=preflight_path,
        preflight_sha256=preflight_sha,
        cancellation_observation=cancellation_path,
        cancellation_sha256=cancellation_sha,
        settled_observation=settled_path,
        settled_sha256=settled_sha,
    )

    assert result["status"] == "local_inflight_reconciled"
    assert (
        json.loads(_local_reconciliation_fixture_path(state, "ledger_path").read_bytes())["entries"]
        == []
    )
    receipt = json.loads(Path(result["reconciliation_receipt"]).read_bytes())
    assert receipt["cause"] == "unproven"
    assert receipt["external_evidence"]["mode"] == "external_terminal_and_readback"


def test_typed_local_reconciliation_accepts_only_a_verified_local_failure_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    generation = _local_generation()
    failure = {
        "schema": bounded.LOCAL_FAILURE_SCHEMA,
        "status": "failed",
        "tag": state["tag"],
        "revision": state["revision"],
        "context_sha256": state["context_hash"],
        "role": "current",
        "builder": bounded.BUILDER,
        "setup_receipt_sha256": "f" * 64,
        "reservation_ledger_sha256": hashlib.sha256(state["ledger_bytes"]).hexdigest(),
        "failure_ledger_sha256": hashlib.sha256(state["ledger_bytes"]).hexdigest(),
        "ledger_reservation_retained": True,
        "local_tag_and_placeholder_absent": True,
        "remaining_inventory_matches": True,
        "build_completed": False,
        "finished_utc": datetime.now(UTC).isoformat(),
        "primary_error_code": "fixed_command_unavailable_or_timeout",
        "builder_generation_before": generation,
        "backend_cancellation": {
            "status": "verified_stopped_same_generation",
            "builder_container_id": generation["container_id"],
            "generation": {key: generation[key] for key in ("created", "started", "restart_count")},
            "stop_grace_seconds": bounded.LOCAL_BUILDKIT_STOP_GRACE_SECONDS,
        },
        "failure_cause": "unproven",
    }
    failure_path = _local_reconciliation_fixture_path(state, "run_dir") / "local-failure.json"
    failure_sha = _write_private_json(failure_path, failure)
    stopped_generation = _local_generation(running=False)
    monkeypatch.setattr(
        bounded,
        "_verify_local_stopped_builder",
        lambda _setup, expected: {
            "status": "verified_stopped_same_generation",
            "builder_container_id": expected["container_id"],
            "current_generation": stopped_generation,
            "worker_cgroup": {"status": "empty", "process_ids_observed": 0},
        },
    )
    monkeypatch.setattr(
        bounded,
        "_assert_no_running_buildkit_history",
        lambda: pytest.fail("a stopped backend cannot provide historical BuildKit status"),
    )

    result = bounded._reconcile_local_inflight_reservation(
        tag=str(state["tag"]),
        revision=str(state["revision"]),
        context_hash=str(state["context_hash"]),
        role="current",
        local_failure_receipt_sha256=failure_sha,
    )

    assert result["status"] == "local_inflight_reconciled"
    assert (
        json.loads(_local_reconciliation_fixture_path(state, "ledger_path").read_bytes())["entries"]
        == []
    )
    receipt = json.loads(Path(result["reconciliation_receipt"]).read_bytes())
    evidence = receipt["external_evidence"]
    assert evidence["historical_buildkit_terminal"] == "unavailable"
    assert evidence["fresh_stopped_backend"]["worker_cgroup"]["status"] == "empty"
    assert receipt["current_buildkit_history"]["status"] == "unavailable_backend_stopped"


def _local_unverified_failure_fixture(
    state: dict[str, object], **updates: object
) -> tuple[dict[str, object], str]:
    ledger_bytes = state["ledger_bytes"]
    assert isinstance(ledger_bytes, bytes)
    generation = _local_generation()
    failure: dict[str, object] = {
        "schema": bounded.LOCAL_FAILURE_SCHEMA,
        "status": "failed",
        "tag": state["tag"],
        "revision": state["revision"],
        "context_sha256": state["context_hash"],
        "role": "current",
        "builder": bounded.BUILDER,
        "setup_receipt_sha256": "f" * 64,
        "reservation_ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "failure_ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "ledger_reservation_retained": True,
        "reservation_verification_error": "fixed_command_unavailable_or_timeout",
        "local_tag_and_placeholder_absent": None,
        "remaining_inventory_matches": None,
        "build_completed": False,
        "finished_utc": datetime.now(UTC).isoformat(),
        "primary_error_code": "bounded_build_timeout_cancel_unverified",
        "secondary_error_codes": [
            "fixed_command_unavailable_or_timeout",
            "fixed_command_unavailable_or_timeout",
        ],
        "builder_generation_before": generation,
        "backend_cancellation": {
            "status": "unverified",
            "error_code": "fixed_command_unavailable_or_timeout",
        },
        "failure_cause": "unproven",
    }
    failure.update(updates)
    failure_path = _local_reconciliation_fixture_path(state, "run_dir") / "local-failure.json"
    failure_sha = _write_private_json(failure_path, failure)
    return failure, failure_sha


def test_typed_local_reconciliation_uses_fresh_stop_for_unverified_timeout_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    failure, failure_sha = _local_unverified_failure_fixture(state)
    stopped_generation = _local_generation(running=False)
    observed: list[dict[str, object]] = []

    def verify_stopped(
        received_setup: dict[str, object], original: dict[str, object]
    ) -> dict[str, object]:
        assert received_setup is state["setup"]
        assert original == failure["builder_generation_before"]
        observed.append(original)
        scope_path = f"/sys/fs/cgroup/system.slice/docker-{original['container_id']}.scope"
        return {
            "status": "verified_stopped_same_generation",
            "builder_container_id": original["container_id"],
            "current_generation": stopped_generation,
            "worker_cgroup": {
                "status": "absent",
                "scope_path": scope_path,
                "process_ids_observed": 0,
            },
        }

    monkeypatch.setattr(bounded, "_verify_local_stopped_builder", verify_stopped)
    monkeypatch.setattr(
        bounded,
        "_assert_no_running_buildkit_history",
        lambda: pytest.fail("unverified historical terminal must not invoke Buildx"),
    )

    result = bounded._reconcile_local_inflight_reservation(
        tag=str(state["tag"]),
        revision=str(state["revision"]),
        context_hash=str(state["context_hash"]),
        role="current",
        local_failure_receipt_sha256=failure_sha,
    )

    assert result["status"] == "local_inflight_reconciled"
    assert observed == [failure["builder_generation_before"]]
    receipt = json.loads(Path(result["reconciliation_receipt"]).read_bytes())
    evidence = receipt["external_evidence"]
    assert evidence["backend_cancellation"]["status"] == "unverified"
    assert evidence["historical_buildkit_terminal"] == "unavailable"
    assert evidence["historical_tag_absence"] == "unavailable"
    assert evidence["historical_inventory_match"] == "unavailable"
    assert evidence["fresh_inventory"]["exact_tag_absent"] is True
    assert evidence["fresh_inventory"]["placeholder_image_id_absent"] is True
    assert receipt["current_buildkit_history"]["status"] == "unavailable_backend_stopped"
    assert (
        json.loads(_local_reconciliation_fixture_path(state, "ledger_path").read_bytes())["entries"]
        == []
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"local_tag_and_placeholder_absent": False},
        {"remaining_inventory_matches": False},
        {"reservation_verification_error": "candidate_ledger_inventory_mismatch"},
        {
            "backend_cancellation": {
                "status": "unverified",
                "error_code": "candidate_ledger_inventory_mismatch",
            }
        },
        {"secondary_error_codes": ["local_reconciliation_inventory_mismatch"]},
    ],
)
def test_typed_local_reconciliation_rejects_historical_negative_or_unknown_error_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, object],
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    _failure, failure_sha = _local_unverified_failure_fixture(state, **updates)
    monkeypatch.setattr(
        bounded,
        "_verify_local_stopped_builder",
        lambda *_args: pytest.fail("historical negative facts must fail before fresh proof"),
    )

    with pytest.raises(
        bounded.BuildError, match="local_reconciliation_failure_receipt_contract_mismatch"
    ):
        bounded._reconcile_local_inflight_reservation(
            tag=str(state["tag"]),
            revision=str(state["revision"]),
            context_hash=str(state["context_hash"]),
            role="current",
            local_failure_receipt_sha256=failure_sha,
        )

    assert (
        _local_reconciliation_fixture_path(state, "ledger_path").read_bytes()
        == state["ledger_bytes"]
    )


def test_typed_local_reconciliation_keeps_reservation_when_fresh_tag_is_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    _failure, failure_sha = _local_unverified_failure_fixture(state)
    monkeypatch.setattr(
        bounded,
        "_verify_local_stopped_builder",
        lambda _setup, expected: {
            "status": "verified_stopped_same_generation",
            "builder_container_id": expected["container_id"],
            "current_generation": _local_generation(running=False),
            "worker_cgroup": {"status": "empty", "process_ids_observed": 0},
        },
    )
    monkeypatch.setattr(
        bounded, "_image_inventory", lambda: {str(state["tag"]): "sha256:" + "9" * 64}
    )

    with pytest.raises(
        bounded.BuildError, match="local_reconciliation_candidate_image_still_present"
    ):
        bounded._reconcile_local_inflight_reservation(
            tag=str(state["tag"]),
            revision=str(state["revision"]),
            context_hash=str(state["context_hash"]),
            role="current",
            local_failure_receipt_sha256=failure_sha,
        )

    assert (
        _local_reconciliation_fixture_path(state, "ledger_path").read_bytes()
        == state["ledger_bytes"]
    )


def test_typed_local_reconciliation_rolls_back_if_recovery_receipt_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    _failure, failure_sha = _local_unverified_failure_fixture(state)
    monkeypatch.setattr(
        bounded,
        "_verify_local_stopped_builder",
        lambda _setup, expected: {
            "status": "verified_stopped_same_generation",
            "builder_container_id": expected["container_id"],
            "current_generation": _local_generation(running=False),
            "worker_cgroup": {"status": "absent", "process_ids_observed": 0},
        },
    )
    monkeypatch.setattr(
        bounded,
        "_publish_receipt_no_replace",
        lambda *_args: (_ for _ in ()).throw(OSError("fixture publication failure")),
    )

    with pytest.raises(bounded.BuildError, match="local_reconciliation_receipt_publish_failed"):
        bounded._reconcile_local_inflight_reservation(
            tag=str(state["tag"]),
            revision=str(state["revision"]),
            context_hash=str(state["context_hash"]),
            role="current",
            local_failure_receipt_sha256=failure_sha,
        )

    assert (
        _local_reconciliation_fixture_path(state, "ledger_path").read_bytes()
        == state["ledger_bytes"]
    )
    assert not list(
        _local_reconciliation_fixture_path(state, "run_dir").glob(
            "local-inflight-reconciliation-*.json"
        )
    )


def test_typed_local_reconciliation_rejects_unverified_local_stop_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    failure = {
        "schema": bounded.LOCAL_FAILURE_SCHEMA,
        "status": "failed",
        "tag": state["tag"],
        "revision": state["revision"],
        "context_sha256": state["context_hash"],
        "role": "current",
        "builder": bounded.BUILDER,
        "setup_receipt_sha256": "f" * 64,
        "reservation_ledger_sha256": hashlib.sha256(state["ledger_bytes"]).hexdigest(),
        "failure_ledger_sha256": hashlib.sha256(state["ledger_bytes"]).hexdigest(),
        "ledger_reservation_retained": True,
        "local_tag_and_placeholder_absent": True,
        "remaining_inventory_matches": True,
        "finished_utc": datetime.now(UTC).isoformat(),
        "builder_generation_before": _local_generation(),
        "backend_cancellation": {"status": "unverified"},
        "failure_cause": "unproven",
    }
    failure_sha = _write_private_json(
        _local_reconciliation_fixture_path(state, "run_dir") / "local-failure.json", failure
    )
    with pytest.raises(
        bounded.BuildError, match="local_reconciliation_failure_receipt_contract_mismatch"
    ):
        bounded._reconcile_local_inflight_reservation(
            tag=str(state["tag"]),
            revision=str(state["revision"]),
            context_hash=str(state["context_hash"]),
            role="current",
            local_failure_receipt_sha256=failure_sha,
        )

    assert (
        _local_reconciliation_fixture_path(state, "ledger_path").read_bytes()
        == state["ledger_bytes"]
    )


def test_typed_local_reconciliation_restores_ledger_if_receipt_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    terminal_path, preflight_path, cancellation_path, settled_path = state["paths"]
    terminal_sha, preflight_sha, cancellation_sha, settled_sha = state["hashes"]
    monkeypatch.setattr(
        bounded,
        "_publish_receipt_no_replace",
        lambda *_args: (_ for _ in ()).throw(OSError("fixture publication failure")),
    )

    with pytest.raises(bounded.BuildError, match="local_reconciliation_receipt_publish_failed"):
        bounded._reconcile_local_inflight_reservation(
            tag=str(state["tag"]),
            revision=str(state["revision"]),
            context_hash=str(state["context_hash"]),
            role="current",
            terminal_observation=terminal_path,
            terminal_sha256=terminal_sha,
            preflight_observation=preflight_path,
            preflight_sha256=preflight_sha,
            cancellation_observation=cancellation_path,
            cancellation_sha256=cancellation_sha,
            settled_observation=settled_path,
            settled_sha256=settled_sha,
        )

    assert (
        _local_reconciliation_fixture_path(state, "ledger_path").read_bytes()
        == state["ledger_bytes"]
    )
    assert not list(
        _local_reconciliation_fixture_path(state, "run_dir").glob(
            "local-inflight-reconciliation-*.json"
        )
    )


@pytest.mark.parametrize(
    "bad_evidence", ["wrong_hash", "active_history", "builder_rebound", "tag_present"]
)
def test_typed_local_reconciliation_fails_closed_on_drifted_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_evidence: str
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    terminal_path, preflight_path, cancellation_path, settled_path = state["paths"]
    terminal_sha, preflight_sha, cancellation_sha, settled_sha = state["hashes"]
    kwargs: dict[str, object] = {}
    if bad_evidence == "wrong_hash":
        terminal_sha = "0" * 64
    elif bad_evidence == "active_history":
        settled = state["documents"][3]
        history_path = Path(settled["history"]["path"])
        active = {
            "cached_steps": 0,
            "completed_at": datetime.now(UTC).isoformat(),
            "completed_steps": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "name": "active-build",
            "ref": f"r120-bounded/r120-bounded0/{'b' * 25}",
            "status": "running",
            "total_steps": 1,
        }
        history_raw = _encode_buildkit_history_jsonl([active])
        history_path.write_bytes(history_raw)
        history_path.chmod(0o600)
        settled["history"].update(
            {
                "sha256": hashlib.sha256(history_raw).hexdigest(),
                "bytes": len(history_raw),
                "row_count": 1,
            }
        )
        settled_sha = _write_private_json(settled_path, settled)
    elif bad_evidence == "builder_rebound":
        monkeypatch.setattr(
            bounded,
            "_builder_generation",
            lambda _setup: _local_generation(container_id="9" * 64),
        )
    elif bad_evidence == "tag_present":
        monkeypatch.setattr(
            bounded, "_image_inventory", lambda: {str(state["tag"]): "sha256:" + "1" * 64}
        )
    kwargs.update(
        terminal_observation=terminal_path,
        terminal_sha256=terminal_sha,
        preflight_observation=preflight_path,
        preflight_sha256=preflight_sha,
        cancellation_observation=cancellation_path,
        cancellation_sha256=cancellation_sha,
        settled_observation=settled_path,
        settled_sha256=settled_sha,
    )

    with pytest.raises(bounded.BuildError):
        bounded._reconcile_local_inflight_reservation(
            tag=str(state["tag"]),
            revision=str(state["revision"]),
            context_hash=str(state["context_hash"]),
            role="current",
            **kwargs,
        )

    assert (
        _local_reconciliation_fixture_path(state, "ledger_path").read_bytes()
        == state["ledger_bytes"]
    )


def test_typed_local_reconciliation_rejects_missing_evidence_before_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _local_reconciliation_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bounded,
        "_current_setup_receipt_sha256",
        lambda: pytest.fail("missing evidence must fail before state reads"),
    )

    with pytest.raises(bounded.BuildError, match="local_reconciliation_evidence_mode_invalid"):
        bounded._reconcile_local_inflight_reservation(
            tag=str(state["tag"]),
            revision=str(state["revision"]),
            context_hash=str(state["context_hash"]),
            role="current",
        )

    assert (
        _local_reconciliation_fixture_path(state, "ledger_path").read_bytes()
        == state["ledger_bytes"]
    )


def test_local_observation_reader_requires_the_pinned_sd_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        bounded,
        "checked",
        lambda argv, **_kwargs: calls.append(argv) or b"wrong-uuid\n",
    )

    with pytest.raises(bounded.BuildError, match="local_reconciliation_observation_mount_mismatch"):
        bounded._verify_local_observation_mount(Path("/var") / "tmp" / "r12r")

    assert calls == [
        [
            bounded.FINDMNT,
            "-n",
            "-o",
            "UUID",
            "--target",
            str(Path("/var") / "tmp" / "r12r"),
        ]
    ]


def test_local_reconciliation_cli_passes_only_exact_external_evidence_bindings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tag = f"stock-probs:local-{'a' * 12}-{'b' * 12}-{'c' * 12}"
    revision, context_hash = "a" * 40, "b" * 64
    observation_root = Path("/var") / "tmp" / "r12r" / "task"
    paths = tuple(
        observation_root / f"{name}.json" for name in ("terminal", "preflight", "cancel", "settled")
    )
    hashes = tuple(f"{index:x}" * 64 for index in range(1, 5))
    result = {"status": "local_inflight_reconciled", "tag": tag}
    calls: list[dict[str, object]] = []

    def reconcile(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return result

    monkeypatch.setattr(bounded.os, "geteuid", lambda: bounded.USER.pw_uid)
    monkeypatch.setattr(bounded, "validate_user_state", lambda: None)
    monkeypatch.setattr(bounded.os, "access", lambda *_args: True)
    monkeypatch.setattr(bounded, "_reconcile_local_inflight_reservation", reconcile)
    argv = [
        "bounded_docker_build.py",
        "--reconcile-local-inflight-reservation",
        "--tag",
        tag,
        "--revision",
        revision,
        "--context-sha256",
        context_hash,
        "--role",
        "current",
    ]
    for flag, path, digest in zip(
        (
            "--terminal-observation",
            "--preflight-observation",
            "--cancellation-observation",
            "--settled-observation",
        ),
        paths,
        hashes,
        strict=True,
    ):
        argv.extend((flag, str(path), f"{flag}-sha256", digest))
    monkeypatch.setattr(sys, "argv", argv)

    assert bounded.main() == 0
    assert json.loads(capsys.readouterr().out) == result
    assert calls == [
        {
            "tag": tag,
            "revision": revision,
            "context_hash": context_hash,
            "role": "current",
            "local_failure_receipt_sha256": None,
            "terminal_observation": paths[0],
            "terminal_sha256": hashes[0],
            "preflight_observation": paths[1],
            "preflight_sha256": hashes[1],
            "cancellation_observation": paths[2],
            "cancellation_sha256": hashes[2],
            "settled_observation": paths[3],
            "settled_sha256": hashes[3],
        }
    ]
