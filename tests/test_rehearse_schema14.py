from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import research_recovery_overlay as overlay
from scripts.rehearse_schema14 import (
    _API_CONTENT_CHECKS,
    _FIXTURE_CLOCK,
    Deployment,
    LocalDockerSchema14Adapter,
    OwnerApiEvidence,
    OwnerFixture,
    ResponseDigest,
    Schema14RehearsalError,
    _load_runtime_primitives,
    _runtime_verifier_source,
    load_reviewed_candidate_binding,
    main,
    parse_reviewed_candidate_binding,
    run_schema14_rehearsal,
)

_VOLUME = "disposable-volume-r1-schema14"
_CANDIDATE_IMAGE = "sha256:" + "1" * 64
_RECOVERY_IMAGE = "sha256:" + "2" * 64
_OWNER_FIXTURES = (
    OwnerFixture(
        "owner_a",
        101,
        "11111111-1111-4111-8111-111111111111",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ),
    OwnerFixture(
        "owner_b",
        202,
        "22222222-2222-4222-8222-222222222222",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ),
)


def _binding_raw(**changes: object) -> bytes:
    value: dict[str, object] = {
        "format_version": 1,
        "status": "Pass",
        "review_scope": "r1-schema14-f6-recovery-input",
        "f6_merged": True,
        "f6_merge_commit": "f" * 40,
        "f6_merge_is_candidate_ancestor": True,
        "candidate_source_commit": "c" * 40,
        "candidate_image_digest": _CANDIDATE_IMAGE,
        "candidate_repository_blob_sha1": "a" * 40,
        "candidate_repository_sha256": "b" * 64,
        "recovery_image_digest": _RECOVERY_IMAGE,
        "recovery_source_revision": overlay.BASELINE_REVISION,
        "recovery_repository_sha256": overlay.OVERLAY_REPOSITORY_SHA256,
        "recovery_overlay_sha256": overlay.OVERLAY_SHA256,
        "migration14_sha256": overlay.MIGRATION_SHA256,
        "source_review_sha256": "3" * 64,
        "independent_qa_sha256": "4" * 64,
        "parent_review_sha256": "5" * 64,
    }
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _run(adapter: FakeAdapter, tmp_path) -> dict[str, object]:
    raw = _binding_raw()
    path = tmp_path / "reviewed-binding.json"
    if not path.exists():
        path.write_bytes(raw)
        path.chmod(0o600)
    return run_schema14_rehearsal(adapter, path, hashlib.sha256(raw).hexdigest())


