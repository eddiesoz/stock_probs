from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCAL_GATE = ROOT / "scripts/local-gate.sh"
EXPECTED_CHECKS = [
    "documentation-completeness",
    "frontend-npm-ci-typecheck-build-test-stage",
    "python-checks",
]


def _fixture(tmp_path: Path, *, kind: str = "complete") -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".dev-venv/bin").mkdir(parents=True)
    (repo / "frontend").mkdir()
    (repo / "docs").mkdir()
    script = LOCAL_GATE.read_text(encoding="utf-8")
    if kind == "incomplete":
        # Exercise the genuine EXIT receipt trap after an early successful shell path: the
        # disposable copy deliberately skips its profile case while retaining all other code.
        source = 'case "$PROFILE" in'
        index = script.rfind(source)
        assert index > 0
        script = script[:index] + script[index:].replace(
            source, 'case "__fixture_without_profile_match__" in', 1
        )
    (repo / "scripts/local-gate.sh").write_text(script, encoding="utf-8")
    (repo / "scripts/bootstrap.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'if [[ -n "${FIXTURE_BOOTSTRAP_READY:-}" ]]; then : >"$FIXTURE_BOOTSTRAP_READY"; fi\n'
        'if [[ -n "${FIXTURE_BOOTSTRAP_WAIT:-}" ]]; then\n'
        '  while [[ ! -e "$FIXTURE_BOOTSTRAP_WAIT" ]]; do sleep 0.05; done\n'
        "fi\n"
        'exit "${FIXTURE_BOOTSTRAP_EXIT:-0}"\n',
        encoding="utf-8",
    )
    (repo / "scripts/build-frontend.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    (repo / "scripts/check-doc-coverage.py").write_text("# synthetic no-op\n", encoding="utf-8")
    (repo / "scripts/comment_audit.py").write_text("# synthetic no-op\n", encoding="utf-8")
    (repo / "frontend/package-lock.json").write_text("{}\n", encoding="utf-8")
    (repo / "documentation-map.json").write_text("{}\n", encoding="utf-8")
    python_stub = repo / ".dev-venv/bin/python"
    python_stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${FIXTURE_FAIL_STAGE:-}" == "ruff" && '
        '"$*" == "-m ruff check src tests scripts" ]]; then exit 17; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    for path in (
        repo / "scripts/local-gate.sh",
        repo / "scripts/bootstrap.sh",
        repo / "scripts/build-frontend.sh",
        python_stub,
    ):
        path.chmod(0o755)

    subprocess.run(  # noqa: S603 - fixed Git executable and fixture-owned directory
        ["/usr/bin/git", "-C", str(repo), "init", "-q"], check=True, timeout=5
    )
    subprocess.run(  # noqa: S603 - fixed Git executable and fixture-owned directory
        ["/usr/bin/git", "-C", str(repo), "config", "user.name", "Local Gate Fixture"],
        check=True,
        timeout=5,
    )
    subprocess.run(  # noqa: S603 - fixed Git executable and fixture-owned directory
        ["/usr/bin/git", "-C", str(repo), "config", "user.email", "fixture@example.invalid"],
        check=True,
        timeout=5,
    )
    subprocess.run(  # noqa: S603 - fixed Git executable and fixture-owned directory
        ["/usr/bin/git", "-C", str(repo), "add", "."], check=True, timeout=5
    )
    subprocess.run(  # noqa: S603 - fixed Git executable and fixture-owned directory
        ["/usr/bin/git", "-C", str(repo), "commit", "-qm", "fixture"], check=True, timeout=5
    )

    home = tmp_path / "home"
    temp = tmp_path / "tmp"
    home.mkdir()
    temp.mkdir(mode=0o700)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(temp),
        "TASK_ID": "R-ASTRA-120",
        "DOC_GATE_TIMEOUT_SECONDS": "10",
        "PYTHONNOUSERSITE": "1",
    }
    if kind == "failure":
        env["FIXTURE_FAIL_STAGE"] = "ruff"
    if kind == "write-failure":
        fake_bin = tmp_path / "fake-bin"
        fake_bin.mkdir()
        fake_python = fake_bin / "python3"
        fake_python.write_text("#!/usr/bin/env bash\nexit 19\n", encoding="utf-8")
        fake_python.chmod(0o755)
        env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
    return repo, env


def _receipt(repo: Path) -> dict[str, object]:
    receipts = list((repo / "test-results/local-gates").glob("R-ASTRA-120-*/evidence.json"))
    assert len(receipts) == 1
    return json.loads(receipts[0].read_text(encoding="utf-8"))


