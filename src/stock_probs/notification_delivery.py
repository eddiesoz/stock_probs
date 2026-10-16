"""Explicit bounded consumer for persisted, at-most-once notification email deliveries.

The consumer is inert until ``run_due`` is called. It owns no scheduler and reads neither
environment variables nor application secrets; validated mail settings and the configured
public origin must be injected by its caller.
"""

from __future__ import annotations

import re
import smtplib
import ssl
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from typing import Protocol
from urllib.parse import urlsplit

from stock_probs.invitation_mail import (
    SMTP_TIMEOUT_SECONDS,
    InvitationMailSettings,
    validate_email_address,
    validate_smtp_host,
)
from stock_probs.monitoring_domain import MonitoringError, price
from stock_probs.monitoring_store import (
    MAX_JOB_BATCH,
    MonitoringConflictError,
    MonitoringStore,
    MonitoringStoreError,
)

MAX_NOTIFICATION_BATCH = 4
_SAFE_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._^$:/=-]{0,79}$")
_SAFE_CURRENCY = re.compile(r"^[A-Za-z]{3}$")
_NO_CLOSE_METHOD = object()


class PreparedSMTPSubmission(Protocol):
    """An authenticated SMTP session ready to submit one message."""

    def send_message(self, message: EmailMessage) -> Mapping[str, object]:
        """Submit a single-recipient message and return refused recipients, if any."""

    def close(self) -> None:
        """Close the prepared SMTP session without surfacing transport details."""


class NotificationSMTPTransport(Protocol):
    """Prepare an authenticated session without sending a recipient message."""

    def prepare(
        self,
        settings: InvitationMailSettings,
        *,
        timeout_seconds: float,
    ) -> PreparedSMTPSubmission:
        """Open, negotiate TLS, and authenticate before the persisted send boundary."""


class _SMTPSession:
    """Thin wrapper keeping SMTP submission and close phases separate."""

    def __init__(self, connection: smtplib.SMTP):
        self._connection = connection

    def send_message(self, message: EmailMessage) -> Mapping[str, object]:
        return self._connection.send_message(message)

    def close(self) -> None:
        try:
            self._connection.quit()
        except Exception:
            self._connection.close()


class SMTPNotificationTransport:
    """Production SMTP transport compatible with the invitation mail settings."""

    def prepare(
        self,
        settings: InvitationMailSettings,
        *,
        timeout_seconds: float,
    ) -> PreparedSMTPSubmission:
        if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 30:
            raise ValueError("The SMTP timeout is outside its bound.")
        context = ssl.create_default_context()
        connection: smtplib.SMTP | None = None
        try:
            if settings.security == "implicit_tls":
                connection = smtplib.SMTP_SSL(
                    settings.host,
                    settings.port,
                    timeout=timeout_seconds,
                    context=context,
                )
                connection.ehlo()
            elif settings.security == "starttls":
                connection = smtplib.SMTP(
                    settings.host,
                    settings.port,
                    timeout=timeout_seconds,
                )
                connection.ehlo()
                connection.starttls(context=context)
                connection.ehlo()
            else:
                raise ValueError("The SMTP security mode is unsupported.")
            connection.login(settings.username, settings.password)
            return _SMTPSession(connection)
        except Exception:
            if connection is not None:
                with suppress(Exception):
                    connection.close()
            raise


@dataclass(frozen=True)
class DeliveryRunSummary:
    """Aggregate delivery result without owner, recipient, payload, or SMTP detail."""

    available: bool
    claimed: int = 0
    accepted: int = 0
    failed: int = 0
    uncertain: int = 0
    retry_scheduled: int = 0
    blocked: int = 0
    cancelled: bool = False


@dataclass(frozen=True)
class _DeliveryOutcome:
    """Represent one message result and whether cooperative cancellation stopped its batch."""

    state: str
    cancelled: bool = False


