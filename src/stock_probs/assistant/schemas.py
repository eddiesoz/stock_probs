"""Typed browser, storage and runtime contracts for the local research assistant."""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

AssistantRoute: TypeAlias = Literal[
    "/",
    "/overview",
    "/research",
    "/tools",
    "/tools/forecast",
    "/tools/markets",
    "/tools/live-trading",
    "/api-docs",
    "/account",
    "/admin",
]
AssistantEventType: TypeAlias = Literal[
    "meta",
    "token",
    "tool",
    "source",
    "proposed_action",
    "private_context_preview",
    "webfetch_preview",
    "complete",
    "error",
]

NonEmptyText = Annotated[str, Field(min_length=1, strip_whitespace=True)]
PositiveIdentifier = Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]
Sha256Digest = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]


class AssistantStrictModel(BaseModel):
    """Reject undocumented fields before assistant data reaches a service or SQLite."""

    model_config = ConfigDict(extra="forbid")


class AssistantInstrumentRef(AssistantStrictModel):
    """Identify an instrument by the existing normalized market contract."""

    symbol: str = Field(min_length=1, max_length=15, pattern=r"^[A-Z0-9.^-]+$")
    asset_type: Literal["stock", "etf"]
    provider: str = Field(min_length=1, max_length=80)
    exchange: str = Field(min_length=1, max_length=40)
    # Context GET fills this from the validated provider identity. The browser cannot assert it.
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class AssistantContextRef(AssistantStrictModel):
    """Describe only route and stable resource references, never client-supplied private data."""

    route: AssistantRoute
    instrument: AssistantInstrumentRef | None = None
    event_ref: AssistantEventRef | None = None
    result_ref: AssistantResultRef | None = None
    context_version: Sha256Digest

    @model_validator(mode="after")
    def resource_refs_are_coherent(self) -> AssistantContextRef:
        if self.result_ref is not None and self.event_ref is None:
            raise ValueError("result_ref requires its owning event_ref")
        if (self.event_ref is not None or self.result_ref is not None) and self.route not in {
            "/",
            "/research",
            "/tools/forecast",
            "/tools/live-trading",
            "/tools/markets",
        }:
            raise ValueError("saved references are not supported on this route")
        if self.instrument is not None and self.route in {"/admin", "/account", "/api-docs"}:
            raise ValueError("instrument context is not supported on this route")
        if self.route in {"/admin", "/account", "/api-docs"} and (
            self.event_ref is not None or self.result_ref is not None
        ):
            raise ValueError("saved resources are not supported on this route")
        return self


class AssistantEventRef(AssistantStrictModel):
    """Owner-validated immutable submitted-search identity and content version."""

    id: PositiveIdentifier
    version: Sha256Digest


class AssistantResultRef(AssistantStrictModel):
    """Owner-validated immutable result identity and content version."""

    id: PositiveIdentifier
    version: Sha256Digest


class AssistantContextQuery(AssistantStrictModel):
    """Bound the route and optional existing-resource references requested by the UI."""

    route: AssistantRoute
    symbol: str | None = Field(default=None, min_length=1, max_length=15)
    asset_type: Literal["stock", "etf"] | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    exchange: str | None = Field(default=None, min_length=1, max_length=40)
    event_id: PositiveIdentifier | None = None
    result_id: PositiveIdentifier | None = None

    @model_validator(mode="after")
    def instrument_fields_are_paired(self) -> AssistantContextQuery:
        if (self.symbol is None) != (self.asset_type is None):
            raise ValueError("symbol and asset_type must be supplied together")
        if self.symbol is not None and (self.provider is None or self.exchange is None):
            raise ValueError("provider and exchange identity assertions are required")
        if self.symbol is None and (self.provider is not None or self.exchange is not None):
            raise ValueError("provider and exchange require an instrument symbol")
        if self.result_id is not None and self.event_id is None:
            raise ValueError("result_id requires event_id")
        if (self.event_id is not None or self.result_id is not None) and self.route not in {
            "/",
            "/research",
            "/tools/forecast",
            "/tools/live-trading",
            "/tools/markets",
        }:
            raise ValueError("saved references are not supported on this route")
        return self


