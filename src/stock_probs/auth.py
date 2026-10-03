"""Authentication primitives for local bootstrap and production GitHub sign-in.

The module deliberately keeps persistence behind a small protocol.  Authentication code never
receives a database connection and never stores a raw session, invitation, OAuth-state, or CSRF
token.  The application adapter supplied by the persistence layer owns those records.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from inspect import Parameter, signature
from typing import Literal, Protocol, cast

import httpx

from stock_probs.totp import (
    RECOVERY_CODE_COUNT,
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    matching_step,
    otpauth_uri,
)

AuthMode = Literal["disabled", "local", "github"]
UserRole = Literal["admin", "member"]
ChallengeKind = Literal["registration", "assertion"]

SESSION_COOKIE_NAME = "signal_ledger_session"
CSRF_COOKIE_NAME = "signal_ledger_csrf"
OAUTH_TRANSACTION_COOKIE_NAME = "signal_ledger_oauth_tx"
MAX_SESSION_TOKEN_BYTES = 64
MAX_PASSWORD_BYTES = 1024
MAX_INVITATION_TTL = timedelta(days=7)
MAX_OAUTH_STATE_TTL = timedelta(minutes=10)
MAX_PASSKEY_CHALLENGE_TTL = timedelta(minutes=5)
OAUTH_START_WINDOW = timedelta(minutes=1)
MAX_OAUTH_STARTS_PER_WINDOW = 64
MAX_OAUTH_STARTS_PER_CALLER_WINDOW = 8
MAX_PENDING_OAUTH_STATES = 128
MAX_PENDING_OAUTH_STATES_PER_CALLER = 8
UNATTRIBUTED_OAUTH_CALLER_KEY_HASH = "0" * 64


class AuthError(Exception):
    """Base class for errors that have a safe public authentication category."""

    code = "authentication_failed"
    status_code = 401
    message = "Authentication could not be completed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.public_message = message or self.message


class InvalidCredentials(AuthError):
    """Raised without revealing whether a local account exists."""

    code = "invalid_credentials"


class AuthenticationRequired(AuthError):
    """Raised when an endpoint requires a valid session."""

    code = "authentication_required"


class AuthorizationDenied(AuthError):
    """Raised when a session lacks the required role or account state."""

    code = "authorization_denied"
    status_code = 403
    message = "You do not have permission to perform this action."


class CsrfRejected(AuthError):
    """Raised when a mutating request lacks the session-bound CSRF token."""

    code = "csrf_rejected"
    status_code = 403
    message = "The security token is missing or invalid."


class AuthUnavailable(AuthError):
    """Raised when a required authentication dependency is not configured."""

    code = "authentication_unavailable"
    status_code = 503
    message = "Authentication is temporarily unavailable."


class OAuthStartLimited(AuthError):
    """Report an OAuth caller's bounded admission limit without exposing its identity."""

    code = "oauth_start_limited"
    status_code = 429
    message = "GitHub sign-in was started too many times. Try again later."
    retry_after_seconds = int(OAUTH_START_WINDOW.total_seconds())


class OAuthRejected(AuthError):
    """Raised when a GitHub authorization response is invalid or expired."""

    code = "oauth_rejected"
    status_code = 400
    message = "The GitHub sign-in response is invalid or expired."


class InvitationRejected(AuthError):
    """Raised when an invitation is missing, expired, revoked, or already consumed."""

    code = "invitation_rejected"
    status_code = 403
    message = "The invitation is invalid or has expired."


class PasskeyRejected(AuthError):
    """Raised when WebAuthn verification fails without exposing verifier details."""

    code = "passkey_rejected"
    status_code = 403
    message = "The passkey response could not be verified."


class TotpRejected(AuthError):
    """Raised when an authenticator code or recovery code is invalid or replayed."""

    code = "totp_rejected"
    status_code = 403
    message = "The authenticator code could not be verified."


class TotpRequired(AuthError):
    """Raised when a production session has not completed authenticator verification."""

    code = "totp_required"
    status_code = 403
    message = "Verify your authenticator code before using this application."


class TotpThrottled(AuthError):
    """Raised after bounded account-scoped authenticator failures."""

    code = "totp_rate_limited"
    status_code = 429
    message = "Too many authenticator attempts. Try again later."