class NotificationDeliveryConsumer:
    """Process a bounded explicit batch through typed persisted outbox transitions only."""

    def __init__(
        self,
        store: MonitoringStore,
        *,
        settings: InvitationMailSettings | None,
        public_origin: str | None,
        transport: NotificationSMTPTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(store, MonitoringStore):
            raise TypeError("store must be a MonitoringStore")
        if settings is not None and not isinstance(settings, InvitationMailSettings):
            raise TypeError("settings must be validated InvitationMailSettings")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._store = store
        self._settings = settings
        self._public_origin = _configured_origin(public_origin)
        self._transport = transport if transport is not None else SMTPNotificationTransport()
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    def run_due(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int = MAX_NOTIFICATION_BATCH,
        lease_seconds: int = 30,
        cancelled: Callable[[], bool] | None = None,
    ) -> DeliveryRunSummary:
        """Process at most four deliveries with cooperative stop checks.

        Cancellation is observed at explicit checkpoints. A send already past its final check
        may complete; cancellation does not interrupt an in-flight SMTP call.
        """

        if type(limit) is not int or not 1 <= limit <= MAX_NOTIFICATION_BATCH:
            raise ValueError("The notification delivery batch is outside its bound.")
        if self._settings is None or self._public_origin is None:
            return DeliveryRunSummary(available=False)
        if _cancellation_requested(cancelled):
            return DeliveryRunSummary(available=True, cancelled=True)
        claims = self._store.claim_due_notification_outbox(
            worker_id,
            now,
            limit=min(limit, MAX_JOB_BATCH),
            lease_seconds=lease_seconds,
        )
        totals = {
            "accepted": 0,
            "failed": 0,
            "uncertain": 0,
            "retry_scheduled": 0,
            "blocked": 0,
        }
        cancellation_requested = False
        for claim in claims:
            if _cancellation_requested(cancelled):
                cancellation_requested = True
                break
            outcome = self._deliver_claim(claim, cancelled)
            if outcome.state != "cancelled":
                totals[outcome.state] += 1
            if outcome.cancelled:
                cancellation_requested = True
                break
        return DeliveryRunSummary(
            available=True,
            claimed=len(claims),
            cancelled=cancellation_requested,
            **totals,
        )

    def _deliver_claim(
        self,
        claim: Mapping[str, object],
        cancelled: Callable[[], bool] | None,
    ) -> _DeliveryOutcome:
        owner = claim.get("owner_user_id")
        settings = self._settings
        public_origin = self._public_origin
        if type(owner) is not int or settings is None or public_origin is None:
            return _DeliveryOutcome("blocked")
        try:
            message = _notification_message(
                settings,
                public_origin,
                claim,
            )
        except (TypeError, ValueError, MonitoringError, MonitoringStoreError):
            try:
                result = self._store.record_notification_outbox_pre_submission_failure(
                    owner,
                    claim,
                    "message_invalid",
                    self._clock(),
                    retryable=False,
                )
            except (MonitoringConflictError, MonitoringStoreError):
                return _DeliveryOutcome("blocked")
            return _DeliveryOutcome("failed" if result["state"] == "failed" else "blocked")

        if _cancellation_requested(cancelled):
            return _DeliveryOutcome("cancelled", cancelled=True)
        try:
            session = self._transport.prepare(
                settings,
                timeout_seconds=SMTP_TIMEOUT_SECONDS,
            )
        except (OSError, smtplib.SMTPException, TimeoutError):
            return _DeliveryOutcome(
                self._record_safe_pre_submission_failure(
                    owner, claim, self._clock(), retryable=True
                )
            )
        except Exception:
            return _DeliveryOutcome(
                self._record_safe_pre_submission_failure(
                    owner, claim, self._clock(), retryable=False
                )
            )

        if _cancellation_requested(cancelled):
            _close_session(session)
            return _DeliveryOutcome("cancelled", cancelled=True)
        send_method = getattr(session, "send_message", None)
        close_method = getattr(session, "close", None)
        if not callable(send_method) or not callable(close_method):
            _close_session(session, close_method)
            return _DeliveryOutcome(
                self._record_safe_pre_submission_failure(
                    owner, claim, self._clock(), retryable=False
                )
            )

        if _cancellation_requested(cancelled):
            _close_session(session, close_method)
            return _DeliveryOutcome("cancelled", cancelled=True)

        try:
            checkpoint = self._store.mark_notification_outbox_submission_started(
                owner,
                claim,
                self._clock(),
            )
        except (MonitoringConflictError, MonitoringStoreError):
            _close_session(session, close_method)
            return _DeliveryOutcome("blocked")
        if checkpoint.get("outbox_state") != "submitting":
            _close_session(session, close_method)
            return _DeliveryOutcome("failed" if checkpoint.get("state") == "failed" else "blocked")

        if _cancellation_requested(cancelled):
            _close_session(session, close_method)
            outcome = self._finalize(
                owner,
                checkpoint,
                "failed",
                self._clock(),
                "delivery_cancelled_before_send",
            )
            return _DeliveryOutcome(outcome, cancelled=True)

        try:
            refused = send_method(message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
            return _DeliveryOutcome(
                self._finalize(owner, checkpoint, "failed", self._clock(), "smtp_rejected")
            )
        except Exception:
            return _DeliveryOutcome(
                self._finalize(
                    owner, checkpoint, "uncertain", self._clock(), "smtp_outcome_unknown"
                )
            )
        finally:
            _close_session(session, close_method)

        if not isinstance(refused, Mapping):
            return _DeliveryOutcome(
                self._finalize(
                    owner, checkpoint, "uncertain", self._clock(), "smtp_outcome_unknown"
                )
            )
        if refused:
            return _DeliveryOutcome(
                self._finalize(owner, checkpoint, "failed", self._clock(), "smtp_rejected")
            )
        return _DeliveryOutcome(self._finalize(owner, checkpoint, "accepted", self._clock(), None))

    def _record_safe_pre_submission_failure(
        self,
        owner: int,
        claim: Mapping[str, object],
        now: datetime,
        *,
        retryable: bool,
    ) -> str:
        try:
            result = self._store.record_notification_outbox_pre_submission_failure(
                owner,
                claim,
                "smtp_prepare_failed",
                now,
                retryable=retryable,
            )
        except (MonitoringConflictError, MonitoringStoreError):
            return "blocked"
        return "retry_scheduled" if result["state"] == "queued" else "failed"

    def _finalize(
        self,
        owner: int,
        claim: Mapping[str, object],
        outcome: str,
        now: datetime,
        failure_code: str | None,
    ) -> str:
        try:
            result = self._store.finalize_notification_outbox(
                owner,
                claim,
                outcome,
                now,
                failure_code=failure_code,
            )
        except (MonitoringConflictError, MonitoringStoreError):
            # The persisted submitting state is recovered to uncertain after lease expiry.
            return "uncertain"
        return "accepted" if result["state"] == "accepted" else result["state"]


def _configured_origin(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value
        or value != value.strip()
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise ValueError("A configured public origin is required.")
    origin = value.rstrip("/")
    parsed = urlsplit(origin)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("The configured public origin has an invalid port.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise ValueError("The configured public origin must be an exact HTTP(S) origin.")
    try:
        validate_smtp_host(parsed.hostname)
    except ValueError as error:
        raise ValueError("The configured public origin host is invalid.") from error
    return origin


def _notification_message(
    settings: InvitationMailSettings | None,
    public_origin: str | None,
    claim: Mapping[str, object],
) -> EmailMessage:
    if settings is None or public_origin is None:
        raise ValueError("Notification delivery is not configured.")
    recipient = claim.get("recipient")
    if not isinstance(recipient, str):
        raise ValueError("The notification recipient is invalid.")
    try:
        destination = validate_email_address(recipient)
    except ValueError as error:
        raise ValueError("The notification recipient is invalid.") from error
    payload = claim.get("outbox_payload")
    if not isinstance(payload, Mapping) or payload.get("notification_kind") != "price_alert":
        raise ValueError("The notification payload is invalid.")
    notification = payload.get("notification")
    if not isinstance(notification, Mapping):
        raise ValueError("The notification payload is invalid.")
    symbol = _safe_field(notification.get("symbol"), 80)
    if not _SAFE_SYMBOL.fullmatch(symbol):
        raise ValueError("The notification symbol is invalid.")
    currency = _safe_field(notification.get("currency"), 3).upper()
    if not _SAFE_CURRENCY.fullmatch(currency):
        raise ValueError("The notification currency is invalid.")
    direction = notification.get("direction")
    if direction not in {"above", "below"}:
        raise ValueError("The notification direction is invalid.")
    try:
        threshold = str(price(_safe_field(notification.get("threshold"), 64)))
        observed_price = str(price(_safe_field(notification.get("price"), 64)))
        observed_at = _safe_timestamp(notification.get("observed_at"))
    except (MonitoringError, TypeError, ValueError) as error:
        raise ValueError("The notification price evidence is invalid.") from error
    outbox_id = claim.get("outbox_id")
    delivery_version = claim.get("delivery_version")
    if (
        not isinstance(outbox_id, str)
        or not re.fullmatch(r"[0-9a-f-]{36}", outbox_id)
        or type(delivery_version) is not int
        or delivery_version < 1
    ):
        raise ValueError("The notification delivery identity is invalid.")
    requested_at = _safe_timestamp(claim.get("requested_at"))
    manage_url = f"{public_origin}/notifications"
    message = EmailMessage()
    message["Subject"] = "A price alert was triggered"
    message["From"] = formataddr(("Signal Ledger", settings.from_address))
    message["To"] = destination
    message["Date"] = format_datetime(requested_at)
    message["Message-ID"] = f"<{outbox_id}.{delivery_version}@notifications.signal-ledger.invalid>"
    message.set_content(
        f"Your {symbol} price alert was triggered.\n\n"
        f"Rule: price {direction} {threshold} {currency}.\n"
        f"Observed price: {observed_price} {currency}.\n"
        f"Provider observation time: {observed_at.isoformat(timespec='seconds')}.\n\n"
        "To manage or turn off email notifications, sign in at:\n"
        f"{manage_url}\n"
    )
    return message


def _safe_field(value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isprintable()
        or not 1 <= len(value) <= maximum
    ):
        raise ValueError("The saved notification field is invalid.")
    return value


def _safe_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise ValueError("The notification timestamp is invalid.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("The notification timestamp is invalid.") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("The notification timestamp is invalid.")
    return result.astimezone(UTC)


def _close_session(
    session: object,
    close: object = _NO_CLOSE_METHOD,
) -> None:
    if close is _NO_CLOSE_METHOD:
        try:
            close = getattr(session, "close", None)
        except Exception:
            return
    if not callable(close):
        return
    with suppress(Exception):
        close()


def _cancellation_requested(callback: Callable[[], bool] | None) -> bool:
    if callback is None:
        return False
    try:
        result = callback()
    except Exception:
        return True
    return type(result) is not bool or result
