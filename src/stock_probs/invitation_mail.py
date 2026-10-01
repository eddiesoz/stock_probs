"""Submit GitHub account invitations through a narrowly configured SMTP server."""

from __future__ import annotations

import html
import ipaddress
import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from uuid import uuid4

from stock_probs.auth import AuthError

SMTP_TIMEOUT_SECONDS = 10.0
_SUPPORTED_SMTP_SECURITY_PORTS = {
    ("implicit_tls", 465),
    ("implicit_tls", 2465),
    ("starttls", 587),
}
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_LOCAL_PART = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$")


def validate_email_address(value: str) -> str:
    """Validate the bounded ASCII mailbox form accepted by the invitation mailer."""

    if not isinstance(value, str) or not value.isascii() or len(value) > 320:
        raise ValueError("email address must be a valid ASCII mailbox")
    if any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise ValueError("email address must be a valid ASCII mailbox")
    if value.count("@") != 1:
        raise ValueError("email address must be a valid ASCII mailbox")
    local_part, domain = value.rsplit("@", 1)
    if (
        not local_part
        or len(local_part) > 64
        or not _LOCAL_PART.fullmatch(local_part)
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or not domain
        or len(domain) > 253
        or "." not in domain
    ):
        raise ValueError("email address must be a valid ASCII mailbox")
    labels = domain.split(".")
    if any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise ValueError("email address must be a valid ASCII mailbox")
    return value


