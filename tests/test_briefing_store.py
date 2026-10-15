"""Disposable SQLite tests for briefing persistence and owner/CAS boundaries."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

import stock_probs.briefing_store as briefing_store_module
from stock_probs.briefing_domain import (
    BriefingSnapshot,
    BriefingWindow,
    PriceObservation,
    request_fingerprint,
    summarize_price_movements,
)
from stock_probs.briefing_store import (
    BriefingCapacityError,
    BriefingConflictError,
    BriefingNotFoundError,
    BriefingStore,
    BriefingUnavailableError,
)
from stock_probs.repository import SCHEMA_VERSION, Repository

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    repo = Repository(tmp_path / "briefing.sqlite3")
    repo.migrate()
    with repo.connect() as connection:
        for user_id, role, status in [(2, "member", "active"), (3, "admin", "active")]:
            connection.execute(
                "INSERT INTO users(id,display_name,role,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    user_id,
                    f"Fixture {user_id}",
                    role,
                    status,
                    "2026-10-14T00:00:00Z",
                    "2026-10-14T00:00:00Z",
                ),
            )
        connection.commit()
    return repo


def _snapshot(
    owner: int,
    *,
    key: str | None = None,
    snapshot_id: str | None = None,
    as_of: datetime = NOW,
    anchor_revision: int = 0,
    preference_revision: int = 0,
    threshold_bps: int = 300,
    baseline_at: datetime | None = None,
) -> BriefingSnapshot:
    return BriefingSnapshot(
        snapshot_id=snapshot_id or str(uuid4()),
        owner_user_id=owner,
        idempotency_key=key or str(uuid4()),
        request_sha256=request_fingerprint(BriefingWindow.SINCE_LAST_VISIT, as_of),
        window=BriefingWindow.SINCE_LAST_VISIT,
        baseline_at=baseline_at,
        observed_as_of=as_of,
        baseline_anchor_revision=anchor_revision,
        preference_revision=preference_revision,
        threshold_bps=threshold_bps,
        generated_at=as_of + timedelta(seconds=1),
        price_changes=(),
        outcome_changes=(),
        triggered_alerts=(),
        due_thesis_reviews=(),
    )


def _price(ref: str, price: str, observed_at: datetime, *, owner: int = 1) -> PriceObservation:
    return PriceObservation(
        owner_user_id=owner,
        source_ref=ref,
        symbol="SPY",
        asset_type="etf",
        provider="FixtureProvider",
        currency="USD",
        price=Decimal(price),
        observed_at=observed_at,
        received_at=observed_at,
        state="observed",
    )


def _create(
    store: BriefingStore,
    snapshot: BriefingSnapshot,
    observations: tuple[PriceObservation, ...] = (),
) -> BriefingSnapshot:
    return store.create_snapshot(
        snapshot,
        observations=observations,
        expected_preference_revision=snapshot.preference_revision,
        expected_anchor_revision=snapshot.baseline_anchor_revision,
    )


def _owner_counts(connection: sqlite3.Connection, owner_user_id: int) -> tuple[int, ...]:
    queries = (
        "SELECT COUNT(*) FROM briefing_price_observations WHERE owner_user_id=?",
        "SELECT COUNT(*) FROM briefing_snapshots WHERE owner_user_id=?",
        "SELECT COUNT(*) FROM briefing_preferences WHERE owner_user_id=?",
        "SELECT COUNT(*) FROM briefing_visit_anchors WHERE owner_user_id=?",
    )
    return tuple(
        int(connection.execute(query, (owner_user_id,)).fetchone()[0]) for query in queries
    )


def test_registered_migrations_apply_through_current_schema(repository: Repository) -> None:
    with repository.connect() as connection:
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        assert versions == list(range(1, SCHEMA_VERSION + 1))
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM briefing_snapshots").fetchone()[0] == 0


def test_snapshot_owner_isolation_and_keyset_pagination(repository: Repository) -> None:
    store = BriefingStore(repository)
    first = _create(store, _snapshot(1, as_of=NOW))
    second = _create(store, _snapshot(1, as_of=NOW + timedelta(hours=1)))
    member = _create(store, _snapshot(2, as_of=NOW))

    with pytest.raises(BriefingNotFoundError):
        store.get_snapshot(2, first.snapshot_id)
    assert [item.snapshot_id for item in store.list_snapshots(2).items] == [member.snapshot_id]
    page = store.list_snapshots(1, limit=1)
    assert [item.snapshot_id for item in page.items] == [second.snapshot_id]
    assert page.next_cursor == second.snapshot_id
    next_page = store.list_snapshots(1, limit=1, cursor=page.next_cursor)
    assert [item.snapshot_id for item in next_page.items] == [first.snapshot_id]
    assert next_page.next_cursor is None


def test_inactive_owner_and_admin_role_do_not_bypass_owner_scope(repository: Repository) -> None:
    store = BriefingStore(repository)
    admin_snapshot = _create(store, _snapshot(3))
    assert store.get_snapshot(3, admin_snapshot.snapshot_id).owner_user_id == 3
    with pytest.raises(BriefingNotFoundError):
        store.get_snapshot(1, admin_snapshot.snapshot_id)
    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=3")
        connection.commit()
    with pytest.raises(BriefingUnavailableError):
        store.get_snapshot(3, admin_snapshot.snapshot_id)


def test_preference_revision_is_bounded_append_only_and_cas_guarded(repository: Repository) -> None:
    store = BriefingStore(repository)
    default = store.get_preference(1)
    assert (default.revision, default.threshold_bps) == (0, 300)
    changed = store.update_preference(1, 450, expected_revision=0, updated_at=NOW)
    assert (changed.revision, changed.threshold_bps) == (1, 450)
    with pytest.raises(BriefingConflictError, match="concurrently"):
        store.update_preference(1, 500, expected_revision=0, updated_at=NOW)
    with pytest.raises(ValueError, match="range"):
        store.update_preference(1, 0, expected_revision=1, updated_at=NOW)
    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE briefing_preferences SET threshold_bps=500 WHERE owner_user_id=1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "INSERT OR REPLACE INTO briefing_preferences(owner_user_id,revision,"
                "threshold_bps,updated_at) "
                "VALUES(1,1,500,?)",
                ("2026-10-14T12:00:00Z",),
            )


def test_idempotent_creation_replays_exact_snapshot_and_rejects_key_reuse(
    repository: Repository,
) -> None:
    store = BriefingStore(repository)
    key = str(uuid4())
    created = _snapshot(1, key=key)
    request_hash = created.request_sha256
    first = _create(store, created)
    replay_candidate = _snapshot(
        1,
        key=key,
        threshold_bps=600,
        snapshot_id=str(uuid4()),
    )
    replay = _create(store, replay_candidate, (_price("ignored-on-replay", "100", NOW),))
    assert replay == first
    assert store.get_snapshot_by_idempotency(1, key, request_hash) == first
    with pytest.raises(BriefingConflictError, match="another request"):
        store.get_snapshot_by_idempotency(1, key, "b" * 64)
    with repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM briefing_snapshots WHERE owner_user_id=1"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM briefing_price_observations").fetchone()[0]
            == 0
        )


def test_observation_provenance_is_owner_bound_immutable_and_ref_conflicts_rollback(
    repository: Repository,
) -> None:
    store = BriefingStore(repository)
    first_point = _price("source-1", "100", NOW)
    first_snapshot = _snapshot(1)
    first_snapshot = replace(
        first_snapshot,
        price_changes=summarize_price_movements(
            (first_point,),
            owner_user_id=1,
            baseline_at=None,
            observed_as_of=NOW,
        ),
    )
    first = _create(store, first_snapshot, (first_point,))
    assert store.list_price_observations(1, through=NOW + timedelta(hours=1)) == (first_point,)
    assert store.list_price_observations(2, through=NOW + timedelta(hours=1)) == ()

    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE briefing_price_observations SET price_text='200' "
                "WHERE owner_user_id=1 AND source_ref='source-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM briefing_price_observations WHERE owner_user_id=1")

    new = _price("source-2", "102", NOW + timedelta(minutes=1))
    conflicting = _price("source-1", "101", NOW + timedelta(minutes=2))
    with pytest.raises(BriefingConflictError, match="conflicting content"):
        _create(store, _snapshot(1, as_of=NOW + timedelta(hours=1)), (new, conflicting))
    with repository.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM briefing_price_observations").fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM briefing_snapshots WHERE owner_user_id=1"
            ).fetchone()[0]
            == 1
        )
    assert store.get_snapshot(1, first.snapshot_id) == first


def test_snapshot_and_visit_anchor_are_immutable_explicit_and_never_rewound(
    repository: Repository,
) -> None:
    store = BriefingStore(repository)
    first = _create(store, _snapshot(1, as_of=NOW))
    initial = store.get_visit_anchor(1)
    assert (initial.revision, initial.baseline_at) == (0, None)
    anchored = store.record_visit(
        1, first.snapshot_id, expected_revision=0, visited_at=NOW + timedelta(minutes=1)
    )
    assert anchored.revision == 1 and anchored.baseline_at == NOW

    second_time = NOW + timedelta(hours=1)
    second = _create(
        store,
        _snapshot(1, as_of=second_time, anchor_revision=1, baseline_at=NOW),
    )
    second_anchor = store.record_visit(
        1, second.snapshot_id, expected_revision=1, visited_at=second_time + timedelta(minutes=1)
    )
    with pytest.raises(BriefingConflictError, match="back"):
        store.record_visit(
            1, first.snapshot_id, expected_revision=2, visited_at=NOW + timedelta(hours=2)
        )
    assert store.get_snapshot(1, first.snapshot_id).baseline_at is None
    assert store.get_visit_anchor(1) == second_anchor
    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE briefing_snapshots SET baseline_at=? WHERE id=?",
                ("2026-10-14T10:00:00Z", first.snapshot_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM briefing_visit_anchors WHERE owner_user_id=1")


def test_snapshot_creation_compares_preference_and_anchor_revisions(repository: Repository) -> None:
    store = BriefingStore(repository)
    store.update_preference(1, 350, expected_revision=0, updated_at=NOW)
    stale = _snapshot(1, preference_revision=0)
    with pytest.raises(BriefingConflictError, match="state changed"):
        _create(store, stale)
    assert store.list_snapshots(1).items == ()


@pytest.mark.parametrize(
    ("limit_name", "usage_index", "message"),
    [
        ("MAX_OWNER_RETAINED_ROWS", 0, "retained-row"),
        ("MAX_OWNER_RETAINED_BYTES", 1, "retained-byte"),
    ],
)
def test_owner_capacity_rejects_all_appends_without_deleting_history(
    repository: Repository,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    usage_index: int,
    message: str,
) -> None:
    store = BriefingStore(repository)
    point = _price("capacity-base", "100", NOW)
    first_snapshot = replace(
        _snapshot(1, as_of=NOW + timedelta(minutes=1)),
        price_changes=summarize_price_movements(
            (point,), owner_user_id=1, baseline_at=None, observed_as_of=NOW + timedelta(minutes=1)
        ),
    )
    _create(store, first_snapshot, (point,))
    with repository.connect() as connection:
        original_usage = briefing_store_module._owner_usage(connection, 1)
        original_counts = _owner_counts(connection, 1)
    monkeypatch.setattr(briefing_store_module, limit_name, original_usage[usage_index])

    later = _price("capacity-later", "101", NOW + timedelta(minutes=2))
    as_of = NOW + timedelta(minutes=3)
    known_history = (*store.list_price_observations(1, through=as_of), later)
    candidate = replace(
        _snapshot(1, as_of=as_of),
        price_changes=summarize_price_movements(
            known_history, owner_user_id=1, baseline_at=None, observed_as_of=as_of
        ),
    )
    with pytest.raises(BriefingCapacityError, match=message):
        _create(store, candidate, (later,))
    with pytest.raises(BriefingCapacityError, match=message):
        store.update_preference(1, 400, expected_revision=0, updated_at=NOW)
    with pytest.raises(BriefingCapacityError, match=message):
        store.record_visit(
            1,
            first_snapshot.snapshot_id,
            expected_revision=0,
            visited_at=NOW + timedelta(minutes=2),
        )

    with repository.connect() as connection:
        after_usage = briefing_store_module._owner_usage(connection, 1)
        after_counts = _owner_counts(connection, 1)
    assert after_usage == original_usage
    assert after_counts == original_counts
    assert store.list_price_observations(1, through=NOW + timedelta(hours=1)) == (point,)

    other_owner_snapshot = _create(store, _snapshot(2, as_of=NOW + timedelta(minutes=1)))
    assert store.get_snapshot(2, other_owner_snapshot.snapshot_id) == other_owner_snapshot