class AssistantContextPreview(AssistantStrictModel):
    """Present the exact low-sensitivity page references the user is about to share."""

    summary: str = Field(max_length=500)
    fields: list[str] = Field(max_length=12)
    note: str = Field(max_length=500)


class AssistantContextResponse(AssistantStrictModel):
    """Canonical page context and version validated by the backend."""

    context: AssistantContextRef
    preview: AssistantContextPreview


class AssistantConversationCreateRequest(AssistantStrictModel):
    """Create one durable owner conversation with optional safe page context."""

    title: str | None = Field(default=None, min_length=1, max_length=160)
    context: AssistantContextRef | None = None


class AssistantConversationUpdateRequest(AssistantStrictModel):
    """Rename a conversation using its current revision as an optimistic lock."""

    title: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=1)


class AssistantConversationDeleteRequest(AssistantStrictModel):
    """Require explicit typed deletion confirmation for one exact conversation revision."""

    expected_revision: int = Field(ge=1)
    confirmation_phrase: str = Field(min_length=8, max_length=64)


class AssistantConsentRequest(AssistantStrictModel):
    """Record versioned explicit permission to send prompts, context, and tool results."""

    policy_version: str = Field(min_length=1, max_length=80)
    accepted_terms: StrictBool
    data_collection_opt_in: StrictBool = False

    @model_validator(mode="after")
    def collection_requires_terms(self) -> AssistantConsentRequest:
        if self.data_collection_opt_in and not self.accepted_terms:
            raise ValueError("data collection opt-in requires accepted terms")
        return self


class AssistantModelAdminPolicyRequest(AssistantStrictModel):
    """Bind one administrator approval update to an exact model-policy revision."""

    enabled: StrictBool
    acknowledged_privacy_policy_version: StrictStr | None = Field(default=None, max_length=80)
    acknowledged_billing_policy_version: StrictStr | None = Field(default=None, max_length=80)
    expected_revision: StrictInt = Field(ge=0, le=2_147_483_647)


class AssistantTurnCreateRequest(AssistantStrictModel):
    """Start a user-requested model turn with a current context and stored consent."""

    prompt: str = Field(min_length=1, max_length=8192)
    model_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=80)
    context: AssistantContextRef
    context_preview_accepted: StrictBool

    @field_validator("prompt")
    @classmethod
    def prompt_has_visible_content(cls, value: str) -> str:
        if not value.strip() or any(ord(character) == 0 for character in value):
            raise ValueError("prompt must contain visible text")
        return value.strip()


class AssistantActionConfirmationRequest(AssistantStrictModel):
    """Bind a browser confirmation to the exact immutable proposal version."""

    action_version: int = Field(ge=1)
    context: AssistantContextRef
    allow: StrictBool = True
    confirmation_phrase: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def approval_requires_phrase(self) -> AssistantActionConfirmationRequest:
        if self.allow and not self.confirmation_phrase:
            raise ValueError("an affirmative action decision requires its exact phrase")
        return self


class AssistantSearchPreviewConfirmationRequest(AssistantStrictModel):
    """Approve or deny one exact web query before it can contain private account data."""

    context_version: Sha256Digest
    context: AssistantContextRef
    confirmation_phrase: str = Field(default="", max_length=100)
    allow: StrictBool

    @model_validator(mode="after")
    def approval_requires_phrase(self) -> AssistantSearchPreviewConfirmationRequest:
        if self.allow and not self.confirmation_phrase:
            raise ValueError("an affirmative search decision requires its exact phrase")
        return self


class AssistantWebfetchPreviewConfirmationRequest(AssistantStrictModel):
    """Bind one exact native fetch destination to a same-session decision."""

    context_version: Sha256Digest
    context: AssistantContextRef | None = None
    confirmation_phrase: str = Field(default="", max_length=100)
    allow: StrictBool

    @model_validator(mode="after")
    def approval_requires_phrase(self) -> AssistantWebfetchPreviewConfirmationRequest:
        if self.allow and (self.context is None or not self.confirmation_phrase):
            raise ValueError(
                "an affirmative fetch decision requires its current context and exact phrase"
            )
        return self


