"""Owner-bound persistence for monitoring rules, observations and queued work.

This store records work and provider evidence only. It never dispatches providers, sends email,
or starts a scheduler. Schema 016 remains an unregistered draft until repository integration and
migration review are complete.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .auth import AuthContext
from .auth_write_guard import StepUpChecker, authorize_current_write
from .monitoring_domain import (
    ArmBaselineSnapshot,
    CrossingState,
    MonitoringError,
    PriceObservation,
    begin_arm_generation,
    evaluate_arm_snapshot,
    evaluate_crossing,
    instant,
    pause_crossing,
    price,
)
from .repository import Repository

MAX_ALERTS_PER_OWNER = 50
MAX_PAGE_SIZE = 100
MAX_JOB_BATCH = 50
MAX_LEASE_SECONDS = 300
MAX_OUTBOX_ATTEMPTS = 3
MAX_OUTBOX_PAYLOAD_BYTES = 16384
MAX_CHECKPOINT_BYTES = 4096
MAX_NOTIFICATION_BYTES = 8192
MAX_CURSOR_BYTES = 256
DEFAULT_RETRY_SECONDS = 300
DISABLED_JOB_DUE = "9999-12-31T23:59:59.999999Z"
CONFIG_KEYS = frozenset({"symbol", "currency", "threshold", "direction", "repeating"})
JOB_KINDS = frozenset({"outcome", "mail", "digest", "brief_price"})
PRICE_FAILURE_CODES = frozenset(
    {"provider_unavailable", "provider_response_invalid", "provider_busy"}
)
WORKER_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
FAILURE_RE = re.compile(r"[a-z0-9_:-]{1,80}\Z")
CLAIM_FIELDS = frozenset(
    {
        "job_id",
        "owner_user_id",
        "kind",
        "resource_id",
        "lease_token",
        "lease_until",
        "request_id",
        "requested_at",
        "request_kind",
        "arm_generation",
        "expected_monitor_revision",
        "job_revision",
        "worker_id",
        "checkpoint",
    }
)
OUTBOX_CLAIM_FIELDS = CLAIM_FIELDS | frozenset(
    {
        "outbox_id",
        "outbox_revision",
        "attempt_id",
        "attempt_revision",
        "notification_id",
        "delivery_version",
        "preference_revision",
        "outbox_kind",
        "outbox_payload",
        "recipient",
        "outbox_state",
    }
)


class MonitoringStoreError(ValueError):
    """Safe validation, ownership, and compare-and-swap failure for this store."""


class MonitoringConflictError(MonitoringStoreError):
    """The durable request or revision conflicts with an earlier accepted state."""


class MonitoringArmingUnavailableError(MonitoringStoreError):
    """New monitoring work cannot be accepted while its arming path is unavailable."""


WriteAuthorizationMode = Literal["required", "development_no_auth", "test_no_auth"]


def _canonical_json(value: Any, maximum: int) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MonitoringStoreError("The stored request is not valid JSON data.") from error
    if len(encoded.encode("utf-8")) > maximum:
        raise MonitoringStoreError("The stored request exceeds its size limit.")
    return encoded


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value, 32768).encode("utf-8")).hexdigest()


def _canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise MonitoringStoreError(f"{field} must be a canonical UUID.")
    try:
        normalized = str(UUID(value))
    except ValueError as error:
        raise MonitoringStoreError(f"{field} must be a canonical UUID.") from error
    if normalized != value:
        raise MonitoringStoreError(f"{field} must be a canonical lowercase UUID.")
    return value


def _owner_id(value: object) -> int:
    if type(value) is not int or value < 1:
        raise MonitoringStoreError("The owner is unavailable.")
    return value


def _revision(value: object, field: str = "revision", *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum or value > 2**63 - 1:
        raise MonitoringStoreError(f"{field} is invalid.")
    return value


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise MonitoringStoreError(f"{field} must be a timezone-aware timestamp.")
    try:
        return instant(value)
    except MonitoringError as error:
        raise MonitoringStoreError(f"{field} must be a timezone-aware timestamp.") from error


def _timestamp(value: object, field: str) -> str:
    return _datetime(value, field).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise MonitoringStoreError(f"Saved {field} is invalid.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise MonitoringStoreError(f"Saved {field} is invalid.") from error
    return _datetime(parsed, field)


def _config(value: object) -> tuple[dict[str, Any], str, str]:
    if not isinstance(value, Mapping) or set(value) != CONFIG_KEYS:
        raise MonitoringStoreError("The alert fields are invalid.")
    symbol = value["symbol"]
    currency = value["currency"]
    direction = value["direction"]
    repeating = value["repeating"]
    threshold = value["threshold"]
    if (
        not isinstance(symbol, str)
        or not symbol.strip()
        or len(symbol.strip()) > 80
        or not symbol.strip().isprintable()
        or not symbol.strip().isascii()
        or not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or not isinstance(direction, str)
        or direction not in {"above", "below"}
        or type(repeating) is not bool
    ):
        raise MonitoringStoreError("The alert instrument or rule is invalid.")
    normalized_symbol = symbol.strip().upper()
    normalized_currency = currency.upper()
    try:
        normalized_threshold = str(price(threshold))
    except MonitoringError as error:
        raise MonitoringStoreError(str(error)) from error
    result = {
        "symbol": normalized_symbol,
        "currency": normalized_currency,
        "threshold": normalized_threshold,
        "direction": direction,
        "repeating": repeating,
    }
    encoded = _canonical_json(result, 4096)
    return result, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cursor_encode(created_at: str, identifier: str) -> str:
    raw = _canonical_json({"created_at": created_at, "id": identifier}, 128).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(value: object) -> tuple[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_CURSOR_BYTES:
        raise MonitoringStoreError("The page cursor is invalid.")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if not isinstance(payload, dict) or set(payload) != {"created_at", "id"}:
            raise ValueError
        created_at = payload["created_at"]
        identifier = _canonical_uuid(payload["id"], "cursor id")
        if (
            _timestamp(_parse_timestamp(created_at, "cursor timestamp"), "cursor timestamp")
            != created_at
        ):
            raise ValueError
        return created_at, identifier
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise MonitoringStoreError("The page cursor is invalid.") from error


class MonitoringStore:
    """Short-transaction, owner-bound persistence over the existing SQLite repository."""

    def __init__(
        self,
        repository: Repository,
        *,
        admin_only: bool = False,
        write_authorization_mode: WriteAuthorizationMode = "required",
        step_up_checker: StepUpChecker | None = None,
    ):
        if not isinstance(repository, Repository):
            raise TypeError("repository must be a Repository")
        if type(admin_only) is not bool:
            raise TypeError("admin_only must be a boolean")
        if write_authorization_mode not in {
            "required",
            "development_no_auth",
            "test_no_auth",
        }:
            raise TypeError("write_authorization_mode is invalid")
        if step_up_checker is not None and not callable(step_up_checker):
            raise TypeError("step_up_checker must be callable")
        self.repository = repository
        self.admin_only = admin_only
        self.write_authorization_mode = write_authorization_mode
        self.step_up_checker = step_up_checker

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _active_owner(self, connection: sqlite3.Connection, owner: object) -> int:
        owner_id = _owner_id(owner)
        try:
            Repository._ensure_owner_can_write(connection, owner_id)
        except ValueError as error:
            raise MonitoringStoreError("The owner is unavailable.") from error
        if self.admin_only:
            account = connection.execute(
                "SELECT status,role FROM users WHERE id=?", (owner_id,)
            ).fetchone()
            if account is None or account["status"] != "active" or account["role"] != "admin":
                raise MonitoringStoreError("The owner is unavailable.")
        return owner_id

    def _authorize_user_mutation(
        self,
        connection: sqlite3.Connection,
        auth_context: AuthContext | None,
        owner: int,
        *,
        required_role: str | None = None,
        require_step_up: bool = False,
    ) -> None:
        """Bind an interactive write to its cached context inside the existing transaction."""
        if self.write_authorization_mode != "required":
            return
        authorize_current_write(
            connection,
            auth_context,
            owner,
            datetime.now(UTC),
            required_role=required_role,
            require_step_up=require_step_up,
            step_up_checker=self.step_up_checker,
        )

    def get_control(self) -> dict[str, Any]:
        """Return the persisted global monitoring switch and its compare-and-swap revision."""

        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT enabled,revision,updated_at FROM monitoring_control WHERE id=1"
            ).fetchone()
        if row is None:
            raise MonitoringStoreError("The monitoring control is unavailable.")
        return {
            "enabled": row["enabled"] == 1,
            "revision": row["revision"],
            "updated_at": row["updated_at"],
        }

    def set_control(
        self,
        expected_revision: int,
        enabled: bool,
        now: datetime,
        *,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        """CAS the global switch and fail claimed work that has not crossed its effect boundary."""

        expected = _revision(expected_revision, "control revision")
        if type(enabled) is not bool:
            raise MonitoringStoreError("The monitoring switch must be a boolean.")
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            self._authorize_user_mutation(
                connection,
                auth_context,
                auth_context.user.id if isinstance(auth_context, AuthContext) else 0,
                required_role="admin",
                require_step_up=True,
            )
            row = connection.execute(
                "SELECT enabled,revision,updated_at FROM monitoring_control WHERE id=1"
            ).fetchone()
            if row is None:
                raise MonitoringStoreError("The monitoring control is unavailable.")
            if row["revision"] != expected:
                raise MonitoringConflictError("The monitoring control changed. Reload it first.")
            if row["enabled"] != int(enabled):
                changed = connection.execute(
                    "UPDATE monitoring_control SET enabled=?,revision=revision+1,updated_at=? "
                    "WHERE id=1 AND revision=? AND enabled=?",
                    (int(enabled), now_text, expected, row["enabled"]),
                ).rowcount
                if changed != 1:
                    raise MonitoringConflictError(
                        "The monitoring control changed while it was being updated."
                    )
                if not enabled:
                    connection.execute(
                        "UPDATE monitoring_jobs SET lease_token=NULL,lease_until=NULL,"
                        "active_request_id=NULL,active_requested_at=NULL,revision=revision+1 "
                        "WHERE kind IN ('price','outcome') AND lease_token IS NOT NULL"
                    )
                    claimed_outboxes = connection.execute(
                        "SELECT id,owner_user_id,job_id,lease_token,revision FROM "
                        "notification_outbox WHERE state='claimed' AND lease_token IS NOT NULL "
                        "ORDER BY owner_user_id,id"
                    ).fetchall()
                    for outbox in claimed_outboxes:
                        failed = connection.execute(
                            "UPDATE notification_outbox SET state='failed',revision=revision+1,"
                            "lease_token=NULL,lease_until=NULL,completed_at=?,transitioned_at=?,"
                            "failure_code='monitoring_disabled' WHERE id=? AND owner_user_id=? "
                            "AND revision=? AND state='claimed' AND lease_token=?",
                            (
                                now_text,
                                now_text,
                                outbox["id"],
                                outbox["owner_user_id"],
                                outbox["revision"],
                                outbox["lease_token"],
                            ),
                        ).rowcount
                        if failed != 1:
                            raise MonitoringConflictError(
                                "The claimed notification changed while monitoring was disabled."
                            )
                        self._release_outbox_job(
                            connection,
                            job_id=outbox["job_id"],
                            owner=outbox["owner_user_id"],
                            outbox_id=outbox["id"],
                            lease_token=outbox["lease_token"],
                            now_text=now_text,
                            failure_code="monitoring_disabled",
                        )
            return {
                "enabled": enabled,
                "revision": expected if row["enabled"] == int(enabled) else expected + 1,
                "updated_at": now_text if row["enabled"] != int(enabled) else row["updated_at"],
            }

    @staticmethod
    def _alert_row(connection: sqlite3.Connection, owner: int, alert_id: str) -> sqlite3.Row:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT * FROM price_alerts WHERE id=? AND owner_user_id=?",
                (alert_id, owner),
            ).fetchone(),
        )
        if row is None:
            raise MonitoringStoreError("The alert is unavailable.")
        return row

    @staticmethod
    def _alert_dict(row: sqlite3.Row) -> dict[str, Any]:
        config = json.loads(row["payload_json"])
        return {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "revision": row["revision"],
            "monitor_revision": row["monitor_revision"],
            "enabled": bool(row["enabled"]) and row["check_state"] != "triggered",
            "configured_enabled": bool(row["enabled"]),
            "config": config,
            "arm_generation": row["arm_generation"],
            "arm_snapshot_generation": row["arm_snapshot_generation"],
            "arm_snapshot_requested_at": row["arm_snapshot_requested_at"],
            "arm_snapshot_received_at": row["arm_snapshot_received_at"],
            "last_side": row["last_side"],
            "ready": bool(row["ready"]),
            "last_observed_at": row["last_observed_at"],
            "last_observation": json.loads(row["last_observation_json"])
            if row["last_observation_json"] is not None
            else None,
            "last_check_at": row["last_check_at"],
            "last_success_at": row["last_success_at"],
            "check_state": row["check_state"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _crossing_state(row: sqlite3.Row, config: Mapping[str, Any] | None = None) -> CrossingState:
        saved = json.loads(row["payload_json"]) if config is None else config
        observed_at = (
            _parse_timestamp(row["last_observed_at"], "last observation")
            if row["last_observed_at"] is not None
            else None
        )
        return CrossingState(
            symbol=saved["symbol"],
            currency=saved["currency"],
            threshold=saved["threshold"],
            direction=saved["direction"],
            repeating=saved["repeating"],
            armed_at=_parse_timestamp(row["armed_at"], "armed time"),
            enabled=bool(row["enabled"]) and row["check_state"] not in {"paused", "triggered"},
            last_side=row["last_side"],
            ready=bool(row["ready"]),
            last_observed_at=observed_at,
            arm_generation=row["arm_generation"],
            arm_snapshot_generation=row["arm_snapshot_generation"],
        )

    @staticmethod
    def _ensure_queue(connection: sqlite3.Connection, owner: int, now: str) -> None:
        connection.execute(
            "INSERT INTO monitoring_owner_queue(owner_user_id,service_sequence,last_served_at) "
            "VALUES (?,0,?) ON CONFLICT(owner_user_id) DO NOTHING",
            (owner, now),
        )

    @staticmethod
    def _write_revision(
        connection: sqlite3.Connection,
        owner: int,
        alert_id: str,
        revision: int,
        payload_json: str,
        enabled: bool,
        now: str,
    ) -> None:
        connection.execute(
            "INSERT INTO price_alert_revisions(alert_id,owner_user_id,revision,payloa"
            "d_json,enabled,recorded_at) "
            "VALUES (?,?,?,?,?,?)",
            (alert_id, owner, revision, payload_json, int(enabled), now),
        )

    @staticmethod
    def _sync_price_job(
        connection: sqlite3.Connection,
        owner: int,
        alert_id: str,
        generation: int,
        monitor_revision: int,
        request_kind: str,
        due_at: str,
        now: str,
    ) -> None:
        existing = connection.execute(
            "SELECT id,revision FROM monitoring_jobs WHERE owner_user_id=? AND "
            "kind='price' AND resource_id=?",
            (owner, alert_id),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO monitoring_jobs(id,owner_user_id,kind,resource_id,due_at,ale"
                "rt_generation,"
                "expected_monitor_revision,request_kind,checkpoint_json) VALUES "
                "(?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    owner,
                    "price",
                    alert_id,
                    due_at,
                    generation,
                    monitor_revision,
                    request_kind,
                    "{}",
                ),
            )
        else:
            changed = connection.execute(
                "UPDATE monitoring_jobs SET due_at=?,alert_generation=?,expected_monitor_"
                "revision=?,"
                "request_kind=?,lease_token=NULL,lease_until=NULL,active_request_id=NULL,"
                "active_requested_at=NULL,checkpoint_json='{}',revision=revision+1,failur"
                "e_code=NULL "
                "WHERE id=? AND owner_user_id=? AND revision=?",
                (
                    due_at,
                    generation,
                    monitor_revision,
                    request_kind,
                    existing["id"],
                    owner,
                    existing["revision"],
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError(
                    "The alert job changed. Retry from its current state."
                )
        MonitoringStore._ensure_queue(connection, owner, now)

    def create_alert(
        self,
        owner_user_id: int,
        idempotency_key: str,
        payload: Mapping[str, Any],
        now: datetime,
        *,
        allow_new_creation: bool = True,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        if type(allow_new_creation) is not bool:
            raise MonitoringStoreError("allow_new_creation must be a boolean.")
        key = _canonical_uuid(idempotency_key, "idempotency_key")
        normalized, payload_json, request_hash = _config(payload)
        timestamp = _timestamp(now, "now")
        with self._write() as connection:
            self._authorize_user_mutation(connection, auth_context, owner)
            owner = self._active_owner(connection, owner)
            existing = connection.execute(
                "SELECT id,request_sha256 FROM price_alerts WHERE owner_user_id=? AND "
                "idempotency_key=?",
                (owner, key),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_hash:
                    raise MonitoringConflictError("This request key belongs to a different alert.")
                return {
                    **self._alert_dict(self._alert_row(connection, owner, existing["id"])),
                    "replayed": True,
                }
            if not allow_new_creation:
                raise MonitoringArmingUnavailableError(
                    "New alert creation is unavailable until arming can be scheduled."
                )
            count = connection.execute(
                "SELECT COUNT(*) FROM price_alerts WHERE owner_user_id=?", (owner,)
            ).fetchone()[0]
            if count >= MAX_ALERTS_PER_OWNER:
                raise MonitoringStoreError("The owner has reached the alert limit.")
            initial = CrossingState(
                normalized["symbol"],
                normalized["currency"],
                normalized["threshold"],
                normalized["direction"],
                normalized["repeating"],
                _datetime(now, "now"),
            )
            armed = begin_arm_generation(initial, now)
            alert_id = str(uuid4())
            connection.execute(
                "INSERT INTO price_alerts(id,owner_user_id,idempotency_key,request_sha256,revision,"
                "monitor_revision,payload_json,enabled,armed_at,arm_generation,arm_snapshot_generation,"
                "arm_snapshot_request_id,arm_snapshot_requested_at,arm_snapshot_received_at,last_side,ready,"
                "last_observed_at,last_observation_json,last_fetch_request_id,last_fetch_requested_at,"
                "last_fetch_received_at,last_check_at,last_success_at,check_state,created"
                "_at,updated_at) "
                "VALUES (?,?,?,?,1,1,?,1,?,?,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NU"
                "LL,NULL,NULL,NULL,'arming',?,?)",
                (
                    alert_id,
                    owner,
                    key,
                    request_hash,
                    payload_json,
                    timestamp,
                    armed.arm_generation,
                    timestamp,
                    timestamp,
                ),
            )
            self._write_revision(connection, owner, alert_id, 1, payload_json, True, timestamp)
            self._sync_price_job(
                connection,
                owner,
                alert_id,
                armed.arm_generation,
                1,
                "arm_snapshot",
                timestamp,
                timestamp,
            )
            return {
                **self._alert_dict(self._alert_row(connection, owner, alert_id)),
                "replayed": False,
            }

    def get_alert(self, owner_user_id: int, alert_id: str) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(alert_id, "alert_id")
        with self.repository.connect() as connection:
            self._active_owner(connection, owner)
            return self._alert_dict(self._alert_row(connection, owner, identifier))

    def list_alerts(
        self, owner_user_id: int, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise MonitoringStoreError("The alert page size is invalid.")
        decoded = _cursor_decode(cursor)
        with self.repository.connect() as connection:
            self._active_owner(connection, owner)
            if decoded is None:
                rows = connection.execute(
                    "SELECT * FROM price_alerts WHERE owner_user_id=? "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (owner, limit + 1),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM price_alerts WHERE owner_user_id=? AND "
                    "(created_at < ? OR (created_at = ? AND id < ?)) "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (owner, decoded[0], decoded[0], decoded[1], limit + 1),
                ).fetchall()
        page = rows[:limit]
        next_cursor = (
            _cursor_encode(page[-1]["created_at"], page[-1]["id"]) if len(rows) > limit else None
        )
        return {"items": [self._alert_dict(row) for row in page], "next_cursor": next_cursor}

    def _change_configuration(
        self,
        connection: sqlite3.Connection,
        owner: int,
        row: sqlite3.Row,
        payload: Mapping[str, Any],
        payload_json: str,
        now: datetime,
    ) -> dict[str, Any]:
        now_text = _timestamp(now, "now")
        new_revision = row["revision"] + 1
        new_monitor_revision = row["monitor_revision"] + 1
        base = self._crossing_state(row, payload)
        transitioned = begin_arm_generation(base, now) if row["enabled"] else pause_crossing(base)
        enabled = transitioned.enabled
        check_state = "arming" if enabled else "paused"
        self._write_revision(
            connection, owner, row["id"], new_revision, payload_json, enabled, now_text
        )
        changed = connection.execute(
            "UPDATE price_alerts SET revision=?,monitor_revision=?,payload_json=?,ena"
            "bled=?,armed_at=?,"
            "arm_generation=?,arm_snapshot_generation=NULL,arm_snapshot_request_id=NULL,"
            "arm_snapshot_requested_at=NULL,arm_snapshot_received_at=NULL,last_side=NULL,ready=0,"
            "last_observed_at=NULL,last_observation_json=NULL,last_fetch_request_id=NULL,"
            "last_fetch_requested_at=NULL,last_fetch_received_at=NULL,last_check_at=NULL,last_success_at=NULL,"
            "check_state=?,updated_at=? WHERE id=? AND owner_user_id=? AND "
            "revision=? AND monitor_revision=?",
            (
                new_revision,
                new_monitor_revision,
                payload_json,
                int(enabled),
                _timestamp(transitioned.armed_at, "armed_at"),
                transitioned.arm_generation,
                check_state,
                now_text,
                row["id"],
                owner,
                row["revision"],
                row["monitor_revision"],
            ),
        ).rowcount
        if changed != 1:
            raise MonitoringConflictError("The alert changed. Reload it before saving.")
        if enabled:
            self._sync_price_job(
                connection,
                owner,
                row["id"],
                transitioned.arm_generation,
                new_monitor_revision,
                "arm_snapshot",
                now_text,
                now_text,
            )
        else:
            self._sync_price_job(
                connection,
                owner,
                row["id"],
                transitioned.arm_generation,
                new_monitor_revision,
                "arm_snapshot",
                DISABLED_JOB_DUE,
                now_text,
            )
        return self._alert_dict(self._alert_row(connection, owner, row["id"]))

    def edit_alert(
        self,
        owner_user_id: int,
        alert_id: str,
        expected_revision: int,
        payload: Mapping[str, Any],
        now: datetime,
        *,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(alert_id, "alert_id")
        expected = _revision(expected_revision)
        normalized, payload_json, _ = _config(payload)
        with self._write() as connection:
            self._authorize_user_mutation(connection, auth_context, owner)
            self._active_owner(connection, owner)
            row = self._alert_row(connection, owner, identifier)
            if row["revision"] != expected:
                raise MonitoringConflictError("The alert changed. Reload it before saving.")
            return self._change_configuration(connection, owner, row, normalized, payload_json, now)

    def pause_alert(
        self,
        owner_user_id: int,
        alert_id: str,
        expected_revision: int,
        now: datetime,
        *,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(alert_id, "alert_id")
        expected = _revision(expected_revision)
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            self._authorize_user_mutation(connection, auth_context, owner)
            self._active_owner(connection, owner)
            row = self._alert_row(connection, owner, identifier)
            if row["revision"] != expected:
                raise MonitoringConflictError("The alert changed. Reload it before pausing.")
            if not row["enabled"]:
                return self._alert_dict(row)
            state = pause_crossing(self._crossing_state(row))
            new_revision = row["revision"] + 1
            new_monitor_revision = row["monitor_revision"] + 1
            self._write_revision(
                connection, owner, identifier, new_revision, row["payload_json"], False, now_text
            )
            changed = connection.execute(
                "UPDATE price_alerts SET revision=?,monitor_revision=?,enabled=0,armed_at=?,"
                "arm_generation=?,arm_snapshot_generation=NULL,arm_snapshot_request_id=NULL,"
                "arm_snapshot_requested_at=NULL,arm_snapshot_received_at=NULL,last_side=NULL,ready=0,"
                "last_observed_at=NULL,last_observation_json=NULL,last_fetch_request_id=NULL,"
                "last_fetch_requested_at=NULL,last_fetch_received_at=NULL,last_check_at=?,"
                "last_success_at=NULL,check_state='paused',updated_at=? "
                "WHERE id=? AND owner_user_id=? AND revision=? AND monitor_revision=? "
                "AND enabled=1",
                (
                    new_revision,
                    new_monitor_revision,
                    _timestamp(state.armed_at, "armed_at"),
                    state.arm_generation,
                    now_text,
                    now_text,
                    identifier,
                    owner,
                    expected,
                    row["monitor_revision"],
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError("The alert changed while it was being paused.")
            self._sync_price_job(
                connection,
                owner,
                identifier,
                state.arm_generation,
                new_monitor_revision,
                "arm_snapshot",
                DISABLED_JOB_DUE,
                now_text,
            )
            return self._alert_dict(self._alert_row(connection, owner, identifier))

    def resume_alert(
        self,
        owner_user_id: int,
        alert_id: str,
        expected_revision: int,
        now: datetime,
        *,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(alert_id, "alert_id")
        expected = _revision(expected_revision)
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            self._authorize_user_mutation(connection, auth_context, owner)
            self._active_owner(connection, owner)
            row = self._alert_row(connection, owner, identifier)
            if row["revision"] != expected:
                raise MonitoringConflictError("The alert changed. Reload it before resuming.")
            if row["enabled"] and row["check_state"] != "triggered":
                raise MonitoringConflictError("The alert is already active.")
            state = begin_arm_generation(self._crossing_state(row), now)
            new_revision = row["revision"] + 1
            new_monitor_revision = row["monitor_revision"] + 1
            self._write_revision(
                connection, owner, identifier, new_revision, row["payload_json"], True, now_text
            )
            changed = connection.execute(
                "UPDATE price_alerts SET revision=?,monitor_revision=?,enabled=1,armed_at=?,"
                "arm_generation=?,arm_snapshot_generation=NULL,arm_snapshot_request_id=NULL,"
                "arm_snapshot_requested_at=NULL,arm_snapshot_received_at=NULL,last_side=NULL,ready=0,"
                "last_observed_at=NULL,last_observation_json=NULL,last_fetch_request_id=NULL,"
                "last_fetch_requested_at=NULL,last_fetch_received_at=NULL,last_check_at=NULL,"
                "last_success_at=NULL,check_state='arming',updated_at=? "
                "WHERE id=? AND owner_user_id=? AND revision=? AND monitor_revision=? "
                "AND (enabled=0 OR check_state='triggered')",
                (
                    new_revision,
                    new_monitor_revision,
                    _timestamp(state.armed_at, "armed_at"),
                    state.arm_generation,
                    now_text,
                    identifier,
                    owner,
                    expected,
                    row["monitor_revision"],
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError("The alert changed while it was being resumed.")
            self._sync_price_job(
                connection,
                owner,
                identifier,
                state.arm_generation,
                new_monitor_revision,
                "arm_snapshot",
                now_text,
                now_text,
            )
            return self._alert_dict(self._alert_row(connection, owner, identifier))

    def get_notification_preferences(self, owner_user_id: int) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        with self.repository.connect() as connection:
            self._active_owner(connection, owner)
            row = connection.execute(
                "SELECT owner_user_id,revision,address_id,alert_email,digest_email,digest_time,"
                "digest_timezone,updated_at FROM notification_preferences WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
        if row is None:
            return {
                "owner_user_id": owner,
                "revision": 0,
                "address_id": None,
                "alert_email": False,
                "digest_email": False,
                "digest_time": "09:00",
                "digest_timezone": "America/Toronto",
                "updated_at": None,
            }
        result = dict(row)
        result["alert_email"] = bool(result["alert_email"])
        result["digest_email"] = bool(result["digest_email"])
        return result

    def set_notification_preferences(
        self,
        owner_user_id: int,
        expected_revision: int,
        *,
        alert_email: bool,
        digest_email: bool,
        digest_time: str = "09:00",
        digest_timezone: str = "America/Toronto",
        address_id: str | None = None,
        now: datetime,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        expected = _revision(expected_revision, allow_zero=True)
        if type(alert_email) is not bool or type(digest_email) is not bool:
            raise MonitoringStoreError("Email preferences must be boolean.")
        if not isinstance(digest_time, str) or not re.fullmatch(
            r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", digest_time
        ):
            raise MonitoringStoreError("The digest time is invalid.")
        if not isinstance(digest_timezone, str) or not 1 <= len(digest_timezone) <= 64:
            raise MonitoringStoreError("The digest timezone is invalid.")
        try:
            ZoneInfo(digest_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise MonitoringStoreError("The digest timezone is invalid.") from error
        address = _canonical_uuid(address_id, "address_id") if address_id is not None else None
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            self._authorize_user_mutation(connection, auth_context, owner)
            self._active_owner(connection, owner)
            existing = connection.execute(
                "SELECT revision FROM notification_preferences WHERE owner_user_id=?", (owner,)
            ).fetchone()
            current = existing["revision"] if existing is not None else 0
            if current != expected:
                raise MonitoringConflictError(
                    "Notification preferences changed. Reload before saving."
                )
            if address is not None:
                verified = connection.execute(
                    "SELECT 1 FROM notification_addresses WHERE id=? AND owner_user_id=? AND "
                    "verified_at IS NOT NULL",
                    (address, owner),
                ).fetchone()
                if verified is None:
                    raise MonitoringStoreError("Choose a verified notification address.")
            if (alert_email or digest_email) and address is None:
                raise MonitoringStoreError(
                    "A verified notification address is required to enable email."
                )
            revision = current + 1
            if existing is None:
                connection.execute(
                    "INSERT INTO notification_preferences(owner_user_id,revision,address_id,a"
                    "lert_email,"
                    "digest_email,digest_time,digest_timezone,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        owner,
                        revision,
                        address,
                        int(alert_email),
                        int(digest_email),
                        digest_time,
                        digest_timezone,
                        now_text,
                    ),
                )
            else:
                updated = connection.execute(
                    "UPDATE notification_preferences SET "
                    "revision=?,address_id=?,alert_email=?,digest_email=?,"
                    "digest_time=?,digest_timezone=?,updated_at=? WHERE owner_user_id=? AND "
                    "revision=?",
                    (
                        revision,
                        address,
                        int(alert_email),
                        int(digest_email),
                        digest_time,
                        digest_timezone,
                        now_text,
                        owner,
                        expected,
                    ),
                ).rowcount
                if updated != 1:
                    raise MonitoringConflictError(
                        "Notification preferences changed. Reload before saving."
                    )
            row = connection.execute(
                "SELECT owner_user_id,revision,address_id,alert_email,digest_email,digest_time,"
                "digest_timezone,updated_at FROM notification_preferences WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            result = dict(row)
            result["alert_email"] = bool(result["alert_email"])
            result["digest_email"] = bool(result["digest_email"])
            return result

    @staticmethod
    def _outbox_summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "owner_user_id": row["owner_user_id"],
            "notification_id": row["notification_id"],
            "delivery_version": row["delivery_version"],
            "preference_revision": row["preference_revision"],
            "kind": row["kind"],
            "state": row["state"],
            "attempts": row["attempts"],
            "attempt_revision": row["attempt_revision"],
            "attempt_id": row["attempt_id"],
            "revision": row["revision"],
            "next_attempt_at": row["next_attempt_at"],
            "submitted_at": row["submitted_at"],
            "completed_at": row["completed_at"],
            "failure_code": row["failure_code"],
        }

    @staticmethod
    def _outbox_eligibility(connection: sqlite3.Connection, owner: int) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT u.status,u.role,p.revision,p.address_id,p.alert_email,"
                "a.verified_at,a.address "
                "FROM users u LEFT JOIN notification_preferences p ON p.owner_user_id=u.id "
                "LEFT JOIN notification_addresses a ON a.id=p.address_id "
                "AND a.owner_user_id=p.owner_user_id "
                "WHERE u.id=?",
                (owner,),
            ).fetchone(),
        )

    def _outbox_is_eligible(self, outbox: sqlite3.Row, eligibility: sqlite3.Row | None) -> bool:
        return bool(
            eligibility is not None
            and eligibility["status"] == "active"
            and (not self.admin_only or eligibility["role"] == "admin")
            and eligibility["revision"] == outbox["preference_revision"]
            and eligibility["address_id"] == outbox["address_id"]
            and eligibility["alert_email"] == 1
            and eligibility["verified_at"] is not None
        )

    def _outbox_pre_submission_block_code(
        self, connection: sqlite3.Connection, owner: int, outbox: sqlite3.Row
    ) -> str | None:
        """Return a terminal code if global, owner, or verified-opt-in authority was revoked."""

        control = connection.execute("SELECT enabled FROM monitoring_control WHERE id=1").fetchone()
        if control is None or control["enabled"] != 1:
            return "monitoring_disabled"
        eligibility = self._outbox_eligibility(connection, owner)
        if eligibility is None or eligibility["status"] != "active":
            return "delivery_not_eligible"
        if self.admin_only and eligibility["role"] != "admin":
            return "delivery_not_eligible"
        if not self._outbox_is_eligible(outbox, eligibility):
            return "delivery_not_eligible"
        return None

    @staticmethod
    def _outbox_row_for_claim(
        connection: sqlite3.Connection,
        owner: int,
        claim: Mapping[str, Any],
        now_text: str,
    ) -> sqlite3.Row:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT o.*,a.address AS current_recipient,j.revision AS current_job_revision,"
                "j.lease_token AS current_job_lease_token,j.lease_until AS current_job_lease_until,"
                "j.active_request_id AS current_job_request_id,"
                "j.active_requested_at AS current_job_requested_at "
                "FROM notification_outbox o JOIN notification_addresses a ON a.id=o.address_id "
                "AND a.owner_user_id=o.owner_user_id JOIN monitoring_jobs j ON j.id=o.job_id "
                "AND j.owner_user_id=o.owner_user_id WHERE o.id=? AND o.owner_user_id=? "
                "AND j.id=? AND j.resource_id=o.id AND j.kind='mail'",
                (claim["outbox_id"], owner, claim["job_id"]),
            ).fetchone(),
        )
        if (
            row is None
            or row["state"] != claim["outbox_state"]
            or row["revision"] != claim["outbox_revision"]
            or row["attempt_id"] != claim["attempt_id"]
            or row["attempt_revision"] != claim["attempt_revision"]
            or row["notification_id"] != claim["notification_id"]
            or row["delivery_version"] != claim["delivery_version"]
            or row["preference_revision"] != claim["preference_revision"]
            or row["kind"] != claim["outbox_kind"]
            or row["current_recipient"] != claim["recipient"]
            or json.loads(row["payload_json"]) != dict(claim["outbox_payload"])
            or row["current_job_revision"] != claim["job_revision"]
            or row["current_job_lease_token"] != claim["lease_token"]
            or row["current_job_lease_until"] != claim["lease_until"]
            or row["current_job_request_id"] != claim["request_id"]
            or row["current_job_requested_at"] != claim["requested_at"]
            or row["lease_token"] != claim["lease_token"]
            or row["lease_until"] != claim["lease_until"]
            or row["lease_until"] <= now_text
        ):
            raise MonitoringConflictError(
                "The notification delivery claim is stale or no longer owned by this worker."
            )
        return row

    def enqueue_notification_outbox(
        self,
        owner_user_id: int,
        notification_id: str,
        expected_preference_revision: int,
        *,
        delivery_version: int = 1,
        now: datetime,
    ) -> dict[str, Any]:
        """Persist one idempotent price-alert email delivery for a current verified opt-in."""

        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(notification_id, "notification id")
        expected_preferences = _revision(expected_preference_revision, "preference revision")
        version = _revision(delivery_version, "delivery version")
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            self._active_owner(connection, owner)
            notification = connection.execute(
                "SELECT id,kind,payload_json FROM notifications WHERE id=? AND owner_user_id=?",
                (identifier, owner),
            ).fetchone()
            if notification is None or notification["kind"] != "price_alert":
                raise MonitoringStoreError("The notification is unavailable for email delivery.")
            preferences = connection.execute(
                "SELECT revision,address_id,alert_email FROM notification_preferences "
                "WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            if preferences is None:
                raise MonitoringStoreError("A current verified notification address is required.")
            if preferences["revision"] != expected_preferences:
                raise MonitoringConflictError("Notification preferences changed before enqueue.")
            if preferences["alert_email"] != 1 or preferences["address_id"] is None:
                raise MonitoringStoreError("Price-alert email is not enabled for this owner.")
            address = connection.execute(
                "SELECT id FROM notification_addresses WHERE id=? AND owner_user_id=? "
                "AND verified_at IS NOT NULL",
                (preferences["address_id"], owner),
            ).fetchone()
            if address is None:
                raise MonitoringStoreError("A current verified notification address is required.")
            return self._enqueue_notification_outbox_in_transaction(
                connection,
                owner,
                notification,
                expected_preference_revision=expected_preferences,
                address_id=preferences["address_id"],
                delivery_version=version,
                now_text=now_text,
                ignore_existing=False,
            )

    def _enqueue_notification_outbox_in_transaction(
        self,
        connection: sqlite3.Connection,
        owner: int,
        notification: sqlite3.Row,
        *,
        expected_preference_revision: int,
        address_id: str,
        delivery_version: int,
        now_text: str,
        ignore_existing: bool,
    ) -> dict[str, Any]:
        """Create the outbox and delivery job on the caller's active transaction."""

        identifier = notification["id"]
        payload_json = _canonical_json(
            {
                "notification_id": identifier,
                "notification_kind": notification["kind"],
                "notification": json.loads(notification["payload_json"]),
            },
            MAX_OUTBOX_PAYLOAD_BYTES,
        )
        dedupe = _sha256(["notification_email", owner, identifier, delivery_version])
        existing = connection.execute(
            "SELECT * FROM notification_outbox WHERE notification_id=? AND delivery_version=?",
            (identifier, delivery_version),
        ).fetchone()
        if existing is not None:
            if ignore_existing:
                # In particular, never turn a duplicate crossing into a retry of an uncertain send.
                return self._outbox_summary(existing)
            if (
                existing["owner_user_id"] != owner
                or existing["preference_revision"] != expected_preference_revision
                or existing["address_id"] != address_id
                or existing["payload_json"] != payload_json
                or existing["dedupe_sha256"] != dedupe
            ):
                raise MonitoringConflictError(
                    "This notification delivery version already has different content or ownership."
                )
            return self._outbox_summary(existing)

        outbox_id = str(uuid4())
        job_id = str(uuid4())
        connection.execute(
            "INSERT INTO monitoring_jobs(id,owner_user_id,kind,resource_id,due_at) "
            "VALUES (?,?,'mail',?,?)",
            (job_id, owner, outbox_id, now_text),
        )
        connection.execute(
            "INSERT INTO notification_outbox(id,owner_user_id,notification_id,delivery_version,"
            "preference_revision,job_id,dedupe_sha256,address_id,kind,payload_json,state,next_attempt_at,"
            "created_at,transitioned_at) VALUES (?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)",
            (
                outbox_id,
                owner,
                identifier,
                delivery_version,
                expected_preference_revision,
                job_id,
                dedupe,
                address_id,
                notification["kind"],
                payload_json,
                now_text,
                now_text,
                now_text,
            ),
        )
        self._ensure_queue(connection, owner, now_text)
        row = connection.execute(
            "SELECT * FROM notification_outbox WHERE id=? AND owner_user_id=?",
            (outbox_id, owner),
        ).fetchone()
        return self._outbox_summary(row)

    def _enqueue_crossing_email_if_eligible(
        self,
        connection: sqlite3.Connection,
        owner: int,
        notification_id: str,
        now_text: str,
    ) -> None:
        """Queue a crossing email only for a currently active owner's verified opt-in."""

        eligibility = self._outbox_eligibility(connection, owner)
        if (
            eligibility is None
            or eligibility["status"] != "active"
            or (self.admin_only and eligibility["role"] != "admin")
            or eligibility["revision"] is None
            or eligibility["alert_email"] != 1
            or eligibility["address_id"] is None
            or eligibility["verified_at"] is None
        ):
            return
        notification = connection.execute(
            "SELECT id,kind,payload_json FROM notifications WHERE id=? AND owner_user_id=?",
            (notification_id, owner),
        ).fetchone()
        if notification is None or notification["kind"] != "price_alert":
            raise MonitoringConflictError("The crossing notification is unavailable for enqueue.")
        self._enqueue_notification_outbox_in_transaction(
            connection,
            owner,
            notification,
            expected_preference_revision=eligibility["revision"],
            address_id=eligibility["address_id"],
            delivery_version=1,
            now_text=now_text,
            ignore_existing=True,
        )

    def mark_notification_outbox_submission_started(
        self,
        owner_user_id: int,
        claim: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Persist the at-most-once boundary immediately before an external SMTP call."""

        owner = _owner_id(owner_user_id)
        validated = self._validated_outbox_claim(claim, owner)
        if validated["outbox_state"] != "claimed":
            raise MonitoringConflictError(
                "The notification delivery already crossed its submission boundary."
            )
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            row = self._outbox_row_for_claim(connection, owner, validated, now_text)
            failure_code = self._outbox_pre_submission_block_code(connection, owner, row)
            if failure_code is not None:
                changed = connection.execute(
                    "UPDATE notification_outbox SET state='failed',revision=revision+1,"
                    "lease_token=NULL,"
                    "lease_until=NULL,completed_at=?,transitioned_at=?,failure_code=? "
                    "WHERE id=? AND owner_user_id=? AND revision=? "
                    "AND state='claimed' AND lease_token=?",
                    (
                        now_text,
                        now_text,
                        failure_code,
                        row["id"],
                        owner,
                        row["revision"],
                        validated["lease_token"],
                    ),
                ).rowcount
                if changed != 1:
                    raise MonitoringConflictError(
                        "The notification delivery changed during revocation."
                    )
                self._release_outbox_job(
                    connection,
                    job_id=row["job_id"],
                    owner=owner,
                    outbox_id=row["id"],
                    lease_token=validated["lease_token"],
                    now_text=now_text,
                    failure_code=failure_code,
                )
                failed = connection.execute(
                    "SELECT * FROM notification_outbox WHERE id=? AND owner_user_id=?",
                    (row["id"], owner),
                ).fetchone()
                return self._outbox_summary(failed)
            changed = connection.execute(
                "UPDATE notification_outbox SET state='submitting',revision=revision+1,"
                "submission_started_at=?,transitioned_at=?,failure_code=NULL "
                "WHERE id=? AND owner_user_id=? AND revision=? AND state='claimed' "
                "AND lease_token=? AND lease_until>?",
                (
                    now_text,
                    now_text,
                    row["id"],
                    owner,
                    row["revision"],
                    validated["lease_token"],
                    now_text,
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError(
                    "The notification delivery claim expired before submission."
                )
            return {
                **validated,
                "outbox_revision": row["revision"] + 1,
                "outbox_state": "submitting",
            }

    def record_notification_outbox_pre_submission_failure(
        self,
        owner_user_id: int,
        claim: Mapping[str, Any],
        failure_code: str,
        now: datetime,
        *,
        retryable: bool,
        retry_after_seconds: int = DEFAULT_RETRY_SECONDS,
    ) -> dict[str, Any]:
        """Record a failure known to predate SMTP and retry it only when safe."""

        owner = _owner_id(owner_user_id)
        validated = self._validated_outbox_claim(claim, owner)
        if validated["outbox_state"] != "claimed":
            raise MonitoringConflictError("A submitted notification cannot be safely retried.")
        if not isinstance(failure_code, str) or not FAILURE_RE.fullmatch(failure_code):
            raise MonitoringStoreError("The outbox failure code is invalid.")
        if type(retryable) is not bool:
            raise MonitoringStoreError("The retryable flag must be boolean.")
        if type(retry_after_seconds) is not int or not 0 <= retry_after_seconds <= 3600:
            raise MonitoringStoreError("The outbox retry delay is invalid.")
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            row = self._outbox_row_for_claim(connection, owner, validated, now_text)
            block_code = self._outbox_pre_submission_block_code(connection, owner, row)
            can_retry = retryable and row["attempts"] < MAX_OUTBOX_ATTEMPTS and block_code is None
            if can_retry:
                next_attempt = _timestamp(
                    now + timedelta(seconds=retry_after_seconds), "next_attempt_at"
                )
                state = "queued"
                completed = None
            else:
                next_attempt = row["next_attempt_at"]
                state = "failed"
                completed = now_text
            changed = connection.execute(
                "UPDATE notification_outbox SET state=?,revision=revision+1,next_attempt_at=?,"
                "lease_token=NULL,lease_until=NULL,completed_at=?,transitioned_at=?,failure_code=? "
                "WHERE id=? AND owner_user_id=? AND revision=? "
                "AND state='claimed' AND lease_token=?",
                (
                    state,
                    next_attempt,
                    completed,
                    now_text,
                    block_code or failure_code,
                    row["id"],
                    owner,
                    row["revision"],
                    validated["lease_token"],
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError(
                    "The notification delivery changed before safe retry."
                )
            self._release_outbox_job(
                connection,
                job_id=row["job_id"],
                owner=owner,
                outbox_id=row["id"],
                lease_token=validated["lease_token"],
                now_text=now_text,
                failure_code=block_code or failure_code,
                due_at=next_attempt if can_retry else DISABLED_JOB_DUE,
            )
            saved = connection.execute(
                "SELECT * FROM notification_outbox WHERE id=? AND owner_user_id=?",
                (row["id"], owner),
            ).fetchone()
            return self._outbox_summary(saved)

    def finalize_notification_outbox(
        self,
        owner_user_id: int,
        claim: Mapping[str, Any],
        outcome: str,
        now: datetime,
        *,
        failure_code: str | None = None,
    ) -> dict[str, Any]:
        """Finalize an SMTP attempt as accepted, definitely failed, or uncertain.

        The accepted state means the transport acknowledged submission only; it does not
        establish mailbox delivery. An uncertain result is terminal and is never auto-requeued.
        """

        owner = _owner_id(owner_user_id)
        validated = self._validated_outbox_claim(claim, owner)
        if validated["outbox_state"] != "submitting":
            raise MonitoringConflictError(
                "The notification has no persisted submission checkpoint."
            )
        if not isinstance(outcome, str) or outcome not in {"accepted", "failed", "uncertain"}:
            raise MonitoringStoreError("The outbox submission outcome is invalid.")
        if outcome == "accepted":
            if failure_code is not None:
                raise MonitoringStoreError("An accepted outbox attempt cannot have a failure code.")
        elif not isinstance(failure_code, str) or not FAILURE_RE.fullmatch(failure_code):
            raise MonitoringStoreError("A bounded outbox failure code is required.")
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            row = self._outbox_row_for_claim(connection, owner, validated, now_text)
            if row["state"] != "submitting":
                raise MonitoringConflictError("The notification submission state changed.")
            submitted_at = now_text if outcome == "accepted" else None
            changed = connection.execute(
                "UPDATE notification_outbox SET state=?,revision=revision+1,lease_token=NULL,"
                "lease_until=NULL,submitted_at=?,completed_at=?,transitioned_at=?,failure_code=? "
                "WHERE id=? AND owner_user_id=? AND revision=? AND state='submitting' "
                "AND attempt_id=? AND attempt_revision=? AND lease_token=? AND lease_until>?",
                (
                    outcome,
                    submitted_at,
                    now_text,
                    now_text,
                    failure_code,
                    row["id"],
                    owner,
                    row["revision"],
                    validated["attempt_id"],
                    validated["attempt_revision"],
                    validated["lease_token"],
                    now_text,
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError(
                    "The notification submission lease expired or changed."
                )
            self._release_outbox_job(
                connection,
                job_id=row["job_id"],
                owner=owner,
                outbox_id=row["id"],
                lease_token=validated["lease_token"],
                now_text=now_text,
                failure_code=failure_code,
                last_success_at=now_text if outcome == "accepted" else None,
            )
            saved = connection.execute(
                "SELECT * FROM notification_outbox WHERE id=? AND owner_user_id=?",
                (row["id"], owner),
            ).fetchone()
            return self._outbox_summary(saved)

    def list_notifications(
        self, owner_user_id: int, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise MonitoringStoreError("The notification page size is invalid.")
        decoded = _cursor_decode(cursor)
        with self.repository.connect() as connection:
            self._active_owner(connection, owner)
            if decoded is None:
                rows = connection.execute(
                    "SELECT * FROM notifications WHERE owner_user_id=? "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (owner, limit + 1),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM notifications WHERE owner_user_id=? AND "
                    "(created_at < ? OR (created_at = ? AND id < ?)) "
                    "ORDER BY created_at DESC,id DESC LIMIT ?",
                    (owner, decoded[0], decoded[0], decoded[1], limit + 1),
                ).fetchall()
        page = rows[:limit]
        next_cursor = (
            _cursor_encode(page[-1]["created_at"], page[-1]["id"]) if len(rows) > limit else None
        )
        return {
            "items": [
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "payload": json.loads(row["payload_json"]),
                    "is_read": bool(row["is_read"]),
                    "revision": row["revision"],
                    "created_at": row["created_at"],
                }
                for row in page
            ],
            "next_cursor": next_cursor,
        }

    def set_notification_read(
        self,
        owner_user_id: int,
        notification_id: str,
        expected_revision: int,
        is_read: bool,
        now: datetime,
        *,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(notification_id, "notification_id")
        expected = _revision(expected_revision)
        if type(is_read) is not bool:
            raise MonitoringStoreError("Read state must be boolean.")
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            self._authorize_user_mutation(connection, auth_context, owner)
            self._active_owner(connection, owner)
            row = connection.execute(
                "SELECT id,kind,payload_json,is_read,revision,created_at FROM notifications "
                "WHERE id=? AND owner_user_id=?",
                (identifier, owner),
            ).fetchone()
            if row is None:
                raise MonitoringStoreError("The notification is unavailable.")
            if row["revision"] != expected:
                raise MonitoringConflictError(
                    "The notification changed. Reload before updating it."
                )
            if bool(row["is_read"]) == is_read:
                return {
                    "id": row["id"],
                    "kind": row["kind"],
                    "payload": json.loads(row["payload_json"]),
                    "is_read": is_read,
                    "revision": row["revision"],
                    "created_at": row["created_at"],
                }
            new_revision = expected + 1
            connection.execute(
                "INSERT INTO notification_read_events(id,notification_id,owner_user_id,re"
                "vision,is_read,changed_at) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid4()), identifier, owner, new_revision, int(is_read), now_text),
            )
            updated = connection.execute(
                "UPDATE notifications SET is_read=?,revision=? WHERE id=? AND "
                "owner_user_id=? AND revision=?",
                (int(is_read), new_revision, identifier, owner, expected),
            ).rowcount
            if updated != 1:
                raise MonitoringConflictError(
                    "The notification changed. Reload before updating it."
                )
            return {
                "id": row["id"],
                "kind": row["kind"],
                "payload": json.loads(row["payload_json"]),
                "is_read": is_read,
                "revision": new_revision,
                "created_at": row["created_at"],
            }

    def schedule_job(
        self,
        owner_user_id: int,
        kind: str,
        resource_id: str,
        due_at: datetime,
        *,
        checkpoint: Mapping[str, Any] | None = None,
        now: datetime,
    ) -> str:
        owner = _owner_id(owner_user_id)
        if kind not in JOB_KINDS:
            raise MonitoringStoreError("The monitoring job kind is unsupported here.")
        if (
            not isinstance(resource_id, str)
            or not 1 <= len(resource_id) <= 80
            or not resource_id.isprintable()
        ):
            raise MonitoringStoreError("The monitoring job resource is invalid.")
        payload = {} if checkpoint is None else checkpoint
        if not isinstance(payload, Mapping) or "claim" in payload:
            raise MonitoringStoreError("The job checkpoint is invalid.")
        checkpoint_json = _canonical_json(payload, MAX_CHECKPOINT_BYTES)
        due_text = _timestamp(due_at, "due_at")
        now_text = _timestamp(now, "now")
        with self._write() as connection:
            owner = self._active_owner(connection, owner)
            row = connection.execute(
                "SELECT id,revision,lease_token,lease_until FROM monitoring_jobs "
                "WHERE owner_user_id=? AND kind=? AND resource_id=?",
                (owner, kind, resource_id),
            ).fetchone()
            if row is None:
                job_id = str(uuid4())
                connection.execute(
                    "INSERT INTO monitoring_jobs(id,owner_user_id,kind,resource_id,due_at,che"
                    "ckpoint_json) "
                    "VALUES (?,?,?,?,?,?)",
                    (job_id, owner, kind, resource_id, due_text, checkpoint_json),
                )
            else:
                if row["lease_token"] is not None and row["lease_until"] > now_text:
                    raise MonitoringConflictError("The job is currently leased.")
                job_id = row["id"]
                updated = connection.execute(
                    "UPDATE monitoring_jobs SET due_at=?,checkpoint_json=?,lease_token=NULL,l"
                    "ease_until=NULL,"
                    "active_request_id=NULL,active_requested_at=NULL,revision=revision+1,fail"
                    "ure_code=NULL "
                    "WHERE id=? AND owner_user_id=? AND revision=?",
                    (due_text, checkpoint_json, job_id, owner, row["revision"]),
                ).rowcount
                if updated != 1:
                    raise MonitoringConflictError("The job changed. Retry from its current state.")
            self._ensure_queue(connection, owner, now_text)
            return job_id

    def _claim_row(
        self,
        connection: sqlite3.Connection,
        now_text: str,
        outbox_only: bool = False,
        price_only: bool = False,
    ) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT j.*,COALESCE(q.service_sequence,0) AS owner_sequence "
                "FROM monitoring_jobs j JOIN users u ON u.id=j.owner_user_id "
                "LEFT JOIN monitoring_owner_queue q ON q.owner_user_id=j.owner_user_id "
                "WHERE u.status='active' AND (?=0 OR u.role='admin') AND j.due_at<=? "
                "AND (j.lease_token IS NULL OR j.lease_until<=?) "
                "AND (j.kind!='price' OR EXISTS (SELECT 1 FROM price_alerts a "
                "WHERE a.id=j.resource_id AND a.owner_user_id=j.owner_user_id AND a.enabled=1 "
                "AND a.check_state!='triggered' "
                "AND a.arm_generation=j.alert_generation AND "
                "a.monitor_revision=j.expected_monitor_revision)) "
                "AND (?=0 OR j.kind IN ('mail','digest')) "
                "AND (?=0 OR EXISTS (SELECT 1 FROM notification_outbox required_outbox "
                "WHERE required_outbox.job_id=j.id)) "
                "AND (?=0 OR j.kind='price') "
                "AND (j.kind NOT IN ('mail','digest') OR NOT EXISTS ("
                "SELECT 1 FROM notification_outbox linked WHERE linked.job_id=j.id) OR EXISTS ("
                "SELECT 1 FROM notification_outbox o "
                "JOIN notification_preferences p ON p.owner_user_id=o.owner_user_id "
                "JOIN notification_addresses a ON a.id=o.address_id "
                "AND a.owner_user_id=o.owner_user_id "
                "WHERE o.job_id=j.id AND o.id=j.resource_id AND o.owner_user_id=j.owner_user_id "
                "AND o.state IN ('queued','claimed') AND o.attempts<? AND o.next_attempt_at<=? "
                "AND (o.state='queued' OR o.lease_until<=?) "
                "AND (o.lease_token IS NULL OR o.lease_until<=?) "
                "AND p.revision=o.preference_revision AND p.address_id=o.address_id "
                "AND a.verified_at IS NOT NULL "
                "AND ((j.kind='mail' AND o.kind='price_alert' AND p.alert_email=1) "
                "OR (j.kind='digest' AND o.kind='daily_digest' AND p.digest_email=1)) "
                ")) "
                "ORDER BY owner_sequence,j.owner_user_id,j.due_at,j.id LIMIT 1",
                (
                    int(self.admin_only),
                    now_text,
                    now_text,
                    int(outbox_only),
                    int(outbox_only),
                    int(price_only),
                    MAX_OUTBOX_ATTEMPTS,
                    now_text,
                    now_text,
                    now_text,
                ),
            ).fetchone(),
        )

    @staticmethod
    def _release_outbox_job(
        connection: sqlite3.Connection,
        *,
        job_id: str,
        owner: int,
        outbox_id: str,
        lease_token: str,
        now_text: str,
        failure_code: str | None,
        last_success_at: str | None = None,
        due_at: str = DISABLED_JOB_DUE,
    ) -> None:
        changed = connection.execute(
            "UPDATE monitoring_jobs SET due_at=?,lease_token=NULL,lease_until=NULL,"
            "active_request_id=NULL,active_requested_at=NULL,revision=revision+1,"
            "last_success_at=COALESCE(?,last_success_at),failure_code=? "
            "WHERE id=? AND owner_user_id=? AND kind='mail' AND resource_id=? AND lease_token=?",
            (due_at, last_success_at, failure_code, job_id, owner, outbox_id, lease_token),
        ).rowcount
        if changed != 1:
            raise MonitoringConflictError("The notification delivery job lease changed.")

    def _recover_expired_outbox(self, connection: sqlite3.Connection, now_text: str) -> None:
        rows = connection.execute(
            "SELECT id,owner_user_id,job_id,lease_token,state,revision,attempts,attempt_id,"
            "attempt_revision,submission_started_at FROM notification_outbox "
            "WHERE state IN ('claimed','submitting') AND lease_until<=? "
            "AND (?=0 OR EXISTS (SELECT 1 FROM users AS account "
            "WHERE account.id=notification_outbox.owner_user_id "
            "AND account.status='active' AND account.role='admin')) "
            "AND (state='submitting' OR attempts>=?) ORDER BY lease_until,id LIMIT ?",
            (now_text, int(self.admin_only), MAX_OUTBOX_ATTEMPTS, MAX_JOB_BATCH),
        ).fetchall()
        for row in rows:
            uncertain = row["state"] == "submitting"
            terminal_state = "uncertain" if uncertain else "failed"
            failure_code = "submission_lease_expired" if uncertain else "attempt_limit_reached"
            changed = connection.execute(
                "UPDATE notification_outbox SET state=?,revision=revision+1,lease_token=NULL,"
                "lease_until=NULL,completed_at=?,transitioned_at=?,failure_code=? "
                "WHERE id=? AND owner_user_id=? AND revision=? AND state=? AND lease_token=? "
                "AND lease_until<=?",
                (
                    terminal_state,
                    now_text,
                    now_text,
                    failure_code,
                    row["id"],
                    row["owner_user_id"],
                    row["revision"],
                    row["state"],
                    row["lease_token"],
                    now_text,
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError("The expired notification attempt changed.")
            self._release_outbox_job(
                connection,
                job_id=row["job_id"],
                owner=row["owner_user_id"],
                outbox_id=row["id"],
                lease_token=row["lease_token"],
                now_text=now_text,
                failure_code=failure_code,
            )

    def claim_due_jobs(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int = 20,
        lease_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        return self._claim_due_jobs(
            worker_id,
            now,
            limit=limit,
            lease_seconds=lease_seconds,
            outbox_only=False,
            price_only=False,
        )

    def claim_due_price_jobs(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int = 2,
        lease_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        """Claim only price checks, leaving outcomes and notification work for their consumers."""

        return self._claim_due_jobs(
            worker_id,
            now,
            limit=limit,
            lease_seconds=lease_seconds,
            outbox_only=False,
            price_only=True,
        )

    def claim_due_notification_outbox(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int = 20,
        lease_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        """Claim eligible persisted notification deliveries through shared fair job leases.

        A returned recipient is suitable only for an immediate SMTP attempt after the caller
        persists the submission checkpoint. This method never opens a network connection.
        """

        return self._claim_due_jobs(
            worker_id,
            now,
            limit=limit,
            lease_seconds=lease_seconds,
            outbox_only=True,
            price_only=False,
        )

    def _claim_due_jobs(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int,
        lease_seconds: int,
        outbox_only: bool,
        price_only: bool,
    ) -> list[dict[str, Any]]:
        if not isinstance(worker_id, str) or not WORKER_RE.fullmatch(worker_id):
            raise MonitoringStoreError("The worker identifier is invalid.")
        if type(limit) is not int or not 1 <= limit <= MAX_JOB_BATCH:
            raise MonitoringStoreError("The job batch size is invalid.")
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise MonitoringStoreError("The job lease duration is invalid.")
        now_dt = _datetime(now, "now")
        now_text = _timestamp(now_dt, "now")
        lease_until = _timestamp(now_dt + timedelta(seconds=lease_seconds), "lease_until")
        claims: list[dict[str, Any]] = []
        with self._write() as connection:
            self._recover_expired_outbox(connection, now_text)
            control = connection.execute(
                "SELECT enabled,queue_sequence FROM monitoring_control WHERE id=1"
            ).fetchone()
            if control is None or control["enabled"] != 1:
                return []
            for _ in range(limit):
                row = self._claim_row(connection, now_text, outbox_only, price_only)
                if row is None:
                    break
                owner = row["owner_user_id"]
                self._active_owner(connection, owner)
                checkpoint = json.loads(row["checkpoint_json"])
                request_id = str(uuid4())
                requested_at = now_text
                checkpoint_claim = {
                    "request_id": request_id,
                    "requested_at": requested_at,
                    "worker_id": worker_id,
                    "generation": row["alert_generation"],
                    "expected_monitor_revision": row["expected_monitor_revision"],
                    "request_kind": row["request_kind"],
                }
                checkpoint["active_claim"] = checkpoint_claim
                encoded_checkpoint = _canonical_json(checkpoint, MAX_CHECKPOINT_BYTES)
                lease_token = str(uuid4())
                job_revision = row["revision"] + 1
                changed = connection.execute(
                    "UPDATE monitoring_jobs SET lease_token=?,lease_until=?,active_request_id=?,"
                    "active_requested_at=?,attempts=attempts+1,revision=revision+1,last_attempt_at=?,"
                    "checkpoint_json=? WHERE id=? AND owner_user_id=? AND revision=? "
                    "AND (lease_token IS NULL OR lease_until<=?)",
                    (
                        lease_token,
                        lease_until,
                        request_id,
                        requested_at,
                        now_text,
                        encoded_checkpoint,
                        row["id"],
                        owner,
                        row["revision"],
                        now_text,
                    ),
                ).rowcount
                if changed != 1:
                    raise MonitoringConflictError(
                        "The job lease changed before it could be claimed."
                    )
                claim: dict[str, Any] = {
                    "job_id": row["id"],
                    "owner_user_id": owner,
                    "kind": row["kind"],
                    "resource_id": row["resource_id"],
                    "lease_token": lease_token,
                    "lease_until": lease_until,
                    "request_id": request_id,
                    "requested_at": requested_at,
                    "request_kind": row["request_kind"],
                    "arm_generation": row["alert_generation"],
                    "expected_monitor_revision": row["expected_monitor_revision"],
                    "job_revision": job_revision,
                    "worker_id": worker_id,
                    "checkpoint": checkpoint,
                }
                if (
                    row["kind"] in {"mail", "digest"}
                    and connection.execute(
                        "SELECT 1 FROM notification_outbox WHERE job_id=?", (row["id"],)
                    ).fetchone()
                    is not None
                ):
                    outbox = connection.execute(
                        "SELECT o.*,a.address AS recipient FROM notification_outbox o "
                        "JOIN notification_preferences p ON p.owner_user_id=o.owner_user_id "
                        "JOIN notification_addresses a ON a.id=o.address_id "
                        "AND a.owner_user_id=o.owner_user_id "
                        "WHERE o.job_id=? AND o.id=? AND o.owner_user_id=? "
                        "AND o.state IN ('queued','claimed') AND o.attempts<? "
                        "AND o.next_attempt_at<=? AND (o.state='queued' OR o.lease_until<=?) "
                        "AND (o.lease_token IS NULL OR o.lease_until<=?) "
                        "AND p.revision=o.preference_revision AND p.address_id=o.address_id "
                        "AND a.verified_at IS NOT NULL AND p.alert_email=1",
                        (
                            row["id"],
                            row["resource_id"],
                            owner,
                            MAX_OUTBOX_ATTEMPTS,
                            now_text,
                            now_text,
                            now_text,
                        ),
                    ).fetchone()
                    if outbox is None:
                        raise MonitoringConflictError(
                            "The notification delivery became ineligible before claim."
                        )
                    attempt_id = str(uuid4())
                    outbox_revision = outbox["revision"] + 1
                    attempt_revision = outbox["attempt_revision"] + 1
                    outbox_changed = connection.execute(
                        "UPDATE notification_outbox SET state='claimed',attempts=attempts+1,"
                        "attempt_revision=attempt_revision+1,attempt_id=?,revision=revision+1,"
                        "next_attempt_at=next_attempt_at,lease_token=?,lease_until=?,"
                        "transitioned_at=?,failure_code=NULL WHERE id=? AND owner_user_id=? "
                        "AND revision=? AND state=? AND (lease_token IS NULL OR lease_until<=?)",
                        (
                            attempt_id,
                            lease_token,
                            lease_until,
                            now_text,
                            outbox["id"],
                            owner,
                            outbox["revision"],
                            outbox["state"],
                            now_text,
                        ),
                    ).rowcount
                    if outbox_changed != 1:
                        raise MonitoringConflictError(
                            "The notification delivery changed before claim."
                        )
                    claim.update(
                        {
                            "outbox_id": outbox["id"],
                            "outbox_revision": outbox_revision,
                            "attempt_id": attempt_id,
                            "attempt_revision": attempt_revision,
                            "notification_id": outbox["notification_id"],
                            "delivery_version": outbox["delivery_version"],
                            "preference_revision": outbox["preference_revision"],
                            "outbox_kind": outbox["kind"],
                            "outbox_payload": json.loads(outbox["payload_json"]),
                            "recipient": outbox["recipient"],
                            "outbox_state": "claimed",
                        }
                    )
                queue_sequence = connection.execute(
                    "SELECT queue_sequence FROM monitoring_control WHERE id=1"
                ).fetchone()[0]
                if queue_sequence >= 2**63 - 1:
                    raise MonitoringStoreError("The job fairness sequence is exhausted.")
                next_sequence = queue_sequence + 1
                control_changed = connection.execute(
                    "UPDATE monitoring_control SET queue_sequence=? "
                    "WHERE id=1 AND queue_sequence=?",
                    (next_sequence, queue_sequence),
                ).rowcount
                if control_changed != 1:
                    raise MonitoringConflictError("The monitoring queue changed during claim.")
                self._ensure_queue(connection, owner, now_text)
                queue_changed = connection.execute(
                    "UPDATE monitoring_owner_queue SET service_sequence=?,last_served_at=? "
                    "WHERE owner_user_id=?",
                    (next_sequence, now_text, owner),
                ).rowcount
                if queue_changed != 1:
                    raise MonitoringStoreError("The owner fairness row is unavailable.")
                claims.append(claim)
        return claims

    @staticmethod
    def _validated_claim(claim: object, owner: int) -> dict[str, Any]:
        if not isinstance(claim, Mapping):
            raise MonitoringStoreError("The job claim is invalid.")
        result = dict(claim)
        claim_kind = result.get("kind")
        if not isinstance(claim_kind, str) or claim_kind not in JOB_KINDS | {"price"}:
            raise MonitoringStoreError("The job claim is invalid.")
        is_outbox_claim = isinstance(claim_kind, str) and claim_kind in {"mail", "digest"}
        expected_fields = OUTBOX_CLAIM_FIELDS if is_outbox_claim else CLAIM_FIELDS
        if set(result) != expected_fields:
            raise MonitoringStoreError("The job claim is invalid.")
        claim_owner = _owner_id(result["owner_user_id"])
        if claim_owner != owner:
            raise MonitoringStoreError("The job claim is unavailable.")
        result["job_id"] = _canonical_uuid(result["job_id"], "job id")
        result["lease_token"] = _canonical_uuid(result["lease_token"], "lease token")
        result["request_id"] = _canonical_uuid(result["request_id"], "request id")
        if not isinstance(result["worker_id"], str) or not WORKER_RE.fullmatch(result["worker_id"]):
            raise MonitoringStoreError("The job claim is invalid.")
        if type(result["job_revision"]) is not int or result["job_revision"] < 2:
            raise MonitoringStoreError("The job claim is invalid.")
        if result["request_kind"] is not None and (
            not isinstance(result["request_kind"], str)
            or result["request_kind"] not in {"arm_snapshot", "tick"}
        ):
            raise MonitoringStoreError("The job claim is invalid.")
        if result["kind"] in {"mail", "digest"}:
            result["outbox_id"] = _canonical_uuid(result["outbox_id"], "outbox id")
            result["attempt_id"] = _canonical_uuid(result["attempt_id"], "attempt id")
            result["notification_id"] = _canonical_uuid(
                result["notification_id"], "notification id"
            )
            if result["resource_id"] != result["outbox_id"]:
                raise MonitoringStoreError("The outbox claim is invalid.")
            _revision(result["outbox_revision"], "outbox revision")
            _revision(result["attempt_revision"], "attempt revision")
            _revision(result["delivery_version"], "delivery version")
            _revision(result["preference_revision"], "preference revision")
            if not isinstance(result["outbox_state"], str) or result["outbox_state"] not in {
                "claimed",
                "submitting",
            }:
                raise MonitoringStoreError("The outbox claim is invalid.")
            if result["outbox_kind"] != "price_alert":
                raise MonitoringStoreError("The outbox claim is invalid.")
            if not isinstance(result["outbox_payload"], Mapping):
                raise MonitoringStoreError("The outbox claim is invalid.")
            if (
                not isinstance(result["recipient"], str)
                or not 3 <= len(result["recipient"]) <= 320
                or not result["recipient"].isascii()
                or not result["recipient"].isprintable()
            ):
                raise MonitoringStoreError("The outbox claim is invalid.")
        if result["arm_generation"] is not None:
            _revision(result["arm_generation"], "arm generation")
        if result["expected_monitor_revision"] is not None:
            _revision(result["expected_monitor_revision"], "monitor revision")
        if not isinstance(result["checkpoint"], Mapping):
            raise MonitoringStoreError("The job claim is invalid.")
        _timestamp(_parse_timestamp(result["lease_until"], "lease expiry"), "lease expiry")
        _timestamp(_parse_timestamp(result["requested_at"], "request time"), "request time")
        return result

    @staticmethod
    def _validated_price_claim(claim: object, owner: int, alert_id: str) -> dict[str, Any]:
        """Require the complete lease identity for a typed persisted price transition."""

        result = MonitoringStore._validated_claim(claim, owner)
        if (
            result["kind"] != "price"
            or result["resource_id"] != alert_id
            or result["arm_generation"] is None
            or result["expected_monitor_revision"] is None
            or result["request_kind"] not in {"arm_snapshot", "tick"}
        ):
            raise MonitoringStoreError("The active price claim does not match this alert.")
        return result

    def get_price_claim_context(
        self,
        owner_user_id: int,
        alert_id: str,
        claim: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Read alert configuration only while its active price lease and control remain valid."""

        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(alert_id, "alert_id")
        validated = self._validated_price_claim(claim, owner, identifier)
        now_text = _timestamp(now, "now")
        with self.repository.connect() as connection:
            self._active_owner(connection, owner)
            control = connection.execute(
                "SELECT enabled FROM monitoring_control WHERE id=1"
            ).fetchone()
            if control is None or control["enabled"] != 1:
                raise MonitoringConflictError("Monitoring is disabled.")
            alert = self._alert_row(connection, owner, identifier)
            job = connection.execute(
                "SELECT * FROM monitoring_jobs WHERE id=? AND owner_user_id=? AND "
                "kind='price' AND resource_id=?",
                (validated["job_id"], owner, identifier),
            ).fetchone()
        if (
            job is None
            or alert["enabled"] != 1
            or alert["check_state"] == "triggered"
            or alert["arm_generation"] != validated["arm_generation"]
            or alert["monitor_revision"] != validated["expected_monitor_revision"]
            or job["alert_generation"] != validated["arm_generation"]
            or job["expected_monitor_revision"] != validated["expected_monitor_revision"]
            or job["request_kind"] != validated["request_kind"]
            or job["revision"] != validated["job_revision"]
            or job["lease_token"] != validated["lease_token"]
            or job["lease_until"] is None
            or job["lease_until"] <= now_text
            or job["active_request_id"] != validated["request_id"]
            or job["active_requested_at"] != validated["requested_at"]
        ):
            raise MonitoringConflictError("The price claim is stale or no longer leased.")
        return self._alert_dict(alert)

    @staticmethod
    def _validated_outbox_claim(claim: object, owner: int) -> dict[str, Any]:
        validated = MonitoringStore._validated_claim(claim, owner)
        if not isinstance(validated["kind"], str) or validated["kind"] not in {
            "mail",
            "digest",
        }:
            raise MonitoringStoreError("The notification delivery claim is invalid.")
        return validated

    def record_price_failure(
        self,
        owner_user_id: int,
        alert_id: str,
        claim: Mapping[str, Any],
        failure_code: str,
        now: datetime,
        *,
        next_due_at: datetime,
    ) -> dict[str, Any]:
        """Persist one bounded provider failure without replacing the last good quote."""

        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(alert_id, "alert_id")
        validated = self._validated_price_claim(claim, owner, identifier)
        if not isinstance(failure_code, str) or failure_code not in PRICE_FAILURE_CODES:
            raise MonitoringStoreError("The price failure code is invalid.")
        current = _timestamp(now, "now")
        due = _timestamp(next_due_at, "next_due_at")
        current_dt = _parse_timestamp(current, "now")
        due_dt = _parse_timestamp(due, "next_due_at")
        if due_dt <= current_dt or due_dt > current_dt + timedelta(days=7):
            raise MonitoringStoreError("The next monitoring check time is outside its bound.")
        expected_revision = _revision(validated["expected_monitor_revision"], "monitor revision")
        generation = _revision(validated["arm_generation"], "arm generation")
        with self._write() as connection:
            self._active_owner(connection, owner)
            control = connection.execute(
                "SELECT enabled FROM monitoring_control WHERE id=1"
            ).fetchone()
            if control is None or control["enabled"] != 1:
                raise MonitoringConflictError("Monitoring was disabled before failure recording.")
            row = self._alert_row(connection, owner, identifier)
            job = connection.execute(
                "SELECT * FROM monitoring_jobs WHERE id=? AND owner_user_id=? AND "
                "kind='price' AND resource_id=?",
                (validated["job_id"], owner, identifier),
            ).fetchone()
            if job is None:
                raise MonitoringConflictError("The price job is unavailable.")
            checkpoint = json.loads(job["checkpoint_json"])
            prior = checkpoint.get("last_failure")
            if isinstance(prior, dict) and (
                prior.get("request_id") == validated["request_id"]
                and prior.get("lease_token") == validated["lease_token"]
            ):
                if prior.get("failure_code") != failure_code:
                    raise MonitoringConflictError(
                        "This price request already has a different failure result."
                    )
                return {
                    "alert_id": identifier,
                    "request_id": validated["request_id"],
                    "failure_code": failure_code,
                    "monitor_revision": prior["monitor_revision"],
                    "replayed": True,
                }
            if (
                row["enabled"] != 1
                or row["check_state"] == "triggered"
                or row["arm_generation"] != generation
                or row["monitor_revision"] != expected_revision
                or job["alert_generation"] != generation
                or job["expected_monitor_revision"] != expected_revision
                or job["request_kind"] != validated["request_kind"]
                or job["revision"] != validated["job_revision"]
                or job["lease_token"] != validated["lease_token"]
                or job["lease_until"] is None
                or job["lease_until"] <= current
                or job["active_request_id"] != validated["request_id"]
                or job["active_requested_at"] != validated["requested_at"]
            ):
                raise MonitoringConflictError(
                    "The price failure is from a stale generation or server lease."
                )
            after_revision = expected_revision + 1
            alert_changed = connection.execute(
                "UPDATE price_alerts SET monitor_revision=?,last_check_at=?,check_state="
                "'unavailable',updated_at=? WHERE id=? AND owner_user_id=? AND enabled=1 "
                "AND monitor_revision=? AND arm_generation=? AND check_state!='triggered'",
                (
                    after_revision,
                    current,
                    current,
                    identifier,
                    owner,
                    expected_revision,
                    generation,
                ),
            ).rowcount
            if alert_changed != 1:
                raise MonitoringConflictError("The alert changed while recording a price failure.")
            checkpoint_json = _canonical_json(
                {
                    "last_failure": {
                        "request_id": validated["request_id"],
                        "lease_token": validated["lease_token"],
                        "failure_code": failure_code,
                        "monitor_revision": after_revision,
                    }
                },
                MAX_CHECKPOINT_BYTES,
            )
            job_changed = connection.execute(
                "UPDATE monitoring_jobs SET due_at=?,expected_monitor_revision=?,lease_token=NULL,"
                "lease_until=NULL,active_request_id=NULL,active_requested_at=NULL,revision=revision+1,"
                "failure_code=?,checkpoint_json=? WHERE id=? AND owner_user_id=? AND kind='price' "
                "AND resource_id=? AND revision=? AND lease_token=? AND active_request_id=?",
                (
                    due,
                    after_revision,
                    failure_code,
                    checkpoint_json,
                    validated["job_id"],
                    owner,
                    identifier,
                    validated["job_revision"],
                    validated["lease_token"],
                    validated["request_id"],
                ),
            ).rowcount
            if job_changed != 1:
                raise MonitoringConflictError(
                    "The price job lease changed during failure recording."
                )
            return {
                "alert_id": identifier,
                "request_id": validated["request_id"],
                "failure_code": failure_code,
                "monitor_revision": after_revision,
                "replayed": False,
            }

    def checkpoint_job(
        self,
        owner_user_id: int,
        claim: Mapping[str, Any],
        checkpoint: Mapping[str, Any],
        now: datetime,
        *,
        due_at: datetime,
        failure_code: str | None = None,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        validated = self._validated_claim(claim, owner)
        if validated["kind"] == "price" or "outbox_id" in validated:
            raise MonitoringStoreError(
                "Price and email jobs require their typed evidence transition."
            )
        if not isinstance(checkpoint, Mapping) or "active_claim" in checkpoint:
            raise MonitoringStoreError("The job checkpoint is invalid.")
        payload = _canonical_json(checkpoint, MAX_CHECKPOINT_BYTES)
        now_text = _timestamp(now, "now")
        due_text = _timestamp(due_at, "due_at")
        if failure_code is not None and (
            not isinstance(failure_code, str) or not FAILURE_RE.fullmatch(failure_code)
        ):
            raise MonitoringStoreError("The job failure code is invalid.")
        with self._write() as connection:
            self._active_owner(connection, owner)
            row = connection.execute(
                "SELECT revision,lease_token,lease_until,active_request_id,active_requested_at "
                "FROM monitoring_jobs WHERE id=? AND owner_user_id=? AND kind=? AND resource_id=?",
                (validated["job_id"], owner, validated["kind"], validated["resource_id"]),
            ).fetchone()
            if (
                row is None
                or row["revision"] != validated["job_revision"]
                or row["lease_token"] != validated["lease_token"]
                or row["active_request_id"] != validated["request_id"]
                or row["active_requested_at"] != validated["requested_at"]
                or row["lease_until"] <= now_text
            ):
                raise MonitoringConflictError(
                    "The job lease is stale or no longer owned by this worker."
                )
            updated = connection.execute(
                "UPDATE monitoring_jobs SET due_at=?,checkpoint_json=?,lease_token=NULL,l"
                "ease_until=NULL,"
                "active_request_id=NULL,active_requested_at=NULL,revision=revision+1,last"
                "_success_at=?,failure_code=? "
                "WHERE id=? AND owner_user_id=? AND revision=? AND lease_token=? AND "
                "active_request_id=?",
                (
                    due_text,
                    payload,
                    now_text,
                    failure_code,
                    validated["job_id"],
                    owner,
                    validated["job_revision"],
                    validated["lease_token"],
                    validated["request_id"],
                ),
            ).rowcount
            if updated != 1:
                raise MonitoringConflictError("The job lease changed during checkpoint.")
            return {
                "job_id": validated["job_id"],
                "owner_user_id": owner,
                "kind": validated["kind"],
                "due_at": due_text,
                "checkpoint": json.loads(payload),
                "failure_code": failure_code,
            }

    def record_price_observation(
        self,
        owner_user_id: int,
        alert_id: str,
        claim: Mapping[str, Any],
        observation: PriceObservation,
        received_at: datetime,
        now: datetime,
        *,
        next_due_at: datetime,
    ) -> dict[str, Any]:
        owner = _owner_id(owner_user_id)
        identifier = _canonical_uuid(alert_id, "alert_id")
        validated = self._validated_price_claim(claim, owner, identifier)
        if not isinstance(observation, PriceObservation):
            raise MonitoringStoreError("A provider-labelled observation is required.")
        received = _timestamp(received_at, "received_at")
        current = _timestamp(now, "now")
        due = _timestamp(next_due_at, "next_due_at")
        request_time = _timestamp(
            _parse_timestamp(validated["requested_at"], "request time"), "request time"
        )
        received_dt = _parse_timestamp(received, "received_at")
        current_dt = _parse_timestamp(current, "now")
        due_dt = _parse_timestamp(due, "next_due_at")
        if received_dt < _parse_timestamp(request_time, "request time") or received_dt > current_dt:
            raise MonitoringStoreError("Fetch receipt time is outside the active server request.")
        if due_dt <= current_dt or due_dt > current_dt + timedelta(days=7):
            raise MonitoringStoreError("The next monitoring check time is outside its bound.")
        generation = _revision(validated["arm_generation"], "arm generation")
        request_material = {
            "owner_user_id": owner,
            "alert_id": identifier,
            "job_id": validated["job_id"],
            "generation": generation,
            "request_id": validated["request_id"],
            "request_kind": validated["request_kind"],
            "requested_at": request_time,
            "lease_token": validated["lease_token"],
            "worker_id": validated["worker_id"],
        }
        request_hash = _sha256(request_material)
        receipt_material = {
            "request": request_material,
            "received_at": received,
            "observation": {
                "symbol": observation.symbol,
                "price": observation.price,
                "currency": observation.currency,
                "observed_at": _timestamp(observation.observed_at, "observed_at"),
                "provider": observation.provider,
            },
        }
        receipt_hash = _sha256(receipt_material)
        dedupe_hash = _sha256([owner, identifier, generation, validated["request_id"]])
        observed_text = _timestamp(observation.observed_at, "observed_at")
        with self._write() as connection:
            self._active_owner(connection, owner)
            control = connection.execute(
                "SELECT enabled FROM monitoring_control WHERE id=1"
            ).fetchone()
            if control is None or control["enabled"] != 1:
                raise MonitoringConflictError(
                    "Monitoring was disabled before observation recording."
                )
            prior = connection.execute(
                "SELECT receipt_sha256,lease_token,disposition,stale,state_revision_after "
                "FROM price_alert_observations WHERE request_id=? AND owner_user_id=?",
                (validated["request_id"], owner),
            ).fetchone()
            if prior is not None:
                if (
                    prior["receipt_sha256"] != receipt_hash
                    or prior["lease_token"] != validated["lease_token"]
                ):
                    raise MonitoringConflictError(
                        "This request id already has a different provider receipt."
                    )
                return {
                    "alert_id": identifier,
                    "request_id": validated["request_id"],
                    "generation": generation,
                    "disposition": prior["disposition"],
                    "stale": bool(prior["stale"]),
                    "monitor_revision": prior["state_revision_after"],
                    "replayed": True,
                }
            row = self._alert_row(connection, owner, identifier)
            job = connection.execute(
                "SELECT * FROM monitoring_jobs WHERE id=? AND owner_user_id=? AND "
                "kind='price' AND resource_id=?",
                (validated["job_id"], owner, identifier),
            ).fetchone()
            if (
                job is None
                or row["enabled"] != 1
                or row["check_state"] == "triggered"
                or row["arm_generation"] != generation
                or row["monitor_revision"] != validated["expected_monitor_revision"]
                or job["alert_generation"] != generation
                or job["expected_monitor_revision"] != row["monitor_revision"]
                or job["request_kind"] != validated["request_kind"]
                or job["revision"] != validated["job_revision"]
                or job["lease_token"] != validated["lease_token"]
                or job["lease_until"] <= current
                or job["active_request_id"] != validated["request_id"]
                or job["active_requested_at"] != request_time
            ):
                raise MonitoringConflictError(
                    "The price observation is from a stale generation or server lease."
                )
            state = self._crossing_state(row)
            if validated["request_kind"] == "arm_snapshot":
                if state.arm_snapshot_generation is not None:
                    raise MonitoringConflictError(
                        "The current arm already has its baseline snapshot."
                    )
                snapshot = ArmBaselineSnapshot(
                    generation,
                    observation,
                    _parse_timestamp(request_time, "request time"),
                    received_dt,
                )
                try:
                    evaluation = evaluate_arm_snapshot(state, snapshot, current_dt)
                except MonitoringError as error:
                    raise MonitoringStoreError(str(error)) from error
            elif validated["request_kind"] == "tick":
                if state.arm_snapshot_generation != generation:
                    raise MonitoringConflictError(
                        "The current arm has no accepted baseline snapshot."
                    )
                try:
                    evaluation = evaluate_crossing(
                        state,
                        observation,
                        current_dt,
                        generation=generation,
                    )
                except MonitoringError as error:
                    raise MonitoringStoreError(str(error)) from error
            else:
                raise MonitoringStoreError("The active price request kind is invalid.")
            updated_state = evaluation.state
            before_revision = row["monitor_revision"]
            after_revision = before_revision + 1
            snapshot_generation = updated_state.arm_snapshot_generation
            if snapshot_generation == generation and row["arm_snapshot_generation"] is None:
                snapshot_request_id = validated["request_id"]
                snapshot_requested_at = request_time
                snapshot_received_at = received
            else:
                snapshot_request_id = row["arm_snapshot_request_id"]
                snapshot_requested_at = row["arm_snapshot_requested_at"]
                snapshot_received_at = row["arm_snapshot_received_at"]
            observed_changed = updated_state.last_observed_at != state.last_observed_at
            if observed_changed:
                last_observed = _timestamp(updated_state.last_observed_at, "last_observed_at")
                last_observation_json = _canonical_json(
                    {
                        "symbol": observation.symbol,
                        "currency": observation.currency,
                        "price": observation.price,
                        "provider": observation.provider,
                        "observed_at": observed_text,
                    },
                    4096,
                )
            else:
                last_observed = row["last_observed_at"]
                last_observation_json = row["last_observation_json"]
            if not updated_state.enabled and evaluation.disposition == "triggered":
                check_state = "triggered"
            elif not updated_state.enabled:
                check_state = "paused"
            elif updated_state.arm_snapshot_generation is None:
                check_state = "arming"
            else:
                check_state = "watching"
            connection.execute(
                "INSERT INTO price_alert_observations(request_id,owner_user_id,alert_id,j"
                "ob_id,generation,"
                "observation_kind,request_sha256,receipt_sha256,dedupe_sha256,lease_token,requested_at,"
                "received_at,accepted_at,observed_at,provider,symbol,currency,price,disposition,stale,"
                "state_revision_before,state_revision_after) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    validated["request_id"],
                    owner,
                    identifier,
                    validated["job_id"],
                    generation,
                    validated["request_kind"],
                    request_hash,
                    receipt_hash,
                    dedupe_hash,
                    validated["lease_token"],
                    request_time,
                    received,
                    current,
                    observed_text,
                    observation.provider,
                    observation.symbol,
                    observation.currency,
                    observation.price,
                    evaluation.disposition,
                    int(evaluation.stale),
                    before_revision,
                    after_revision,
                ),
            )
            if evaluation.disposition == "triggered":
                notification_id = self._insert_crossing_notification(
                    connection,
                    owner,
                    row,
                    generation,
                    observation,
                    received,
                )
                self._enqueue_crossing_email_if_eligible(
                    connection,
                    owner,
                    notification_id,
                    received,
                )
            changed = connection.execute(
                "UPDATE price_alerts SET monitor_revision=?,enabled=?,arm_generation=?,"
                "arm_snapshot_generation=?,arm_snapshot_request_id=?,arm_snapshot_requested_at=?,"
                "arm_snapshot_received_at=?,last_side=?,ready=?,last_observed_at=?,last_observation_json=?,"
                "last_fetch_request_id=?,last_fetch_requested_at=?,last_fetch_received_at=?,last_check_at=?,"
                "last_success_at=?,check_state=?,updated_at=? WHERE id=? AND owner_user_id=? "
                "AND monitor_revision=? AND arm_generation=? AND enabled=1",
                (
                    after_revision,
                    int(row["enabled"]),
                    updated_state.arm_generation,
                    snapshot_generation,
                    snapshot_request_id,
                    snapshot_requested_at,
                    snapshot_received_at,
                    updated_state.last_side,
                    int(updated_state.ready),
                    last_observed,
                    last_observation_json,
                    validated["request_id"],
                    request_time,
                    received,
                    current,
                    current,
                    check_state,
                    current,
                    identifier,
                    owner,
                    before_revision,
                    generation,
                ),
            ).rowcount
            if changed != 1:
                raise MonitoringConflictError("The alert checkpoint changed during observation.")
            next_kind = "tick" if snapshot_generation == generation else "arm_snapshot"
            next_due = due if updated_state.enabled else DISABLED_JOB_DUE
            checkpoint_json = _canonical_json(
                {
                    "last_request_id": validated["request_id"],
                    "last_disposition": evaluation.disposition,
                },
                MAX_CHECKPOINT_BYTES,
            )
            finished = connection.execute(
                "UPDATE monitoring_jobs SET due_at=?,expected_monitor_revision=?,request_kind=?,"
                "lease_token=NULL,lease_until=NULL,active_request_id=NULL,active_requested_at=NULL,"
                "revision=revision+1,last_success_at=?,failure_code=NULL,checkpoint_json=? "
                "WHERE id=? AND owner_user_id=? AND revision=? AND lease_token=? AND "
                "active_request_id=?",
                (
                    next_due,
                    after_revision,
                    next_kind,
                    current,
                    checkpoint_json,
                    validated["job_id"],
                    owner,
                    validated["job_revision"],
                    validated["lease_token"],
                    validated["request_id"],
                ),
            ).rowcount
            if finished != 1:
                raise MonitoringConflictError("The price job lease changed during checkpoint.")
            return {
                "alert_id": identifier,
                "request_id": validated["request_id"],
                "generation": generation,
                "disposition": evaluation.disposition,
                "stale": evaluation.stale,
                "monitor_revision": after_revision,
                "notification_dedupe_sha256": self._crossing_dedupe(
                    owner, identifier, generation, observation
                )
                if evaluation.disposition == "triggered"
                else None,
                "replayed": False,
            }

    @staticmethod
    def _crossing_dedupe(
        owner: int, alert_id: str, generation: int, observation: PriceObservation
    ) -> str:
        return _sha256(
            [
                "price_alert",
                owner,
                alert_id,
                generation,
                observation.symbol,
                observation.currency,
                observation.observed_at.astimezone(UTC).isoformat(timespec="microseconds"),
                observation.price,
            ]
        )

    def _insert_crossing_notification(
        self,
        connection: sqlite3.Connection,
        owner: int,
        alert: sqlite3.Row,
        generation: int,
        observation: PriceObservation,
        received_at: str,
    ) -> str:
        dedupe = self._crossing_dedupe(owner, alert["id"], generation, observation)
        payload = {
            "alert_id": alert["id"],
            "generation": generation,
            "symbol": observation.symbol,
            "currency": observation.currency,
            "threshold": json.loads(alert["payload_json"])["threshold"],
            "direction": json.loads(alert["payload_json"])["direction"],
            "price": observation.price,
            "provider": observation.provider,
            "observed_at": _timestamp(observation.observed_at, "observed_at"),
        }
        payload_json = _canonical_json(payload, MAX_NOTIFICATION_BYTES)
        existing = connection.execute(
            "SELECT id,payload_json,kind FROM notifications WHERE owner_user_id=? "
            "AND dedupe_sha256=?",
            (owner, dedupe),
        ).fetchone()
        if existing is not None:
            if existing["kind"] != "price_alert" or existing["payload_json"] != payload_json:
                raise MonitoringConflictError("A notification dedupe key has conflicting content.")
            return cast(str, existing["id"])
        notification_id = str(uuid4())
        connection.execute(
            "INSERT INTO notifications(id,owner_user_id,dedupe_sha256,kind,payload_js"
            "on,created_at) "
            "VALUES (?,?,?,'price_alert',?,?)",
            (notification_id, owner, dedupe, payload_json, received_at),
        )
        return notification_id
