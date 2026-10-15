"""Owner-bound, restart-safe persistence for verified notification addresses.

This module uses the draft schema in migration 018. The repository does not register that
migration yet; app integration must wait for schema, backup, restore and export review.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from stock_probs.invitation_mail import validate_email_address
from stock_probs.monitoring_store import (
    MonitoringStore,
    MonitoringStoreError,
)

CHALLENGE_LIFETIME = timedelta(minutes=20)
REQUEST_WINDOW = timedelta(hours=1)
MAX_REQUESTS_PER_WINDOW = 3
MAX_CODE_ATTEMPTS = 5
MAX_CHALLENGES_PER_OWNER = 100
MAINTENANCE_BATCH_SIZE = 20
SUBMISSION_RECOVERY_AGE = timedelta(seconds=30)
_FAILURE_CODES = frozenset(
    {
        "smtp_prepare_failed",
        "smtp_rejected",
        "smtp_outcome_unknown",
        "challenge_expired",
        "attempts_exhausted",
    }
)
_SAFE_HEX = re.compile(r"^[0-9a-f]{64}$")


class NotificationAddressError(ValueError):
    """Safe validation, ownership, and state failure for notification-address work."""


class NotificationAddressConflict(NotificationAddressError):
    """An idempotency key or expected revision conflicts with persisted state."""


class NotificationAddressRateLimited(NotificationAddressError):
    """The owner has reached the bounded challenge-request rate."""


class NotificationAddressUnavailable(NotificationAddressError):
    """The owner, feature control, schema, or challenge is unavailable."""


@dataclass(frozen=True)
class VerificationIssue:
    """One explicit request result; the email and code are never part of its representation."""

    verification_id: str
    address_id: str
    state: str
    revision: int
    expires_at: str
    replayed: bool
    _code: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class VerificationStatus:
    """Safe status projection that contains no mailbox, token, or transport detail."""

    verification_id: str
    address_id: str
    state: str
    revision: int
    attempts: int
    expires_at: str
    invalidated: bool


class NotificationAddressStore:
    """Persist challenges through typed transitions and recheck authorization in SQLite."""

    def __init__(self, monitoring_store: MonitoringStore):
        if not isinstance(monitoring_store, MonitoringStore):
            raise TypeError("monitoring_store must be a MonitoringStore")
        self._monitoring = monitoring_store
        self.repository = monitoring_store.repository

    def request_verification(
        self,
        owner_user_id: int,
        address: str,
        idempotency_key: str,
        now: datetime,
        *,
        supersedes_verification_id: str | None = None,
        expected_revision: int | None = None,
    ) -> VerificationIssue:
        """Queue a new explicit challenge, invalidating older pending codes atomically.

        A replay returns only the persisted status and never recreates or resends a code. Use a
        new key to request a replacement code after reading the prior challenge status.
        """

        owner = self._owner_id(owner_user_id)
        mailbox = self._mailbox(address)
        key = self._uuid(idempotency_key, "idempotency key")
        supersedes = (
            self._uuid(supersedes_verification_id, "verification id")
            if supersedes_verification_id is not None
            else None
        )
        expected = self._revision(expected_revision) if expected_revision is not None else None
        if (supersedes is None) != (expected is None):
            raise NotificationAddressError("The replacement challenge is invalid.")
        timestamp = self._timestamp(now)
        key_digest = self._sha256(key.encode("ascii"))
        request_digest = self._sha256(mailbox.encode("ascii"))
        code = secrets.token_urlsafe(32)
        code_digest = self._sha256(code.encode("ascii"))
        challenge_id = str(uuid4())
        expires = timestamp + CHALLENGE_LIFETIME
        with self._monitoring._write() as connection:
            owner = self._authorized_owner(connection, owner, require_control=True)
            existing = connection.execute(
                "SELECT * FROM notification_address_verifications WHERE owner_user_id=? "
                "AND idempotency_sha256=?",
                (owner, key_digest),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_digest:
                    raise NotificationAddressConflict("The idempotency key conflicts.")
                existing = self._reconcile_challenge(connection, existing, timestamp)
                self._maintain_owner(
                    connection,
                    owner,
                    timestamp,
                    limit=MAINTENANCE_BATCH_SIZE,
                    exclude=existing["id"],
                )
                return self._issue(existing, replayed=True)

            window_start = (
                (timestamp - REQUEST_WINDOW)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
            recent = connection.execute(
                "SELECT COUNT(*) AS count FROM notification_address_verifications "
                "WHERE owner_user_id=? AND requested_at>=?",
                (owner, window_start),
            ).fetchone()["count"]
            if type(recent) is not int or recent >= MAX_REQUESTS_PER_WINDOW:
                raise NotificationAddressRateLimited("Too many verification requests.")

            challenge_count = connection.execute(
                "SELECT COUNT(*) AS count FROM notification_address_verifications "
                "WHERE owner_user_id=?",
                (owner,),
            ).fetchone()["count"]
            if type(challenge_count) is not int or challenge_count >= MAX_CHALLENGES_PER_OWNER:
                raise NotificationAddressRateLimited("The verification history limit was reached.")

            if supersedes is not None:
                previous = self._verification_row(connection, owner, supersedes)
                previous = self._reconcile_challenge(connection, previous, timestamp)
                if previous["revision"] != expected:
                    raise NotificationAddressConflict("The verification challenge changed.")
                if previous["invalidated_at"] is not None or previous["state"] == "verified":
                    raise NotificationAddressConflict(
                        "The verification challenge cannot be replaced."
                    )
                if previous["state"] == "submitting":
                    raise NotificationAddressConflict(
                        "The verification submission is still active."
                    )
                if previous["state"] not in {
                    "queued",
                    "accepted",
                    "uncertain",
                    "failed",
                    "expired",
                }:
                    raise NotificationAddressConflict(
                        "The verification challenge cannot be replaced."
                    )
                previous = self._invalidate(connection, previous, timestamp)

            prior = connection.execute(
                "SELECT * FROM notification_address_verifications WHERE owner_user_id=? "
                "AND invalidated_at IS NULL AND state IN "
                "('queued','submitting','accepted','uncertain')",
                (owner,),
            ).fetchall()
            for row in prior:
                if supersedes is not None and row["id"] == supersedes:
                    continue
                current = row
                if current["state"] == "submitting":
                    current = self._recover_stale_submission(connection, current, timestamp)
                if current["state"] == "submitting":
                    raise NotificationAddressConflict(
                        "The verification submission is still active."
                    )
                self._invalidate(connection, current, timestamp)

            verified = connection.execute(
                "SELECT id,verified_at FROM notification_addresses WHERE owner_user_id=? "
                "AND address=? AND verified_at IS NOT NULL ORDER BY created_at DESC,id LIMIT 1",
                (owner, mailbox),
            ).fetchone()
            address_id = verified["id"] if verified is not None else str(uuid4())
            state = "already_verified" if verified is not None else "queued"
            completed_at = timestamp if verified is not None else None
            connection.execute(
                "INSERT INTO notification_address_verifications("
                "id,owner_user_id,address_id,idempotency_sha256,request_sha256,token_sha256,"
                "state,revision,attempts,requested_at,expires_at,completed_at) "
                "VALUES (?,?,?,?,?,?,?,1,0,?,?,?)",
                (
                    challenge_id,
                    owner,
                    address_id,
                    key_digest,
                    request_digest,
                    code_digest,
                    state,
                    self._format_time(timestamp),
                    self._format_time(expires),
                    self._format_time(completed_at) if completed_at is not None else None,
                ),
            )
            if state == "queued":
                connection.execute(
                    "INSERT INTO notification_address_verification_recipients("
                    "verification_id,owner_user_id,address,created_at,expires_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        challenge_id,
                        owner,
                        mailbox,
                        self._format_time(timestamp),
                        self._format_time(expires),
                    ),
                )
            self._event(
                connection,
                challenge_id,
                owner,
                1,
                "already_verified" if verified is not None else "queued",
                timestamp,
            )
            row = connection.execute(
                "SELECT * FROM notification_address_verifications WHERE id=? AND owner_user_id=?",
                (challenge_id, owner),
            ).fetchone()
            if row is None:
                raise NotificationAddressUnavailable("The verification challenge is unavailable.")
            self._maintain_owner(
                connection, owner, timestamp, limit=MAINTENANCE_BATCH_SIZE, exclude=challenge_id
            )
            return self._issue(
                row,
                replayed=False,
                code=code if state == "queued" else None,
            )

    def get_status(
        self, owner_user_id: int, verification_id: str, now: datetime
    ) -> VerificationStatus:
        """Return and safely reconcile the authenticated owner's challenge state."""

        owner = self._owner_id(owner_user_id)
        identifier = self._uuid(verification_id, "verification id")
        timestamp = self._timestamp(now)
        with self._monitoring._write() as connection:
            self._authorized_owner(connection, owner, require_control=False)
            row = self._verification_row(connection, owner, identifier)
            row = self._reconcile_challenge(connection, row, timestamp)
            self._maintain_owner(
                connection, owner, timestamp, limit=MAINTENANCE_BATCH_SIZE, exclude=identifier
            )
            return self._status(row)

    def get_current_status(self, owner_user_id: int, now: datetime) -> VerificationStatus | None:
        """Return the owner's latest challenge so a lost creation response is recoverable."""

        owner = self._owner_id(owner_user_id)
        timestamp = self._timestamp(now)
        with self._monitoring._write() as connection:
            self._authorized_owner(connection, owner, require_control=False)
            row = connection.execute(
                "SELECT v.* FROM notification_address_verifications AS v "
                "JOIN notification_address_verification_events AS e "
                "ON e.verification_id=v.id AND e.owner_user_id=v.owner_user_id "
                "AND e.revision=1 AND e.event_kind IN ('queued','already_verified') "
                "WHERE v.owner_user_id=? ORDER BY e.event_id DESC LIMIT 1",
                (owner,),
            ).fetchone()
            if row is None:
                return None
            row = self._reconcile_challenge(connection, row, timestamp)
            self._maintain_owner(
                connection,
                owner,
                timestamp,
                limit=MAINTENANCE_BATCH_SIZE,
                exclude=row["id"],
            )
            return self._status(row)

    def list_verified_addresses(
        self, owner_user_id: int, now: datetime | None = None
    ) -> list[dict[str, str]]:
        """List safe address metadata and run one bounded recipient-retention batch."""

        owner = self._owner_id(owner_user_id)
        timestamp = self._timestamp(datetime.now(UTC) if now is None else now)
        with self._monitoring._write() as connection:
            self._authorized_owner(connection, owner, require_control=False)
            self._maintain_owner(connection, owner, timestamp, limit=MAINTENANCE_BATCH_SIZE)
            rows = connection.execute(
                "SELECT id,verified_at FROM notification_addresses WHERE owner_user_id=? "
                "AND verified_at IS NOT NULL ORDER BY created_at DESC,id LIMIT 100",
                (owner,),
            ).fetchall()
        return [{"id": row["id"], "verified_at": row["verified_at"]} for row in rows]

    def select_verified_address(
        self,
        owner_user_id: int,
        address_id: str,
        expected_revision: int,
        now: datetime,
    ) -> dict[str, Any]:
        """Select an owned verified address with both email choices reset to off."""

        owner = self._owner_id(owner_user_id)
        identifier = self._uuid(address_id, "address id")
        expected = self._preference_revision(expected_revision)
        timestamp = self._format_time(self._timestamp(now))
        with self._monitoring._write() as connection:
            self._authorized_owner(connection, owner, require_control=True)
            verified = connection.execute(
                "SELECT 1 FROM notification_addresses WHERE id=? AND owner_user_id=? "
                "AND verified_at IS NOT NULL",
                (identifier, owner),
            ).fetchone()
            if verified is None:
                raise NotificationAddressUnavailable("The verified address is unavailable.")
            current_row = connection.execute(
                "SELECT revision FROM notification_preferences WHERE owner_user_id=?", (owner,)
            ).fetchone()
            current = 0 if current_row is None else current_row["revision"]
            if current != expected:
                raise NotificationAddressConflict("Notification preferences changed.")
            revision = current + 1
            if current_row is None:
                connection.execute(
                    "INSERT INTO notification_preferences(owner_user_id,revision,address_id,"
                    "alert_email,digest_email,digest_time,digest_timezone,updated_at) "
                    "VALUES (?,?,?,0,0,'09:00','America/Toronto',?)",
                    (owner, revision, identifier, timestamp),
                )
            else:
                changed = connection.execute(
                    "UPDATE notification_preferences SET revision=?,address_id=?,alert_email=0,"
                    "digest_email=0,updated_at=? WHERE owner_user_id=? AND revision=?",
                    (revision, identifier, timestamp, owner, expected),
                ).rowcount
                if changed != 1:
                    raise NotificationAddressConflict("Notification preferences changed.")
            selected = connection.execute(
                "SELECT owner_user_id,revision,address_id,alert_email,digest_email,digest_time,"
                "digest_timezone,updated_at FROM notification_preferences WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            if selected is None:
                raise NotificationAddressUnavailable("Notification preferences are unavailable.")
            result = dict(selected)
            result["alert_email"] = bool(result["alert_email"])
            result["digest_email"] = bool(result["digest_email"])
            return result

    def maintain_expired_challenges(self, owner_user_id: int, now: datetime) -> int:
        """Reconcile a bounded number of due challenges and redact terminal recipients."""

        owner = self._owner_id(owner_user_id)
        timestamp = self._timestamp(now)
        with self._monitoring._write() as connection:
            self._authorized_owner(connection, owner, require_control=False)
            return self._maintain_owner(connection, owner, timestamp, limit=MAINTENANCE_BATCH_SIZE)

    def mark_submission_started(
        self,
        owner_user_id: int,
        verification_id: str,
        expected_revision: int,
        code: str,
        now: datetime,
    ) -> VerificationStatus:
        """Persist the irreversible SMTP boundary after the prepared session exists."""

        owner = self._owner_id(owner_user_id)
        identifier = self._uuid(verification_id, "verification id")
        revision = self._revision(expected_revision)
        token_digest = self._code_digest(code)
        timestamp = self._timestamp(now)
        with self._monitoring._write() as connection:
            owner = self._authorized_owner(connection, owner, require_control=True)
            row = self._verification_row(connection, owner, identifier)
            recipient = connection.execute(
                "SELECT address FROM notification_address_verification_recipients "
                "WHERE verification_id=? AND owner_user_id=?",
                (identifier, owner),
            ).fetchone()
            if row["revision"] != revision:
                raise NotificationAddressConflict("The verification challenge changed.")
            if (
                row["state"] != "queued"
                or row["invalidated_at"] is not None
                or row["expires_at"] <= self._format_time(timestamp)
                or not secrets.compare_digest(row["token_sha256"], token_digest)
                or recipient is None
                or self._sha256(self._mailbox(recipient["address"]).encode("ascii"))
                != row["request_sha256"]
            ):
                raise NotificationAddressUnavailable("The verification challenge is unavailable.")
            updated = connection.execute(
                "UPDATE notification_address_verifications "
                "SET state='submitting',revision=revision+1,"
                "submission_started_at=? WHERE id=? AND owner_user_id=? AND state='queued' "
                "AND revision=? AND invalidated_at IS NULL",
                (self._format_time(timestamp), identifier, owner, revision),
            ).rowcount
            if updated != 1:
                raise NotificationAddressConflict("The verification challenge changed.")
            self._event(
                connection, identifier, owner, revision + 1, "submission_started", timestamp
            )
            return self._status(self._verification_row(connection, owner, identifier))

    def dispatch_recipient(
        self,
        owner_user_id: int,
        verification_id: str,
        expected_revision: int,
        code: str,
        now: datetime,
    ) -> str:
        """Return the stored recipient only to the explicit sender after a fresh auth check."""

        owner = self._owner_id(owner_user_id)
        identifier = self._uuid(verification_id, "verification id")
        revision = self._revision(expected_revision)
        token_digest = self._code_digest(code)
        timestamp = self._format_time(self._timestamp(now))
        with self.repository.connect() as connection:
            owner = self._authorized_owner(connection, owner, require_control=True)
            row = self._verification_row(connection, owner, identifier)
            recipient = connection.execute(
                "SELECT address FROM notification_address_verification_recipients "
                "WHERE verification_id=? AND owner_user_id=?",
                (identifier, owner),
            ).fetchone()
            if (
                row["revision"] != revision
                or row["state"] != "queued"
                or row["invalidated_at"] is not None
                or row["expires_at"] <= timestamp
                or not secrets.compare_digest(row["token_sha256"], token_digest)
                or recipient is None
                or self._sha256(self._mailbox(recipient["address"]).encode("ascii"))
                != row["request_sha256"]
            ):
                raise NotificationAddressUnavailable("The verification challenge is unavailable.")
            return self._mailbox(recipient["address"])

    def record_pre_submission_failure(
        self,
        owner_user_id: int,
        verification_id: str,
        expected_revision: int,
        failure_code: str,
        now: datetime,
    ) -> VerificationStatus:
        """Close a challenge after a definite failure before the recipient submission call."""

        if failure_code not in {"smtp_prepare_failed", "challenge_expired"}:
            raise NotificationAddressError("The failure category is invalid.")
        owner = self._owner_id(owner_user_id)
        identifier = self._uuid(verification_id, "verification id")
        revision = self._revision(expected_revision)
        timestamp = self._timestamp(now)
        with self._monitoring._write() as connection:
            self._authorized_owner(connection, owner, require_control=False)
            row = self._verification_row(connection, owner, identifier)
            if row["revision"] != revision or row["state"] != "queued":
                raise NotificationAddressConflict("The verification challenge changed.")
            updated = self._transition(
                connection,
                row,
                state="failed",
                now=timestamp,
                failure_code=failure_code,
                event="failed",
            )
            return self._status(updated)

    def finish_submission(
        self,
        owner_user_id: int,
        verification_id: str,
        outcome: str,
        now: datetime,
        *,
        failure_code: str | None = None,
    ) -> VerificationStatus:
        """Persist accepted, rejected, or ambiguous SMTP completion exactly once."""

        if outcome not in {"accepted", "failed", "uncertain"}:
            raise NotificationAddressError("The delivery outcome is invalid.")
        if outcome == "accepted" and failure_code is not None:
            raise NotificationAddressError("Accepted delivery cannot have a failure category.")
        expected_failure = {
            "failed": {"smtp_rejected", "smtp_prepare_failed"},
            "uncertain": {"smtp_outcome_unknown"},
        }
        if outcome != "accepted" and failure_code not in expected_failure[outcome]:
            raise NotificationAddressError("The failure category is invalid.")
        owner = self._owner_id(owner_user_id)
        identifier = self._uuid(verification_id, "verification id")
        timestamp = self._timestamp(now)
        with self._monitoring._write() as connection:
            # Finalization records the already-started irreversible effect even if the account or
            # global switch changed after the checkpoint. It never sends or restores consent.
            row = self._verification_row(connection, owner, identifier)
            if row["state"] != "submitting":
                raise NotificationAddressConflict("The verification submission already finished.")
            if row["invalidated_at"] is not None:
                # Record the real transport result while keeping verification disabled.
                pass
            updated = self._transition(
                connection,
                row,
                state=outcome,
                now=timestamp,
                failure_code=failure_code,
                event=outcome,
            )
            return self._status(updated)

    def verify_code(
        self,
        owner_user_id: int,
        verification_id: str,
        code: str,
        expected_revision: int,
        now: datetime,
    ) -> dict[str, Any]:
        """Verify possession atomically, never selecting the address or enabling email consent."""

        owner = self._owner_id(owner_user_id)
        identifier = self._uuid(verification_id, "verification id")
        revision = self._revision(expected_revision)
        token_digest = self._code_digest(code)
        timestamp = self._timestamp(now)
        with self._monitoring._write() as connection:
            owner = self._authorized_owner(connection, owner, require_control=True)
            row = self._verification_row(connection, owner, identifier)
            row = self._reconcile_challenge(connection, row, timestamp)
            if (
                row["invalidated_at"] is None
                and row["state"] == "expired"
                and row["failure_code"] == "challenge_expired"
            ):
                return {
                    "state": "expired",
                    "revision": row["revision"],
                    "attempts": row["attempts"],
                    "verified": False,
                }
            if row["revision"] != revision:
                raise NotificationAddressConflict("The verification challenge changed.")
            if row["invalidated_at"] is not None:
                raise NotificationAddressUnavailable("The verification challenge is unavailable.")
            if row["expires_at"] <= self._format_time(timestamp):
                expired = self._transition(
                    connection,
                    row,
                    state="expired",
                    now=timestamp,
                    failure_code="challenge_expired",
                    event="expired",
                )
                return {
                    "state": "expired",
                    "revision": expired["revision"],
                    "attempts": expired["attempts"],
                }
            if row["state"] not in {"accepted", "uncertain"}:
                raise NotificationAddressUnavailable("The verification challenge is unavailable.")
            if row["attempts"] >= MAX_CODE_ATTEMPTS:
                exhausted = self._transition(
                    connection,
                    row,
                    state="expired",
                    now=timestamp,
                    failure_code="attempts_exhausted",
                    event="expired",
                )
                return {
                    "state": "expired",
                    "revision": exhausted["revision"],
                    "attempts": exhausted["attempts"],
                }
            if not secrets.compare_digest(row["token_sha256"], token_digest):
                attempts = row["attempts"] + 1
                state = "expired" if attempts >= MAX_CODE_ATTEMPTS else row["state"]
                updated = self._transition(
                    connection,
                    row,
                    state=state,
                    now=timestamp,
                    attempts=attempts,
                    failure_code="attempts_exhausted" if state == "expired" else None,
                    event="expired" if state == "expired" else "attempt_failed",
                )
                return {
                    "state": updated["state"],
                    "revision": updated["revision"],
                    "attempts": updated["attempts"],
                    "verified": False,
                }

            verified_at = self._format_time(timestamp)
            recipient = connection.execute(
                "SELECT address FROM notification_address_verification_recipients "
                "WHERE verification_id=? AND owner_user_id=?",
                (identifier, owner),
            ).fetchone()
            if recipient is None:
                raise NotificationAddressUnavailable("The verification challenge is unavailable.")
            address = self._mailbox(recipient["address"])
            if self._sha256(address.encode("ascii")) != row["request_sha256"]:
                raise NotificationAddressUnavailable("The verification challenge is unavailable.")
            address_id = row["address_id"]
            inserted = connection.execute(
                "INSERT INTO notification_addresses(id,owner_user_id,address,challenge_hash,"
                "challenge_expires_at,challenge_attempts,verified_at,created_at) "
                "VALUES (?,?,?,NULL,NULL,0,?,?)",
                (address_id, owner, address, verified_at, verified_at),
            ).rowcount
            if inserted != 1:
                raise NotificationAddressConflict("The verified address changed.")
            preference = connection.execute(
                "SELECT owner_user_id FROM notification_preferences WHERE owner_user_id=?", (owner,)
            ).fetchone()
            if preference is None:
                connection.execute(
                    "INSERT INTO notification_preferences(owner_user_id,revision,address_id,"
                    "alert_email,digest_email,digest_time,digest_timezone,updated_at) "
                    "VALUES (?,1,NULL,0,0,'09:00','America/Toronto',?)",
                    (owner, verified_at),
                )
            updated = self._transition(
                connection,
                row,
                state="verified",
                now=timestamp,
                event="verified",
            )
            return {
                "state": updated["state"],
                "revision": updated["revision"],
                "attempts": updated["attempts"],
                "verified": True,
                "address_id": address_id,
            }

    def _authorized_owner(
        self, connection: sqlite3.Connection, owner: int, *, require_control: bool
    ) -> int:
        try:
            selected = self._monitoring._active_owner(connection, owner)
        except MonitoringStoreError as error:
            raise NotificationAddressUnavailable(
                "The notification address is unavailable."
            ) from error
        if require_control:
            control = connection.execute(
                "SELECT enabled FROM monitoring_control WHERE id=1"
            ).fetchone()
            if control is None or control["enabled"] != 1:
                raise NotificationAddressUnavailable("Notification verification is unavailable.")
        return selected

    def _invalidate(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> sqlite3.Row:
        revision = row["revision"] + 1
        changed = connection.execute(
            "UPDATE notification_address_verifications SET invalidated_at=?,revision=? "
            "WHERE id=? AND owner_user_id=? AND revision=? AND invalidated_at IS NULL",
            (self._format_time(now), revision, row["id"], row["owner_user_id"], row["revision"]),
        ).rowcount
        if changed != 1:
            raise NotificationAddressConflict("The verification challenge changed.")
        self._event(connection, row["id"], row["owner_user_id"], revision, "invalidated", now)
        connection.execute(
            "DELETE FROM notification_address_verification_recipients "
            "WHERE verification_id=? AND owner_user_id=?",
            (row["id"], row["owner_user_id"]),
        )
        return self._verification_row(connection, row["owner_user_id"], row["id"])

    def _reconcile_challenge(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> sqlite3.Row:
        if row["invalidated_at"] is not None:
            connection.execute(
                "DELETE FROM notification_address_verification_recipients "
                "WHERE verification_id=? AND owner_user_id=?",
                (row["id"], row["owner_user_id"]),
            )
            return row
        row = self._recover_stale_submission(connection, row, now)
        timestamp = self._format_time(now)
        if row["state"] == "queued":
            if row["expires_at"] <= timestamp:
                return self._transition(
                    connection,
                    row,
                    state="expired",
                    now=now,
                    failure_code="challenge_expired",
                    event="expired",
                )
            if self._parse_time(row["requested_at"]) + SUBMISSION_RECOVERY_AGE <= now:
                return self._transition(
                    connection,
                    row,
                    state="failed",
                    now=now,
                    failure_code="smtp_prepare_failed",
                    event="failed",
                )
        if row["state"] in {"accepted", "uncertain"} and row["expires_at"] <= timestamp:
            return self._transition(
                connection,
                row,
                state="expired",
                now=now,
                failure_code="challenge_expired",
                event="expired",
            )
        return row

    def _maintain_owner(
        self,
        connection: sqlite3.Connection,
        owner: int,
        now: datetime,
        *,
        limit: int,
        exclude: str | None = None,
    ) -> int:
        selected_limit = self._maintenance_limit(limit)
        timestamp = self._format_time(now)
        cutoff = self._format_time(now - SUBMISSION_RECOVERY_AGE)
        rows = connection.execute(
            "SELECT * FROM notification_address_verifications WHERE owner_user_id=? "
            "AND (? IS NULL OR id != ?) AND ("
            "(state='queued' AND (requested_at<=? OR expires_at<=?)) OR "
            "(state='submitting' AND (submission_started_at<=? OR expires_at<=?)) OR "
            "(state IN ('accepted','uncertain') AND expires_at<=?)) "
            "ORDER BY requested_at,id LIMIT ?",
            (
                owner,
                exclude,
                exclude,
                cutoff,
                timestamp,
                cutoff,
                timestamp,
                timestamp,
                selected_limit,
            ),
        ).fetchall()
        for row in rows:
            self._reconcile_challenge(connection, row, now)
        return len(rows)

    def _recover_stale_submission(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> sqlite3.Row:
        if row["state"] != "submitting" or row["submission_started_at"] is None:
            return row
        started = self._parse_time(row["submission_started_at"])
        if started + SUBMISSION_RECOVERY_AGE > now:
            return row
        return self._transition(
            connection,
            row,
            state="uncertain",
            now=now,
            failure_code="smtp_outcome_unknown",
            event="uncertain",
        )

    def _transition(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        state: str,
        now: datetime,
        failure_code: str | None = None,
        event: str,
        attempts: int | None = None,
    ) -> sqlite3.Row:
        if failure_code is not None and failure_code not in _FAILURE_CODES:
            raise NotificationAddressError("The failure category is invalid.")
        if attempts is None:
            attempts = row["attempts"]
        revision = row["revision"] + 1
        accepted_at = row["accepted_at"]
        submission_started_at = row["submission_started_at"]
        completed_at = row["completed_at"]
        if state == "accepted":
            accepted_at = self._format_time(now)
        if state in {"failed", "uncertain", "verified", "expired"}:
            completed_at = self._format_time(now)
        if state == "submitting":
            submission_started_at = self._format_time(now)
        changed = connection.execute(
            "UPDATE notification_address_verifications SET state=?,revision=?,attempts=?,"
            "submission_started_at=?,accepted_at=?,completed_at=?,failure_code=? "
            "WHERE id=? AND owner_user_id=? AND revision=?",
            (
                state,
                revision,
                attempts,
                submission_started_at,
                accepted_at,
                completed_at,
                failure_code if failure_code is not None else row["failure_code"],
                row["id"],
                row["owner_user_id"],
                row["revision"],
            ),
        ).rowcount
        if changed != 1:
            raise NotificationAddressConflict("The verification challenge changed.")
        self._event(connection, row["id"], row["owner_user_id"], revision, event, now, failure_code)
        updated = self._verification_row(connection, row["owner_user_id"], row["id"])
        if state in {"failed", "verified", "expired"}:
            connection.execute(
                "DELETE FROM notification_address_verification_recipients "
                "WHERE verification_id=? AND owner_user_id=?",
                (row["id"], row["owner_user_id"]),
            )
        return updated

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        verification_id: str,
        owner: int,
        revision: int,
        kind: str,
        now: datetime,
        failure_code: str | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO notification_address_verification_events("
            "verification_id,owner_user_id,revision,event_kind,occurred_at,failure_code) "
            "VALUES (?,?,?,?,?,?)",
            (
                verification_id,
                owner,
                revision,
                kind,
                NotificationAddressStore._format_time(now),
                failure_code,
            ),
        )

    @staticmethod
    def _verification_row(
        connection: sqlite3.Connection, owner: int, verification_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM notification_address_verifications WHERE id=? AND owner_user_id=?",
            (verification_id, owner),
        ).fetchone()
        if row is None:
            raise NotificationAddressUnavailable("The verification challenge is unavailable.")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _status(row: sqlite3.Row) -> VerificationStatus:
        return VerificationStatus(
            verification_id=row["id"],
            address_id=row["address_id"],
            state="superseded" if row["invalidated_at"] is not None else row["state"],
            revision=row["revision"],
            attempts=row["attempts"],
            expires_at=row["expires_at"],
            invalidated=row["invalidated_at"] is not None,
        )

    @staticmethod
    def _issue(
        row: sqlite3.Row,
        *,
        replayed: bool,
        code: str | None = None,
    ) -> VerificationIssue:
        return VerificationIssue(
            verification_id=row["id"],
            address_id=row["address_id"],
            state="superseded" if row["invalidated_at"] is not None else row["state"],
            revision=row["revision"],
            expires_at=row["expires_at"],
            replayed=replayed,
            _code=code,
        )

    @staticmethod
    def _owner_id(value: object) -> int:
        if type(value) is not int or value < 1:
            raise NotificationAddressUnavailable("The notification address is unavailable.")
        return value

    @staticmethod
    def _preference_revision(value: object) -> int:
        if type(value) is not int or not 0 <= value <= 2**63 - 1:
            raise NotificationAddressError("The preference revision is invalid.")
        return value

    @staticmethod
    def _maintenance_limit(value: object) -> int:
        if type(value) is not int or not 1 <= value <= MAINTENANCE_BATCH_SIZE:
            raise NotificationAddressError("The maintenance limit is invalid.")
        return value

    @staticmethod
    def _revision(value: object) -> int:
        if type(value) is not int or not 1 <= value <= 2**63 - 1:
            raise NotificationAddressError("The verification revision is invalid.")
        return value

    @staticmethod
    def _uuid(value: object, field_name: str) -> str:
        if not isinstance(value, str) or len(value) != 36:
            raise NotificationAddressError(f"The {field_name} is invalid.")
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise NotificationAddressError(f"The {field_name} is invalid.") from error
        canonical = str(parsed)
        if value != canonical:
            raise NotificationAddressError(f"The {field_name} is invalid.")
        return canonical

    @staticmethod
    def _mailbox(value: object) -> str:
        if type(value) is not str:
            raise NotificationAddressError("The notification address is invalid.")
        try:
            return validate_email_address(value)
        except (TypeError, ValueError) as error:
            raise NotificationAddressError("The notification address is invalid.") from error

    @staticmethod
    def _code_digest(value: object) -> str:
        if not isinstance(value, str) or len(value) != 43 or not value.isascii():
            raise NotificationAddressError("The verification code is invalid.")
        if any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
            for character in value
        ):
            raise NotificationAddressError("The verification code is invalid.")
        return NotificationAddressStore._sha256(value.encode("ascii"))

    @staticmethod
    def _sha256(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise NotificationAddressError("Use a timezone-aware timestamp.")
        selected = value.astimezone(UTC)
        if selected.microsecond:
            return selected
        return selected

    @staticmethod
    def _format_time(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise NotificationAddressUnavailable("The verification timestamp is invalid.")
        return parsed.astimezone(UTC)