class AssistantProviderUpdateRequest(AssistantStrictModel):
    """Accept write-only provider fields without ever reflecting credential material."""

    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2048)
    credential: str | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("base_url")
    @classmethod
    def provider_url_is_bounded_and_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validated_public_https_url(value, field_name="base_url")


def _validated_public_https_url(value: str, *, field_name: str) -> str:
    message = f"{field_name} must be a public HTTPS URL on port 443"
    if (
        not value
        or len(value.encode("utf-8")) > 2048
        or value != value.strip()
        or any(character.isspace() for character in value)
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        or "\\" in value
    ):
        raise ValueError(message)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(message) from exc
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
        or host in {"localhost"}
        or host.endswith(".localhost")
    ):
        raise ValueError(message)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError(message)
    return value.rstrip("/")


class AssistantCustomProviderEndpointRequest(AssistantStrictModel):
    """Require the complete administrator-reviewed custom endpoint policy as one update."""

    base_url: StrictStr = Field(min_length=1, max_length=2048)
    terms_url: StrictStr = Field(min_length=1, max_length=2048)
    privacy_disclosure: StrictStr = Field(min_length=1, max_length=2000)
    billing_disclosure: StrictStr = Field(min_length=1, max_length=2000)
    billing_class: Literal["unknown", "free", "paid"]
    endpoint_policy_reviewed: StrictBool
    credential: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
    model_id: StrictStr | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("base_url", "terms_url")
    @classmethod
    def urls_are_public_https(cls, value: str, info) -> str:
        return _validated_public_https_url(value, field_name=info.field_name)

    @field_validator("privacy_disclosure", "billing_disclosure")
    @classmethod
    def disclosures_are_bounded_plain_text(cls, value: str, info) -> str:
        if (
            not value.strip()
            or len(value.encode("utf-8")) > 2000
            or any(ord(character) < 0x20 and character not in "\n\r\t" for character in value)
            or any(ord(character) == 0x7F for character in value)
        ):
            raise ValueError(f"{info.field_name} must be bounded plain text")
        return value

    @model_validator(mode="after")
    def requires_explicit_endpoint_review(self) -> AssistantCustomProviderEndpointRequest:
        if self.endpoint_policy_reviewed is not True:
            raise ValueError("endpoint_policy_reviewed must be true")
        return self


class AssistantOpenCodeModelReviewRequest(AssistantStrictModel):
    """Review one owner-bound OpenCode package without accepting executable config."""

    terms_url: StrictStr = Field(min_length=1, max_length=2048)
    privacy_disclosure: StrictStr = Field(min_length=1, max_length=2000)
    billing_disclosure: StrictStr = Field(min_length=1, max_length=2000)
    billing_class: Literal["unknown", "free", "paid"]
    training_policy: Literal["unknown", "no_training", "training_possible"]
    confidential_data_policy: Literal["unknown", "allowed", "prohibited"]
    endpoint_policy_reviewed: StrictBool
    expected_revision: StrictInt = Field(ge=0, le=2_147_483_647)
    expected_config_fingerprint: Sha256Digest

    @field_validator("terms_url")
    @classmethod
    def terms_are_public_https(cls, value: str) -> str:
        return _validated_public_https_url(value, field_name="terms_url")

    @field_validator("privacy_disclosure", "billing_disclosure")
    @classmethod
    def disclosures_are_bounded_plain_text(cls, value: str, info) -> str:
        if (
            not value.strip()
            or len(value.encode("utf-8")) > 2000
            or any(ord(character) < 0x20 and character not in "\n\r\t" for character in value)
            or any(ord(character) == 0x7F for character in value)
        ):
            raise ValueError(f"{info.field_name} must be bounded plain text")
        return value

    @model_validator(mode="after")
    def requires_explicit_endpoint_review(self) -> AssistantOpenCodeModelReviewRequest:
        if self.endpoint_policy_reviewed is not True:
            raise ValueError("endpoint_policy_reviewed must be true")
        return self


class AssistantOAuthAttemptCreateRequest(AssistantStrictModel):
    """Select one manager-listed provider and native OAuth method."""

    provider_id: StrictStr = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    method_id: StrictStr = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")


