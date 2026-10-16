"""Explicit, at-most-once SMTP submission for notification-address challenges.

Construction is inert. Callers must inject already validated SMTP settings and an exact
configured origin; this module never reads the environment, starts background work, or sends
without an explicit ``submit`` call.
"""

from __future__ import annotations

import html
import smtplib
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from urllib.parse import urlsplit

from stock_probs.invitation_mail import (
    SMTP_TIMEOUT_SECONDS,
    InvitationMailSettings,
    validate_email_address,
    validate_smtp_host,
)
from stock_probs.monitoring_store import MonitoringConflictError, MonitoringStoreError
from stock_probs.notification_address_store import (
    NotificationAddressError,
    NotificationAddressStore,
    VerificationIssue,
)
from stock_probs.notification_delivery import (
    NotificationSMTPTransport,
    SMTPNotificationTransport,
)


@dataclass(frozen=True)
class SubmissionSummary:
    """Non-sensitive result of one explicit recipient submission."""

    state: str
    revision: int
    available: bool = True


class NotificationVerificationService:
    """Send one explicitly requested, hash-backed verification code at most once."""

    def __init__(
        self,
        store: NotificationAddressStore,
        *,
        settings: InvitationMailSettings | None,
        public_origin: str | None,
        transport: NotificationSMTPTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(store, NotificationAddressStore):
            raise TypeError("store must be a NotificationAddressStore")
        if settings is not None and not isinstance(settings, InvitationMailSettings):
            raise TypeError("settings must be validated InvitationMailSettings")
        self._store = store
        self._settings = settings
        self._public_origin = _configured_origin(public_origin)
        self._transport = SMTPNotificationTransport() if transport is None else transport
        self._clock: Callable[[], datetime] = (
            (lambda: datetime.now(UTC)) if clock is None else clock
        )
        if not callable(self._clock):
            raise TypeError("clock must be callable")

    @property
    def available(self) -> bool:
        """Return whether validated settings and an exact origin were injected."""

        return self._settings is not None and self._public_origin is not None

    def submit(self, owner_user_id: int, issue: VerificationIssue) -> SubmissionSummary:
        """Submit a newly issued challenge; replayed or non-queued issues never send."""

        if not self.available:
            return SubmissionSummary(state="unavailable", revision=issue.revision, available=False)
        if issue.replayed or issue.state != "queued" or issue._code is None:
            return SubmissionSummary(state=issue.state, revision=issue.revision)
        settings = self._settings
        origin = self._public_origin
        if settings is None or origin is None:
            return SubmissionSummary(state="unavailable", revision=issue.revision, available=False)
        try:
            recipient = self._store.dispatch_recipient(
                owner_user_id,
                issue.verification_id,
                issue.revision,
                issue._code,
                self._now(),
            )
        except (
            MonitoringConflictError,
            MonitoringStoreError,
            NotificationAddressError,
            sqlite3.Error,
            ValueError,
        ):
            return SubmissionSummary(state="blocked", revision=issue.revision)
        try:
            message = _verification_message(settings, origin, issue, recipient, self._now())
        except (TypeError, ValueError):
            try:
                failed = self._store.record_pre_submission_failure(
                    owner_user_id,
                    issue.verification_id,
                    issue.revision,
                    "smtp_prepare_failed",
                    self._now(),
                )
                return SubmissionSummary(state=failed.state, revision=failed.revision)
            except (MonitoringConflictError, MonitoringStoreError, NotificationAddressError):
                return SubmissionSummary(state="blocked", revision=issue.revision)

        try:
            session = self._transport.prepare(
                settings,
                timeout_seconds=SMTP_TIMEOUT_SECONDS,
            )
        except Exception:
            return self._record_prepare_failure(owner_user_id, issue)

        send_method = getattr(session, "send_message", None)
        close_method = getattr(session, "close", None)
        if not callable(send_method) or not callable(close_method):
            _close_session(session, close_method)
            return self._record_prepare_failure(owner_user_id, issue)

        try:
            checkpoint = self._store.mark_submission_started(
                owner_user_id,
                issue.verification_id,
                issue.revision,
                issue._code,
                self._now(),
            )
        except (
            MonitoringConflictError,
            MonitoringStoreError,
            NotificationAddressError,
            sqlite3.Error,
            ValueError,
        ):
            _close_session(session, close_method)
            return SubmissionSummary(state="blocked", revision=issue.revision)
        if checkpoint.state != "submitting":
            _close_session(session, close_method)
            return SubmissionSummary(state=checkpoint.state, revision=checkpoint.revision)

        try:
            refused = send_method(message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
            result = self._finish(owner_user_id, issue.verification_id, "failed", "smtp_rejected")
        except Exception:
            result = self._finish(
                owner_user_id, issue.verification_id, "uncertain", "smtp_outcome_unknown"
            )
        else:
            if not isinstance(refused, Mapping):
                result = self._finish(
                    owner_user_id, issue.verification_id, "uncertain", "smtp_outcome_unknown"
                )
            elif refused:
                result = self._finish(
                    owner_user_id, issue.verification_id, "failed", "smtp_rejected"
                )
            else:
                result = self._finish(owner_user_id, issue.verification_id, "accepted", None)
        finally:
            _close_session(session, close_method)
        return result

    def _record_prepare_failure(self, owner: int, issue: VerificationIssue) -> SubmissionSummary:
        try:
            failed = self._store.record_pre_submission_failure(
                owner,
                issue.verification_id,
                issue.revision,
                "smtp_prepare_failed",
                self._now(),
            )
        except (
            MonitoringConflictError,
            MonitoringStoreError,
            NotificationAddressError,
            sqlite3.Error,
            ValueError,
        ):
            return SubmissionSummary(state="blocked", revision=issue.revision)
        return SubmissionSummary(state=failed.state, revision=failed.revision)

    def _finish(
        self, owner: int, verification_id: str, outcome: str, failure_code: str | None
    ) -> SubmissionSummary:
        try:
            final = self._store.finish_submission(
                owner,
                verification_id,
                outcome,
                self._now(),
                failure_code=failure_code,
            )
        except (
            MonitoringConflictError,
            MonitoringStoreError,
            NotificationAddressError,
            sqlite3.Error,
            ValueError,
        ):
            # The persisted submission checkpoint is recovered to uncertain after restart.
            return SubmissionSummary(state="uncertain", revision=0)
        return SubmissionSummary(state=final.state, revision=final.revision)

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("The verification clock must return an aware timestamp.")
        return now.astimezone(UTC)


def _configured_origin(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or value != value.strip()
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise ValueError("A configured notification origin is invalid.")
    origin = value.rstrip("/")
    parsed = urlsplit(origin)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("A configured notification origin is invalid.") from error
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
        raise ValueError("A configured notification origin must be an exact HTTP(S) origin.")
    try:
        validate_smtp_host(parsed.hostname)
    except ValueError as error:
        raise ValueError("A configured notification origin is invalid.") from error
    return origin


def _verification_message(
    settings: InvitationMailSettings,
    origin: str,
    issue: VerificationIssue,
    recipient_address: str,
    now: datetime,
) -> EmailMessage:
    if issue._code is None:
        raise ValueError("The verification challenge is unavailable.")
    try:
        recipient = validate_email_address(recipient_address)
    except ValueError as error:
        raise ValueError("The verification recipient is invalid.") from error
    if len(issue._code) != 43 or not issue._code.isascii():
        raise ValueError("The verification code is invalid.")
    preferences_url = f"{origin}/notifications"
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = formataddr(("Signal Ledger", settings.from_address))
    message["Subject"] = "Verify your notification address"
    message["Date"] = format_datetime(now)
    message["Message-ID"] = (
        f"<notification-address-{issue.verification_id.replace('-', '')}@stock-probs.invalid>"
    )
    message.set_content(
        "You requested email notifications in Signal Ledger.\n\n"
        f"Enter this one-time verification code in your signed-in workspace: {issue._code}\n\n"
        "The code expires in 20 minutes and can be used once. Verifying an address does not "
        "enable alert or digest email. You can manage notification preferences in your "
        f"signed-in workspace: {preferences_url}\n"
    )
    escaped_code = html.escape(issue._code)
    escaped_url = html.escape(preferences_url, quote=True)
    message.add_alternative(
        "<html><body><p>You requested email notifications in Signal Ledger.</p>"
        "<p>Enter this one-time verification code in your signed-in workspace:</p>"
        f"<p><strong>{escaped_code}</strong></p>"
        "<p>The code expires in 20 minutes and can be used once. Verifying an address does not "
        "enable alert or digest email.</p>"
        f'<p>Manage preferences in your signed-in workspace: <a href="{escaped_url}">'
        "Notification preferences</a>.</p></body></html>",
        subtype="html",
    )
    return message


def _close_session(session: object, close_method: object | None = None) -> None:
    selected_close = getattr(session, "close", None) if close_method is None else close_method
    if callable(selected_close):
        with suppress(Exception):
            selected_close()
