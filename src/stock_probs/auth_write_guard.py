"""Validate cached request authorization at the same SQLite boundary as a write.

HTTP middleware authenticates before reading a bounded request body. User-facing stores call
this guard only after opening their write transaction, so session revocation, account changes,
and role changes cannot race the final mutation.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from stock_probs.auth import AuthContext

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ROLES = frozenset({"admin", "member"})
StepUpChecker = Callable[[AuthContext, datetime], bool]


class AuthWriteAuthorizationError(ValueError):
    """Safe refusal when a cached request context is no longer authorized to write."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def authorize_current_write(
    connection: sqlite3.Connection,
    context: AuthContext | None,
    owner_user_id: int,
    now: datetime,
    *,
    required_role: str | None = None,
    require_step_up: bool = False,
    step_up_checker: StepUpChecker | None = None,
) -> None:
    """Require a current owner-bound session and any route-specific role/step-up in-transaction."""

    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a SQLite connection")
    if not isinstance(context, AuthContext):
        raise _unauthenticated()
    if (
        type(owner_user_id) is not int
        or owner_user_id < 1
        or context.user.id != owner_user_id
        or type(context.user.id) is not int
        or not isinstance(context.session_id, str)
        or not 16 <= len(context.session_id) <= 128
        or not isinstance(context.token_hash, str)
        or _HEX_64.fullmatch(context.token_hash) is None
        or not isinstance(context.csrf_token_hash, str)
        or _HEX_64.fullmatch(context.csrf_token_hash) is None
    ):
        raise _unauthenticated()
    if required_role is not None and required_role not in _ROLES:
        raise ValueError("required_role is invalid")
    if type(require_step_up) is not bool:
        raise ValueError("require_step_up must be a boolean")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = now.astimezone(UTC)

    row = connection.execute(
        """SELECT users.status AS user_status,users.role AS user_role,
                  sessions.session_id,sessions.token_hash,sessions.csrf_token_hash,
                  sessions.idle_expires_at,sessions.absolute_expires_at,sessions.revoked_at,
                  sessions.mfa_method,sessions.mfa_verified_at,sessions.mfa_factor_id,
                  EXISTS (SELECT 1 FROM totp_factors AS factor
                          WHERE factor.id=sessions.mfa_factor_id
                            AND factor.user_id=sessions.user_id) AS factor_current
             FROM sessions JOIN users ON users.id=sessions.user_id
            WHERE users.id=? AND sessions.session_id=? AND sessions.token_hash=?
              AND sessions.csrf_token_hash=?""",
        (
            owner_user_id,
            context.session_id,
            context.token_hash,
            context.csrf_token_hash,
        ),
    ).fetchone()
    if row is None or row["user_status"] != "active":
        raise _unauthenticated()
    if row["revoked_at"] is not None:
        raise _unauthenticated()
    idle_expiry = _stored_instant(row["idle_expires_at"])
    absolute_expiry = _stored_instant(row["absolute_expires_at"])
    if (
        idle_expiry is None
        or absolute_expiry is None
        or current >= idle_expiry
        or current >= absolute_expiry
    ):
        raise _unauthenticated()

    current_role = row["user_role"]
    if (
        current_role not in _ROLES
        or context.user.role not in _ROLES
        or current_role != context.user.role
        or (required_role is not None and current_role != required_role)
    ):
        raise _forbidden()

    stored_mfa = row["mfa_method"]
    context_mfa = context.mfa_method
    if context_mfa in {"totp", "recovery"}:
        verified_at = _stored_instant(row["mfa_verified_at"])
        context_verified_at = context.mfa_verified_at
        if (
            stored_mfa != context_mfa
            or type(context.mfa_factor_id) is not int
            or row["mfa_factor_id"] != context.mfa_factor_id
            or row["factor_current"] != 1
            or verified_at is None
            or not isinstance(context_verified_at, datetime)
            or context_verified_at.tzinfo is None
            or verified_at != context_verified_at.astimezone(UTC)
        ):
            raise _unauthenticated()
    elif context_mfa in {"none", "passkey"}:
        # Local development passkey step-up is process-local; ordinary requests still bind to
        # the live session row, while step-up requests also consult AuthManager's existing rule.
        if stored_mfa is not None or row["mfa_factor_id"] is not None:
            raise _unauthenticated()
    else:
        raise _unauthenticated()

    if require_step_up:
        if step_up_checker is None or step_up_checker(context, current) is not True:
            raise _step_up_required()
        if context_mfa == "totp":
            verified_at = _stored_instant(row["mfa_verified_at"])
            if verified_at is None or verified_at > current:
                raise _step_up_required()
        elif context_mfa != "passkey":
            raise _step_up_required()


def _stored_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _unauthenticated() -> AuthWriteAuthorizationError:
    return AuthWriteAuthorizationError(
        401,
        "AUTHENTICATION_REQUIRED",
        "The active session is unavailable; sign in again.",
    )


def _forbidden() -> AuthWriteAuthorizationError:
    return AuthWriteAuthorizationError(
        403,
        "AUTHORIZATION_REQUIRED",
        "The current account permissions do not allow this action.",
    )


def _step_up_required() -> AuthWriteAuthorizationError:
    return AuthWriteAuthorizationError(
        403,
        "STEP_UP_REQUIRED",
        "A fresh authenticator code is required for this operation.",
    )