class AssistantOAuthAttemptCompleteRequest(AssistantStrictModel):
    """Carry only a bounded authorization code; an empty object claims a ready handoff."""

    code: StrictStr | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("code")
    @classmethod
    def authorization_code_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or any(
            ord(character) < 0x21 or ord(character) == 0x7F for character in value
        ):
            raise ValueError("code must be bounded plain text")
        return value


class AssistantOAuthAttemptCallbackRequest(AssistantStrictModel):
    """Accept only the exact native localhost callback shape for its registered relay."""

    callback_url: StrictStr = Field(min_length=1, max_length=4096)

    @field_validator("callback_url")
    @classmethod
    def callback_is_native_localhost(cls, value: str) -> str:
        message = "callback_url is not a supported native OAuth callback"
        if (
            value != value.strip()
            or any(ord(character) < 0x21 or ord(character) == 0x7F for character in value)
            or "\\" in value
        ):
            raise ValueError(message)
        try:
            parsed = urlsplit(value)
            port = parsed.port
            query = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=4,
            )
        except ValueError as exc:
            raise ValueError(message) from exc
        query_map = dict(query)
        query_values_are_plain = all(
            len(key.encode("utf-8")) <= 64
            and len(item.encode("utf-8")) <= 4096
            and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in key)
            and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in item)
            for key, item in query
        )
        keys = set(query_map)
        has_success = "code" in keys
        has_error = "error" in keys
        if (
            parsed.scheme != "http"
            or parsed.hostname != "localhost"
            or port not in {1455, 1457}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/auth/callback"
            or parsed.fragment
            or len(query) != len(query_map)
            or not query_values_are_plain
            or not {"state"}.issubset(keys)
            or keys - {"code", "state", "error", "error_description"}
            or has_success == has_error
            or not query_map.get("state")
            or not query_map.get("code" if has_success else "error")
            or ("error_description" in keys and not has_error)
        ):
            raise ValueError(message)
        return value


class AssistantConversation(AssistantStrictModel):
    """Public metadata for one conversation owned by the current authenticated account."""

    id: str
    title: str
    revision: int
    created_at: str
    updated_at: str
    last_message_preview: str | None
    delete_confirmation_phrase: str


class AssistantMessage(AssistantStrictModel):
    """Durable user or assistant text with owner-scoped source identifiers."""

    id: str
    turn_id: str
    seq: int
    role: Literal["user", "assistant"]
    text: str
    created_at: str
    sources: list[dict[str, object]] = Field(max_length=50)


class AssistantTurnSummary(AssistantStrictModel):
    """Bounded persisted status for reconnect and transcript rendering."""

    id: str
    status: Literal["queued", "running", "completed", "cancelled", "failed", "timed_out"]
    model_id: str
    policy_version: str
    context_version: Sha256Digest
    context: AssistantContextRef
    created_at: str
    completed_at: str | None


class AssistantContextEvent(AssistantStrictModel):
    """One durable replay item from the current conversation's normalized app event stream."""

    turn_id: str
    sequence: int = Field(ge=1)
    type: AssistantEventType
    data: dict[str, object]
    created_at: str


@dataclass(frozen=True, slots=True)
class AssistantTurnContext:
    """Trusted server-built identifiers and page references for exactly one runtime turn."""

    user_id: int
    app_id: str
    conversation_id: str
    turn_id: str
    execution_id: str
    capability: str
    model_id: str
    policy_version: str
    context_version: str
    page_context: Mapping[str, object]
    history: tuple[Mapping[str, str], ...]


EventEmitter: TypeAlias = Callable[[Mapping[str, object]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AssistantTurnResult:
    """Safe terminal result returned by the runtime after it closes its ephemeral session."""

    status: Literal["completed", "cancelled", "failed", "timed_out"]
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AssistantModelPolicy:
    """Reviewed catalog terms and privacy facts used for explicit versioned consent."""

    model_id: str
    provider_id: str
    display_name: str
    available: bool
    free: bool
    training: bool
    terms_url: str
    terms_reviewed_at: str
    policy_version: str
    disclosure: str
    data_collection_allowed: bool
    data_collection_default: bool


@dataclass(frozen=True, slots=True)
class AssistantRuntimeStatus:
    """Safe assistant-worker readiness facts; app health is reported separately."""

    status: Literal["disabled", "starting", "ready", "unavailable", "stopped"]
    message: str | None = None