def _snapshot(*, assistant_message_digest: str | None = None) -> dict[str, object]:
    tables: dict[str, dict[str, object]] = {}
    for table in sorted(overlay.RECOVERY_REQUIRED_TABLES):
        rows = {
            "research_theses": 2,
            "research_thesis_revisions": 4,
            "research_comparisons": 2,
            "schema_migrations": 14,
            "assistant_conversations": 1,
            "assistant_turns": 1,
            "assistant_messages": 2,
            "assistant_execution_leases": 1,
        }.get(table, 0)
        row_digest = assistant_message_digest or hashlib.sha256(table.encode()).hexdigest()
        tables[table] = {
            "columns_sha256": hashlib.sha256(f"columns:{table}".encode()).hexdigest(),
            "rows": rows,
            "sha256": row_digest,
        }
    canonical = json.dumps(
        {"schema_versions": list(range(1, 15)), "tables": tables},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return {
        "schema_version": 14,
        "schema_versions": list(range(1, 15)),
        "tables": tables,
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


def _api_evidence(fixtures: tuple[OwnerFixture, ...]) -> tuple[OwnerApiEvidence, ...]:
    foreign = (
        "thesis_get",
        "thesis_revisions",
        "comparison_get",
        "comparison_export_json",
        "comparison_export_csv",
    )
    evidence = []
    for fixture in fixtures:
        other = next(candidate for candidate in fixtures if candidate != fixture)
        endpoints = (
            f"thesis_get:{fixture.thesis_id}",
            f"thesis_revisions:{fixture.thesis_id}",
            "theses_export_json",
            "theses_export_csv",
            f"comparison_get:{fixture.comparison_id}",
            f"comparison_export_json:{fixture.comparison_id}",
            f"comparison_export_csv:{fixture.comparison_id}",
        )
        evidence.append(
            OwnerApiEvidence(
                fixture.owner_slot,
                fixture.owner_id,
                fixture.thesis_id,
                fixture.comparison_id,
                other.owner_slot,
                other.thesis_id,
                other.comparison_id,
                (1, 2),
                tuple(
                    ResponseDigest(
                        endpoint,
                        200,
                        hashlib.sha256(f"{fixture.owner_slot}:{endpoint}".encode()).hexdigest(),
                        _API_CONTENT_CHECKS[endpoint.split(":", 1)[0]],
                    )
                    for endpoint in endpoints
                ),
                tuple((endpoint, 404) for endpoint in foreign),
            )
        )
    return tuple(evidence)


def _runtime_api_content_case():
    namespace = {"__name__": "schema14_content_test"}
    exec(compile(_runtime_verifier_source(), "schema14-verifier-test.py", "exec"), namespace)  # noqa: S102 - fixed generated verifier
    own = _OWNER_FIXTURES[0]
    other = _OWNER_FIXTURES[1]
    now = _FIXTURE_CLOCK
    thesis_initial = namespace["expected_thesis_data"]("owner_a", 1)
    thesis_latest = namespace["expected_thesis_data"]("owner_a", 2)
    thesis_record = {
        "id": own.thesis_id,
        "revision": 2,
        "created_at": now,
        "updated_at": now,
        "data": thesis_latest,
    }
    revisions = {
        "items": [
            {"revision": 2, "data": thesis_latest, "recorded_at": now},
            {"revision": 1, "data": thesis_initial, "recorded_at": now},
        ],
        "page": 1,
        "page_size": 20,
        "total": 2,
        "has_next": False,
    }
    thesis_json = {
        "format_version": 1,
        "items": [thesis_record],
        "revisions": [
            {"thesis_id": own.thesis_id, "revision": 1, "data": thesis_initial, "recorded_at": now},
            {"thesis_id": own.thesis_id, "revision": 2, "data": thesis_latest, "recorded_at": now},
        ],
    }
    thesis_columns = [
        "thesis_id",
        "revision",
        "recorded_at",
        "symbol",
        "asset_type",
        "title",
        "reasoning",
        "risks",
        "invalidation",
        "status",
        "review_date",
        "reviewed_at",
        "evidence_json",
        "identity_json",
    ]
    thesis_stream = io.StringIO()
    thesis_writer = csv.writer(thesis_stream)
    thesis_writer.writerow(thesis_columns)
    for revision, data in ((1, thesis_initial), (2, thesis_latest)):
        thesis_writer.writerow(
            [own.thesis_id, revision, now]
            + [data.get(key) for key in thesis_columns[3:12]]
            + [json.dumps(data["evidence"]), json.dumps(data["identity"])]
        )
    comparison_data = {
        **namespace["expected_comparison_data"](),
        "preview_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }
    comparison = {
        "id": own.comparison_id,
        "revision": None,
        "created_at": now,
        "updated_at": None,
        "data": comparison_data,
    }
    comparison_json = {"id": own.comparison_id, "created_at": now, "data": comparison_data}
    comparison_columns = [
        "snapshot_id",
        "captured_at",
        "symbol",
        "currency",
        "source",
        "as_of",
        "price_change",
        "volatility",
        "max_drawdown",
        "sample_count",
        "quality",
    ]
    comparison_stream = io.StringIO()
    comparison_writer = csv.writer(comparison_stream)
    comparison_writer.writerow(comparison_columns)
    for instrument in comparison_data["instruments"]:
        comparison_writer.writerow(
            [own.comparison_id, now] + [instrument.get(key) for key in comparison_columns[2:]]
        )
    arguments = (
        "owner_a",
        own.thesis_id,
        other.thesis_id,
        own.comparison_id,
        other.comparison_id,
        thesis_record,
        revisions,
        thesis_json,
        thesis_stream.getvalue(),
        comparison,
        comparison_json,
        comparison_stream.getvalue(),
    )
    return namespace, arguments


def _runtime_probe_namespace(payload: dict[str, object], monkeypatch) -> dict[str, object]:
    import http.client

    class FakeResponse:
        status = 200

        def read(self, limit: int) -> bytes:
            assert limit == 16_385
            return json.dumps(payload).encode("utf-8")

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            assert (host, port, timeout) == ("127.0.0.1", 8000, 2.0)

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            assert (method, path, headers) == (
                "GET",
                "/api/v1/readiness",
                {"Host": "localhost"},
            )

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(http.client, "HTTPConnection", FakeConnection)
    namespace: dict[str, object] = {"__name__": "schema14_readiness_test"}
    exec(  # noqa: S102 - fixed generated verifier
        compile(_runtime_verifier_source(), "schema14-readiness-verifier.py", "exec"),
        namespace,
    )
    return namespace


def test_generated_verifier_accepts_pinned_recovery_readiness_shape(monkeypatch, capsys):
    response = {
        "status": "ready",
        "schema_version": 14,
        "provider": "fixture",
        "assistant": {"enabled": False, "status": "disabled"},
    }
    namespace = _runtime_probe_namespace(response, monkeypatch)

    namespace["probe"]("recovery")

    assert json.loads(capsys.readouterr().out) == response


def test_generated_verifier_rejects_candidate_readiness_without_research(monkeypatch, capsys):
    response = {
        "status": "ready",
        "schema_version": 14,
        "provider": "fixture",
        "assistant": {"enabled": False, "status": "disabled"},
    }
    namespace = _runtime_probe_namespace(response, monkeypatch)

    with pytest.raises(namespace["CheckFailure"], match="readiness"):
        namespace["probe"]("candidate")

    assert capsys.readouterr().out == ""


def test_generated_verifier_requires_enabled_invited_candidate_research(monkeypatch, capsys):
    response = {
        "status": "ready",
        "schema_version": 14,
        "provider": "fixture",
        "assistant": {"enabled": False, "status": "disabled"},
        "research": {"enabled": True, "rollout_mode": "invited"},
    }
    namespace = _runtime_probe_namespace(response, monkeypatch)

    namespace["probe"]("candidate")
    assert json.loads(capsys.readouterr().out) == response


def _replace_csv_cell(raw: str, row_index: int, column: str, value: str) -> str:
    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    rows[row_index][column] = value
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=reader.fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class FakeAdapter:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.snapshot = _snapshot()
        self.recovery_snapshot = self.snapshot
        self.initial_api = _api_evidence(_OWNER_FIXTURES)
        self.final_api = self.initial_api
        self.recovery_volume = _VOLUME
        self.recovery_controls = (False, False, False)
        self.candidate_image = _CANDIDATE_IMAGE

    def start_candidate(
        self,
        binding,
        *,
        volume_id,
        assistant_enabled,
        research_enabled,
        research_canary_only,
    ):
        self.events.append(
            (
                "start_candidate",
                volume_id,
                assistant_enabled,
                research_enabled,
                research_canary_only,
            )
        )
        return Deployment(
            "candidate",
            self.candidate_image,
            binding.candidate_source_commit,
            binding.candidate_repository_blob_sha1,
            binding.candidate_repository_sha256,
            14,
            True,
            volume_id or _VOLUME,
            assistant_enabled,
            research_enabled,
            research_canary_only,
            False,
        )

    def start_recovery(
        self,
        binding,
        *,
        volume_id,
        assistant_enabled,
        research_enabled,
        research_canary_only,
        restore_database,
    ):
        self.events.append(
            (
                "start_recovery",
                volume_id,
                assistant_enabled,
                research_enabled,
                research_canary_only,
                restore_database,
            )
        )
        assistant, research, restored = self.recovery_controls
        return Deployment(
            "recovery",
            binding.recovery_image_digest,
            overlay.BASELINE_REVISION,
            None,
            overlay.OVERLAY_REPOSITORY_SHA256,
            14,
            True,
            self.recovery_volume,
            assistant,
            research,
            None,
            restored,
            overlay.OVERLAY_SHA256,
        )

    def create_two_owner_research_fixtures(self, deployment):
        self.events.append(("create_fixtures", deployment.phase))
        return _OWNER_FIXTURES

    def read_research_api(self, deployment, fixtures):
        self.events.append(("read_api", deployment.phase))
        return (
            self.initial_api
            if deployment.phase == "candidate" and self.events.count(("read_api", "candidate")) == 1
            else self.final_api
        )

    def snapshot_database(self, deployment):
        self.events.append(("snapshot", deployment.phase))
        return self.snapshot if deployment.phase == "candidate" else self.recovery_snapshot

    def stop(self, deployment):
        self.events.append(("stop", deployment.phase))


def test_review_binding_requires_exact_merged_f6_and_immutable_images() -> None:
    raw = _binding_raw()
    binding = parse_reviewed_candidate_binding(raw, hashlib.sha256(raw).hexdigest())
    assert binding.f6_merge_commit == "f" * 40
    assert binding.candidate_image_digest == _CANDIDATE_IMAGE
    assert binding.recovery_image_digest == _RECOVERY_IMAGE
    with pytest.raises(Schema14RehearsalError, match="review_binding_digest_mismatch"):
        parse_reviewed_candidate_binding(raw, "0" * 64)
    for changes in (
        {"f6_merged": False},
        {"f6_merge_is_candidate_ancestor": False},
        {"recovery_source_revision": "main"},
        {"candidate_image_digest": "signal-ledger:latest"},
    ):
        malformed = _binding_raw(**changes)
        with pytest.raises(Schema14RehearsalError):
            parse_reviewed_candidate_binding(malformed, hashlib.sha256(malformed).hexdigest())


def test_reviewed_binding_file_is_required_private_and_no_follow(tmp_path) -> None:
    path = tmp_path / "reviewed-binding.json"
    with pytest.raises(Schema14RehearsalError, match="review_binding_file_invalid"):
        load_reviewed_candidate_binding(path, "0" * 64)
    adapter = FakeAdapter()
    with pytest.raises(Schema14RehearsalError, match="review_binding_file_invalid"):
        run_schema14_rehearsal(adapter, path, "0" * 64)
    assert adapter.events == []

    raw = _binding_raw()
    path.write_bytes(raw)
    path.chmod(0o600)
    digest = hashlib.sha256(raw).hexdigest()
    assert load_reviewed_candidate_binding(path, digest) == parse_reviewed_candidate_binding(
        raw, digest
    )
    linked = tmp_path / "linked-binding.json"
    linked.symlink_to(path)
    with pytest.raises(Schema14RehearsalError, match="review_binding_file_invalid"):
        load_reviewed_candidate_binding(linked, digest)


def test_same_volume_lifecycle_checks_schema_data_api_digests_and_owner_isolation(tmp_path) -> None:
    adapter = FakeAdapter()
    result = _run(adapter, tmp_path)
    assert result["status"] == "Pass"
    assert result["schema_versions"] == list(range(1, 15))
    assert result["database_restored"] is False
    table_results = {item["table"]: item for item in result["database_snapshot_tables"]}
    assert table_results["assistant_messages"]["rows"] == 2
    assert table_results["schema_migrations"]["rows"] == 14
    assert result["fixture_provider"] == "deterministic_fixture"
    assert result["comparison_price_data"] == "synthetic_fixture_not_live_market_data"
    assert result["network_mode"] == "none"
    assert result["data_path_evidence"] == {
        "initial_thesis_and_comparison_writes": "authenticated_candidate_api",
        "recovery_retention_check": "read_only_sqlite_snapshot",
        "candidate_reentry_check": "authenticated_candidate_api",
    }
    api_results = result["api_evidence"]
    assert [item["owner_slot"] for item in api_results] == ["owner_a", "owner_b"]
    assert all(len(item["responses"]) == 7 for item in api_results)
    assert all(
        all(row["status_code"] == 404 for row in item["foreign_statuses"]) for item in api_results
    )
    assert adapter.events == [
        ("start_candidate", None, False, True, False),
        ("create_fixtures", "candidate"),
        ("read_api", "candidate"),
        ("stop", "candidate"),
        ("snapshot", "candidate"),
        ("start_recovery", _VOLUME, False, False, False, False),
        ("snapshot", "recovery"),
        ("stop", "recovery"),
        ("start_candidate", _VOLUME, False, True, False),
        ("read_api", "candidate"),
        ("stop", "candidate"),
    ]
    assert result["volume_id_sha256"] == hashlib.sha256(_VOLUME.encode()).hexdigest()


def test_runtime_verifier_checks_exact_fixture_content_in_all_seven_success_responses():
    namespace, arguments = _runtime_api_content_case()
    checks = namespace["verify_api_content"](*arguments)
    assert checks == {
        "thesis_get": ["fixture_thesis_content"],
        "thesis_revisions": ["fixture_revision_history"],
        "theses_export_json": ["owner_scoped_thesis_json"],
        "theses_export_csv": ["owner_scoped_thesis_csv"],
        "comparison_get": ["fixture_comparison_content"],
        "comparison_export_json": ["owner_scoped_comparison_json"],
        "comparison_export_csv": ["owner_scoped_comparison_csv"],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "thesis_json_foreign_revision_id",
        "thesis_json_changed_content",
        "thesis_csv_foreign_id",
        "thesis_get_changed_content",
        "comparison_json_foreign_id",
        "comparison_json_changed_content",
        "comparison_csv_foreign_id",
        "comparison_csv_changed_content",
    ],
)
def test_runtime_verifier_rejects_stable_but_foreign_or_changed_export_content(mutation):
    namespace, original = _runtime_api_content_case()
    arguments = list(copy.deepcopy(original))
    if mutation == "thesis_json_foreign_revision_id":
        arguments[7]["revisions"][0]["thesis_id"] = arguments[2]
    elif mutation == "thesis_json_changed_content":
        arguments[7]["items"][0]["data"]["reasoning"] = "unexpected retained thesis"
    elif mutation == "thesis_csv_foreign_id":
        arguments[8] = _replace_csv_cell(arguments[8], 0, "thesis_id", arguments[2])
    elif mutation == "thesis_get_changed_content":
        arguments[5]["data"]["reasoning"] = "unexpected retained thesis"
    elif mutation == "comparison_json_foreign_id":
        arguments[10]["id"] = arguments[4]
    elif mutation == "comparison_json_changed_content":
        arguments[10]["data"]["instruments"][0]["symbol"] = "ACDC"
    elif mutation == "comparison_csv_foreign_id":
        arguments[11] = _replace_csv_cell(arguments[11], 0, "snapshot_id", arguments[4])
    else:
        arguments[11] = _replace_csv_cell(arguments[11], 0, "symbol", "ACDC")
    with pytest.raises(namespace["CheckFailure"]):
        namespace["verify_api_content"](*arguments)


def test_lifecycle_rejects_api_evidence_without_content_validation_markers(tmp_path):
    adapter = FakeAdapter()
    first = adapter.initial_api[0]
    response = first.responses[0]
    changed = OwnerApiEvidence(
        first.owner_slot,
        first.owner_id,
        first.thesis_id,
        first.comparison_id,
        first.foreign_owner_slot,
        first.foreign_thesis_id,
        first.foreign_comparison_id,
        first.revision_numbers,
        (ResponseDigest(response.endpoint, 200, response.body_sha256, ()), *first.responses[1:]),
        first.foreign_statuses,
    )
    adapter.initial_api = (changed, *adapter.initial_api[1:])
    with pytest.raises(Schema14RehearsalError, match="api_content_checks_missing"):
        _run(adapter, tmp_path)


def test_recovery_data_change_in_assistant_row_stops_before_candidate_reentry(tmp_path) -> None:
    adapter = FakeAdapter()
    adapter.recovery_snapshot = _snapshot(assistant_message_digest="0" * 64)
    with pytest.raises(Schema14RehearsalError, match="recovery_data_changed"):
        _run(adapter, tmp_path)
    assert ("stop", "recovery") in adapter.events
    assert not any(
        event[0] == "start_candidate" and event[1] == _VOLUME for event in adapter.events
    )


def test_recovery_must_use_same_volume_and_keep_both_features_disabled(tmp_path) -> None:
    adapter = FakeAdapter()
    adapter.recovery_volume = "different-volume"
    with pytest.raises(Schema14RehearsalError, match="recovery_identity_or_control_mismatch"):
        _run(adapter, tmp_path)
    assert adapter.events[-1] == ("stop", "recovery")
    assert not any(event[0] == "snapshot" and event[1] == "recovery" for event in adapter.events)

    adapter = FakeAdapter()
    adapter.recovery_controls = (False, True, False)
    with pytest.raises(Schema14RehearsalError, match="recovery_identity_or_control_mismatch"):
        _run(adapter, tmp_path)


def test_api_digest_drift_and_cross_owner_access_fail_closed(tmp_path) -> None:
    adapter = FakeAdapter()
    changed = list(adapter.final_api)
    first = changed[0]
    first_response = first.responses[0]
    changed[0] = OwnerApiEvidence(
        first.owner_slot,
        first.owner_id,
        first.thesis_id,
        first.comparison_id,
        first.foreign_owner_slot,
        first.foreign_thesis_id,
        first.foreign_comparison_id,
        first.revision_numbers,
        (
            ResponseDigest(
                first_response.endpoint,
                200,
                "0" * 64,
                first_response.content_checks,
            ),
            *first.responses[1:],
        ),
        first.foreign_statuses,
    )
    adapter.final_api = tuple(changed)
    with pytest.raises(Schema14RehearsalError, match="research_api_data_changed"):
        _run(adapter, tmp_path)
    assert adapter.events[-1] == ("stop", "candidate")

    adapter = FakeAdapter()
    first = adapter.initial_api[0]
    wrong_foreign_id = OwnerApiEvidence(
        first.owner_slot,
        first.owner_id,
        first.thesis_id,
        first.comparison_id,
        first.foreign_owner_slot,
        first.thesis_id,
        first.foreign_comparison_id,
        first.revision_numbers,
        first.responses,
        first.foreign_statuses,
    )
    adapter.initial_api = (wrong_foreign_id, *adapter.initial_api[1:])
    with pytest.raises(Schema14RehearsalError, match="api_evidence_identity_mismatch"):
        _run(adapter, tmp_path)

    adapter = FakeAdapter()
    first = adapter.initial_api[0]
    changed_foreign = OwnerApiEvidence(
        first.owner_slot,
        first.owner_id,
        first.thesis_id,
        first.comparison_id,
        first.foreign_owner_slot,
        first.foreign_thesis_id,
        first.foreign_comparison_id,
        first.revision_numbers,
        first.responses,
        (("thesis_get", 200), *first.foreign_statuses[1:]),
    )
    adapter.initial_api = (changed_foreign, *adapter.initial_api[1:])
    with pytest.raises(Schema14RehearsalError, match="owner_isolation_failed"):
        _run(adapter, tmp_path)
    assert adapter.events[-1] == ("stop", "candidate")


def test_candidate_identity_mismatch_never_starts_recovery(tmp_path) -> None:
    adapter = FakeAdapter()
    adapter.candidate_image = "sha256:" + "9" * 64
    with pytest.raises(Schema14RehearsalError, match="candidate_identity_or_control_mismatch"):
        _run(adapter, tmp_path)
    assert adapter.events == [
        ("start_candidate", None, False, True, False),
        ("stop", "candidate"),
    ]


class FakeDockerRuntime:
    IMAGE_MEMORY_BYTES = 768 * 1024 * 1024
    IMAGE_CPUS = 1
    IMAGE_PIDS = 128
    _APP_READINESS_TIMEOUT_SECONDS = 1

    def __init__(
        self, binding, *, wrong_volume=False, wrong_image=False, candidate_missing_research=False
    ):
        self.binding = binding
        self.wrong_volume = wrong_volume
        self.wrong_image = wrong_image
        self.candidate_missing_research = candidate_missing_research
        self.volume = None
        self.run_commands = []
        self.stopped = []
        self.container_images = {}
        self.container_config = {}
        self.snapshot_command = None

    def _docker_environment(self, config_dir):
        config_dir.mkdir(mode=0o700)
        return {"HOME": str(config_dir), "DOCKER_CONFIG": str(config_dir)}

    @staticmethod
    def _image_run_args(volume, env_values, verifier, *, identity_drop):
        del verifier
        user = "--user=0:0" if identity_drop else "--user=10001:10001"
        return [
            "--network=none",
            "--read-only",
            "--volume",
            f"{volume}:/data",
            *env_values,
            user,
            "--detach",
            "--rm",
        ]

    @staticmethod
    def _recovery_profile_mismatch(_host):
        return None

    @staticmethod
    def _string_set(value):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        return frozenset(value)

    def _stop_container(self, container, _env):
        self.stopped.append(container)
        self.container_images.pop(container, None)

    def _projection(self, container):
        recovery = self.container_images[container] == self.binding.recovery_image_digest
        volume = "stock-probs-schema14-010203040506"
        if self.wrong_volume:
            volume = "unrelated-volume"
        revision = (
            self.binding.candidate_source_commit
            if not recovery
            else "schema14-recovery-" + overlay.OVERLAY_SHA256
        )
        return {
            "Id": container,
            "Image": self.container_images[container],
            "State": {"Running": True},
            "Config": {
                "User": "0:0" if recovery else "10001:10001",
                "Revision": revision,
                "Mounts": [
                    {"Type": "volume", "Name": volume, "Destination": "/data", "RW": True},
                    {
                        "Type": "bind",
                        "Name": "",
                        "Destination": "/run/assistant/rehearsal.py",
                        "RW": False,
                    },
                    {
                        "Type": "bind",
                        "Name": "",
                        "Destination": "/run/assistant/research_recovery_overlay.py",
                        "RW": False,
                    },
                ],
            },
            "HostConfig": {
                "ReadonlyRootfs": True,
                "NetworkMode": "none",
                "Memory": self.IMAGE_MEMORY_BYTES,
                "NanoCpus": 1_000_000_000,
                "PidsLimit": self.IMAGE_PIDS,
                "CapDrop": ["ALL"],
                "CapAdd": ["SETUID", "SETGID"] if recovery else [],
                "SecurityOpt": ["no-new-privileges:true"],
            },
        }

    def _run(self, command, *, env, timeout, check=True, diagnostic_stage=None):
        del timeout, check
        if diagnostic_stage == "schema14_snapshot":
            self.snapshot_command = list(command)
            return SimpleNamespace(returncode=0, stdout=json.dumps(_snapshot()), stderr="")
        if command[:3] == ["docker", "volume", "inspect"]:
            if self.volume is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            output = self.volume
            if command[3] == "--format" and command[4] == "{{.Name}}|{{.Driver}}":
                output += "|local"
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        if command[:3] == ["docker", "volume", "create"]:
            self.volume = command[-1]
            return SimpleNamespace(returncode=0, stdout=self.volume + "\n", stderr="")
        if command[:3] == ["docker", "image", "inspect"]:
            image = command[-1]
            if image == self.binding.candidate_image_digest:
                label = "wrong" if self.wrong_image else self.binding.candidate_source_commit
            else:
                label = "schema14-recovery-" + overlay.OVERLAY_SHA256
            output = f"{image}|linux|amd64|{label}\n"
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        if command[:2] == ["docker", "run"]:
            self.run_commands.append((command, env))
            container = ("a" if len(self.run_commands) == 1 else "b") * 64
            self.container_images[container] = command[-1]
            return SimpleNamespace(returncode=0, stdout=container + "\n", stderr="")
        if command[:2] == ["docker", "inspect"]:
            if command[2] == "--format" and command[3] == "{{.State.Running}}":
                return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(self._projection(command[-1])) + "\n",
                stderr="",
            )
        if command[:2] == ["docker", "exec"]:
            if command[-2] == "probe":
                recovery = self.container_images[command[4]] == self.binding.recovery_image_digest
                value = {
                    "status": "ready",
                    "schema_version": 14,
                    "provider": "fixture",
                    "assistant": {"enabled": False, "status": "disabled"},
                }
                if not recovery and not self.candidate_missing_research:
                    value["research"] = {"enabled": True, "rollout_mode": "invited"}
            else:
                value = {
                    "uid": 10001,
                    "gid": 10001,
                    "capabilities_zero": True,
                    "no_new_privileges": True,
                }
            return SimpleNamespace(returncode=0, stdout=json.dumps(value) + "\n", stderr="")
        if command[:3] == ["docker", "ps", "--all"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:3] == ["docker", "volume", "rm"]:
            self.volume = None
            return SimpleNamespace(returncode=0, stdout=command[-1] + "\n", stderr="")
        if command[:3] == ["docker", "volume", "ls"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected fake Docker operation: {command[:4]}")


def _reviewed_binding():
    raw = _binding_raw()
    return parse_reviewed_candidate_binding(raw, hashlib.sha256(raw).hexdigest())


def test_local_runtime_verifier_compiles_and_schema13_primitives_are_exact_pinned():
    source = _runtime_verifier_source()
    compile(source, "schema14-rehearsal-verifier.py", "exec")
    assert '"/api/v1/comparisons/"' in source
    assert '"/api/v1/theses/"' in source
    assert "response.content" in source
    runtime_path = Path(__file__).parents[1] / "scripts" / "rehearse_schema13.py"
    runtime_digest = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    runtime = _load_runtime_primitives(runtime_digest)
    assert callable(runtime._start_app)
    with pytest.raises(Schema14RehearsalError, match="runtime_helper_pin_mismatch"):
        _load_runtime_primitives("0" * 64)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("IMAGE_MEMORY_BYTES", 1024 * 1024 * 1024),
        ("IMAGE_CPUS", 2),
        ("IMAGE_PIDS", 256),
        ("_APP_READINESS_TIMEOUT_SECONDS", 61),
        ("IMAGE_PIDS", True),
    ],
)
def test_runtime_helper_cannot_change_canonical_profile_or_readiness_budget(
    tmp_path, monkeypatch, field, value
):
    import scripts.rehearse_schema14 as runner

    canonical = {
        "IMAGE_MEMORY_BYTES": 768 * 1024 * 1024,
        "IMAGE_CPUS": 1,
        "IMAGE_PIDS": 128,
        "_APP_READINESS_TIMEOUT_SECONDS": 60,
    }
    canonical[field] = value
    source = "\n".join(f"{name} = {value!r}" for name, value in canonical.items()) + "\n"
    source += """
def _docker_environment(*args): return {}
def _image_run_args(*args, **kwargs): return []
def _run(*args, **kwargs): return None
def _stop_container(*args, **kwargs): return None
def _recovery_profile_mismatch(*args, **kwargs): return None
def _string_set(*args, **kwargs): return frozenset()
"""
    helper = tmp_path / "schema13-helper.py"
    helper.write_text(source, encoding="utf-8")
    monkeypatch.setattr(runner, "_SCHEMA13_RUNTIME_PATH", helper)
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    with pytest.raises(Schema14RehearsalError, match="runtime_helper_profile_mismatch"):
        _load_runtime_primitives(digest)


