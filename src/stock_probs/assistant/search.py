"""Policy bridge for native OpenCode V2 websearch permission requests."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import unquote_plus, urlsplit

from stock_probs.assistant.schemas import AssistantTurnContext, EventEmitter
from stock_probs.domain import DomainError, safe_news_url

MAX_SEARCH_QUERY_BYTES = 1000
MAX_FETCH_URL_BYTES = 2048
_SECRETISH_URL_QUERY_KEY = re.compile(
    r"(?:access[_-]?token|api[_-]?key|auth(?:orization)?|bearer|code|credential|"
    r"jwt|key|password|secret|session|signature|token)",
    re.IGNORECASE,
)
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_MAX_URL_QUERY_FIELDS = 64


@dataclass(frozen=True, slots=True)
class NativePermissionDecision:
    """One permission decision bound to a native session and exact request resource."""

    decision: str
    reason: str


class NativeSearchPermissionBridge:
    """Approve native public search and fetch after exact browser-confirmed previews.

    Search and fetch stay in OpenCode's native tool implementations. This class only translates
    session-scoped permission requests into authenticated backend preview flows; it does not
    fetch pages or trust native session metadata as application authorization.
    """

    def __init__(
        self,
        approval: Callable[[AssistantTurnContext, str, EventEmitter], Awaitable[str | None]] | None,
        webfetch_approval: (
            Callable[[AssistantTurnContext, str, EventEmitter], Awaitable[str | None]] | None
        ) = None,
    ) -> None:
        self._approval = approval
        self._webfetch_approval = webfetch_approval

    def set_approval(
        self,
        approval: Callable[[AssistantTurnContext, str, EventEmitter], Awaitable[str | None]] | None,
    ) -> None:
        self._approval = approval

    def set_webfetch_approval(
        self,
        approval: Callable[[AssistantTurnContext, str, EventEmitter], Awaitable[str | None]] | None,
    ) -> None:
        """Attach the separate browser-confirmed exact-destination callback."""

        self._webfetch_approval = approval

    async def decide(
        self,
        *,
        context: AssistantTurnContext,
        permission: str,
        resources: object,
        emit: EventEmitter,
    ) -> NativePermissionDecision:
        """Fail closed except for an exact, user-approved native websearch query."""

        if permission == "websearch":
            if self._approval is None:
                return NativePermissionDecision("reject", "unsupported_permission")
            resource = self._single_query(resources)
            if resource is None:
                return NativePermissionDecision("reject", "invalid_search_resource")
            callback = self._approval
            reason = "search_not_approved"
            approved_reason = "exact_search_approved"
        elif permission == "webfetch":
            if self._webfetch_approval is None:
                return NativePermissionDecision("reject", "unsupported_permission")
            resource = self._single_fetch_url(resources)
            if resource is None:
                return NativePermissionDecision("reject", "invalid_fetch_resource")
            callback = self._webfetch_approval
            reason = "fetch_not_approved"
            approved_reason = "exact_fetch_approved"
        else:
            return NativePermissionDecision("reject", "unsupported_permission")
        try:
            approved = await callback(context, resource, emit)
        except Exception:
            return NativePermissionDecision("reject", "approval_unavailable")
        if approved != resource:
            return NativePermissionDecision("reject", reason)
        return NativePermissionDecision("once", approved_reason)

    @staticmethod
    def _single_query(resources: object) -> str | None:
        """Accept one exact native query string; reject widened or ambiguous resources."""

        candidate: object = resources
        if isinstance(resources, Mapping):
            # V2 permission events use `patterns`; some API versions project the resource
            # directly. Both forms are accepted only when they resolve to exactly one string.
            patterns = resources.get("patterns")
            if isinstance(patterns, list | tuple) and len(patterns) == 1:
                candidate = patterns[0]
            elif "query" in resources and set(resources) <= {"query"}:
                candidate = resources.get("query")
        elif isinstance(resources, list | tuple) and len(resources) == 1:
            candidate = resources[0]
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or candidate != candidate.strip()
            or len(candidate.encode("utf-8")) > MAX_SEARCH_QUERY_BYTES
            or any(ord(character) < 32 and character not in "\t\n" for character in candidate)
        ):
            return None
        return candidate

    @staticmethod
    def _single_fetch_url(resources: object) -> str | None:
        """Accept only one exact public HTTPS URL from V2's native permission resource."""

        if not isinstance(resources, list | tuple) or len(resources) != 1:
            return None
        return validate_webfetch_url(resources[0])


def validate_webfetch_url(candidate: object) -> str | None:
    """Validate one public HTTPS fetch URL without normalizing the approved destination."""

    if not isinstance(candidate, str) or not candidate:
        return None
    try:
        candidate_bytes = candidate.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if len(candidate_bytes) > MAX_FETCH_URL_BYTES or any(
        ord(character) < 32 or ord(character) == 127 for character in candidate
    ):
        return None
    try:
        validated = safe_news_url(candidate)
        parsed = urlsplit(candidate)
    except (DomainError, ValueError):
        return None
    if (
        validated != candidate
        or parsed.scheme != "https"
        or not parsed.hostname
        or _query_has_secretish_key(parsed.query)
    ):
        return None
    return candidate


def _query_has_secretish_key(query: str) -> bool:
    """Check decoded query parameter names without changing the approved URL string."""

    if not query:
        return False
    fields = query.replace(";", "&").split("&")
    if len(fields) > _MAX_URL_QUERY_FIELDS:
        return True
    for field in fields:
        raw_key = field.partition("=")[0]
        if _INVALID_PERCENT_ESCAPE.search(raw_key) is not None:
            return True
        try:
            key = unquote_plus(raw_key, encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            return True
        # Reject nested encoding too; downstream URL handlers may decode a key again.
        if "%" in key or any(ord(character) < 32 or ord(character) == 127 for character in key):
            return True
        if _SECRETISH_URL_QUERY_KEY.fullmatch(key) is not None:
            return True
    return False