def _run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed shell script in the disposable fixture tree
        ["/bin/bash", str(repo / "scripts/local-gate.sh"), "check"],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _proc_identity(pid: int) -> dict[str, str | int] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return None
    close = raw.rfind(")")
    if close < 0:
        return None
    fields = raw[close + 1 :].split()
    if len(fields) <= 19:
        return None
    try:
        return {
            "pid": pid,
            "pgid": int(fields[2]),
            "sid": int(fields[3]),
            "start_token": f"{boot}:{fields[19]}",
        }
    except ValueError:
        return None


def _wait_for_file(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.025)
    pytest.fail("fixture gate did not reach its signal-ready barrier")


def _wait_for_identity(pid: int, timeout: float) -> dict[str, str | int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = _proc_identity(pid)
        if identity is not None:
            return identity
        time.sleep(0.01)
    pytest.fail("fixture gate did not expose a stable /proc start identity")


def test_check_profile_writes_pass_only_after_all_three_checks(tmp_path: Path) -> None:
    repo, env = _fixture(tmp_path)

    completed = _run(repo, env)

    receipt = _receipt(repo)
    assert completed.returncode == 0
    assert receipt["result"] == "Pass"
    assert receipt["exit_code"] == 0
    assert receipt["completed_checks"] == EXPECTED_CHECKS
    assert receipt["expected_checks"] == EXPECTED_CHECKS
    assert receipt["completion_contract_satisfied"] is True


def test_check_profile_refuses_pass_when_shell_exits_zero_before_profile_checks(
    tmp_path: Path,
) -> None:
    repo, env = _fixture(tmp_path, kind="incomplete")

    completed = _run(repo, env)

    receipt = _receipt(repo)
    assert completed.returncode == 1
    assert receipt["result"] == "Fail"
    assert receipt["exit_code"] == 1
    assert receipt["completed_checks"] == EXPECTED_CHECKS[:2]
    assert receipt["expected_checks"] == EXPECTED_CHECKS
    assert receipt["completion_contract_satisfied"] is False


def test_check_profile_preserves_nonzero_failure_in_terminal_receipt(tmp_path: Path) -> None:
    repo, env = _fixture(tmp_path, kind="failure")

    completed = _run(repo, env)

    receipt = _receipt(repo)
    assert completed.returncode == 17
    assert receipt["result"] == "Fail"
    assert receipt["exit_code"] == 17
    assert receipt["completion_contract_satisfied"] is False
    assert receipt["expected_checks"] == EXPECTED_CHECKS


def test_check_profile_fails_when_terminal_receipt_writer_fails(tmp_path: Path) -> None:
    repo, env = _fixture(tmp_path, kind="write-failure")

    completed = _run(repo, env)

    assert completed.returncode == 1
    assert "failed to write terminal evidence" in completed.stderr
    assert not list((repo / "test-results/local-gates").glob("R-ASTRA-120-*/evidence.json"))


@pytest.mark.parametrize(
    ("sig", "expected_exit"),
    [(signal.SIGTERM, 143), (signal.SIGINT, 130), (signal.SIGHUP, 129)],
)
def test_check_profile_records_owned_process_group_signals_as_failures(
    tmp_path: Path,
    sig: signal.Signals,
    expected_exit: int,
) -> None:
    repo, env = _fixture(tmp_path)
    ready = tmp_path / "bootstrap-ready"
    release = tmp_path / "bootstrap-release"
    env.update({"FIXTURE_BOOTSTRAP_READY": str(ready), "FIXTURE_BOOTSTRAP_WAIT": str(release)})
    stdout_path = tmp_path / "gate.stdout"
    stderr_path = tmp_path / "gate.stderr"
    process = subprocess.Popen(  # noqa: S603 - fixed shell script in the disposable fixture tree
        ["/bin/bash", str(repo / "scripts/local-gate.sh"), "check"],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=stdout_path.open("wb"),
        stderr=stderr_path.open("wb"),
        start_new_session=True,
        close_fds=True,
    )
    identity: dict[str, str | int] | None = _wait_for_identity(process.pid, 2)
    try:
        _wait_for_file(ready, 5)
        assert identity["pid"] == identity["pgid"] == identity["sid"] == process.pid
        current = _proc_identity(process.pid)
        assert current == identity
        os.killpg(process.pid, sig)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            current = _proc_identity(process.pid)
            if current == identity:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            pytest.fail("signal-bound fixture gate did not terminate within its limit")
    finally:
        if process.poll() is None:
            current = _proc_identity(process.pid)
            if identity is not None and current == identity:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        stdout_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
    receipt = _receipt(repo)
    assert process.returncode == expected_exit
    assert receipt["result"] == "Fail"
    assert receipt["exit_code"] == expected_exit
    assert receipt["completion_contract_satisfied"] is False
    assert receipt["expected_checks"] == EXPECTED_CHECKS
    assert receipt["result"] != "Pass"