class AuthStore(Protocol):
    """Persistence contract required by :class:`AuthManager`.

    Implementations must hash or encrypt all sensitive values before storing them.  Mapping
    records use ISO-8601 UTC strings for timestamps and stable integer ``user_id`` values.
    """

    def auth_get_user_by_id(self, user_id: int) -> Mapping[str, object] | None: ...

    def auth_get_user_by_username(self, username: str) -> Mapping[str, object] | None: ...

    def auth_get_user_by_github_id(self, github_id: int) -> Mapping[str, object] | None: ...

    def auth_create_user(self, fields: Mapping[str, object]) -> Mapping[str, object]: ...

    def auth_claim_legacy_owner(
        self, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None: ...

    def auth_update_user(
        self, user_id: int, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None: ...

    def auth_create_session(self, fields: Mapping[str, object]) -> Mapping[str, object] | None: ...

    def auth_get_session(
        self, token_hash: str, *, now: datetime | None = None
    ) -> Mapping[str, object] | None: ...

    def auth_touch_session(self, token_hash: str, fields: Mapping[str, object]) -> None: ...

    def auth_revoke_session(self, token_hash: str, revoked_at: str) -> None: ...

    def auth_revoke_all_sessions(self, user_id: int, revoked_at: str) -> None: ...

    def auth_create_invitation(self, fields: Mapping[str, object]) -> Mapping[str, object]: ...

    def auth_consume_invitation(
        self, code_hash: str, consumed_at: str
    ) -> Mapping[str, object] | None: ...

    def auth_redeem_invitation(
        self,
        code_hash: str,
        redeemed_at: str,
        github_id: int,
        verified_email_hashes: Sequence[str],
        github_login: str,
    ) -> Mapping[str, object] | None: ...

    def auth_get_invitation(self, code_hash: str) -> Mapping[str, object] | None: ...

    def auth_list_invitations(self) -> list[Mapping[str, object]]: ...

    def auth_store_oauth_state(self, fields: Mapping[str, object]) -> bool | None: ...

    def auth_consume_oauth_state(
        self, state_hash: str, consumed_at: str
    ) -> Mapping[str, object] | None: ...

    def auth_create_passkey(self, fields: Mapping[str, object]) -> Mapping[str, object]: ...

    def auth_get_passkeys(self, user_id: int) -> list[Mapping[str, object]]: ...

    def auth_get_passkey(
        self, credential_id: str, *, user_id: int | None = None
    ) -> Mapping[str, object] | None: ...

    def auth_update_passkey(
        self, credential_id: str, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None: ...

    def auth_begin_totp_enrollment(
        self,
        user_id: int,
        secret_ciphertext: str,
        created_at: str,
        expires_at: str,
        expected_factor_id: int | None,
        origin_token_hash: str,
        replace: bool = False,
    ) -> Mapping[str, object] | None: ...

    def auth_get_totp_enrollment(
        self, user_id: int, now: str | None = None
    ) -> Mapping[str, object] | None: ...

    def auth_confirm_totp_enrollment(
        self,
        user_id: int,
        confirmed_at: str,
        expected_secret_ciphertext: str,
        accepted_step: int,
        recovery_code_hashes: Sequence[str],
        revoked_at: str,
        expected_factor_id: int | None,
        origin_token_hash: str,
    ) -> Mapping[str, object] | None: ...

    def auth_get_totp_factor(self, user_id: int) -> Mapping[str, object] | None: ...

    def auth_accept_totp_step(
        self, user_id: int, expected_factor_id: int, step: int, accepted_at: str
    ) -> bool: ...

    def auth_reserve_totp_attempt(
        self, user_id: int, attempted_at: str, expected_factor_id: int | None = None
    ) -> bool: ...

    def auth_check_totp_attempt(self, user_id: int, attempted_at: str) -> Mapping[str, object]: ...

    def auth_record_totp_attempt(
        self,
        user_id: int,
        attempted_at: str,
        window_seconds: int = 300,
        max_attempts: int = 5,
        lockout_seconds: int = 900,
        successful: bool = False,
    ) -> Mapping[str, object]: ...

    def auth_create_recovery_codes(
        self,
        user_id: int,
        expected_factor_id: int,
        code_hashes: Sequence[str],
        created_at: str,
        origin_token_hash: str,
    ) -> bool: ...

    def auth_consume_recovery_code(
        self, user_id: int, expected_factor_id: int, code_hash: str, consumed_at: str
    ) -> bool: ...

    def auth_get_recovery_code_status(self, user_id: int) -> Mapping[str, object]: ...

    def auth_set_session_mfa(
        self, token_hash: str, method: str, verified_at: str, expected_factor_id: int
    ) -> bool: ...

    def auth_list_sessions(self, user_id: int) -> list[Mapping[str, object]]: ...

    def auth_revoke_session_by_id(self, user_id: int, session_id: str, revoked_at: str) -> None: ...


class AuthStoreAdapter:
    """Bridge the auth protocol to the repository's owner-scoped method vocabulary.

    The adapter accepts the explicit ``auth_*`` protocol used by tests and the shorter
    repository method names used by the persistence lane. Repository calls are mapped
    explicitly because silently dropping a required owner, timestamp, or revocation reason
    would turn an authentication failure into an unsafe partial write.
    """

    def __init__(self, inner: object) -> None:
        self.inner = inner

    def _method(self, *names: str):
        for name in names:
            candidate = getattr(self.inner, name, None)
            if callable(candidate):
                return candidate
        raise AuthUnavailable("Account persistence is not configured.")

    @staticmethod
    def _invoke(method: object, fields: Mapping[str, object]) -> object:
        """Call a test-store protocol method without dropping security fields."""

        callable_method = cast(object, method)
        try:
            parameters = signature(callable_method).parameters  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise AuthUnavailable("Account persistence signature is unavailable.") from exc
        if "fields" in parameters:
            positional: list[object] = []
            field_mapping = {
                key: value for key, value in fields.items() if key not in parameters and key != "id"
            }
            for name, parameter in parameters.items():
                if name == "self":
                    continue
                if name == "fields":
                    positional.append(fields.get("fields", field_mapping))
                elif name in fields:
                    positional.append(fields[name])
                elif parameter.default is Parameter.empty:
                    raise AuthUnavailable(
                        "Account persistence requires unavailable security fields."
                    )
            return cast(object, callable_method(*positional))  # type: ignore[operator]
        accepts_kwargs = any(
            parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
        if accepts_kwargs:
            return cast(object, callable_method(**dict(fields)))  # type: ignore[operator]
        missing = [
            name
            for name, parameter in parameters.items()
            if name != "self"
            and parameter.default is Parameter.empty
            and parameter.kind in {Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY}
            and name not in fields
        ]
        if missing:
            raise AuthUnavailable("Account persistence requires unavailable security fields.")
        selected = {key: value for key, value in fields.items() if key in parameters}
        return cast(object, callable_method(**selected))  # type: ignore[operator]

    @staticmethod
    def _datetime(value: object, name: str) -> datetime:
        try:
            return _utc(value)
        except AuthUnavailable as exc:
            raise AuthUnavailable(f"Account persistence returned an invalid {name}.") from exc

    @staticmethod
    def _normalize_user(value: Mapping[str, object] | None) -> Mapping[str, object] | None:
        if value is None:
            return None
        result = dict(value)
        if "id" not in result and "user_id" in result:
            result["id"] = result["user_id"]
        if "github_id" not in result and "github_user_id" in result:
            result["github_id"] = result["github_user_id"]
        if "username" not in result and "login" in result:
            result["username"] = result["login"]
        if "github_login" not in result and "login" in result:
            result["github_login"] = result["login"]
        if "name" not in result and "display_name" in result:
            result["name"] = result["display_name"]
        if "active" not in result:
            result["active"] = result.get("status", "active") in {"active", "enabled"}
        result.setdefault("passkey_enrolled", bool(result.get("has_passkey", False)))
        result.setdefault("passkey_required", result.get("role") != "admin")
        return result

    def _with_passkey_state(
        self, value: Mapping[str, object] | None
    ) -> Mapping[str, object] | None:
        """Derive enrollment from credential metadata without returning key material."""

        normalized = self._normalize_user(value)
        if normalized is None or bool(normalized.get("passkey_enrolled")):
            return normalized
        user_id = normalized.get("id")
        method = getattr(self.inner, "auth_get_passkeys", None) or getattr(
            self.inner, "list_user_passkeys", None
        )
        if callable(method) and type(user_id) is int:
            try:
                records = method(user_id)
            except (AuthError, OSError, TypeError, ValueError):
                records = []
            if isinstance(records, list):
                normalized = dict(normalized)
                normalized["passkey_enrolled"] = any(
                    isinstance(item, Mapping) and item.get("revoked_at") is None for item in records
                )
        return normalized

    def auth_get_user_by_id(self, user_id: int) -> Mapping[str, object] | None:
        value = self._method("auth_get_user_by_id", "get_user")(user_id)
        return self._with_passkey_state(value)

    def auth_get_user_by_username(self, username: str) -> Mapping[str, object] | None:
        value = self._method("auth_get_user_by_username", "get_user_by_login")(username)
        return self._with_passkey_state(value)

    def auth_get_user_by_github_id(self, github_id: int) -> Mapping[str, object] | None:
        value = self._method("auth_get_user_by_github_id", "get_user_by_github_id")(github_id)
        return self._with_passkey_state(value)

    def auth_create_user(self, fields: Mapping[str, object]) -> Mapping[str, object]:
        method = self._method("auth_create_user", "create_user")
        login = fields.get("login", fields.get("github_login", fields.get("username")))
        display_name = fields.get("display_name", fields.get("name", login))
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = "Signal Ledger user"
        created_at = fields.get("created_at", datetime.now(UTC))
        result = self._invoke(
            method,
            {
                **fields,
                "github_user_id": fields.get("github_user_id", fields.get("github_id")),
                "login": login,
                "display_name": display_name,
                "password_hash": fields.get("password_hash"),
                "role": fields.get("role", "member"),
                "status": fields.get("status", "active"),
                "created_at": self._datetime(created_at, "created_at"),
            },
        )
        if not isinstance(result, Mapping):
            raise AuthUnavailable("Account persistence returned an invalid user.")
        normalized = self._with_passkey_state(result)
        if normalized is None:
            raise AuthUnavailable("Account persistence returned an invalid user.")
        return normalized

    def auth_claim_legacy_owner(self, fields: Mapping[str, object]) -> Mapping[str, object] | None:
        """Claim the reserved legacy owner only when persistence exposes the atomic operation."""

        method = getattr(self.inner, "claim_legacy_owner", None)
        if not callable(method):
            method = getattr(self.inner, "auth_claim_legacy_owner", None)
        if not callable(method):
            return None
        result = self._invoke(
            method,
            {
                **fields,
                "login": fields.get("login"),
                "display_name": fields.get("display_name", fields.get("login")),
                "claimed_at": self._datetime(
                    fields.get("claimed_at", datetime.now(UTC)), "claimed_at"
                ),
            },
        )
        return self._with_passkey_state(result) if isinstance(result, Mapping) else None

    def auth_update_user(
        self, user_id: int, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        method = getattr(self.inner, "auth_update_user", None) or getattr(
            self.inner, "update_user", None
        )
        if not callable(method):
            method = getattr(self.inner, "update_user_security", None)
        if not callable(method):
            return self.auth_get_user_by_id(user_id)
        allowed = {
            key: value for key, value in fields.items() if key in {"role", "status", "display_name"}
        }
        if not allowed:
            return self.auth_get_user_by_id(user_id)
        result = self._invoke(
            method,
            {"user_id": user_id, "id": user_id, "at": datetime.now(UTC), **allowed},
        )
        return self._with_passkey_state(result) if isinstance(result, Mapping) else None

    def auth_create_session(self, fields: Mapping[str, object]) -> Mapping[str, object] | None:
        method = self._method("auth_create_session", "create_session")
        created = fields.get("created_at", fields.get("issued_at"))
        last_seen = fields.get("last_seen_at", created)
        idle = fields.get("idle_expires_at")
        absolute = fields.get("expires_at", fields.get("absolute_expires_at"))
        result = self._invoke(
            method,
            {
                **fields,
                "user_id": fields.get("user_id"),
                "token_hash": fields.get("token_hash"),
                "csrf_token_hash": fields.get("csrf_token_hash"),
                "issued_at": self._datetime(created, "issued_at"),
                "last_seen_at": self._datetime(last_seen, "last_seen_at"),
                "idle_expires_at": self._datetime(idle, "idle_expires_at"),
                "absolute_expires_at": self._datetime(absolute, "absolute_expires_at"),
            },
        )
        return result if isinstance(result, Mapping) else None

    def auth_get_session(
        self, token_hash: str, *, now: datetime | None = None
    ) -> Mapping[str, object] | None:
        method = self._method("auth_get_session", "get_session")
        try:
            parameters = signature(method).parameters
        except (TypeError, ValueError) as exc:
            raise AuthUnavailable("Account persistence signature is unavailable.") from exc
        if "now" in parameters:
            values: dict[str, object] = {"now": now or datetime.now(UTC)}
            if "touch" in parameters:
                values["touch"] = False
            value = method(token_hash, **values)
        else:
            value = method(token_hash)
        if not isinstance(value, Mapping):
            return None
        result = dict(value)
        if "session_id" not in result and "id" in result:
            result["session_id"] = str(result["id"])
        if "created_at" not in result and "issued_at" in result:
            result["created_at"] = result["issued_at"]
        if "expires_at" not in result and "absolute_expires_at" in result:
            result["expires_at"] = result["absolute_expires_at"]
        result.setdefault("token_hash", token_hash)
        return result

    def auth_touch_session(self, token_hash: str, fields: Mapping[str, object]) -> None:
        method = getattr(self.inner, "auth_touch_session", None) or getattr(
            self.inner, "touch_session", None
        )
        if callable(method):
            self._invoke(method, {"token_hash": token_hash, **fields})
            return
        method = getattr(self.inner, "get_session", None)
        if callable(method):
            method(token_hash, now=datetime.now(UTC), touch=True)

    def auth_revoke_session(self, token_hash: str, revoked_at: str) -> None:
        method = self._method("auth_revoke_session", "revoke_session")
        self._invoke(
            method,
            {
                "token_hash": token_hash,
                "revoked_at": self._datetime(revoked_at, "revoked_at"),
                "reason": "logout",
            },
        )

    def auth_revoke_all_sessions(self, user_id: int, revoked_at: str) -> None:
        method = self._method(
            "auth_revoke_all_sessions", "revoke_all_sessions", "revoke_user_sessions"
        )
        self._invoke(
            method,
            {"user_id": user_id, "revoked_at": self._datetime(revoked_at, "revoked_at")},
        )

    def auth_create_invitation(self, fields: Mapping[str, object]) -> Mapping[str, object]:
        result = self._invoke(
            self._method("auth_create_invitation", "create_invitation"),
            {
                **fields,
                "github_user_id": fields.get("github_user_id", fields.get("github_id")),
                "token_hash": fields.get("token_hash", fields.get("code_hash")),
                "invited_by_user_id": fields.get("invited_by_user_id", fields.get("invited_by")),
                "expires_at": self._datetime(fields.get("expires_at"), "expires_at"),
                "created_at": self._datetime(fields.get("created_at"), "created_at"),
                "github_login": fields.get("github_login"),
            },
        )
        if not isinstance(result, Mapping):
            raise AuthUnavailable("Invitation persistence returned an invalid record.")
        return result

    def auth_consume_invitation(
        self, code_hash: str, consumed_at: str
    ) -> Mapping[str, object] | None:
        method = self._method("auth_consume_invitation", "consume_invitation")
        result = self._invoke(
            method,
            {
                "code_hash": code_hash,
                "token_hash": code_hash,
                "consumed_at": consumed_at,
                "now": self._datetime(consumed_at, "now"),
            },
        )
        return result if isinstance(result, Mapping) else None

    def auth_redeem_invitation(
        self,
        code_hash: str,
        redeemed_at: str,
        github_id: int,
        verified_email_hashes: Sequence[str],
        github_login: str,
    ) -> Mapping[str, object] | None:
        """Require the persistence adapter's atomic identity-check and consume operation."""

        method = getattr(self.inner, "auth_redeem_invitation", None) or getattr(
            self.inner, "redeem_invitation", None
        )
        if not callable(method):
            raise AuthUnavailable("Invitation identity binding is not configured.")
        result = self._invoke(
            method,
            {
                "code_hash": code_hash,
                "token_hash": code_hash,
                "redeemed_at": redeemed_at,
                "now": self._datetime(redeemed_at, "redeemed_at"),
                "github_id": github_id,
                "github_user_id": github_id,
                "verified_email_hashes": tuple(verified_email_hashes),
                "github_login": github_login,
            },
        )
        return result if isinstance(result, Mapping) else None

    def auth_get_invitation(self, code_hash: str) -> Mapping[str, object] | None:
        method = getattr(self.inner, "auth_get_invitation", None) or getattr(
            self.inner, "get_invitation", None
        )
        if not callable(method):
            raise AuthUnavailable("Invitation persistence is not configured.")
        try:
            result = method(code_hash)
        except TypeError:
            result = method(token_hash=code_hash)
        return result if isinstance(result, Mapping) else None

    def auth_list_invitations(self) -> list[Mapping[str, object]]:
        """Return only sanitized invite metadata from the active persistence store."""

        method = getattr(self.inner, "auth_list_invitations", None) or getattr(
            self.inner, "list_invitations", None
        )
        if not callable(method):
            return []
        result = method()
        return (
            [item for item in result if isinstance(item, Mapping)]
            if isinstance(result, list)
            else []
        )

    def auth_store_oauth_state(self, fields: Mapping[str, object]) -> bool:
        method = self._method("auth_store_oauth_state", "store_oauth_state", "create_oauth_state")
        result = self._invoke(
            method,
            {
                **fields,
                "created_at": self._datetime(fields.get("created_at"), "created_at"),
                "expires_at": self._datetime(fields.get("expires_at"), "expires_at"),
            },
        )
        return result is not False

    def auth_consume_oauth_state(
        self, state_hash: str, consumed_at: str
    ) -> Mapping[str, object] | None:
        method = self._method("auth_consume_oauth_state", "consume_oauth_state")
        result = self._invoke(
            method,
            {
                "state_hash": state_hash,
                "consumed_at": consumed_at,
                "now": self._datetime(consumed_at, "now"),
            },
        )
        return result if isinstance(result, Mapping) else None

    def auth_create_passkey(self, fields: Mapping[str, object]) -> Mapping[str, object]:
        result = self._invoke(
            self._method("auth_create_passkey", "register_passkey"),
            {**fields, "created_at": self._datetime(fields.get("created_at"), "created_at")},
        )
        if not isinstance(result, Mapping):
            raise AuthUnavailable("Passkey persistence returned an invalid record.")
        return result

    def auth_get_passkeys(self, user_id: int) -> list[Mapping[str, object]]:
        method = self._method("auth_get_passkeys", "get_passkeys", "list_user_passkeys")
        result = method(user_id)
        records = (
            [item for item in result if isinstance(item, Mapping)]
            if isinstance(result, list)
            else []
        )
        return [item for item in records if item.get("revoked_at") is None]

    def auth_get_passkey(
        self, credential_id: str, *, user_id: int | None = None
    ) -> Mapping[str, object] | None:
        method = self._method("auth_get_passkey", "get_passkey")
        if user_id is None:
            raise AuthUnavailable("Passkey lookup requires an account binding.")
        result = method(credential_id, user_id=user_id)
        if not isinstance(result, Mapping) or result.get("revoked_at") is not None:
            return None
        return result

    def auth_update_passkey(
        self, credential_id: str, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        method = self._method("auth_update_passkey", "update_passkey", "update_passkey_sign_count")
        result = self._invoke(
            method,
            {
                **fields,
                "credential_id": credential_id,
                "used_at": self._datetime(fields.get("used_at", datetime.now(UTC)), "used_at"),
                "last_used_at": self._datetime(
                    fields.get("used_at", fields.get("last_used_at", datetime.now(UTC))),
                    "last_used_at",
                ),
            },
        )
        return result if isinstance(result, Mapping) else None

    def auth_begin_totp_enrollment(
        self,
        user_id: int,
        secret_ciphertext: str,
        created_at: str,
        expires_at: str,
        expected_factor_id: int | None,
        origin_token_hash: str,
        replace: bool = False,
    ) -> Mapping[str, object] | None:
        """Persist one encrypted, expiring TOTP enrollment secret."""

        method = self._method("auth_begin_totp_enrollment", "begin_totp_enrollment")
        result = self._invoke(
            method,
            {
                "user_id": user_id,
                "secret_ciphertext": secret_ciphertext,
                "created_at": created_at,
                "expires_at": expires_at,
                "expected_factor_id": expected_factor_id,
                "origin_token_hash": origin_token_hash,
                "replace": replace,
            },
        )
        return result if isinstance(result, Mapping) else None

    def auth_get_totp_enrollment(
        self, user_id: int, now: str | None = None
    ) -> Mapping[str, object] | None:
        """Load an unexpired TOTP enrollment without exposing its secret."""

        method = self._method("auth_get_totp_enrollment", "get_totp_enrollment")
        values: dict[str, object] = {"user_id": user_id}
        if now is not None:
            values["now"] = now
        try:
            result = self._invoke(method, values)
        except TypeError:
            result = method(user_id)
        return result if isinstance(result, Mapping) else None

    def auth_confirm_totp_enrollment(
        self,
        user_id: int,
        confirmed_at: str,
        expected_secret_ciphertext: str,
        accepted_step: int,
        recovery_code_hashes: Sequence[str],
        revoked_at: str,
        expected_factor_id: int | None,
        origin_token_hash: str,
    ) -> Mapping[str, object] | None:
        """Atomically promote the pending TOTP enrollment to an active factor."""

        method = self._method("auth_confirm_totp_enrollment", "confirm_totp_enrollment")
        result = self._invoke(
            method,
            {
                "user_id": user_id,
                "confirmed_at": confirmed_at,
                "expected_secret_ciphertext": expected_secret_ciphertext,
                "accepted_step": accepted_step,
                "recovery_code_hashes": recovery_code_hashes,
                "revoked_at": revoked_at,
                "expected_factor_id": expected_factor_id,
                "origin_token_hash": origin_token_hash,
            },
        )
        return result if isinstance(result, Mapping) else None

    def auth_get_totp_factor(self, user_id: int) -> Mapping[str, object] | None:
        """Return metadata and encrypted material for one account's active factor."""

        result = self._method("auth_get_totp_factor", "get_totp_factor")(user_id)
        return result if isinstance(result, Mapping) else None

    def auth_accept_totp_step(
        self, user_id: int, expected_factor_id: int, step: int, accepted_at: str
    ) -> bool:
        """Atomically accept one time step and reject a replayed code."""

        method = self._method("auth_accept_totp_step", "accept_totp_step")
        result = self._invoke(
            method,
            {
                "user_id": user_id,
                "expected_factor_id": expected_factor_id,
                "step": step,
                "accepted_at": accepted_at,
            },
        )
        return result is True

    def auth_reserve_totp_attempt(
        self, user_id: int, attempted_at: str, expected_factor_id: int | None = None
    ) -> bool:
        """Reserve one durable throttle slot before doing attacker-controlled crypto."""

        method = self._method("auth_reserve_totp_attempt", "reserve_totp_attempt")
        result = self._invoke(
            method,
            {
                "user_id": user_id,
                "attempted_at": attempted_at,
                "expected_factor_id": expected_factor_id,
            },
        )
        return result is True

    def auth_check_totp_attempt(self, user_id: int, attempted_at: str) -> Mapping[str, object]:
        """Read the durable account lock gate before performing TOTP crypto."""

        method = self._method("auth_check_totp_attempt", "check_totp_attempt")
        result = self._invoke(
            method,
            {"user_id": user_id, "attempted_at": attempted_at},
        )
        if not isinstance(result, Mapping):
            raise AuthUnavailable("Authenticator attempt persistence returned an invalid record.")
        return result

    def auth_record_totp_attempt(
        self,
        user_id: int,
        attempted_at: str,
        window_seconds: int = 300,
        max_attempts: int = 5,
        lockout_seconds: int = 900,
        successful: bool = False,
    ) -> Mapping[str, object]:
        """Record a bounded account-scoped attempt and return the lockout decision."""

        method = getattr(self.inner, "auth_record_totp_attempt", None) or getattr(
            self.inner, "auth_totp_attempt", None
        )
        if not callable(method):
            raise AuthUnavailable("Authenticator attempt persistence is not configured.")
        result = self._invoke(
            method,
            {
                "user_id": user_id,
                "attempted_at": attempted_at,
                "window_seconds": window_seconds,
                "max_attempts": max_attempts,
                "lockout_seconds": lockout_seconds,
                "successful": successful,
            },
        )
        if not isinstance(result, Mapping):
            raise AuthUnavailable("Authenticator attempt persistence returned an invalid record.")
        return result

    def auth_create_recovery_codes(
        self,
        user_id: int,
        expected_factor_id: int,
        code_hashes: Sequence[str],
        created_at: str,
        origin_token_hash: str,
    ) -> bool:
        """Replace an account's recovery codes and return the durable count."""

        method = self._method("auth_create_recovery_codes", "create_recovery_codes")
        result = self._invoke(
            method,
            {
                "user_id": user_id,
                "expected_factor_id": expected_factor_id,
                "code_hashes": code_hashes,
                "created_at": created_at,
                "origin_token_hash": origin_token_hash,
            },
        )
        return result is True

    def auth_consume_recovery_code(
        self, user_id: int, expected_factor_id: int, code_hash: str, consumed_at: str
    ) -> bool:
        """Consume exactly one recovery code atomically."""

        method = self._method("auth_consume_recovery_code", "consume_recovery_code")
        result = self._invoke(
            method,
            {
                "user_id": user_id,
                "expected_factor_id": expected_factor_id,
                "code_hash": code_hash,
                "consumed_at": consumed_at,
            },
        )
        return result is True

    def auth_get_recovery_code_status(self, user_id: int) -> Mapping[str, object]:
        """Return bounded recovery-code counts without exposing code material."""

        method = self._method(
            "auth_get_recovery_code_status",
            "get_recovery_code_status",
            "auth_list_recovery_code_status",
            "list_recovery_code_status",
        )
        result = method(user_id)
        if isinstance(result, Mapping):
            return result
        if isinstance(result, list):
            available = sum(
                1
                for item in result
                if isinstance(item, Mapping)
                and item.get("consumed_at") is None
                and item.get("revoked_at") is None
            )
            return {"available_count": available, "total_count": len(result)}
        raise AuthUnavailable("Recovery code persistence returned an invalid record.")

    def auth_set_session_mfa(
        self, token_hash: str, method: str, verified_at: str, expected_factor_id: int
    ) -> bool:
        """Persist a fresh factor marker on one existing opaque session."""

        setter = self._method("auth_set_session_mfa", "set_session_mfa")
        result = self._invoke(
            setter,
            {
                "token_hash": token_hash,
                "method": method,
                "mfa_method": method,
                "verified_at": verified_at,
                "mfa_verified_at": verified_at,
                "expected_factor_id": expected_factor_id,
            },
        )
        return result is True

    def auth_list_sessions(self, user_id: int) -> list[Mapping[str, object]]:
        method = getattr(self.inner, "auth_list_sessions", None) or getattr(
            self.inner, "list_sessions", None
        )
        if not callable(method):
            return []
        result = method(user_id)
        return (
            [item for item in result if isinstance(item, Mapping)]
            if isinstance(result, list)
            else []
        )

    def auth_revoke_session_by_id(self, user_id: int, session_id: str, revoked_at: str) -> None:
        method = getattr(self.inner, "auth_revoke_session_by_id", None) or getattr(
            self.inner, "revoke_session_by_id", None
        )
        if callable(method):
            self._invoke(
                method,
                {"user_id": user_id, "session_id": session_id, "revoked_at": revoked_at},
            )


@dataclass(frozen=True)
class AuthSettings:
    """Bounded authentication settings with production-safe defaults."""

    mode: AuthMode = "disabled"
    session_secret: str = "development-only-session-secret"  # noqa: S105
    session_idle_seconds: int = 1_800
    session_max_seconds: int = 86_400
    invitation_ttl_seconds: int = 86_400
    oauth_state_ttl_seconds: int = 600
    public_origin: str | None = None
    cookie_secure: bool = False
    cookie_domain: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_redirect_uri: str | None = None
    owner_github_id: int | None = None
    bootstrap_username: str | None = None
    bootstrap_password: str | None = None
    totp_issuer: str = "Signal Ledger"
    totp_enrollment_ttl_seconds: int = 600

    def validate(self) -> None:
        """Reject unsafe production combinations before the application starts."""

        if self.mode not in {"disabled", "local", "github"}:
            raise ValueError("STOCK_PROBS_AUTH_MODE must be disabled, local, or github")
        if not 300 <= self.session_idle_seconds <= self.session_max_seconds:
            raise ValueError("session idle expiry must be between 5 minutes and max expiry")
        if self.session_max_seconds > 2_678_400:
            raise ValueError("session max expiry must be no more than 31 days")
        if not 60 <= self.invitation_ttl_seconds <= int(MAX_INVITATION_TTL.total_seconds()):
            raise ValueError("invitation expiry must be between 60 seconds and 7 days")
        if not 60 <= self.oauth_state_ttl_seconds <= int(MAX_OAUTH_STATE_TTL.total_seconds()):
            raise ValueError("OAuth state expiry must be between 60 and 600 seconds")
        if not 60 <= self.totp_enrollment_ttl_seconds <= 900:
            raise ValueError("TOTP enrollment expiry must be between 60 and 900 seconds")
        if not isinstance(self.totp_issuer, str) or not 1 <= len(self.totp_issuer.strip()) <= 64:
            raise ValueError("TOTP issuer must be between 1 and 64 characters")
        if self.mode == "disabled":
            return
        if not self.session_secret or len(self.session_secret.encode()) < 32:
            raise ValueError("auth session secret must contain at least 32 bytes")
        if not self.public_origin:
            raise ValueError("public origin is required when authentication is enabled")
        if self.mode == "github":
            if not self.github_client_id or not self.github_client_secret:
                raise ValueError("GitHub OAuth credentials are required")
            if not self.github_redirect_uri:
                raise ValueError("GitHub OAuth redirect URI is required")
            if self.owner_github_id is not None and (
                type(self.owner_github_id) is not int or self.owner_github_id < 1
            ):
                raise ValueError("owner GitHub ID must be a positive integer")
        if self.cookie_secure and not self.public_origin.startswith("https://"):
            raise ValueError("secure authentication cookies require an HTTPS public origin")


@dataclass(frozen=True)
class UserRecord:
    """Public-safe account identity used by route authorization and UI responses."""

    id: int
    role: UserRole
    username: str | None
    github_id: int | None
    github_login: str | None
    display_name: str | None
    email: str | None
    active: bool
    passkey_enrolled: bool
    passkey_required: bool
    totp_enrolled: bool = False

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> UserRecord:
        """Convert a persistence row while rejecting malformed security state."""

        raw_id = value.get("id", value.get("user_id"))
        role = value.get("role")
        if type(raw_id) is not int or raw_id < 1 or role not in {"admin", "member"}:
            raise AuthUnavailable("Account security state is invalid.")
        github_id = value.get("github_id")
        if github_id is not None and type(github_id) is not int:
            raise AuthUnavailable("Account security state is invalid.")
        return cls(
            id=raw_id,
            role=cast(UserRole, role),
            username=_optional_text(value.get("username")),
            github_id=github_id,
            github_login=_optional_text(value.get("github_login")),
            display_name=_optional_text(value.get("display_name", value.get("name"))),
            email=_optional_text(value.get("email")),
            active=bool(value.get("active", True)),
            passkey_enrolled=bool(value.get("passkey_enrolled", False)),
            passkey_required=bool(value.get("passkey_required", True)),
            totp_enrolled=bool(value.get("totp_enrolled", value.get("has_totp", False))),
        )

    def public_dict(self) -> dict[str, object]:
        """Return only identity and capability facts suitable for browser JSON."""

        return {
            "id": self.id,
            "role": self.role,
            "username": self.username,
            "login": self.github_login or self.username,
            "name": self.display_name or self.github_login or self.username,
            "github_login": self.github_login,
            "email": self.email,
            "avatar_url": None,
            "passkey_enrolled": self.passkey_enrolled,
            "passkey_required": self.passkey_required,
            "passkey_registered": self.passkey_enrolled,
            "totp_enrolled": self.totp_enrolled,
        }


@dataclass(frozen=True)
class AuthContext:
    """A validated request identity; raw session tokens never appear here."""

    user: UserRecord
    session_id: str
    token_hash: str
    csrf_token_hash: str
    auth_method: Literal["local", "github", "passkey"]
    mfa_method: Literal["none", "totp", "passkey", "recovery"] = "none"
    mfa_verified_at: datetime | None = None
    mfa_factor_id: int | None = None


@dataclass(frozen=True)
class SessionIssue:
    """One-time material returned to the HTTP layer when a session is created."""

    session_token: str
    csrf_token: str
    context: AuthContext
    expires_at: datetime


@dataclass(frozen=True)
class GithubIdentity:
    """Stable GitHub account facts accepted after the OAuth exchange."""

    github_id: int
    login: str
    email: str | None
    invitation_code_hash: str | None = None
    verified_email_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GithubAuthorization:
    """Redirect parameters generated for one server-side OAuth transaction."""

    url: str
    state: str
    code_verifier: str


@dataclass(frozen=True)
class PasskeyCredential:
    """Stored WebAuthn credential facts passed to a backend verifier."""

    credential_id: str
    user_id: int
    public_key: str
    sign_count: int
    transports: tuple[str, ...]


class PasskeyBackend(Protocol):
    """Cryptographic WebAuthn adapter; production must inject a real implementation."""

    def verify_registration(
        self,
        response: Mapping[str, object],
        challenge: str,
        user_id: int,
        rp_id: str,
        origin: str,
    ) -> PasskeyCredential: ...

    def verify_assertion(
        self,
        response: Mapping[str, object],
        challenge: str,
        credential: PasskeyCredential,
        rp_id: str,
        origin: str,
    ) -> int: ...


class UnavailablePasskeyBackend:
    """Fail closed when the optional WebAuthn implementation is not installed."""

    def verify_registration(
        self,
        response: Mapping[str, object],
        challenge: str,
        user_id: int,
        rp_id: str,
        origin: str,
    ) -> PasskeyCredential:
        del response, challenge, user_id, rp_id, origin
        raise AuthUnavailable("Passkey verification is not configured.")

    def verify_assertion(
        self,
        response: Mapping[str, object],
        challenge: str,
        credential: PasskeyCredential,
        rp_id: str,
        origin: str,
    ) -> int:
        del response, challenge, credential, rp_id, origin
        raise AuthUnavailable("Passkey verification is not configured.")


def _passkey_response_payload(response: Mapping[str, object]) -> dict[str, object]:
    """Normalize the browser's compact request fields to the WebAuthn library contract."""

    payload = dict(response)
    raw_id = payload.get("rawId", payload.get("raw_id"))
    if "rawId" not in payload and isinstance(raw_id, str):
        payload["rawId"] = raw_id
    nested = payload.get("response")
    if not isinstance(nested, Mapping):
        raise PasskeyRejected()
    payload["response"] = dict(nested)
    return payload


def _stored_passkey_transports(value: object) -> tuple[str, ...]:
    """Decode the repository's JSON transport representation for WebAuthn."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ()
    if isinstance(value, list | tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


class WebAuthnPasskeyBackend:
    """Verify browser ceremonies with the pinned ``webauthn`` implementation.

    The backend stores only the public credential key and monotonic counter. Private key
    material remains inside the authenticator. Importing the optional package lazily keeps
    disabled/local development installs usable while an enabled production app fails closed.
    """

    @staticmethod
    def _library():
        try:
            from webauthn import verify_authentication_response, verify_registration_response
            from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
        except ImportError as exc:
            raise AuthUnavailable("Passkey verification is not configured.") from exc
        return (
            base64url_to_bytes,
            bytes_to_base64url,
            verify_authentication_response,
            verify_registration_response,
        )

    def verify_registration(
        self,
        response: Mapping[str, object],
        challenge: str,
        user_id: int,
        rp_id: str,
        origin: str,
    ) -> PasskeyCredential:
        try:
            (
                base64url_to_bytes,
                bytes_to_base64url,
                _verify_authentication_response,
                verify_registration_response,
            ) = self._library()
            verified = verify_registration_response(
                credential=_passkey_response_payload(response),
                expected_challenge=base64url_to_bytes(challenge),
                expected_rp_id=rp_id,
                expected_origin=origin,
                require_user_presence=True,
                require_user_verification=True,
            )
            nested = response.get("response")
            transports = (
                tuple(item for item in nested.get("transports", []) if isinstance(item, str))
                if isinstance(nested, Mapping) and isinstance(nested.get("transports", []), list)
                else ()
            )
            return PasskeyCredential(
                credential_id=bytes_to_base64url(verified.credential_id),
                user_id=user_id,
                public_key=bytes_to_base64url(verified.credential_public_key),
                sign_count=verified.sign_count,
                transports=transports,
            )
        except AuthError:
            raise
        except Exception as exc:
            # Library exception text may include attacker-controlled parser details. Keep the
            # public response at one stable category while retaining the cause for diagnostics.
            raise PasskeyRejected() from exc

    def verify_assertion(
        self,
        response: Mapping[str, object],
        challenge: str,
        credential: PasskeyCredential,
        rp_id: str,
        origin: str,
    ) -> int:
        try:
            (
                base64url_to_bytes,
                _bytes_to_base64url,
                verify_authentication_response,
                _verify_registration_response,
            ) = self._library()
            verified = verify_authentication_response(
                credential=_passkey_response_payload(response),
                expected_challenge=base64url_to_bytes(challenge),
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=base64url_to_bytes(credential.public_key),
                credential_current_sign_count=credential.sign_count,
                require_user_verification=True,
            )
            return verified.new_sign_count
        except AuthError:
            raise
        except Exception as exc:
            raise PasskeyRejected() from exc


def default_passkey_backend() -> PasskeyBackend:
    """Return the installed verifier or an explicit fail-closed implementation."""

    try:
        WebAuthnPasskeyBackend._library()
    except AuthUnavailable:
        return UnavailablePasskeyBackend()
    return WebAuthnPasskeyBackend()


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _utc(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise AuthUnavailable("Account security state is invalid.") from exc
    else:
        raise AuthUnavailable("Account security state is invalid.")
    if result.tzinfo is None:
        raise AuthUnavailable("Account security state is invalid.")
    return result.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def re_full_hex(value: str) -> bool:
    """Check a fixed-size digest without accepting Unicode lookalikes."""

    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


def hash_password(password: str) -> str:
    """Hash a local development password with memory-hard scrypt and a random salt."""

    encoded = password.encode("utf-8")
    if not 12 <= len(encoded) <= MAX_PASSWORD_BYTES:
        raise ValueError("password must be between 12 and 1024 UTF-8 bytes")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(encoded, salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024)
    return "scrypt$15$8$1$" + _b64(salt) + "$" + _b64(digest)


def verify_password(password: str, encoded: str) -> bool:
    """Verify the bounded password format without exposing parser or timing details."""

    try:
        scheme, log_n, raw_r, raw_p, salt_text, digest_text = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        log_n_value = int(log_n)
        r_value = int(raw_r)
        p_value = int(raw_p)
        if not (14 <= log_n_value <= 16 and r_value == 8 and p_value == 1):
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        if len(salt) != 16 or len(expected) != 64:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**log_n_value,
            r=r_value,
            p=p_value,
            maxmem=64 * 1024 * 1024,
        )
    except (TypeError, ValueError, UnicodeError):
        return False
    return hmac.compare_digest(actual, expected)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if len(value) > 512 or not value.isascii():
        raise ValueError("invalid encoded value")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _safe_username(value: str) -> str:
    normalized = value.strip().casefold()
    if not 3 <= len(normalized) <= 64 or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in normalized
    ):
        raise ValueError("username contains unsupported characters")
    return normalized


def _safe_github_id(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ValueError("GitHub account ID must be a positive bounded integer")
    return value


class AuthManager:
    """Coordinate account, session, invitation, OAuth, and account-factor state."""

    def __init__(
        self,
        store: AuthStore,
        settings: AuthSettings,
        *,
        passkey_backend: PasskeyBackend | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        settings.validate()
        self.store: AuthStore = (
            store if isinstance(store, AuthStoreAdapter) else AuthStoreAdapter(store)
        )
        self.settings = settings
        self.passkey_backend = passkey_backend or default_passkey_backend()
        self.http_client = http_client
        self._challenge_lock = threading.Lock()
        self._challenges: dict[str, tuple[ChallengeKind, int, datetime]] = {}
        self._oauth_start_lock = threading.Lock()
        self._oauth_start_times: list[tuple[str, datetime]] = []
        # Keep a short-lived local-only marker for development backup step-up checks. Production
        # workspace access is decided by the durable TOTP session fields below.
        self._step_up_sessions: dict[str, tuple[int, datetime]] = {}

    @property
    def enabled(self) -> bool:
        """Return whether route protection is active."""

        return self.settings.mode != "disabled"

    def user_from_record(self, value: Mapping[str, object]) -> UserRecord:
        """Apply the deployment authentication policy to a persisted account row."""

        user = UserRecord.from_record(value)
        if self.settings.mode == "github":
            # WebAuthn credentials are historical audit rows after the authenticator-only
            # cutover. Stale denormalized flags must never make a GitHub account advertise or
            # enter the retired ceremony, whether or not a factor row is still present.
            user = replace(user, passkey_enrolled=False, passkey_required=False)
        if not user.totp_enrolled and self.has_totp_factor(user.id):
            user = replace(user, totp_enrolled=True, passkey_required=False)
        return user

    def local_login(self, username: str, password: str, now: datetime) -> SessionIssue:
        """Authenticate a development-only local account and issue an opaque session."""

        if self.settings.mode != "local":
            raise AuthenticationRequired()
        try:
            normalized = _safe_username(username)
        except ValueError:
            raise InvalidCredentials() from None
        record = self.store.auth_get_user_by_username(normalized)
        if record is None:
            raise InvalidCredentials()
        user = self.user_from_record(record)
        password_hash = record.get("password_hash")
        if (
            not user.active
            or not isinstance(password_hash, str)
            or not verify_password(password, password_hash)
        ):
            raise InvalidCredentials()
        return self.issue_session(user, now, "local")

    def ensure_local_bootstrap(
        self,
        username: str,
        password: str,
        now: datetime,
        *,
        role: UserRole = "admin",
    ) -> Mapping[str, object]:
        """Create one development account once, never replacing its password."""

        if self.settings.mode != "local":
            raise AuthUnavailable("Local bootstrap is not enabled.")
        if role not in {"admin", "member"}:
            raise AuthUnavailable("Local bootstrap role is invalid.")
        normalized = _safe_username(username)
        existing = self.store.auth_get_user_by_username(normalized)
        if existing is not None:
            expected_role = role
            if (
                existing.get("role") != expected_role
                or existing.get("status", "active") not in {"active", "enabled"}
                or not bool(existing.get("active", True))
                or (role == "admin" and existing.get("id") != 1)
            ):
                raise AuthUnavailable(
                    "The development bootstrap identity does not match its configured role."
                )
            password_hash = existing.get("password_hash")
            if not isinstance(password_hash, str) or not verify_password(password, password_hash):
                raise AuthUnavailable(
                    "The development bootstrap identity does not match its configured password."
                )
            return existing
        password_hash = hash_password(password)
        if role == "admin":
            claimed = self.store.auth_claim_legacy_owner(
                {
                    "login": normalized,
                    "display_name": normalized,
                    "claimed_at": _iso(now.astimezone(UTC)),
                    "password_hash": password_hash,
                    "github_user_id": None,
                    "email": None,
                }
            )
            if claimed is not None:
                return claimed
            inner = self.store.inner if isinstance(self.store, AuthStoreAdapter) else self.store
            if not isinstance(inner, MemoryAuthStore):
                raise AuthUnavailable("The reserved legacy owner cannot be claimed safely.")
        created = self.store.auth_create_user(
            {
                "username": normalized,
                "password_hash": password_hash,
                "role": role,
                "status": "active",
                "active": True,
                # Local bootstrap accounts are development-only password identities. The
                # passkey requirement is attached to invited GitHub identities in production;
                # local administrators still use passkeys for explicit backup step-up checks.
                "passkey_required": False,
                "passkey_enrolled": False,
                "created_at": _iso(now.astimezone(UTC)),
            }
        )
        return created

    def issue_session(
        self,
        user: UserRecord,
        now: datetime,
        auth_method: Literal["local", "github", "passkey"],
        *,
        mfa_method: Literal["none", "totp", "passkey", "recovery"] = "none",
        mfa_verified_at: datetime | None = None,
        expected_factor_id: int | None = None,
        origin_token_hash: str | None = None,
        revoke_other_sessions: bool = False,
    ) -> SessionIssue:
        """Create one server-side session while returning raw tokens only once."""

        if not user.active:
            raise AuthenticationRequired()
        if mfa_method not in {"none", "totp", "passkey", "recovery"}:
            raise AuthUnavailable("Account security state is invalid.")
        if self.settings.mode == "github" and (auth_method == "passkey" or mfa_method == "passkey"):
            raise AuthorizationDenied("Passkeys are no longer accepted; use an authenticator code.")
        if mfa_method in {"totp", "recovery"} and type(expected_factor_id) is not int:
            raise AuthUnavailable("Account security state is invalid.")
        if mfa_method not in {"totp", "recovery"} and expected_factor_id is not None:
            raise AuthUnavailable("Account security state is invalid.")
        if origin_token_hash is not None and not re_full_hex(origin_token_hash):
            raise AuthUnavailable("Account security state is invalid.")
        if revoke_other_sessions and origin_token_hash is None:
            raise AuthUnavailable("Account security state is invalid.")
        session_token = secrets.token_urlsafe(MAX_SESSION_TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(32)
        token_hash = _hash_secret(session_token)
        csrf_hash = _hash_secret(csrf_token)
        created = now.astimezone(UTC)
        expires = created + timedelta(seconds=self.settings.session_max_seconds)
        idle = created + timedelta(seconds=self.settings.session_idle_seconds)
        session_id = secrets.token_hex(16)
        verified_at = (mfa_verified_at or created).astimezone(UTC) if mfa_method != "none" else None
        stored = self.store.auth_create_session(
            {
                "session_id": session_id,
                "user_id": user.id,
                "token_hash": token_hash,
                "csrf_token_hash": csrf_hash,
                "auth_method": auth_method,
                "created_at": _iso(created),
                "last_seen_at": _iso(created),
                "idle_expires_at": _iso(idle),
                "expires_at": _iso(expires),
                "last_passkey_at": _iso(created) if auth_method == "passkey" else None,
                # Schema v9 stores only assured TOTP or recovery sessions in the durable MFA
                # columns. Local development may still issue a passkey step-up session.
                "mfa_method": mfa_method if mfa_method in {"totp", "recovery"} else None,
                "mfa_verified_at": _iso(verified_at)
                if verified_at is not None and mfa_method in {"totp", "recovery"}
                else None,
                "mfa_factor_id": expected_factor_id,
                "expected_factor_id": expected_factor_id,
                "origin_token_hash": origin_token_hash,
                "revoke_other_sessions": revoke_other_sessions,
            }
        )
        if (mfa_method in {"totp", "recovery"} or origin_token_hash is not None) and not isinstance(
            stored, Mapping
        ):
            # A generation/live-origin guarded insert must fail closed.  A legacy store that
            # silently drops those guards must never be allowed to mint an assured session.
            raise TotpRejected("The authenticator state changed. Try the current code again.")
        if isinstance(stored, Mapping):
            stored_id = stored.get("session_id", stored.get("id"))
            if isinstance(stored_id, str | int):
                session_id = str(stored_id)
        if auth_method == "passkey" or mfa_method == "passkey":
            self._step_up_sessions[token_hash] = (user.id, created)
        context = AuthContext(
            user,
            session_id,
            token_hash,
            csrf_hash,
            auth_method,
            mfa_method,
            verified_at,
            expected_factor_id,
        )
        return SessionIssue(session_token, csrf_token, context, expires)

    def authenticate(self, session_token: str | None, now: datetime) -> AuthContext:
        """Resolve a cookie value against its hash and enforce idle and absolute expiry."""

        if not session_token or len(session_token) > 256:
            raise AuthenticationRequired()
        token_hash = _hash_secret(session_token)
        current = now.astimezone(UTC)
        record = self.store.auth_get_session(token_hash, now=current)
        if record is None:
            raise AuthenticationRequired()
        if record.get("revoked_at") is not None:
            raise AuthenticationRequired()
        expires = _utc(record.get("expires_at"))
        idle_expires = _utc(record.get("idle_expires_at"))
        if current >= expires or current >= idle_expires:
            self.store.auth_revoke_session(token_hash, _iso(current))
            self._step_up_sessions.pop(token_hash, None)
            raise AuthenticationRequired()
        user_record = self.store.auth_get_user_by_id(int(record["user_id"]))
        if user_record is None:
            raise AuthenticationRequired()
        if self.settings.mode == "github" and (
            record.get("auth_method") == "passkey"
            or record.get("mfa_method") == "passkey"
            or record.get("last_passkey_at") is not None
        ):
            # Migration v10 revokes these rows durably. Keep the request boundary fail-closed
            # for either legacy marker if an old session reaches a process before migration or
            # during a restart race.
            self.store.auth_revoke_session(token_hash, _iso(current))
            raise AuthenticationRequired()
        user = self.user_from_record(user_record)
        if not user.active:
            raise AuthenticationRequired()
        idle = min(current + timedelta(seconds=self.settings.session_idle_seconds), expires)
        self.store.auth_touch_session(
            token_hash, {"last_seen_at": _iso(current), "idle_expires_at": _iso(idle)}
        )
        raw_session_id = record.get("session_id")
        csrf_hash = record.get("csrf_token_hash")
        auth_method = record.get("auth_method", "local")
        mfa_method = record.get("mfa_method") or "none"
        if mfa_method == "none" and record.get("auth_method") == "passkey":
            mfa_method = "passkey"
        if auth_method == "passkey" and self.settings.mode == "local":
            # Development passkey sessions retain the local step-up behavior; production legacy
            # passkey sessions are rejected by the fail-closed guard above.
            auth_method = "local"
        mfa_verified_at_value = record.get("mfa_verified_at")
        mfa_verified_at = _utc(mfa_verified_at_value) if mfa_verified_at_value is not None else None
        if not isinstance(raw_session_id, str) or not isinstance(csrf_hash, str):
            raise AuthUnavailable("Account security state is invalid.")
        if auth_method not in {"local", "github"}:
            raise AuthUnavailable("Account security state is invalid.")
        if mfa_method not in {"none", "totp", "passkey", "recovery"}:
            raise AuthUnavailable("Account security state is invalid.")
        mfa_factor_id: int | None = None
        if mfa_method in {"totp", "recovery"}:
            factor = self.store.auth_get_totp_factor(user.id)
            mfa_factor_id = self._factor_id(factor)
            stored_factor_id = record.get("mfa_factor_id")
            if mfa_factor_id is None or stored_factor_id != mfa_factor_id:
                # A factor replacement revokes old sessions, but this second check protects
                # stores that return a row during the replacement race from treating an old
                # factor marker as an assured session.
                self.store.auth_revoke_session(token_hash, _iso(current))
                raise AuthenticationRequired()
        return AuthContext(
            user,
            raw_session_id,
            token_hash,
            csrf_hash,
            cast(Literal["local", "github"], auth_method),
            cast(Literal["none", "totp", "passkey", "recovery"], mfa_method),
            mfa_verified_at,
            mfa_factor_id,
        )

    def require_csrf(self, context: AuthContext, csrf_token: str | None) -> None:
        """Require the request header token to match the hash bound to its session."""

        if not csrf_token or len(csrf_token) > 256:
            raise CsrfRejected()
        if not hmac.compare_digest(_hash_secret(csrf_token), context.csrf_token_hash):
            raise CsrfRejected()

    def require_role(self, context: AuthContext, role: UserRole) -> None:
        """Require an active account with the requested role."""

        if context.user.role != role and role == "admin":
            raise AuthorizationDenied()

    def logout(self, context: AuthContext, now: datetime) -> None:
        """Revoke one session without exposing its token hash to the caller."""

        self.store.auth_revoke_session(context.token_hash, _iso(now.astimezone(UTC)))
        self._step_up_sessions.pop(context.token_hash, None)

    def revoke_all_sessions(self, user_id: int, now: datetime) -> None:
        """Revoke every session after a password, passkey, role, or restore change."""

        self.store.auth_revoke_all_sessions(user_id, _iso(now.astimezone(UTC)))
        for token_hash, (owner_id, _) in list(self._step_up_sessions.items()):
            if owner_id == user_id:
                del self._step_up_sessions[token_hash]

    def has_recent_step_up(self, context: AuthContext, now: datetime, max_age: int = 300) -> bool:
        """Return true only for a session with a recent TOTP verification."""

        if self.settings.mode == "local" and context.mfa_method == "passkey":
            marker = self._step_up_sessions.get(context.token_hash)
            if marker is None or marker[0] != context.user.id:
                return False
            return now.astimezone(UTC) - marker[1] <= timedelta(seconds=max_age)
        if context.mfa_method != "totp" or context.mfa_verified_at is None:
            return False
        age = now.astimezone(UTC) - context.mfa_verified_at
        return not (age < timedelta(0) or age > timedelta(seconds=max_age))

    def has_totp_factor(self, user_id: int) -> bool:
        """Return whether an account has an active authenticator factor."""

        factor = self.store.auth_get_totp_factor(user_id)
        return isinstance(factor, Mapping) and factor.get("revoked_at") is None

    def can_enroll_totp(self, context: AuthContext, now: datetime | None = None) -> bool:
        """Return whether this session may begin or complete factor enrollment."""

        if not context.user.active:
            return False
        has_factor = self.has_totp_factor(context.user.id)
        if has_factor:
            if context.mfa_method == "recovery":
                return True
            return context.mfa_method == "totp" and self.has_recent_step_up(
                context, now or datetime.now(UTC)
            )
        if context.mfa_method == "recovery":
            return True
        if self.settings.mode == "github":
            # GitHub identity proof is the only bootstrap for a new authenticator. A legacy
            # passkey flag is deliberately ignored after the v10 retirement migration.
            return context.auth_method == "github" and context.mfa_method == "none"
        if context.user.passkey_enrolled:
            return context.mfa_method == "passkey"
        if context.mfa_method == "passkey":
            return False
        return context.auth_method in {"github", "local"}

    def _email_hash(self, email: str) -> str:
        """HMAC a canonical mailbox with the stable auth key so storage hides recipients."""

        from stock_probs.invitation_mail import validate_email_address

        canonical = validate_email_address(email).lower()
        return hmac.new(
            self.settings.session_secret.encode("utf-8"),
            b"signal-ledger:invitation-email:v1\0" + canonical.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def create_invitation(
        self,
        github_id: int | None,
        invited_by: int,
        now: datetime,
        *,
        github_login: str | None = None,
        email: str | None = None,
    ) -> tuple[str, Mapping[str, object]]:
        """Create a single-use GitHub-ID or verified-email invitation."""

        if self.settings.mode != "github":
            raise AuthUnavailable("GitHub invitations are not enabled.")
        if (github_id is None) == (email is None):
            raise ValueError("exactly one invitation identity must be set")
        bounded_id = _safe_github_id(github_id) if github_id is not None else None
        if github_login is not None and bounded_id is None:
            raise ValueError("github_login requires a GitHub ID invitation")
        email_hash = self._email_hash(email) if email is not None else None
        code = secrets.token_urlsafe(32)
        issued = now.astimezone(UTC)
        expires = issued + timedelta(seconds=self.settings.invitation_ttl_seconds)
        result = self.store.auth_create_invitation(
            {
                "code_hash": _hash_secret(code),
                "github_id": bounded_id,
                "github_login": github_login,
                "email_hash": email_hash,
                "invited_by": invited_by,
                "created_at": _iso(issued),
                "expires_at": _iso(expires),
            }
        )
        return code, result

    def consume_invitation(self, code: str, now: datetime) -> Mapping[str, object]:
        """Consume an invitation atomically and reject malformed codes uniformly."""

        if not 20 <= len(code) <= 128 or not code.isascii():
            raise InvitationRejected()
        result = self.store.auth_consume_invitation(_hash_secret(code), _iso(now.astimezone(UTC)))
        if result is None:
            raise InvitationRejected()
        expires = _utc(result.get("expires_at"))
        if expires <= now.astimezone(UTC):
            raise InvitationRejected()
        return result

    def inspect_invitation(self, code: str, now: datetime) -> Mapping[str, object]:
        """Validate an invitation without consuming it before OAuth identity proof."""

        if not 20 <= len(code) <= 128 or not code.isascii():
            raise InvitationRejected()
        result = self.store.auth_get_invitation(_hash_secret(code))
        if (
            result is None
            or result.get("consumed_at", result.get("redeemed_at", result.get("used_at")))
            is not None
        ):
            raise InvitationRejected()
        expires = _utc(result.get("expires_at"))
        if expires <= now.astimezone(UTC):
            raise InvitationRejected()
        return result

    def redeem_invitation_hash(
        self,
        code_hash: str,
        now: datetime,
        *,
        github_id: int,
        verified_email_hashes: Sequence[str],
        github_login: str,
    ) -> Mapping[str, object]:
        """Bind and consume an invitation only after numeric-ID or verified-email proof."""

        if len(code_hash) != 64 or not re_full_hex(code_hash):
            raise InvitationRejected()
        github_id = _safe_github_id(github_id)
        if not isinstance(github_login, str) or not 1 <= len(github_login) <= 100:
            raise InvitationRejected()
        if (
            isinstance(verified_email_hashes, str | bytes)
            or not isinstance(verified_email_hashes, Sequence)
            or len(verified_email_hashes) > 99
        ):
            raise InvitationRejected()
        email_hashes: list[str] = []
        for email_hash in verified_email_hashes:
            if not isinstance(email_hash, str) or not re_full_hex(email_hash):
                raise InvitationRejected()
            email_hashes.append(email_hash)
        result = self.store.auth_redeem_invitation(
            code_hash,
            _iso(now.astimezone(UTC)),
            github_id,
            tuple(email_hashes),
            github_login,
        )
        if result is None:
            raise InvitationRejected()
        expires = _utc(result.get("expires_at"))
        if expires <= now.astimezone(UTC):
            raise InvitationRejected()
        return result

    def inspect_invitation_hash(self, code_hash: str, now: datetime) -> Mapping[str, object]:
        """Read invitation identity before consuming it, preventing wrong-account burns."""

        if len(code_hash) != 64 or not re_full_hex(code_hash):
            raise InvitationRejected()
        result = self.store.auth_get_invitation(code_hash)
        if (
            result is None
            or result.get("consumed_at", result.get("redeemed_at", result.get("used_at")))
            is not None
        ):
            raise InvitationRejected()
        expires = _utc(result.get("expires_at"))
        if expires <= now.astimezone(UTC):
            raise InvitationRejected()
        return result

    def begin_github(
        self,
        now: datetime,
        *,
        caller_identity: str,
        invitation_code: str | None = None,
    ) -> GithubAuthorization:
        """Generate OAuth state and PKCE verifier stored on the server."""

        if self.settings.mode != "github" or not self.settings.github_client_id:
            raise AuthUnavailable("GitHub sign-in is not configured.")
        if not isinstance(caller_identity, str) or not 1 <= len(caller_identity) <= 253:
            raise AuthUnavailable("GitHub sign-in is temporarily unavailable.")
        issued = now.astimezone(UTC)
        caller_key_hash = hmac.new(
            self.settings.session_secret.encode("utf-8"),
            b"signal-ledger:github-oauth-caller:v1\0" + caller_identity.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        with self._oauth_start_lock:
            cutoff = issued - OAUTH_START_WINDOW
            self._oauth_start_times = [
                (caller_hash, started)
                for caller_hash, started in self._oauth_start_times
                if started > cutoff
            ]
            caller_starts = sum(
                caller_hash == caller_key_hash for caller_hash, _ in self._oauth_start_times
            )
            if caller_starts >= MAX_OAUTH_STARTS_PER_CALLER_WINDOW:
                raise OAuthStartLimited()
            if len(self._oauth_start_times) >= MAX_OAUTH_STARTS_PER_WINDOW:
                raise AuthUnavailable("GitHub sign-in is temporarily unavailable.")
            state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
            expires = issued + timedelta(seconds=self.settings.oauth_state_ttl_seconds)
            redirect = self.settings.github_redirect_uri
            if not redirect:
                raise AuthUnavailable("GitHub sign-in is not configured.")
            stored = self.store.auth_store_oauth_state(
                {
                    "state_hash": _hash_secret(state),
                    "code_verifier": verifier,
                    "redirect_uri": redirect,
                    "invitation_code_hash": (
                        _hash_secret(invitation_code)
                        if invitation_code and 20 <= len(invitation_code) <= 128
                        else None
                    ),
                    "caller_key_hash": caller_key_hash,
                    "created_at": _iso(issued),
                    "expires_at": _iso(expires),
                }
            )
            # Persistence owns the cross-restart outstanding-state limit. A refusal still
            # counts as a caller attempt so a client cannot turn rejected starts into a DB loop.
            self._oauth_start_times.append((caller_key_hash, issued))
            if not stored:
                raise OAuthStartLimited()
        query = httpx.QueryParams(
            {
                "client_id": self.settings.github_client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": "read:user user:email",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return GithubAuthorization(
            f"https://github.com/login/oauth/authorize?{query}", state, verifier
        )

    def finish_github(
        self,
        code: str,
        state: str,
        now: datetime,
        *,
        browser_transaction: str | None = None,
    ) -> GithubIdentity:
        """Consume a browser-bound OAuth state and validate the stable GitHub ID."""

        if self.settings.mode != "github" or not self.settings.github_client_id:
            raise AuthUnavailable("GitHub sign-in is not configured.")
        if not 8 <= len(code) <= 512 or not 16 <= len(state) <= 256:
            raise OAuthRejected()
        # The OAuth state is also the one-time browser transaction secret.  Its only durable
        # representation is the state hash stored with the PKCE verifier; the raw value is held
        # in an HttpOnly SameSite cookie for this browser and consumed with the state below.
        if (
            not isinstance(browser_transaction, str)
            or not 16 <= len(browser_transaction) <= 256
            or not browser_transaction.isascii()
            or not hmac.compare_digest(_hash_secret(state), _hash_secret(browser_transaction))
        ):
            raise OAuthRejected()
        state_record = self.store.auth_consume_oauth_state(
            _hash_secret(state), _iso(now.astimezone(UTC))
        )
        if state_record is None:
            raise OAuthRejected()
        expires = _utc(state_record.get("expires_at"))
        if expires <= now.astimezone(UTC):
            raise OAuthRejected()
        verifier = state_record.get("code_verifier")
        redirect = state_record.get("redirect_uri")
        if not isinstance(verifier, str) or not isinstance(redirect, str):
            raise OAuthRejected()
        invitation_code_hash = _optional_text(state_record.get("invitation_code_hash"))
        email_bound_invitation = False
        if invitation_code_hash is not None:
            invitation = self.inspect_invitation_hash(invitation_code_hash, now)
            stored_email_hash = invitation.get("email_hash")
            email_bound_invitation = stored_email_hash is not None
            if email_bound_invitation and (
                not isinstance(stored_email_hash, str) or not re_full_hex(stored_email_hash)
            ):
                raise InvitationRejected()
        client = self.http_client or httpx.Client(timeout=8.0, follow_redirects=False)
        close_client = self.http_client is None
        verified_email_hashes: tuple[str, ...] = ()
        try:
            token_response = client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret or "",
                    "code": code,
                    "redirect_uri": redirect,
                    "code_verifier": verifier,
                },
                timeout=8.0,
                follow_redirects=False,
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            if not isinstance(token_payload, Mapping):
                raise OAuthRejected()
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str) or not 1 <= len(access_token) <= 512:
                raise OAuthRejected()
            profile = client.get(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=8.0,
                follow_redirects=False,
            )
            profile.raise_for_status()
            value = profile.json()
            if not isinstance(value, Mapping):
                raise OAuthRejected()
            if email_bound_invitation:
                email_response = client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    params={"per_page": 100, "page": 1},
                    timeout=8.0,
                    follow_redirects=False,
                )
                email_response.raise_for_status()
                if len(email_response.content) > 64 * 1024:
                    raise OAuthRejected()
                records = email_response.json()
                if (
                    not isinstance(records, list)
                    or len(records) >= 100
                    or "next" in email_response.headers.get("link", "").lower()
                ):
                    raise OAuthRejected()
                verified_hashes: list[str] = []
                from stock_probs.invitation_mail import validate_email_address

                for record in records:
                    if (
                        not isinstance(record, Mapping)
                        or not isinstance(record.get("email"), str)
                        or type(record.get("verified")) is not bool
                    ):
                        raise OAuthRejected()
                    canonical_email = validate_email_address(record["email"]).lower()
                    if record["verified"] is True:
                        verified_hashes.append(self._email_hash(canonical_email))
                verified_email_hashes = tuple(verified_hashes)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, OAuthRejected):
            raise OAuthRejected() from None
        finally:
            if close_client:
                client.close()
        github_id = value.get("id")
        login = value.get("login")
        email = value.get("email")
        if type(github_id) is not int or not isinstance(login, str) or not login:
            raise OAuthRejected()
        return GithubIdentity(
            _safe_github_id(github_id),
            login[:100],
            email if isinstance(email, str) else None,
            invitation_code_hash,
            verified_email_hashes,
        )

    def totp_status(
        self, context_or_user: AuthContext | UserRecord, now: datetime
    ) -> dict[str, object]:
        """Return factor capability metadata without exposing secrets or recovery material."""

        context = (
            context_or_user
            if isinstance(context_or_user, AuthContext)
            else AuthContext(context_or_user, "status", "status", "status", "github")
        )
        user = context.user
        factor = self.store.auth_get_totp_factor(user.id)
        pending = self.store.auth_get_totp_enrollment(user.id, _iso(now.astimezone(UTC)))
        status = self.store.auth_get_recovery_code_status(user.id)
        remaining = int(status.get("available_count", 0) or 0)
        enrolled = isinstance(factor, Mapping) and factor.get("revoked_at") is None
        return {
            "enrolled": enrolled,
            "enrollment_pending": isinstance(pending, Mapping),
            "recovery_codes_remaining": remaining,
            "requires_totp": self.settings.mode == "github",
            "can_enroll": self.can_enroll_totp(context),
        }

    def begin_totp_enrollment(
        self, context: AuthContext, now: datetime, *, replace: bool = False
    ) -> dict[str, object]:
        """Create or reuse a short-lived encrypted enrollment secret for the current account."""

        issued = now.astimezone(UTC)
        if type(replace) is not bool:
            raise ValueError("replace must be a boolean")
        if not self.can_enroll_totp(context, issued):
            raise AuthorizationDenied("Complete the current authenticator check before enrolling.")
        if self.has_totp_factor(context.user.id) and context.mfa_method not in {"totp", "recovery"}:
            raise AuthorizationDenied(
                "A fresh authenticator check is required before replacing it."
            )
        expires = issued + timedelta(seconds=self.settings.totp_enrollment_ttl_seconds)
        secret = generate_secret()
        ciphertext = encrypt_secret(secret, self.settings.session_secret, user_id=context.user.id)
        current_factor = self.store.auth_get_totp_factor(context.user.id)
        expected_factor_id = self._factor_id(current_factor)
        begun = self.store.auth_begin_totp_enrollment(
            context.user.id,
            ciphertext,
            _iso(issued),
            _iso(expires),
            expected_factor_id,
            context.token_hash,
            replace,
        )
        if not isinstance(begun, Mapping):
            raise TotpRejected("The authenticator state changed. Start again.")
        if (
            begun.get("user_id") != context.user.id
            or begun.get("expected_factor_id") != expected_factor_id
            or begun.get("origin_token_hash") != context.token_hash
        ):
            raise TotpRejected("The authenticator state changed. Start again.")
        secret = self._pending_secret(context.user.id, begun)
        try:
            pending_expires = _utc(begun.get("expires_at"))
        except AuthUnavailable:
            raise AuthUnavailable("Authenticator enrollment state is invalid.") from None
        if pending_expires <= issued:
            raise TotpRejected("The authenticator enrollment has expired. Start again.")
        account = context.user.github_login or context.user.username or str(context.user.id)
        return {
            "enrollment": True,
            "secret": secret,
            "otpauth_uri": otpauth_uri(secret, account, self.settings.totp_issuer),
            "expires_at": pending_expires,
        }

    def finish_totp_enrollment(
        self, context: AuthContext, code: str, now: datetime
    ) -> tuple[SessionIssue, list[str]]:
        """Verify a pending code, activate TOTP, rotate sessions, and issue recovery codes."""

        current = now.astimezone(UTC)
        if not self.can_enroll_totp(context, current):
            raise AuthorizationDenied("Complete the current authenticator check before enrolling.")
        pending = self.store.auth_get_totp_enrollment(context.user.id, _iso(current))
        if not isinstance(pending, Mapping):
            raise TotpRejected("The authenticator enrollment has expired. Start again.")
        secret = self._pending_secret(context.user.id, pending)
        accepted_step = self._match_pending_totp(
            context.user.id,
            secret,
            code,
            current,
            pending.get("expected_factor_id"),
        )
        expected_ciphertext = pending.get("secret_ciphertext", pending.get("ciphertext"))
        if not isinstance(expected_ciphertext, str):
            raise AuthUnavailable("Authenticator enrollment state is invalid.")
        if "expected_factor_id" not in pending or "origin_token_hash" not in pending:
            raise AuthUnavailable("Authenticator enrollment state is invalid.")
        recovery_codes = generate_recovery_codes(RECOVERY_CODE_COUNT)
        pending_factor_id = pending.get("expected_factor_id")
        if pending_factor_id is not None and type(pending_factor_id) is not int:
            raise AuthUnavailable("Authenticator enrollment state is invalid.")
        confirmed = self.store.auth_confirm_totp_enrollment(
            context.user.id,
            _iso(current),
            expected_ciphertext,
            accepted_step,
            [hash_recovery_code(code_value) for code_value in recovery_codes],
            _iso(current),
            pending_factor_id,
            context.token_hash,
        )
        if confirmed is None:
            raise TotpRejected("The authenticator enrollment changed. Start again.")
        factor_id = self._factor_id(confirmed)
        if factor_id is None:
            raise AuthUnavailable("Authenticator factor state is invalid.")
        self.store.auth_record_totp_attempt(context.user.id, _iso(current), successful=True)
        user = replace(context.user, totp_enrolled=True, passkey_required=False)
        issue = self.issue_session(
            user,
            current,
            "github",
            mfa_method="totp",
            expected_factor_id=factor_id,
            origin_token_hash=context.token_hash,
        )
        return issue, recovery_codes

    def verify_totp(self, context: AuthContext, code: str, now: datetime) -> SessionIssue:
        """Verify an active authenticator code and issue a fresh TOTP-assured session."""

        if not self.has_totp_factor(context.user.id):
            raise TotpRequired("Enroll an authenticator before verifying a code.")
        current = now.astimezone(UTC)
        factor, secret, factor_id = self._factor_snapshot(context.user.id)
        del factor
        self._verify_totp_secret(context.user.id, secret, code, current, factor_id)
        # A normal sign-in upgrades only the provisional browser session. Other verified devices
        # remain active so authenticator login works across multiple devices.
        user = replace(context.user, totp_enrolled=True, passkey_required=False)
        issue = self.issue_session(
            user,
            current,
            "github",
            mfa_method="totp",
            expected_factor_id=factor_id,
            origin_token_hash=context.token_hash,
        )
        # The repository's guarded insert checked that this origin was live. Revoke it only
        # after the new assured session exists; factor replacement still revokes both atomically.
        self.store.auth_revoke_session(context.token_hash, _iso(current))
        self._step_up_sessions.pop(context.token_hash, None)
        return issue

    def step_up_totp(self, context: AuthContext, code: str, now: datetime) -> datetime:
        """Verify a fresh code and bind its five-minute proof to the current session."""

        if context.mfa_method != "totp" or not self.has_totp_factor(context.user.id):
            raise TotpRequired()
        current = now.astimezone(UTC)
        factor, secret, factor_id = self._factor_snapshot(context.user.id)
        del factor
        self._verify_totp_secret(context.user.id, secret, code, current, factor_id)
        if not self.store.auth_set_session_mfa(
            context.token_hash, "totp", _iso(current), factor_id
        ):
            raise AuthUnavailable("The authenticator proof could not be recorded.")
        return current

    def recover_with_code(self, context: AuthContext, code: str, now: datetime) -> SessionIssue:
        """Consume one recovery code and issue a factor-replacement-only session."""

        if not self.has_totp_factor(context.user.id):
            raise TotpRequired("No active authenticator is available for recovery.")
        current = now.astimezone(UTC)
        try:
            code_hash = hash_recovery_code(code)
        except ValueError:
            raise TotpRejected() from None
        factor = self.store.auth_get_totp_factor(context.user.id)
        factor_id = self._factor_id(factor)
        if factor_id is None:
            raise TotpRequired("No active authenticator is available for recovery.")
        if not self._reserve_totp_attempt(context.user.id, current, factor_id):
            raise TotpThrottled()
        consumed = self.store.auth_consume_recovery_code(
            context.user.id, factor_id, code_hash, _iso(current)
        )
        if not consumed:
            raise TotpRejected()
        user = replace(context.user, totp_enrolled=True, passkey_required=False)
        issue = self.issue_session(
            user,
            current,
            "github",
            mfa_method="recovery",
            expected_factor_id=factor_id,
            origin_token_hash=context.token_hash,
            revoke_other_sessions=True,
        )
        self.store.auth_record_totp_attempt(context.user.id, _iso(current), successful=True)
        return issue

    def rotate_recovery_codes(self, context: AuthContext, code: str, now: datetime) -> list[str]:
        """Replace recovery codes after a fresh authenticator verification."""

        if context.mfa_method != "totp" or not self.has_totp_factor(context.user.id):
            raise TotpRequired()
        current = now.astimezone(UTC)
        factor, secret, factor_id = self._factor_snapshot(context.user.id)
        del factor
        self._verify_totp_secret(context.user.id, secret, code, current, factor_id)
        recovery_codes = generate_recovery_codes(RECOVERY_CODE_COUNT)
        if not self.store.auth_create_recovery_codes(
            context.user.id,
            factor_id,
            [hash_recovery_code(code_value) for code_value in recovery_codes],
            _iso(current),
            context.token_hash,
        ):
            raise TotpRejected("The authenticator state changed. Try the current code again.")
        return recovery_codes

    def _pending_secret(self, user_id: int, record: Mapping[str, object]) -> str:
        """Decrypt one pending enrollment record, failing closed on key or row corruption."""

        ciphertext = record.get("secret_ciphertext", record.get("ciphertext"))
        if not isinstance(ciphertext, str):
            raise AuthUnavailable("Authenticator enrollment state is invalid.")
        try:
            return decrypt_secret(ciphertext, self.settings.session_secret, user_id=user_id)
        except ValueError as exc:
            raise AuthUnavailable("Authenticator enrollment state is invalid.") from exc

    @staticmethod
    def _factor_id(factor: Mapping[str, object] | None) -> int | None:
        """Read the durable factor generation used to bind every proof to one factor."""

        if not isinstance(factor, Mapping) or factor.get("revoked_at") is not None:
            return None
        value = factor.get("id", factor.get("factor_id", factor.get("generation")))
        return value if type(value) is int and value > 0 else None

    def _factor_snapshot(self, user_id: int) -> tuple[Mapping[str, object], str, int]:
        """Read and decrypt one factor together with its immutable generation marker."""

        factor = self.store.auth_get_totp_factor(user_id)
        factor_id = self._factor_id(factor)
        if factor_id is None or not isinstance(factor, Mapping):
            raise TotpRequired()
        return factor, self._pending_secret(user_id, factor), factor_id

    def _factor_secret(self, user_id: int) -> str:
        """Decrypt an active factor without returning its stored ciphertext."""

        _factor, secret, _factor_id = self._factor_snapshot(user_id)
        return secret

    def _verify_totp_secret(
        self,
        user_id: int,
        secret: str,
        code: str,
        now: datetime,
        expected_factor_id: int,
    ) -> int:
        """Apply durable throttling, skewed RFC 6238 validation, and replay prevention."""

        if not self._reserve_totp_attempt(user_id, now, expected_factor_id):
            raise TotpThrottled()
        step = matching_step(secret, code, now)
        if step is None:
            raise TotpRejected()
        if not self.store.auth_accept_totp_step(user_id, expected_factor_id, step, _iso(now)):
            raise TotpRejected("The authenticator state changed. Try the current code again.")
        self.store.auth_record_totp_attempt(user_id, _iso(now), successful=True)
        return step

    def _match_pending_totp(
        self,
        user_id: int,
        secret: str,
        code: str,
        now: datetime,
        expected_factor_id: int | None = None,
    ) -> int:
        """Validate a pending code before the repository atomically promotes its row."""

        if not self._reserve_totp_attempt(user_id, now, expected_factor_id):
            raise TotpThrottled()
        step = matching_step(secret, code, now)
        if step is None:
            raise TotpRejected()
        return step

    def _reserve_totp_attempt(
        self, user_id: int, now: datetime, expected_factor_id: int | None = None
    ) -> bool:
        """Atomically reserve a throttle slot before running TOTP verification crypto."""

        return self.store.auth_reserve_totp_attempt(
            user_id, _iso(now.astimezone(UTC)), expected_factor_id
        )

    def _totp_attempt_gate(self, user_id: int, now: datetime) -> Mapping[str, object]:
        """Read the durable lock state before parsing or verifying an attacker-controlled code."""

        return self.store.auth_check_totp_attempt(user_id, _iso(now.astimezone(UTC)))

    @staticmethod
    def _attempt_allowed(record: Mapping[str, object]) -> bool:
        """Accept only explicit allow values from the persistence throttle boundary."""

        return not (record.get("allowed") is False or record.get("locked") is True)

    def begin_passkey_registration(
        self, user: UserRecord, rp_id: str, origin: str
    ) -> dict[str, object]:
        """Return bounded WebAuthn creation options and retain the challenge server-side."""

        if not user.active:
            raise AuthenticationRequired()
        if self.settings.mode == "github":
            raise AuthorizationDenied("Passkeys are retired; use your authenticator code.")
        challenge = _b64(secrets.token_bytes(32))
        now = datetime.now(UTC)
        with self._challenge_lock:
            self._prune_challenges(now)
            self._challenges[challenge] = ("registration", user.id, now + MAX_PASSKEY_CHALLENGE_TTL)
        return {
            "publicKey": {
                "challenge": challenge,
                "rp": {"name": "Signal Ledger", "id": rp_id},
                "user": {
                    "id": _b64(str(user.id).encode()),
                    "name": user.username or user.github_login or str(user.id),
                    "displayName": user.github_login or user.username or "Signal Ledger user",
                },
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},
                    {"type": "public-key", "alg": -257},
                ],
                "timeout": 60_000,
                "attestation": "none",
                "authenticatorSelection": {
                    "residentKey": "preferred",
                    "userVerification": "required",
                },
            }
        }

    def finish_passkey_registration(
        self, user: UserRecord, response: Mapping[str, object], rp_id: str, origin: str
    ) -> PasskeyCredential:
        """Verify and persist one local-development passkey credential for an account."""

        if self.settings.mode == "github":
            raise AuthorizationDenied("Passkeys are retired; use your authenticator code.")

        challenge = self._consume_challenge("registration", user.id, response)
        credential = self.passkey_backend.verify_registration(
            response, challenge, user.id, rp_id, origin
        )
        if credential.user_id != user.id or not credential.credential_id:
            raise PasskeyRejected()
        self.store.auth_create_passkey(
            {
                "credential_id": credential.credential_id,
                "user_id": user.id,
                "public_key": credential.public_key,
                "sign_count": credential.sign_count,
                "transports": json.dumps(list(credential.transports), separators=(",", ":")),
                "created_at": _iso(datetime.now(UTC)),
            }
        )
        self.store.auth_update_user(user.id, {"passkey_enrolled": True})
        return credential

    def begin_passkey_assertion(self, user: UserRecord, rp_id: str) -> dict[str, object]:
        """Return assertion options for every enrolled credential on an account."""

        if self.settings.mode == "github":
            raise AuthorizationDenied("Passkeys are retired; use your authenticator code.")
        credentials = self.store.auth_get_passkeys(user.id)
        challenge = _b64(secrets.token_bytes(32))
        now = datetime.now(UTC)
        with self._challenge_lock:
            self._prune_challenges(now)
            self._challenges[challenge] = ("assertion", user.id, now + MAX_PASSKEY_CHALLENGE_TTL)
        allowed = [
            {
                "type": "public-key",
                "id": item["credential_id"],
                "transports": list(_stored_passkey_transports(item.get("transports", []))),
            }
            for item in credentials
            if item.get("revoked_at") is None and isinstance(item.get("credential_id"), str)
        ]
        return {
            "publicKey": {
                "challenge": challenge,
                "rpId": rp_id,
                "timeout": 60_000,
                "userVerification": "required",
                "allowCredentials": allowed,
            }
        }

    def finish_passkey_assertion(
        self,
        user: UserRecord,
        response: Mapping[str, object],
        rp_id: str,
        origin: str,
        now: datetime,
    ) -> SessionIssue:
        """Verify a legacy assertion and issue only a factor-migration session."""

        if self.settings.mode == "github":
            raise AuthorizationDenied("Passkeys are retired; use your authenticator code.")

        challenge = self._consume_challenge("assertion", user.id, response)
        credential_id = response.get("id")
        if not isinstance(credential_id, str) or len(credential_id) > 512:
            raise PasskeyRejected()
        record = self.store.auth_get_passkey(credential_id, user_id=user.id)
        if record is None or record.get("revoked_at") is not None:
            raise PasskeyRejected()
        stored_user_id = record.get("user_id")
        if stored_user_id != user.id or record.get("credential_id") != credential_id:
            raise PasskeyRejected()
        transports = _stored_passkey_transports(record.get("transports", []))
        public_key = record.get("public_key")
        sign_count = record.get("sign_count", 0)
        if not isinstance(public_key, str) or type(sign_count) is not int or sign_count < 0:
            raise PasskeyRejected()
        credential = PasskeyCredential(credential_id, user.id, public_key, sign_count, transports)
        new_count = self.passkey_backend.verify_assertion(
            response, challenge, credential, rp_id, origin
        )
        if type(new_count) is not int or new_count < sign_count:
            raise PasskeyRejected()
        updated = self.store.auth_update_passkey(credential_id, {"sign_count": new_count})
        updated_count = updated.get("sign_count") if isinstance(updated, Mapping) else None
        if (
            not isinstance(updated, Mapping)
            or updated.get("credential_id") != credential_id
            or updated.get("user_id") != user.id
            or updated.get("revoked_at") is not None
            or type(updated_count) is not int
            or updated_count < new_count
        ):
            raise PasskeyRejected()
        return self.issue_session(user, now, "passkey", mfa_method="passkey")

    def _consume_challenge(
        self, kind: ChallengeKind, user_id: int, response: Mapping[str, object]
    ) -> str:
        raw_client_data = response.get("response")
        client_data: Mapping[str, object]
        if isinstance(raw_client_data, Mapping):
            encoded_client_data = raw_client_data.get("clientDataJSON")
            if isinstance(encoded_client_data, str):
                try:
                    decoded_client_data = json.loads(_b64decode(encoded_client_data))
                except (ValueError, TypeError, UnicodeError):
                    decoded_client_data = {}
                client_data = (
                    decoded_client_data if isinstance(decoded_client_data, Mapping) else {}
                )
            else:
                # Unit-test adapters may pass parsed client data; browser requests must use the
                # bounded encoded JSON branch above.
                client_data = raw_client_data
        else:
            client_data = {}
        challenge = client_data.get("challenge", response.get("challenge"))
        if not isinstance(challenge, str) or len(challenge) > 256:
            raise PasskeyRejected()
        now = datetime.now(UTC)
        with self._challenge_lock:
            value = self._challenges.pop(challenge, None)
            self._prune_challenges(now)
        if value is None or value[0] != kind or value[1] != user_id or value[2] <= now:
            raise PasskeyRejected()
        return challenge

    def _prune_challenges(self, now: datetime) -> None:
        for challenge, (_, _, expires) in list(self._challenges.items()):
            if expires <= now:
                del self._challenges[challenge]
        if len(self._challenges) > 128:
            for challenge in sorted(self._challenges, key=lambda key: self._challenges[key][2])[
                :64
            ]:
                del self._challenges[challenge]

    def clear_pending_challenges(self) -> None:
        """Invalidate browser ceremonies that were started before a database promotion."""

        with self._challenge_lock:
            self._challenges.clear()


class MemoryAuthStore:
    """Small deterministic store used by auth unit tests and local API smoke checks."""

    def __init__(self) -> None:
        self.users: dict[int, dict[str, object]] = {}
        self.sessions: dict[str, dict[str, object]] = {}
        self.invitations: dict[str, dict[str, object]] = {}
        self.oauth_states: dict[str, dict[str, object]] = {}
        self.passkeys: dict[str, dict[str, object]] = {}
        self.totp_enrollments: dict[int, dict[str, object]] = {}
        self.totp_factors: dict[int, dict[str, object]] = {}
        self.recovery_codes: dict[int, list[dict[str, object]]] = {}
        self.totp_attempts: dict[int, dict[str, object]] = {}
        self._totp_lock = threading.RLock()
        self._oauth_lock = threading.RLock()
        self._next_factor_id = 1
        self._next_user_id = 1

    def auth_get_user_by_id(self, user_id: int) -> Mapping[str, object] | None:
        return self.users.get(user_id)

    def auth_get_user_by_username(self, username: str) -> Mapping[str, object] | None:
        return next(
            (user for user in self.users.values() if user.get("username") == username), None
        )

    def auth_get_user_by_github_id(self, github_id: int) -> Mapping[str, object] | None:
        return next(
            (user for user in self.users.values() if user.get("github_id") == github_id), None
        )

    def auth_create_user(self, fields: Mapping[str, object]) -> Mapping[str, object]:
        user = {"id": self._next_user_id, "active": True, "passkey_required": True, **fields}
        self.users[self._next_user_id] = user
        self._next_user_id += 1
        return user

    def auth_update_user(
        self, user_id: int, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        user.update(fields)
        return user

    def auth_create_session(self, fields: Mapping[str, object]) -> Mapping[str, object] | None:
        """Create a session only while its factor and live origin still match."""

        with self._totp_lock:
            user_id = fields.get("user_id")
            token_hash = str(fields["token_hash"])
            expected_factor_id = fields.get("expected_factor_id")
            if expected_factor_id is not None:
                factor = self.totp_factors.get(user_id) if type(user_id) is int else None
                if self._factor_id(factor) != expected_factor_id:
                    return None
            origin_token_hash = fields.get("origin_token_hash")
            if origin_token_hash is not None:
                origin = self.sessions.get(origin_token_hash)
                if (
                    not isinstance(origin, Mapping)
                    or origin.get("user_id") != user_id
                    or origin.get("revoked_at") is not None
                ):
                    return None
            if fields.get("revoke_other_sessions") is True:
                if origin_token_hash is None:
                    return None
                for session in self.sessions.values():
                    if (
                        session.get("user_id") == user_id
                        and session.get("token_hash") != token_hash
                        and session.get("revoked_at") is None
                    ):
                        session["revoked_at"] = fields.get("created_at")
                        session["revocation_reason"] = "security-change"
            record = dict(fields)
            if expected_factor_id is not None:
                record["mfa_factor_id"] = expected_factor_id
            self.sessions[token_hash] = record
            if origin_token_hash is not None and fields.get("revoke_other_sessions") is not True:
                origin = self.sessions.get(origin_token_hash)
                if origin is not None and origin.get("revoked_at") is None:
                    origin["revoked_at"] = fields.get("created_at")
                    origin["revocation_reason"] = "mfa-upgrade"
            return record

    def auth_get_session(self, token_hash: str) -> Mapping[str, object] | None:
        return self.sessions.get(token_hash)

    def auth_touch_session(self, token_hash: str, fields: Mapping[str, object]) -> None:
        if token_hash in self.sessions:
            self.sessions[token_hash].update(fields)

    def auth_revoke_session(self, token_hash: str, revoked_at: str) -> None:
        with self._totp_lock:
            if token_hash in self.sessions:
                self.sessions[token_hash]["revoked_at"] = revoked_at

    def auth_revoke_all_sessions(self, user_id: int, revoked_at: str) -> None:
        with self._totp_lock:
            for session in self.sessions.values():
                if session.get("user_id") == user_id:
                    session["revoked_at"] = revoked_at

    def auth_create_invitation(self, fields: Mapping[str, object]) -> Mapping[str, object]:
        record = dict(fields)
        self.invitations[str(record["code_hash"])] = record
        return record

    def auth_consume_invitation(
        self, code_hash: str, consumed_at: str
    ) -> Mapping[str, object] | None:
        with self._oauth_lock:
            record = self.invitations.get(code_hash)
            if (
                record is None
                or record.get("consumed_at") is not None
                or record.get("used_at") is not None
                or record.get("github_id", record.get("github_user_id")) is None
            ):
                return None
            record["consumed_at"] = consumed_at
            record["used_at"] = consumed_at
            return record

    def auth_redeem_invitation(
        self,
        code_hash: str,
        redeemed_at: str,
        github_id: int,
        verified_email_hashes: Sequence[str],
        github_login: str,
    ) -> Mapping[str, object] | None:
        """Mirror the SQLite compare-bind-consume transaction for isolated auth tests."""

        with self._oauth_lock:
            record = self.invitations.get(code_hash)
            if (
                record is None
                or record.get("consumed_at") is not None
                or record.get("used_at") is not None
            ):
                return None
            try:
                if _utc(record.get("expires_at")) <= _utc(redeemed_at):
                    return None
            except AuthUnavailable:
                return None
            bound_id = record.get("github_id", record.get("github_user_id"))
            email_hash = record.get("email_hash")
            if bound_id is not None:
                if bound_id != github_id or email_hash is not None:
                    return None
            elif not isinstance(email_hash, str) or not any(
                hmac.compare_digest(email_hash, candidate) for candidate in verified_email_hashes
            ):
                return None
            record["github_id"] = github_id
            record["github_user_id"] = github_id
            record["github_login"] = record.get("github_login") or github_login
            record["consumed_at"] = redeemed_at
            record["used_at"] = redeemed_at
            return record

    def auth_get_invitation(self, code_hash: str) -> Mapping[str, object] | None:
        return self.invitations.get(code_hash)

    def auth_list_invitations(self) -> list[Mapping[str, object]]:
        """List invitation status without returning private email digests or bearer codes."""

        with self._oauth_lock:
            return [
                {
                    key: record.get(key)
                    for key in (
                        "id",
                        "github_id",
                        "github_login",
                        "invited_by",
                        "expires_at",
                        "consumed_at",
                        "used_at",
                        "created_at",
                    )
                }
                | {"email_bound": record.get("email_hash") is not None}
                for record in list(self.invitations.values())[-100:][::-1]
            ]

    def auth_store_oauth_state(self, fields: Mapping[str, object]) -> bool:
        """Apply the durable OAuth admission limits used by the SQLite implementation."""

        try:
            created_at = _utc(fields.get("created_at"))
            expires_at = _utc(fields.get("expires_at"))
        except AuthUnavailable:
            raise
        if expires_at <= created_at:
            raise ValueError("OAuth state must expire after creation")
        caller_key_hash = fields.get("caller_key_hash", UNATTRIBUTED_OAUTH_CALLER_KEY_HASH)
        if not isinstance(caller_key_hash, str) or not re_full_hex(caller_key_hash):
            raise ValueError("caller_key_hash is invalid")
        with self._oauth_lock:
            for state_hash, record in list(self.oauth_states.items()):
                try:
                    record_expiry = _utc(record.get("expires_at"))
                except AuthUnavailable:
                    del self.oauth_states[state_hash]
                    continue
                if record_expiry <= created_at or record.get("consumed_at") is not None:
                    del self.oauth_states[state_hash]
            pending = [
                record
                for record in self.oauth_states.values()
                if record.get("consumed_at") is None
                and record.get("caller_key_hash", UNATTRIBUTED_OAUTH_CALLER_KEY_HASH)
                == caller_key_hash
            ]
            if len(pending) >= MAX_PENDING_OAUTH_STATES_PER_CALLER:
                return False
            if len(self.oauth_states) >= MAX_PENDING_OAUTH_STATES:
                raise AuthUnavailable("GitHub sign-in capacity is temporarily full.")
            self.oauth_states[str(fields["state_hash"])] = dict(fields)
        return True

    def auth_consume_oauth_state(
        self, state_hash: str, consumed_at: str
    ) -> Mapping[str, object] | None:
        with self._oauth_lock:
            record = self.oauth_states.get(state_hash)
            if record is None or record.get("consumed_at") is not None:
                return None
            record["consumed_at"] = consumed_at
            return record

    def auth_create_passkey(self, fields: Mapping[str, object]) -> Mapping[str, object]:
        record = dict(fields)
        self.passkeys[str(record["credential_id"])] = record
        # Keep the deterministic test/local store's denormalized user projection in
        # sync with the credential side table.  Repository-backed users derive this
        # flag from their passkeys, while the memory store has no query layer to do
        # that reconciliation after a provisional GitHub session enrolls.
        user = self.users.get(int(record["user_id"]))
        if user is not None:
            user["passkey_enrolled"] = True
        return record

    def auth_get_passkeys(self, user_id: int) -> list[Mapping[str, object]]:
        return [
            item
            for item in self.passkeys.values()
            if item.get("user_id") == user_id and item.get("revoked_at") is None
        ]

    def auth_get_passkey(
        self, credential_id: str, *, user_id: int | None = None
    ) -> Mapping[str, object] | None:
        if user_id is None:
            return None
        record = self.passkeys.get(credential_id)
        if (
            record is None
            or record.get("user_id") != user_id
            or record.get("revoked_at") is not None
        ):
            return None
        return record

    def auth_update_passkey(
        self, credential_id: str, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        record = self.passkeys.get(credential_id)
        if record is None or record.get("revoked_at") is not None:
            return None
        current_count = record.get("sign_count", 0)
        new_count = fields.get("sign_count")
        if (
            type(current_count) is not int
            or type(new_count) is not int
            or new_count < current_count
        ):
            return None
        record.update(fields)
        return record

    def auth_begin_totp_enrollment(
        self,
        user_id: int,
        secret_ciphertext: str,
        created_at: str,
        expires_at: str,
        expected_factor_id: int | None,
        origin_token_hash: str,
        replace: bool = False,
    ) -> Mapping[str, object] | None:
        if type(replace) is not bool:
            raise ValueError("replace must be a boolean")
        created = _utc(created_at)
        expires = _utc(expires_at)
        if expires <= created or expires - created > timedelta(minutes=10):
            raise ValueError("TOTP enrollment must expire within 10 minutes")
        with self._totp_lock:
            factor = self.totp_factors.get(user_id)
            if self._factor_id(factor) != expected_factor_id:
                return None
            origin = self.sessions.get(origin_token_hash)
            if (
                not isinstance(origin, Mapping)
                or origin.get("user_id") != user_id
                or origin.get("revoked_at") is not None
                or not isinstance(origin.get("idle_expires_at"), str | datetime)
                or not isinstance(origin.get("expires_at"), str | datetime)
                or _utc(origin["idle_expires_at"]) <= created
                or _utc(origin["expires_at"]) <= created
            ):
                return None
            pending = self.totp_enrollments.get(user_id)
            if pending is not None and _utc(str(pending["expires_at"])) > created:
                same_binding = (
                    pending.get("expected_factor_id") == expected_factor_id
                    and pending.get("origin_token_hash") == origin_token_hash
                )
                if not replace:
                    if not same_binding:
                        return None
                    return pending
            record = {
                "user_id": user_id,
                "secret_ciphertext": secret_ciphertext,
                "created_at": created_at,
                "expires_at": expires_at,
                "expected_factor_id": expected_factor_id,
                "origin_token_hash": origin_token_hash,
            }
            self.totp_enrollments[user_id] = record
            return record

    def auth_get_totp_enrollment(
        self, user_id: int, now: str | None = None
    ) -> Mapping[str, object] | None:
        record = self.totp_enrollments.get(user_id)
        if record is None:
            return None
        if now is not None and _utc(record["expires_at"]) <= _utc(now):
            self.totp_enrollments.pop(user_id, None)
            return None
        return record

    def auth_confirm_totp_enrollment(
        self,
        user_id: int,
        confirmed_at: str,
        expected_secret_ciphertext: str,
        accepted_step: int,
        recovery_code_hashes: Sequence[str],
        revoked_at: str,
        expected_factor_id: int | None,
        origin_token_hash: str,
    ) -> Mapping[str, object] | None:
        with self._totp_lock:
            pending = self.totp_enrollments.get(user_id)
            current_factor_id = self._factor_id(self.totp_factors.get(user_id))
            origin = self.sessions.get(origin_token_hash)
            pending_factor_id = pending.get("expected_factor_id") if pending else None
        if (
            pending is None
            or pending.get("secret_ciphertext") != expected_secret_ciphertext
            or pending_factor_id != expected_factor_id
            or current_factor_id != expected_factor_id
            or not isinstance(origin, Mapping)
            or origin.get("user_id") != user_id
            or origin.get("revoked_at") is not None
            or type(accepted_step) is not int
            or accepted_step < 0
            or _utc(pending["expires_at"]) <= _utc(confirmed_at)
        ):
            return None
        with self._totp_lock:
            self.totp_enrollments.pop(user_id, None)
            factor = {
                "id": self._next_factor_id,
                "user_id": user_id,
                "secret_ciphertext": pending["secret_ciphertext"],
                "enrolled_at": confirmed_at,
                "last_totp_step": accepted_step,
                "revoked_at": None,
            }
            self._next_factor_id += 1
            self.totp_factors[user_id] = factor
            self.recovery_codes[user_id] = [
                {"code_hash": code_hash, "created_at": confirmed_at, "consumed_at": None}
                for code_hash in recovery_code_hashes
            ]
            enrolled_origin = pending.get("origin_token_hash")
            for session in self.sessions.values():
                if (
                    session.get("user_id") == user_id
                    and session.get("token_hash") != enrolled_origin
                    and session.get("revoked_at") is None
                ):
                    session["revoked_at"] = revoked_at
                    session["revocation_reason"] = "security-change"
            user = self.users.get(user_id)
            if user is not None:
                user["totp_enrolled"] = True
                user["passkey_required"] = False
        return factor

    def auth_get_totp_factor(self, user_id: int) -> Mapping[str, object] | None:
        factor = self.totp_factors.get(user_id)
        if factor is None or factor.get("revoked_at") is not None:
            return None
        return factor

    def auth_accept_totp_step(
        self, user_id: int, expected_factor_id: int, step: int, accepted_at: str
    ) -> bool:
        with self._totp_lock:
            factor = self.auth_get_totp_factor(user_id)
            if self._factor_id(factor) != expected_factor_id:
                return False
            previous = factor.get("last_totp_step", -1) if factor else -1
            if type(previous) is not int or type(step) is not int or step <= previous:
                return False
            factor["last_totp_step"] = step
            factor["last_used_at"] = accepted_at
            return True

    @staticmethod
    def _factor_id(factor: Mapping[str, object] | None) -> int | None:
        if not isinstance(factor, Mapping):
            return None
        value = factor.get("id", factor.get("factor_id", factor.get("generation")))
        return value if type(value) is int and value > 0 else None

    def auth_check_totp_attempt(self, user_id: int, attempted_at: str) -> Mapping[str, object]:
        record = self.totp_attempts.get(user_id)
        if record is None:
            return {"allowed": True, "failures": 0}
        locked_until = record.get("locked_until")
        if isinstance(locked_until, str) and _utc(locked_until) > _utc(attempted_at):
            return {"allowed": False, "locked": True, "locked_until": locked_until}
        return {"allowed": True, "failures": int(record.get("failures", 0))}

    def auth_record_totp_attempt(
        self,
        user_id: int,
        attempted_at: str,
        window_seconds: int = 300,
        max_attempts: int = 5,
        lockout_seconds: int = 900,
        successful: bool = False,
    ) -> Mapping[str, object]:
        current = _utc(attempted_at)
        if successful:
            self.totp_attempts.pop(user_id, None)
            return {"allowed": True, "failures": 0}
        record = self.totp_attempts.get(user_id)
        if (
            record is None
            or _utc(str(record["window_start"])) + timedelta(seconds=window_seconds) <= current
        ):
            record = {"window_start": attempted_at, "failures": 0, "locked_until": None}
            self.totp_attempts[user_id] = record
        record["failures"] = int(record.get("failures", 0)) + 1
        if int(record["failures"]) >= max_attempts:
            locked_until = current + timedelta(seconds=lockout_seconds)
            record["locked_until"] = _iso(locked_until)
            return {"allowed": False, "locked": True, "locked_until": _iso(locked_until)}
        return {"allowed": True, "failures": record["failures"]}

    def auth_reserve_totp_attempt(
        self, user_id: int, attempted_at: str, expected_factor_id: int | None = None
    ) -> bool:
        """Atomically reserve one bounded attempt before TOTP cryptographic verification."""

        current = _utc(attempted_at)
        with self._totp_lock:
            if (
                expected_factor_id is not None
                and self._factor_id(self.totp_factors.get(user_id)) != expected_factor_id
            ):
                return False
            record = self.totp_attempts.get(user_id)
            if record is not None:
                locked_until = record.get("locked_until")
                if isinstance(locked_until, str) and _utc(locked_until) > current:
                    return False
                if _utc(str(record["window_start"])) + timedelta(seconds=300) <= current:
                    record = None
            if record is None:
                record = {"window_start": attempted_at, "failures": 0, "locked_until": None}
                self.totp_attempts[user_id] = record
            failures = int(record.get("failures", 0)) + 1
            record["failures"] = failures
            if failures >= 5:
                record["locked_until"] = _iso(current + timedelta(seconds=900))
            return True

    def auth_create_recovery_codes(
        self,
        user_id: int,
        expected_factor_id: int,
        code_hashes: Sequence[str],
        created_at: str,
        origin_token_hash: str,
    ) -> bool:
        with self._totp_lock:
            if self._factor_id(self.totp_factors.get(user_id)) != expected_factor_id:
                return False
            origin = self.sessions.get(origin_token_hash)
            if (
                not isinstance(origin, Mapping)
                or origin.get("user_id") != user_id
                or origin.get("revoked_at") is not None
            ):
                return False
            self.recovery_codes[user_id] = [
                {"code_hash": code_hash, "created_at": created_at, "consumed_at": None}
                for code_hash in code_hashes
            ]
            return True

    def auth_consume_recovery_code(
        self, user_id: int, expected_factor_id: int, code_hash: str, consumed_at: str
    ) -> bool:
        with self._totp_lock:
            if self._factor_id(self.totp_factors.get(user_id)) != expected_factor_id:
                return False
            for record in self.recovery_codes.get(user_id, []):
                if record["code_hash"] == code_hash and record.get("consumed_at") is None:
                    record["consumed_at"] = consumed_at
                    return True
            return False

    def auth_get_recovery_code_status(self, user_id: int) -> Mapping[str, object]:
        records = self.recovery_codes.get(user_id, [])
        return {
            "user_id": user_id,
            "total_count": len(records),
            "available_count": sum(
                1
                for record in records
                if record.get("consumed_at") is None and record.get("revoked_at") is None
            ),
            "consumed_count": sum(1 for record in records if record.get("consumed_at") is not None),
            "revoked_count": sum(1 for record in records if record.get("revoked_at") is not None),
        }

    def auth_list_recovery_code_status(self, user_id: int) -> list[Mapping[str, object]]:
        """Retain the old inspection helper for compatibility with existing tests."""

        return [dict(record) for record in self.recovery_codes.get(user_id, [])]

    def auth_set_session_mfa(
        self, token_hash: str, method: str, verified_at: str, expected_factor_id: int
    ) -> bool:
        with self._totp_lock:
            session = self.sessions.get(token_hash)
            if session is None or session.get("revoked_at") is not None:
                return False
            if method not in {"totp", "recovery"}:
                return False
            if self._factor_id(self.totp_factors.get(session.get("user_id"))) != expected_factor_id:
                return False
            session["mfa_method"] = method
            session["mfa_verified_at"] = verified_at
            session["mfa_factor_id"] = expected_factor_id
            return True

    def auth_list_sessions(self, user_id: int) -> list[Mapping[str, object]]:
        return [item for item in self.sessions.values() if item.get("user_id") == user_id]

    def auth_revoke_session_by_id(self, user_id: int, session_id: str, revoked_at: str) -> None:
        for session in self.sessions.values():
            if session.get("user_id") == user_id and session.get("session_id") == session_id:
                session["revoked_at"] = revoked_at