def test_prepare_only_validates_reviewed_pins_without_loading_runtime(
    tmp_path, monkeypatch, capsys
):
    import scripts.rehearse_schema14 as runner

    raw = _binding_raw()
    path = tmp_path / "reviewed-binding.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    monkeypatch.setattr(
        runner,
        "_load_runtime_primitives",
        lambda _digest: pytest.fail("prepare-only must not load runtime primitives"),
    )
    result = main(
        [
            "--prepare-only",
            "--binding",
            str(path),
            "--binding-sha256",
            hashlib.sha256(raw).hexdigest(),
        ]
    )
    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "prepared",
        "executed": False,
        "binding_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_local_docker_adapter_keeps_exact_images_and_one_private_same_volume(tmp_path, monkeypatch):
    import scripts.rehearse_schema14 as runner

    binding = _reviewed_binding()
    runtime = FakeDockerRuntime(binding)
    adapter = LocalDockerSchema14Adapter(runtime, binding, tmp_path)
    monkeypatch.setattr(runner.os, "urandom", lambda size: b"\x01\x02\x03\x04\x05\x06")
    candidate = adapter.start_candidate(
        binding,
        volume_id=None,
        assistant_enabled=False,
        research_enabled=True,
        research_canary_only=False,
    )
    assert candidate.volume_id == "stock-probs-schema14-010203040506"
    candidate_command, candidate_env = runtime.run_commands[-1]
    assert candidate_command[-1] == binding.candidate_image_digest
    assert "--network=none" in candidate_command and "--publish" not in candidate_command
    assert "--volume" in candidate_command and f"{candidate.volume_id}:/data" in candidate_command
    assert f"--env=STOCK_PROBS_FIXTURE_NOW={_FIXTURE_CLOCK}" in candidate_command
    assert "--env=STOCK_PROBS_RESEARCH_FEATURES_ENABLED=1" in candidate_command
    assert candidate_env["STOCK_PROBS_BOOTSTRAP_PASSWORD"] == "schema14-local-admin-0123456789"  # noqa: S105 - synthetic test-only password
    adapter.stop(candidate)

    recovery = adapter.start_recovery(
        binding,
        volume_id=candidate.volume_id,
        assistant_enabled=False,
        research_enabled=False,
        research_canary_only=False,
        restore_database=False,
    )
    recovery_command, _ = runtime.run_commands[-1]
    assert recovery_command[-1] == binding.recovery_image_digest
    assert "--env=STOCK_PROBS_RESEARCH_FEATURES_ENABLED=0" in recovery_command
    assert recovery.volume_id == candidate.volume_id
    assert recovery.research_enabled is False and recovery.research_canary_only is None
    adapter.stop(recovery)
    assert adapter.close() == {"containers_removed": True, "volume_removed": True}


