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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from inspect import Parameter, signature
from typing import Literal, Protocol, cast

import httpx

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

    def auth_get_invitation(self, code_hash: str) -> Mapping[str, object] | None: ...

    def auth_store_oauth_state(self, fields: Mapping[str, object]) -> None: ...

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

    def auth_store_oauth_state(self, fields: Mapping[str, object]) -> None:
        method = self._method("auth_store_oauth_state", "store_oauth_state", "create_oauth_state")
        self._invoke(
            method,
            {
                **fields,
                "created_at": self._datetime(fields.get("created_at"), "created_at"),
                "expires_at": self._datetime(fields.get("expires_at"), "expires_at"),
            },
        )

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
        return (
            [item for item in result if isinstance(item, Mapping)]
            if isinstance(result, list)
            else []
        )

    def auth_get_passkey(
        self, credential_id: str, *, user_id: int | None = None
    ) -> Mapping[str, object] | None:
        method = self._method("auth_get_passkey", "get_passkey")
        if user_id is None:
            raise AuthUnavailable("Passkey lookup requires an account binding.")
        result = method(credential_id, user_id=user_id)
        return result if isinstance(result, Mapping) else None

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
        if isinstance(result, Mapping):
            return result
        return {"credential_id": credential_id, **fields}

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
        }