@dataclass(frozen=True)
class InvitationMailSettings:
    """Validated SMTP settings; credential values are hidden from representations."""

    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)
    security: str
    from_address: str

    def __post_init__(self) -> None:
        """Reject unsafe direct construction as well as malformed environment values."""

        validate_smtp_host(self.host)
        if type(self.port) is not int:
            raise ValueError("STOCK_PROBS_INVITE_SMTP_PORT must be 465, 2465, or 587")
        if (self.security, self.port) not in _SUPPORTED_SMTP_SECURITY_PORTS:
            raise ValueError(
                "SMTP security must be implicit_tls on 465 or 2465, or starttls on 587"
            )
        for name, value, limit in (
            ("STOCK_PROBS_INVITE_SMTP_USERNAME", self.username, 320),
            ("STOCK_PROBS_INVITE_SMTP_PASSWORD", self.password, 2048),
        ):
            if (
                not isinstance(value, str)
                or not value.isascii()
                or not value.strip()
                or len(value) > limit
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ValueError(f"{name} must be a bounded non-empty value")
        validate_email_address(self.from_address)

    @classmethod
    def from_env(cls) -> InvitationMailSettings | None:
        """Read a complete optional SMTP configuration without exposing credential values."""

        names = (
            "STOCK_PROBS_INVITE_SMTP_HOST",
            "STOCK_PROBS_INVITE_SMTP_PORT",
            "STOCK_PROBS_INVITE_SMTP_USERNAME",
            "STOCK_PROBS_INVITE_SMTP_PASSWORD",
            "STOCK_PROBS_INVITE_SMTP_SECURITY",
            "STOCK_PROBS_INVITE_EMAIL_FROM",
        )
        values = {name: os.getenv(name) for name in names}
        configured = {
            name: value for name, value in values.items() if value is not None and value.strip()
        }
        if not configured:
            return None
        if len(configured) != len(names):
            raise ValueError("invitation SMTP configuration must set all six required values")
        raw_port = configured["STOCK_PROBS_INVITE_SMTP_PORT"]
        if not raw_port.isascii() or not raw_port.isdecimal() or len(raw_port) > 5:
            raise ValueError("STOCK_PROBS_INVITE_SMTP_PORT must be 465, 2465, or 587")
        port = int(raw_port)
        security = configured["STOCK_PROBS_INVITE_SMTP_SECURITY"].strip().lower()
        if security not in {"implicit_tls", "starttls"}:
            raise ValueError("STOCK_PROBS_INVITE_SMTP_SECURITY must be implicit_tls or starttls")
        return cls(
            host=validate_smtp_host(configured["STOCK_PROBS_INVITE_SMTP_HOST"].strip()),
            port=port,
            username=configured["STOCK_PROBS_INVITE_SMTP_USERNAME"],
            password=configured["STOCK_PROBS_INVITE_SMTP_PASSWORD"],
            security=security,
            from_address=validate_email_address(
                configured["STOCK_PROBS_INVITE_EMAIL_FROM"].strip()
            ),
        )


@dataclass(frozen=True)
class InviteEmailSubmission:
    """Non-secret facts about acceptance of one message by the configured SMTP server."""

    submission_id: str
    submitted_at: datetime


class InviteEmailError(AuthError):
    """A safe public-category failure while submitting an invitation email."""

    code = "invite_email_failed"
    status_code = 502
    message = "The invitation was created, but its email could not be submitted."


def _message(
    *,
    settings: InvitationMailSettings,
    public_origin: str,
    recipient: str,
    github_id: int,
    github_login: str | None,
    code: str,
    expires_at: datetime,
) -> EmailMessage:
    """Build a plain and HTML invitation with the bearer code only in message content."""

    destination = validate_email_address(recipient)
    sender = validate_email_address(settings.from_address)
    invitation_url = f"{public_origin.rstrip('/')}/invite"
    expiry = expires_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    login_line = f"GitHub login shown for reference: {github_login}\n" if github_login else ""
    message = EmailMessage()
    message["Subject"] = "Your Signal Ledger invitation"
    message["From"] = formataddr(("Signal Ledger", sender))
    message["To"] = destination
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = make_msgid()
    message.set_content(
        "You have been invited to Signal Ledger.\n\n"
        f"Open {invitation_url} and enter this invitation code:\n{code}\n\n"
        f"This invitation expires at {expiry}.\n"
        f"It is bound to GitHub account ID {github_id}; only that numeric "
        f"GitHub account can use it.\n"
        f"{login_line}The recipient email is for delivery only "
        f"and does not establish account identity.\n"
    )
    escaped_login = html.escape(github_login or "Not provided")
    message.add_alternative(
        "<p>You have been invited to Signal Ledger.</p>"
        f'<p><a href="{html.escape(invitation_url, quote=True)}">Open your invitation</a> '
        "and enter this code:</p>"
        f"<p><code>{html.escape(code)}</code></p>"
        f"<p>This invitation expires at <time>{html.escape(expiry)}</time>.</p>"
        f"<p>It is bound to GitHub account ID <strong>{github_id}</strong>; only that numeric "
        "GitHub account can use it.</p>"
        f"<p>GitHub login shown for reference: {escaped_login}. The recipient email address is "
        "for delivery only and does not establish account identity.</p>",
        subtype="html",
    )
    return message


def send_invitation_email(
    settings: InvitationMailSettings,
    *,
    public_origin: str,
    recipient: str,
    github_id: int,
    github_login: str | None,
    code: str,
    expires_at: datetime,
) -> InviteEmailSubmission:
    """Submit one message with verified TLS and a fixed network timeout.

    Args:
        settings: Validated SMTP endpoint, credentials, security mode, and sender.
        public_origin: Exact configured public application origin.
        recipient: Validated delivery mailbox.
        github_id: Stable numeric GitHub account identifier bound to the invitation.
        github_login: Optional login label shown only as a convenience.
        code: One-time bearer code; never returned by this function.
        expires_at: Invitation expiry from the auth manager.

    Returns:
        Non-secret local submission metadata after SMTP accepts the recipient.

    Raises:
        InviteEmailError: If TLS negotiation, authentication, or SMTP submission fails.
    """

    message = _message(
        settings=settings,
        public_origin=public_origin,
        recipient=recipient,
        github_id=github_id,
        github_login=github_login,
        code=code,
        expires_at=expires_at,
    )
    context = ssl.create_default_context()
    try:
        if settings.security == "implicit_tls":
            with smtplib.SMTP_SSL(
                settings.host,
                settings.port,
                timeout=SMTP_TIMEOUT_SECONDS,
                context=context,
            ) as connection:
                connection.ehlo()
                connection.login(settings.username, settings.password)
                refused = connection.send_message(message)
        else:
            with smtplib.SMTP(
                settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS
            ) as connection:
                connection.ehlo()
                connection.starttls(context=context)
                connection.ehlo()
                connection.login(settings.username, settings.password)
                refused = connection.send_message(message)
    except (OSError, smtplib.SMTPException, TimeoutError):
        raise InviteEmailError() from None
    if refused:
        raise InviteEmailError()
    return InviteEmailSubmission(submission_id=uuid4().hex, submitted_at=datetime.now(UTC))


def validate_smtp_host(value: str) -> str:
    """Validate a hostname or IP literal without accepting URL or command syntax."""

    if not isinstance(value, str) or not value.isascii() or not 1 <= len(value) <= 253:
        raise ValueError("STOCK_PROBS_INVITE_SMTP_HOST must be a hostname or IP address")
    if value != value.strip() or any(
        ord(character) < 33 or ord(character) > 126 for character in value
    ):
        raise ValueError("STOCK_PROBS_INVITE_SMTP_HOST must be a hostname or IP address")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    hostname = value[:-1] if value.endswith(".") else value
    if not hostname or any(not _DOMAIN_LABEL.fullmatch(label) for label in hostname.split(".")):
        raise ValueError("STOCK_PROBS_INVITE_SMTP_HOST must be a hostname or IP address")
    return value