def test_recovery_snapshot_uses_readonly_same_volume_mount_and_fixed_resource_profile(tmp_path):
    binding = _reviewed_binding()
    runtime = FakeDockerRuntime(binding)
    adapter = LocalDockerSchema14Adapter(runtime, binding, tmp_path)
    volume = "stock-probs-schema14-010203040506"
    deployment = Deployment(
        "candidate",
        binding.candidate_image_digest,
        binding.candidate_source_commit,
        binding.candidate_repository_blob_sha1,
        binding.candidate_repository_sha256,
        14,
        True,
        volume,
        False,
        True,
        False,
        False,
    )
    snapshot = adapter.snapshot_database(deployment)
    assert snapshot["schema_version"] == 14
    command = runtime.snapshot_command
    assert command is not None
    assert "--volume" not in command
    assert f"type=volume,src={volume},dst=/data,readonly" in command
    assert "--network=none" in command and "--read-only" in command
    assert command[command.index("--memory") + 1] == "805306368"
    assert command[command.index("--cpus") + 1] == "1"
    assert command[command.index("--pids-limit") + 1] == "128"
    assert "immutable=1" not in " ".join(command)
    verifier_source = adapter.verifier.read_text(encoding="utf-8")
    assert "open_schema14_recovery_reader(path)" in verifier_source
    assert "immutable=1" not in verifier_source