@dataclass(frozen=True)
class AuthContext:
    """A validated request identity; raw session tokens never appear here."""

    user: UserRecord
    session_id: str
    token_hash: str
    csrf_token_hash: str
    auth_method: Literal["local", "github", "passkey"]


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
    """Coordinate account, session, invitation, OAuth, and passkey state."""

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
        self._oauth_start_times: list[datetime] = []
        # The persistence schema intentionally stores only opaque sessions and revocation state.
        # Keep the short-lived step-up marker process-local so a passkey response cannot be
        # replayed or promoted into a durable credential/session attribute.
        self._step_up_sessions: dict[str, tuple[int, datetime]] = {}

    @property
    def enabled(self) -> bool:
        """Return whether route protection is active."""

        return self.settings.mode != "disabled"

    def user_from_record(self, value: Mapping[str, object]) -> UserRecord:
        """Apply the deployment authentication policy to a persisted account row."""

        user = UserRecord.from_record(value)
        if self.settings.mode == "github" and not user.passkey_required:
            # Repository role metadata intentionally stays provider-neutral. Production GitHub
            # sessions always complete a UV passkey ceremony, including the designated owner.
            user = replace(user, passkey_required=True)
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
    ) -> SessionIssue:
        """Create one server-side session while returning raw tokens only once."""

        if not user.active:
            raise AuthenticationRequired()
        session_token = secrets.token_urlsafe(MAX_SESSION_TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(32)
        token_hash = _hash_secret(session_token)
        csrf_hash = _hash_secret(csrf_token)
        created = now.astimezone(UTC)
        expires = created + timedelta(seconds=self.settings.session_max_seconds)
        idle = created + timedelta(seconds=self.settings.session_idle_seconds)
        session_id = secrets.token_hex(16)
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
            }
        )
        if isinstance(stored, Mapping):
            stored_id = stored.get("session_id", stored.get("id"))
            if isinstance(stored_id, str | int):
                session_id = str(stored_id)
        if auth_method == "passkey":
            self._step_up_sessions[token_hash] = (user.id, created)
        context = AuthContext(user, session_id, token_hash, csrf_hash, auth_method)
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
        step_up = self._step_up_sessions.get(token_hash)
        if step_up is not None:
            if step_up[0] != user.id or current - step_up[1] > timedelta(seconds=300):
                self._step_up_sessions.pop(token_hash, None)
            else:
                auth_method = "passkey"
        if not isinstance(raw_session_id, str) or not isinstance(csrf_hash, str):
            raise AuthUnavailable("Account security state is invalid.")
        if auth_method not in {"local", "github", "passkey"}:
            raise AuthUnavailable("Account security state is invalid.")
        return AuthContext(
            user,
            raw_session_id,
            token_hash,
            csrf_hash,
            cast(Literal["local", "github", "passkey"], auth_method),
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
        """Return true only for a session authenticated by a recent passkey assertion."""

        entry = self._step_up_sessions.get(context.token_hash)
        if entry is None or entry[0] != context.user.id:
            return False
        age = now.astimezone(UTC) - entry[1]
        if age < timedelta(0) or age > timedelta(seconds=max_age):
            self._step_up_sessions.pop(context.token_hash, None)
            return False
        return True

    def create_invitation(
        self, github_id: int, invited_by: int, now: datetime, *, github_login: str | None = None
    ) -> tuple[str, Mapping[str, object]]:
        """Create a single-use invitation and return its raw code exactly once."""

        if self.settings.mode != "github":
            raise AuthUnavailable("GitHub invitations are not enabled.")
        bounded_id = _safe_github_id(github_id)
        code = secrets.token_urlsafe(32)
        issued = now.astimezone(UTC)
        expires = issued + timedelta(seconds=self.settings.invitation_ttl_seconds)
        result = self.store.auth_create_invitation(
            {
                "code_hash": _hash_secret(code),
                "github_id": bounded_id,
                "github_login": github_login,
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

    def consume_invitation_hash(self, code_hash: str, now: datetime) -> Mapping[str, object]:
        """Consume a state-bound invitation without ever recovering its raw browser code."""

        if len(code_hash) != 64 or not re_full_hex(code_hash):
            raise InvitationRejected()
        result = self.store.auth_consume_invitation(code_hash, _iso(now.astimezone(UTC)))
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
        self, now: datetime, *, invitation_code: str | None = None
    ) -> GithubAuthorization:
        """Generate OAuth state and PKCE verifier stored on the server."""

        if self.settings.mode != "github" or not self.settings.github_client_id:
            raise AuthUnavailable("GitHub sign-in is not configured.")
        issued = now.astimezone(UTC)
        with self._oauth_start_lock:
            cutoff = issued - OAUTH_START_WINDOW
            self._oauth_start_times = [
                started for started in self._oauth_start_times if started > cutoff
            ]
            if len(self._oauth_start_times) >= MAX_OAUTH_STARTS_PER_WINDOW:
                raise AuthUnavailable("GitHub sign-in is temporarily unavailable.")
            self._oauth_start_times.append(issued)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
        expires = issued + timedelta(seconds=self.settings.oauth_state_ttl_seconds)
        redirect = self.settings.github_redirect_uri
        if not redirect:
            raise AuthUnavailable("GitHub sign-in is not configured.")
        self.store.auth_store_oauth_state(
            {
                "state_hash": _hash_secret(state),
                "code_verifier": verifier,
                "redirect_uri": redirect,
                "invitation_code_hash": (
                    _hash_secret(invitation_code)
                    if invitation_code and 20 <= len(invitation_code) <= 128
                    else None
                ),
                "created_at": _iso(issued),
                "expires_at": _iso(expires),
            }
        )
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
        client = self.http_client or httpx.Client(timeout=8.0, follow_redirects=False)
        close_client = self.http_client is None
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
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
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
            )
            profile.raise_for_status()
            value = profile.json()
        except (httpx.HTTPError, ValueError, TypeError, OAuthRejected):
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
            _optional_text(state_record.get("invitation_code_hash")),
        )

    def begin_passkey_registration(
        self, user: UserRecord, rp_id: str, origin: str
    ) -> dict[str, object]:
        """Return bounded WebAuthn creation options and retain the challenge server-side."""

        if not user.active:
            raise AuthenticationRequired()
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
        """Verify and persist one passkey credential for an account."""

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
                "transports": item.get("transports", []),
            }
            for item in credentials
            if isinstance(item.get("credential_id"), str)
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
        """Verify an assertion, update its counter, and issue a passkey session."""

        challenge = self._consume_challenge("assertion", user.id, response)
        credential_id = response.get("id")
        if not isinstance(credential_id, str) or len(credential_id) > 512:
            raise PasskeyRejected()
        record = self.store.auth_get_passkey(credential_id, user_id=user.id)
        if record is None:
            raise PasskeyRejected()
        stored_user_id = record.get("user_id")
        if stored_user_id != user.id:
            raise PasskeyRejected()
        raw_transports = record.get("transports", [])
        transports: tuple[str, ...]
        if isinstance(raw_transports, str):
            try:
                decoded = json.loads(raw_transports)
            except ValueError:
                decoded = []
            transports = (
                tuple(item for item in decoded if isinstance(item, str))
                if isinstance(decoded, list)
                else ()
            )
        elif isinstance(raw_transports, list):
            transports = tuple(item for item in raw_transports if isinstance(item, str))
        else:
            transports = ()
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
        self.store.auth_update_passkey(credential_id, {"sign_count": new_count})
        return self.issue_session(user, now, "passkey")

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

    def auth_create_session(self, fields: Mapping[str, object]) -> None:
        self.sessions[str(fields["token_hash"])] = dict(fields)

    def auth_get_session(self, token_hash: str) -> Mapping[str, object] | None:
        return self.sessions.get(token_hash)

    def auth_touch_session(self, token_hash: str, fields: Mapping[str, object]) -> None:
        if token_hash in self.sessions:
            self.sessions[token_hash].update(fields)

    def auth_revoke_session(self, token_hash: str, revoked_at: str) -> None:
        if token_hash in self.sessions:
            self.sessions[token_hash]["revoked_at"] = revoked_at

    def auth_revoke_all_sessions(self, user_id: int, revoked_at: str) -> None:
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
        record = self.invitations.get(code_hash)
        if record is None or record.get("consumed_at") is not None:
            return None
        record["consumed_at"] = consumed_at
        return record

    def auth_get_invitation(self, code_hash: str) -> Mapping[str, object] | None:
        return self.invitations.get(code_hash)

    def auth_store_oauth_state(self, fields: Mapping[str, object]) -> None:
        self.oauth_states[str(fields["state_hash"])] = dict(fields)

    def auth_consume_oauth_state(
        self, state_hash: str, consumed_at: str
    ) -> Mapping[str, object] | None:
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
        return [item for item in self.passkeys.values() if item.get("user_id") == user_id]

    def auth_get_passkey(
        self, credential_id: str, *, user_id: int | None = None
    ) -> Mapping[str, object] | None:
        record = self.passkeys.get(credential_id)
        if record is not None and user_id is not None and record.get("user_id") != user_id:
            return None
        return record

    def auth_update_passkey(
        self, credential_id: str, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        record = self.passkeys.get(credential_id)
        if record is None:
            return None
        record.update(fields)
        return record

    def auth_list_sessions(self, user_id: int) -> list[Mapping[str, object]]:
        return [item for item in self.sessions.values() if item.get("user_id") == user_id]

    def auth_revoke_session_by_id(self, user_id: int, session_id: str, revoked_at: str) -> None:
        for session in self.sessions.values():
            if session.get("user_id") == user_id and session.get("session_id") == session_id:
                session["revoked_at"] = revoked_at