def test_local_docker_adapter_rejects_wrong_volume_before_api_and_cleans(tmp_path, monkeypatch):
    import scripts.rehearse_schema14 as runner

    binding = _reviewed_binding()
    runtime = FakeDockerRuntime(binding, wrong_volume=True)
    adapter = LocalDockerSchema14Adapter(runtime, binding, tmp_path)
    monkeypatch.setattr(runner.os, "urandom", lambda size: b"\x01\x02\x03\x04\x05\x06")
    with pytest.raises(Schema14RehearsalError, match="container_volume_mismatch"):
        adapter.start_candidate(
            binding,
            volume_id=None,
            assistant_enabled=False,
            research_enabled=True,
            research_canary_only=False,
        )
    assert runtime.stopped == ["a" * 64]
    assert adapter.close() == {"containers_removed": True, "volume_removed": True}


def test_local_docker_adapter_rejects_candidate_readiness_without_research(tmp_path, monkeypatch):
    import scripts.rehearse_schema14 as runner

    binding = _reviewed_binding()
    runtime = FakeDockerRuntime(binding, candidate_missing_research=True)
    adapter = LocalDockerSchema14Adapter(runtime, binding, tmp_path)
    monkeypatch.setattr(runner.os, "urandom", lambda size: b"\x01\x02\x03\x04\x05\x06")

    with pytest.raises(Schema14RehearsalError, match="readiness_contract_mismatch"):
        adapter.start_candidate(
            binding,
            volume_id=None,
            assistant_enabled=False,
            research_enabled=True,
            research_canary_only=False,
        )

    assert runtime.stopped == ["a" * 64]
    assert adapter.close() == {"containers_removed": True, "volume_removed": True}
