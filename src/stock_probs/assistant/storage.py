"""Owner-scoped durable assistant records in the canonical application SQLite database."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final, cast
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

from stock_probs.assistant.feature_filters import (
    InvalidFeatureFilter,
    history_export_query,
    normalize_history_filters,
    normalize_history_form_filters,
    normalize_market_chart_range,
    normalize_market_columns,
    normalize_market_filters,
    normalize_market_refresh,
)
from stock_probs.repository import Repository

ASSISTANT_USER_HISTORY_LIMIT: Final = 2 * 1024 * 1024
ASSISTANT_GLOBAL_HISTORY_LIMIT: Final = 24 * 1024 * 1024
ASSISTANT_DATABASE_LIMIT: Final = 48 * 1024 * 1024
ASSISTANT_ACTIVE_PER_USER: Final = 1
ASSISTANT_ACTIVE_GLOBAL: Final = 2
ASSISTANT_TOOLS_PER_TURN: Final = 8
ASSISTANT_TURN_SECONDS: Final = 120
_EVENT_TYPES: Final = frozenset(
    {
        "meta",
        "token",
        "tool",
        "source",
        "proposed_action",
        "private_context_preview",
        "webfetch_preview",
        "complete",
        "error",
    }
)


class AssistantStorageError(Exception):
    """Base for safe assistant persistence failures."""


class AssistantStorageConflict(AssistantStorageError):
    """Report an owner-scoped revision, lease, or status conflict."""


class AssistantStorageNotFound(AssistantStorageError):
    """Hide records that are missing or belong to another account."""


class AssistantStorageQuotaExceeded(AssistantStorageError):
    """Stop new assistant writes before any history or database storage bound is exceeded."""

    def __init__(self, scope: str):
        super().__init__(scope)
        self.scope = scope


class AssistantStorageBusy(AssistantStorageError):
    """Report that an owner or the whole app already uses its bounded turn slot."""


class AssistantStorage:
    """Persist conversations, consent, replay events and one-turn MCP leases by owner."""

    def __init__(self, repository: Repository):
        self._repository = repository

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("assistant timestamps must include a timezone offset")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    @staticmethod
    def _new_id() -> str:
        return str(uuid4())

    @staticmethod
    def _require_owner(user_id: int) -> int:
        return Repository._require_owner_id(user_id)

    @classmethod
    def _serialized_bytes(cls, value: object) -> int:
        return len(cls._json(value).encode("utf-8"))

    @staticmethod
    def _size_expression(table: str, expressions: str, where: str) -> str:
        # Callers pass only fixed, enumerated SQL identifiers/expressions; values remain bound.
        return (
            "SELECT COALESCE(SUM(" + expressions + "), 0) FROM " + table + " WHERE " + where  # noqa: S608
        )

    @classmethod
    def _history_bytes(cls, connection: sqlite3.Connection, user_id: int | None) -> int:
        owner_clause = " AND user_id = ?" if user_id is not None else ""
        owner_params: tuple[object, ...] = (user_id,) if user_id is not None else ()
        items: tuple[tuple[str, str, str], ...] = (
            (
                "assistant_conversations",
                "length(CAST(title AS BLOB)) + length(CAST(context_json AS BLOB)) + 192",
                "1 = 1",
            ),
            (
                "assistant_turns",
                "length(CAST(model_id AS BLOB)) + length(CAST(policy_version AS BLOB)) + "
                "length(CAST(context_json AS BLOB)) + "
                "COALESCE(length(CAST(error_code AS BLOB)), 0) + 192",
                "1 = 1",
            ),
            ("assistant_messages", "length(CAST(content AS BLOB)) + 192", "1 = 1"),
            (
                "assistant_events",
                "length(CAST(event_type AS BLOB)) + length(CAST(payload_json AS BLOB)) + 192",
                "1 = 1",
            ),
            (
                "assistant_sources",
                "length(CAST(source_type AS BLOB)) + length(CAST(title AS BLOB)) + "
                "COALESCE(length(CAST(url AS BLOB)), 0) + "
                "COALESCE(length(CAST(source_ref AS BLOB)), 0) + "
                "length(CAST(metadata_json AS BLOB)) + 192",
                "1 = 1",
            ),
            (
                "assistant_proposed_actions",
                "length(CAST(session_id AS BLOB)) + length(CAST(context_version AS BLOB)) + "
                "length(CAST(action_type AS BLOB)) + length(CAST(payload_json AS BLOB)) + 192",
                "1 = 1",
            ),
            (
                "assistant_action_receipts",
                "length(CAST(outcome AS BLOB)) + length(CAST(result_json AS BLOB)) + 192",
                "1 = 1",
            ),
            (
                "assistant_execution_leases",
                "length(CAST(app_id AS BLOB)) + length(CAST(context_version AS BLOB)) + 192",
                "1 = 1",
            ),
            ("assistant_search_previews", "length(CAST(query_text AS BLOB)) + 192", "1 = 1"),
            (
                "assistant_model_consents",
                "length(CAST(model_id AS BLOB)) + length(CAST(policy_version AS BLOB)) + 192",
                "1 = 1",
            ),
            (
                "assistant_conversation_deletions",
                "length(CAST(content_digest AS BLOB)) + 192",
                "1 = 1",
            ),
        )
        total = 0
        for table, byte_expression, predicate in items:
            where = predicate + owner_clause
            query = cls._size_expression(table, byte_expression, where)
            row = connection.execute(query, owner_params).fetchone()
            total += int(row[0]) if row is not None else 0
        return total

    @staticmethod
    def _database_bytes(connection: sqlite3.Connection) -> int:
        pages = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        return pages * page_size

    @staticmethod
    def _safe_destination(value: object) -> str | None:
        """Revalidate persisted local links before reopening a conversation receipt."""

        static = {
            "/admin#invitations",
            "/admin#backups",
            "/admin#restore",
            "/admin#assistant-providers",
            "/account#sessions",
            "/api/v1/history-export.csv",
            "/api/v1/history-export.json",
        }
        if (
            not isinstance(value, str)
            or len(value) > 512
            or not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
        ):
            return None
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            return None
        if value in static:
            return value
        try:
            pairs = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=16,
            )
        except ValueError:
            return None
        if (
            parsed.path == "/"
            and parsed.fragment == "result-section"
            and len(pairs) == 1
            and pairs[0][0] == "event_id"
            and pairs[0][1].isascii()
            and pairs[0][1].isdecimal()
            and 1 <= len(pairs[0][1]) <= 10
            and int(pairs[0][1]) > 0
        ):
            return value
        if parsed.path == "/tools/markets" and not parsed.fragment and len(pairs) == 4:
            values = dict(pairs)
            if (
                len(values) == 4
                and set(values) == {"symbol", "asset_type", "provider", "exchange"}
                and values["asset_type"] in {"stock", "etf"}
                and 1 <= len(values["symbol"]) <= 15
                and all(
                    char.isascii() and (char.isalnum() or char in ".^-")
                    for char in values["symbol"]
                )
                and 1 <= len(values["provider"]) <= 80
                and 1 <= len(values["exchange"]) <= 40
                and all(
                    char.isascii() and (char.isalnum() or char in " ._-")
                    for char in values["provider"] + values["exchange"]
                )
            ):
                return value
        if parsed.path == "/" and parsed.fragment == "history-heading" and len(pairs) <= 3:
            values = dict(pairs)
            if (
                len(values) == len(pairs)
                and set(values) <= {"q", "status", "asset_type"}
                and ("q" not in values or len(values["q"]) <= 30)
                and (
                    "status" not in values
                    or values["status"] in {"successful", "repeated", "failed"}
                )
                and ("asset_type" not in values or values["asset_type"] in {"stock", "etf"})
            ):
                return value
        if (
            parsed.path in {"/api/v1/history-export.csv", "/api/v1/history-export.json"}
            and not parsed.fragment
            and pairs
        ):
            values = dict(pairs)
            if len(values) != len(pairs):
                return None
            allowed = {
                "q",
                "symbol",
                "status",
                "asset_type",
                "analysis_kind",
                "submitted_from",
                "submitted_to",
                "model",
                "horizon",
                "sort_by",
                "sort_order",
            }
            if set(values) - allowed or not {"sort_by", "sort_order"} <= set(values):
                return None
            if values["sort_by"] not in {"event_id", "symbol", "company", "status"}:
                return None
            if values["sort_order"] not in {"asc", "desc"}:
                return None
            start = values.get("submitted_from", "")
            end = values.get("submitted_to", "")
            if start:
                if not start.endswith("T00:00:00Z"):
                    return None
                values["submitted_from"] = start.removesuffix("T00:00:00Z")
            if end:
                if not end.endswith("T23:59:59.999Z"):
                    return None
                values["submitted_to"] = end.removesuffix("T23:59:59.999Z")
            filters: dict[str, object] = {
                "query": values.get("q", ""),
                "symbol": values.get("symbol", ""),
                "status": values.get("status", ""),
                "asset_type": values.get("asset_type", ""),
                "analysis_kind": values.get("analysis_kind", ""),
                "submitted_from": values.get("submitted_from", ""),
                "submitted_to": values.get("submitted_to", ""),
                "model": values.get("model", ""),
                "horizon": values.get("horizon", ""),
                "sort": f"{values['sort_by']}:{values['sort_order']}",
            }
            try:
                normalized = normalize_history_filters(filters)
            except InvalidFeatureFilter:
                return None
            query = history_export_query(normalized)
            return f"{parsed.path}?{urlencode(query)}"
        return None

    @staticmethod
    def _safe_receipt_browser_action(value: object) -> dict[str, object] | None:
        """Allow only fixed browser bridge action shapes into durable detail responses."""

        if not isinstance(value, Mapping):
            return None
        action_type, payload, destination = (
            value.get("type"),
            value.get("payload"),
            value.get("destination"),
        )
        if not isinstance(action_type, str) or not isinstance(payload, Mapping):
            return None
        payload_fields = {
            "theme.set": {"theme"},
            "filters.apply": {
                "query",
                "asset_type",
                "status",
                "analysis_kind",
                "submitted_from",
                "submitted_to",
                "model",
                "horizon",
                "sort",
                "page_size",
            },
            "market.filters.apply": {
                "query",
                "exchange",
                "asset_type",
                "sort",
                "min_price",
                "max_price",
                "min_change",
                "max_change",
                "min_volume",
                "quote_field",
                "quote_min",
                "quote_max",
            },
            "market.chart_range.set": {"symbol", "asset_type", "provider", "exchange", "range"},
            "market.columns.set": {"show_all_columns"},
            "market.refresh": {"kind"},
            "notes.set": {"symbol", "asset_type", "provider", "exchange"},
            "notes.clear": {"symbol", "asset_type", "provider", "exchange"},
            "alerts.add": {"symbol", "asset_type", "provider", "exchange", "threshold"},
            "alerts.remove": {"symbol", "asset_type", "provider", "exchange"},
        }
        if action_type not in payload_fields:
            return None
        if action_type == "filters.apply":
            if set(payload) - payload_fields[action_type] or "query" not in payload:
                return None
            try:
                safe_payload = normalize_history_form_filters(payload)
            except InvalidFeatureFilter:
                return None
        elif action_type == "market.filters.apply":
            try:
                safe_payload = normalize_market_filters(payload)
            except InvalidFeatureFilter:
                return None
        elif action_type == "market.chart_range.set":
            try:
                safe_payload = normalize_market_chart_range(payload)
            except InvalidFeatureFilter:
                return None
        elif action_type == "market.columns.set":
            try:
                safe_payload = normalize_market_columns(payload)
            except InvalidFeatureFilter:
                return None
        elif action_type == "market.refresh":
            try:
                safe_payload = normalize_market_refresh(payload)
            except InvalidFeatureFilter:
                return None
        elif set(payload) != payload_fields[action_type]:
            return None
        else:
            safe_payload = {}
        if action_type not in {
            "filters.apply",
            "market.filters.apply",
            "market.chart_range.set",
            "market.columns.set",
            "market.refresh",
        }:
            for key, item in payload.items():
                if key in {"symbol", "provider", "exchange", "query"}:
                    maximum = 100 if key == "query" else 80
                    if not isinstance(item, str) or len(item) > maximum:
                        return None
                    safe_payload[key] = item
                elif key == "asset_type":
                    if item not in {"stock", "etf"}:
                        return None
                    safe_payload[key] = item
                elif key == "theme":
                    if item not in {"light", "dark", "system"}:
                        return None
                    safe_payload[key] = item
                elif key == "status":
                    if item not in {"successful", "failed", "repeated"}:
                        return None
                    safe_payload[key] = item
                elif key == "threshold":
                    if type(item) not in {int, float} or not 0 < float(item) <= 1_000_000_000:
                        return None
                    safe_payload[key] = float(item)
                elif key == "show_all_columns":
                    if type(item) is not bool:
                        return None
                    safe_payload[key] = item
                elif key == "range":
                    if item not in {"5d", "1mo", "3mo", "6mo", "1y"}:
                        return None
                    safe_payload[key] = item
                elif key == "kind":
                    if item not in {"quotes", "watchlist", "chart"}:
                        return None
                    safe_payload[key] = item
                else:
                    return None
        if (
            not isinstance(destination, Mapping)
            or destination.get("kind") != "current-page"
            or destination.get("route") not in {"/tools/live-trading", "/", "/tools/markets"}
        ):
            return None
        expected_route = (
            "/"
            if action_type == "filters.apply"
            else "/tools/markets"
            if action_type.startswith("market.")
            else "/tools/live-trading"
        )
        if destination.get("route") != expected_route:
            return None
        safe_destination: dict[str, object] = {"kind": "current-page", "route": expected_route}
        focus = destination.get("focus")
        handler = destination.get("handler")
        expected_destination_fields = {"kind", "route"}
        if action_type.startswith("notes.") or action_type == "alerts.remove":
            expected_focus = (
                "notes-heading" if action_type.startswith("notes.") else "alerts-heading"
            )
            if focus != expected_focus:
                return None
            safe_destination["focus"] = expected_focus
            expected_destination_fields.add("focus")
        elif action_type == "alerts.add":
            if handler != "alerts.add":
                return None
            safe_destination["handler"] = "alerts.add"
            expected_destination_fields.add("handler")
        if set(destination) != expected_destination_fields:
            return None
        return {"type": action_type, "payload": safe_payload, "destination": safe_destination}

    @classmethod
    def _verify_database_limit(cls, connection: sqlite3.Connection) -> None:
        """Check allocated SQLite pages after an insert, before its transaction commits."""

        if cls._database_bytes(connection) > ASSISTANT_DATABASE_LIMIT:
            raise AssistantStorageQuotaExceeded("database")

    @classmethod
    def _ensure_capacity(
        cls,
        connection: sqlite3.Connection,
        user_id: int,
        additional_bytes: int,
    ) -> None:
        """Check logical history caps and the SQLite page cap before every assistant insert."""

        if additional_bytes < 0:
            raise ValueError("additional_bytes must be non-negative")
        # Count live pages separately from SQLite's freelist so deleted owner content can fund
        # new history without VACUUM. Two free pages remain available for terminal cleanup.
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        database_bytes = cls._database_bytes(connection)
        freelist_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        live_bytes = database_bytes - (freelist_pages * page_size)
        if live_bytes + additional_bytes + (2 * page_size) > ASSISTANT_DATABASE_LIMIT:
            raise AssistantStorageQuotaExceeded("database")
        # Reserve a fixed floor for row/index metadata so tiny records cannot bypass quotas.
        projected_bytes = additional_bytes + 192
        if cls._history_bytes(connection, user_id) + projected_bytes > ASSISTANT_USER_HISTORY_LIMIT:
            raise AssistantStorageQuotaExceeded("user_history")
        if cls._history_bytes(connection, None) + projected_bytes > ASSISTANT_GLOBAL_HISTORY_LIMIT:
            raise AssistantStorageQuotaExceeded("global_history")

    @classmethod
    def _conversation_bytes(cls, connection: sqlite3.Connection, conversation_id: str) -> int:
        total = 0
        counts: tuple[tuple[str, str], ...] = (
            (
                "assistant_conversations",
                "length(CAST(title AS BLOB)) + length(CAST(context_json AS BLOB)) + 192",
            ),
            (
                "assistant_turns",
                "length(CAST(model_id AS BLOB)) + length(CAST(policy_version AS BLOB)) + "
                "length(CAST(context_json AS BLOB)) + "
                "COALESCE(length(CAST(error_code AS BLOB)), 0) + 192",
            ),
            ("assistant_messages", "length(CAST(content AS BLOB)) + 192"),
            (
                "assistant_events",
                "length(CAST(event_type AS BLOB)) + length(CAST(payload_json AS BLOB)) + 192",
            ),
            (
                "assistant_sources",
                "length(CAST(source_type AS BLOB)) + length(CAST(title AS BLOB)) + "
                "COALESCE(length(CAST(url AS BLOB)), 0) + "
                "COALESCE(length(CAST(source_ref AS BLOB)), 0) + "
                "length(CAST(metadata_json AS BLOB)) + 192",
            ),
            (
                "assistant_proposed_actions",
                "length(CAST(session_id AS BLOB)) + length(CAST(context_version AS BLOB)) + "
                "length(CAST(action_type AS BLOB)) + length(CAST(payload_json AS BLOB)) + 192",
            ),
            (
                "assistant_action_receipts",
                "length(CAST(outcome AS BLOB)) + length(CAST(result_json AS BLOB)) + 192",
            ),
            (
                "assistant_execution_leases",
                "length(CAST(app_id AS BLOB)) + length(CAST(context_version AS BLOB)) + 192",
            ),
            ("assistant_search_previews", "length(CAST(query_text AS BLOB)) + 192"),
        )
        for table, expression in counts:
            # Every child uses its conversation_id FK; the parent stores that key as id.
            conversation_key = "id" if table == "assistant_conversations" else "conversation_id"
            row = connection.execute(  # noqa: S608
                f"SELECT COALESCE(SUM({expression}), 0) FROM {table} "  # noqa: S608
                f"WHERE {conversation_key} = ?",
                (conversation_id,),
            ).fetchone()
            total += int(row[0]) if row is not None else 0
        return total

    def usage(self, user_id: int) -> dict[str, int]:
        """Return bounded owner/global history usage and logical database size."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            return {
                "user_bytes": self._history_bytes(connection, owner_id),
                "global_bytes": self._history_bytes(connection, None),
                "database_bytes": self._database_bytes(connection),
            }

    def create_conversation(
        self,
        user_id: int,
        *,
        title: str,
        context: Mapping[str, object],
        context_version: str,
        created_at: datetime,
    ) -> dict[str, object]:
        """Create one owner row after quota checks inside SQLite's write transaction."""

        owner_id = self._require_owner(user_id)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            raise ValueError("title must be 1-160 characters")
        context_json = self._json(context)
        if len(context_json.encode("utf-8")) > 8192:
            raise ValueError("assistant context is too large")
        if not isinstance(context_version, str) or len(context_version) != 64:
            raise ValueError("context_version must be a digest")
        timestamp = self._timestamp(created_at)
        conversation_id = self._new_id()
        additional = len(title.strip().encode("utf-8")) + len(context_json.encode("utf-8"))
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(connection, owner_id, additional)
            self._repository._ensure_owner_can_write(connection, owner_id)
            connection.execute(
                """INSERT INTO assistant_conversations
                (id, user_id, title, context_json, context_version, revision, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    conversation_id,
                    owner_id,
                    title.strip(),
                    context_json,
                    context_version,
                    timestamp,
                    timestamp,
                ),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return self.get_conversation(owner_id, conversation_id)

    def list_conversations(self, user_id: int, *, page: int, page_size: int) -> dict[str, object]:
        """List only the caller's conversations with mandatory bounded pagination."""

        owner_id = self._require_owner(user_id)
        if type(page) is not int or not 1 <= page <= 10_000:
            raise ValueError("page must be between 1 and 10000")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise ValueError("page_size must be between 1 and 50")
        offset = (page - 1) * page_size
        with self._repository.connect() as connection:
            total_row = connection.execute(
                "SELECT COUNT(*) FROM assistant_conversations WHERE user_id = ?",
                (owner_id,),
            ).fetchone()
            rows = connection.execute(
                """SELECT conversation.id, conversation.title, conversation.revision,
                    conversation.created_at, conversation.updated_at,
                    (SELECT substr(message.content, 1, 160)
                     FROM assistant_messages AS message
                     WHERE message.conversation_id = conversation.id
                       AND message.user_id = conversation.user_id
                     ORDER BY message.sequence DESC LIMIT 1) AS last_message_preview
                FROM assistant_conversations AS conversation
                WHERE conversation.user_id = ?
                ORDER BY conversation.updated_at DESC, conversation.id DESC
                LIMIT ? OFFSET ?""",
                (owner_id, page_size, offset),
            ).fetchall()
        items = [self._public_conversation(dict(row)) for row in rows]
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": int(total_row[0]) if total_row is not None else 0,
        }

    @staticmethod
    def _public_conversation(row: Mapping[str, object]) -> dict[str, object]:
        conversation_id = row.get("id")
        if not isinstance(conversation_id, str):
            raise AssistantStorageError("conversation storage is invalid")
        return {
            "id": conversation_id,
            "title": row.get("title"),
            "revision": row.get("revision"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "last_message_preview": row.get("last_message_preview"),
            "delete_confirmation_phrase": f"DELETE {conversation_id[-8:]}",
        }

    def get_conversation(
        self,
        user_id: int,
        conversation_id: str,
        *,
        message_page: int = 1,
        message_page_size: int = 50,
        event_page: int = 1,
        event_page_size: int = 100,
        action_page: int = 1,
        action_page_size: int = 100,
        session_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Read bounded owner transcript, replay events, and action receipt summaries."""

        owner_id = self._require_owner(user_id)
        if type(message_page) is not int or not 1 <= message_page <= 10_000:
            raise ValueError("message_page must be between 1 and 10000")
        if type(message_page_size) is not int or not 1 <= message_page_size <= 100:
            raise ValueError("message_page_size must be between 1 and 100")
        if type(event_page) is not int or not 1 <= event_page <= 10_000:
            raise ValueError("event_page must be between 1 and 10000")
        if type(event_page_size) is not int or not 1 <= event_page_size <= 200:
            raise ValueError("event_page_size must be between 1 and 200")
        if type(action_page) is not int or not 1 <= action_page <= 10_000:
            raise ValueError("action_page must be between 1 and 10000")
        if type(action_page_size) is not int or not 1 <= action_page_size <= 200:
            raise ValueError("action_page_size must be between 1 and 200")
        if session_id is not None and not 16 <= len(session_id) <= 128:
            raise ValueError("assistant session binding is invalid")
        now_text = self._timestamp(now) if now is not None else None
        offset = (message_page - 1) * message_page_size
        event_offset = (event_page - 1) * event_page_size
        action_offset = (action_page - 1) * action_page_size
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT id, title, revision, created_at, updated_at,
                    (SELECT substr(message.content, 1, 160)
                     FROM assistant_messages AS message
                     WHERE message.conversation_id = assistant_conversations.id
                       AND message.user_id = assistant_conversations.user_id
                     ORDER BY message.sequence DESC LIMIT 1) AS last_message_preview
                FROM assistant_conversations WHERE id = ? AND user_id = ?""",
                (conversation_id, owner_id),
            ).fetchone()
            if row is None:
                raise AssistantStorageNotFound()
            total_row = connection.execute(
                """SELECT COUNT(*) FROM assistant_messages
                WHERE conversation_id = ? AND user_id = ?""",
                (conversation_id, owner_id),
            ).fetchone()
            messages = connection.execute(
                """SELECT message.id, message.turn_id, message.sequence, message.role,
                    message.content, message.created_at,
                    (SELECT json_group_array(json_object(
                        'source_id', source.id, 'title', source.title, 'url', source.url,
                        'source_type', source.source_type, 'retrieved_at', source.retrieved_at,
                        'as_of', source.as_of
                    )) FROM assistant_sources AS source
                     WHERE source.turn_id = message.turn_id AND source.user_id = message.user_id)
                    AS sources_json
                FROM assistant_messages AS message
                WHERE message.conversation_id = ? AND message.user_id = ?
                ORDER BY message.sequence DESC LIMIT ? OFFSET ?""",
                (conversation_id, owner_id, message_page_size, offset),
            ).fetchall()
            actions = connection.execute(
                """SELECT action.id, action.turn_id, action.action_type, action.status,
                    action.expires_at, action.action_version, action.context_version,
                    action.session_id, action.payload_json,
                    receipt.id AS receipt_id, receipt.outcome,
                    receipt.result_json
                FROM assistant_proposed_actions AS action
                LEFT JOIN assistant_action_receipts AS receipt ON receipt.action_id = action.id
                WHERE action.conversation_id = ? AND action.user_id = ?
                ORDER BY CASE
                    WHEN action.status = 'pending' AND action.expires_at > ? THEN 0
                    ELSE 1
                END, action.created_at DESC, action.id DESC LIMIT ? OFFSET ?""",
                (conversation_id, owner_id, now_text or "", action_page_size, action_offset),
            ).fetchall()
            action_total_row = connection.execute(
                "SELECT COUNT(*) FROM assistant_proposed_actions "
                "WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
            event_total_row = connection.execute(
                "SELECT COUNT(*) FROM assistant_events WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
            event_rows = connection.execute(
                """SELECT turn_id, sequence, event_type, payload_json, created_at
                FROM assistant_events WHERE conversation_id = ? AND user_id = ?
                ORDER BY created_at DESC, turn_id DESC, sequence DESC LIMIT ? OFFSET ?""",
                (conversation_id, owner_id, event_page_size, event_offset),
            ).fetchall()
            # Keep the canonical turn snapshot with every displayed transcript/action page.
            # This makes older messages interpretable and pending-card confirmation resumable
            # without loading every turn in a long conversation.
            turn_ids = list(
                dict.fromkeys(
                    [str(message["turn_id"]) for message in messages if message["turn_id"]]
                    + [str(action["turn_id"]) for action in actions if action["turn_id"]]
                )
            )
            active_turn_rows = connection.execute(
                """SELECT id FROM assistant_turns
                WHERE conversation_id = ? AND user_id = ?
                  AND status IN ('queued', 'running')
                ORDER BY created_at DESC, id DESC LIMIT 2""",
                (conversation_id, owner_id),
            ).fetchall()
            turn_ids.extend(
                str(turn["id"]) for turn in active_turn_rows if str(turn["id"]) not in turn_ids
            )
            if turn_ids:
                turns = connection.execute(
                    """SELECT id, status, model_id, policy_version, context_json, context_version,
                        created_at, completed_at FROM assistant_turns
                    WHERE conversation_id = ? AND user_id = ?
                      AND id IN (SELECT value FROM json_each(?))
                    ORDER BY created_at DESC, id DESC""",
                    (conversation_id, owner_id, self._json(turn_ids)),
                ).fetchall()
            else:
                turns = []
        message_items: list[dict[str, object]] = []
        for message in reversed(messages):
            item = dict(message)
            raw_sources = item.pop("sources_json", "[]")
            try:
                source_ids = json.loads(str(raw_sources))
            except json.JSONDecodeError:
                source_ids = []
            if not isinstance(source_ids, list):
                source_ids = []
            source_items = [
                source
                for source in source_ids
                if isinstance(source, dict)
                and isinstance(source.get("source_id"), str)
                and isinstance(source.get("title"), str)
            ][:50]
            message_items.append(
                {
                    "id": item["id"],
                    "turn_id": item["turn_id"],
                    "seq": int(item["sequence"]),
                    "role": item["role"],
                    "text": item["content"],
                    "created_at": item["created_at"],
                    "sources": source_items,
                }
            )
        actions_by_turn: dict[str, list[dict[str, object]]] = {}
        for action_row in actions:
            action = dict(action_row)
            turn_key = str(action["turn_id"])
            action_status = str(action["status"])
            if (
                action_status == "pending"
                and now_text is not None
                and str(action["expires_at"]) <= now_text
            ):
                action_status = "expired"
            public_action: dict[str, object] = {
                "action_id": action["id"],
                "turn_id": action["turn_id"],
                "action_type": action["action_type"],
                "status": action_status,
                "expires_at": action["expires_at"],
                "receipt": None,
            }
            if session_id is not None and action_status in {"pending", "expired"}:
                try:
                    proposal_payload = json.loads(str(action["payload_json"]))
                except json.JSONDecodeError as exc:
                    raise AssistantStorageError("assistant action storage is invalid") from exc
                if not isinstance(proposal_payload, dict):
                    raise AssistantStorageError("assistant action storage is invalid")
                # This internal projection is consumed and sanitized by AssistantService before
                # the API response. The phrase is only materialized for the issuing session.
                public_action["_proposal_payload"] = proposal_payload
                public_action["_proposal_action_version"] = int(action["action_version"])
                public_action["_proposal_context_version"] = str(action["context_version"])
                public_action["_proposal_session_matches"] = action["session_id"] == session_id
            if action.get("receipt_id"):
                try:
                    receipt_data = json.loads(str(action.get("result_json") or "{}"))
                except json.JSONDecodeError:
                    receipt_data = {}
                receipt: dict[str, object] = {
                    "receipt_id": action["receipt_id"],
                    "outcome": action["outcome"],
                    "message": (
                        receipt_data.get("message", "Action completed.")
                        if isinstance(receipt_data, dict)
                        else "Action completed."
                    ),
                }
                destination = (
                    receipt_data.get("destination") if isinstance(receipt_data, dict) else None
                )
                safe_destination = self._safe_destination(destination)
                if safe_destination is not None:
                    receipt["destination"] = safe_destination
                if isinstance(receipt_data, dict):
                    browser_action = self._safe_receipt_browser_action(
                        receipt_data.get("browser_action")
                    )
                    if browser_action is not None:
                        receipt["browser_action"] = browser_action
                public_action["receipt"] = receipt
            actions_by_turn.setdefault(turn_key, []).append(public_action)
        turn_items = [self._public_turn(dict(turn)) for turn in turns]
        for turn in turn_items:
            turn["actions"] = actions_by_turn.get(str(turn["id"]), [])
        action_items = [
            action
            for turn in turn_items
            for action in cast(list[dict[str, object]], turn.get("actions", []))
        ]
        event_items: list[dict[str, object]] = []
        for event_row in reversed(event_rows):
            try:
                event_data = json.loads(str(event_row["payload_json"]))
            except json.JSONDecodeError as exc:
                raise AssistantStorageError("assistant event storage is invalid") from exc
            if not isinstance(event_data, dict):
                raise AssistantStorageError("assistant event storage is invalid")
            if event_row["event_type"] == "proposed_action":
                # Detail replay is content-only. Confirmation material is supplied through the
                # same-session action projection above, never copied into a durable export list.
                event_data.pop("confirmation_phrase", None)
            event_items.append(
                {
                    "turn_id": event_row["turn_id"],
                    "sequence": int(event_row["sequence"]),
                    "type": event_row["event_type"],
                    "data": event_data,
                    "created_at": event_row["created_at"],
                }
            )
        return {
            "conversation": self._public_conversation(dict(row)),
            "messages": {
                "items": message_items,
                "page": message_page,
                "page_size": message_page_size,
                "total": int(total_row[0]) if total_row is not None else 0,
            },
            "turns": turn_items,
            "actions": action_items,
            "action_pagination": {
                "page": action_page,
                "page_size": action_page_size,
                "total": int(action_total_row[0]) if action_total_row is not None else 0,
            },
            "event_pagination": {
                "page": event_page,
                "page_size": event_page_size,
                "total": int(event_total_row[0]) if event_total_row is not None else 0,
            },
            "events": {
                "items": event_items,
                "page": event_page,
                "page_size": event_page_size,
                "total": int(event_total_row[0]) if event_total_row is not None else 0,
            },
        }

    @staticmethod
    def _public_turn(row: Mapping[str, object]) -> dict[str, object]:
        """Decode the canonical safe context snapshot without returning SQL representation."""

        result = dict(row)
        try:
            context = json.loads(str(result.pop("context_json")))
        except json.JSONDecodeError as exc:
            raise AssistantStorageError("assistant context storage is invalid") from exc
        if not isinstance(context, dict):
            raise AssistantStorageError("assistant context storage is invalid")
        result["context"] = context
        return result

    def rename_conversation(
        self,
        user_id: int,
        conversation_id: str,
        *,
        title: str,
        expected_revision: int,
        updated_at: datetime,
    ) -> dict[str, object]:
        """Rename one owner conversation only when its displayed revision is current."""

        owner_id = self._require_owner(user_id)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            raise ValueError("title must be 1-160 characters")
        timestamp = self._timestamp(updated_at)
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM assistant_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
            if current is None:
                raise AssistantStorageNotFound()
            if int(current[0]) != expected_revision:
                raise AssistantStorageConflict("conversation_revision")
            self._ensure_capacity(connection, owner_id, len(title.strip().encode("utf-8")))
            cursor = connection.execute(
                """UPDATE assistant_conversations SET title = ?, revision = revision + 1,
                    updated_at = ? WHERE id = ? AND user_id = ? AND revision = ?""",
                (title.strip(), timestamp, conversation_id, owner_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise AssistantStorageConflict("conversation_revision")
            connection.commit()
        return self.get_conversation(owner_id, conversation_id)

    def delete_conversation(
        self,
        user_id: int,
        conversation_id: str,
        *,
        expected_revision: int,
        confirmation_phrase: str,
        deleted_at: datetime,
    ) -> dict[str, object]:
        """Purge chosen conversation content and leave only a non-content deletion receipt."""

        owner_id = self._require_owner(user_id)
        timestamp = self._timestamp(deleted_at)
        expected_phrase = f"DELETE {conversation_id[-8:]}"
        if not hmac.compare_digest(confirmation_phrase, expected_phrase):
            raise AssistantStorageConflict("delete_confirmation")
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            allocated_bytes_before = self._database_bytes(connection)
            conversation = connection.execute(
                """SELECT revision FROM assistant_conversations
                WHERE id = ? AND user_id = ?""",
                (conversation_id, owner_id),
            ).fetchone()
            if conversation is None:
                raise AssistantStorageNotFound()
            if int(conversation[0]) != expected_revision:
                raise AssistantStorageConflict("conversation_revision")
            content_rows: list[tuple[str, str]] = []
            for table, field in (
                ("assistant_messages", "content"),
                ("assistant_events", "payload_json"),
                ("assistant_sources", "metadata_json"),
                ("assistant_proposed_actions", "payload_json"),
                ("assistant_action_receipts", "result_json"),
                ("assistant_search_previews", "query_text"),
            ):
                rows = connection.execute(  # noqa: S608
                    f"SELECT CAST({field} AS TEXT) FROM {table} "  # noqa: S608
                    "WHERE conversation_id = ? AND user_id = ?",
                    (conversation_id, owner_id),
                ).fetchall()
                content_rows.extend((table, str(row[0])) for row in rows)
            content_rows.sort()
            digest = hashlib.sha256(
                self._json([[table, value] for table, value in content_rows]).encode("utf-8")
            ).hexdigest()
            deleted_bytes = self._conversation_bytes(connection, conversation_id)
            connection.execute(
                """INSERT INTO assistant_conversation_deletions
                (conversation_id, user_id, content_digest, deleted_bytes, deleted_at)
                VALUES (?, ?, ?, ?, ?)""",
                (conversation_id, owner_id, digest, deleted_bytes, timestamp),
            )
            # The tombstone is inserted first so direct SQLite deletes remain owner-visible and
            # trigger-checked; children are removed in FK order within this same transaction.
            for table, conversation_key in (
                ("assistant_search_previews", "conversation_id"),
                ("assistant_action_receipts", "conversation_id"),
                ("assistant_proposed_actions", "conversation_id"),
                ("assistant_messages", "conversation_id"),
                ("assistant_events", "conversation_id"),
                ("assistant_sources", "conversation_id"),
                ("assistant_execution_leases", "conversation_id"),
                ("assistant_turns", "conversation_id"),
                ("assistant_conversations", "id"),
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE {conversation_key} = ? AND user_id = ?",  # noqa: S608
                    (conversation_id, owner_id),
                )
            # Existing market-data rows can put the shared database above the assistant's write
            # cap. Deletion must still release assistant content in that state, while its small
            # tombstone may not increase allocated SQLite pages beyond the pre-delete size.
            if self._database_bytes(connection) > allocated_bytes_before:
                raise AssistantStorageQuotaExceeded("database")
            connection.commit()
        return {
            "conversation_id": conversation_id,
            "deleted_at": timestamp,
            "deleted_bytes": deleted_bytes,
            "content_digest": digest,
            "canonical_content_removed": True,
        }

    def validate_conversation_delete(
        self,
        user_id: int,
        conversation_id: str,
        *,
        expected_revision: int,
        confirmation_phrase: str,
    ) -> None:
        """Check owner, revision, and phrase before any runtime cancellation or purge request.

        The destructive transaction repeats these checks after cache sanitation to close the
        race with a concurrent rename or turn update.
        """

        owner_id = self._require_owner(user_id)
        expected_phrase = f"DELETE {conversation_id[-8:]}"
        if not hmac.compare_digest(confirmation_phrase, expected_phrase):
            raise AssistantStorageConflict("delete_confirmation")
        with self._repository.connect() as connection:
            conversation = connection.execute(
                "SELECT revision FROM assistant_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
        if conversation is None:
            raise AssistantStorageNotFound()
        if int(conversation[0]) != expected_revision:
            raise AssistantStorageConflict("conversation_revision")

    def create_consent(
        self,
        user_id: int,
        *,
        model_id: str,
        policy_version: str,
        accepted_terms: bool,
        data_collection_opt_in: bool,
        recorded_at: datetime,
    ) -> dict[str, object]:
        """Append an explicit model-policy acceptance or revocation without rewriting history."""

        owner_id = self._require_owner(user_id)
        if not isinstance(model_id, str) or not 1 <= len(model_id.strip()) <= 160:
            raise ValueError("model_id is invalid")
        if not isinstance(policy_version, str) or not 1 <= len(policy_version.strip()) <= 80:
            raise ValueError("policy_version is invalid")
        if type(accepted_terms) is not bool or type(data_collection_opt_in) is not bool:
            raise ValueError("consent flags must be boolean")
        if data_collection_opt_in and not accepted_terms:
            raise ValueError("data collection opt-in requires accepted terms")
        timestamp = self._timestamp(recorded_at)
        consent_id = self._new_id()
        size = len(model_id.encode("utf-8")) + len(policy_version.encode("utf-8"))
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(connection, owner_id, size)
            self._repository._ensure_owner_can_write(connection, owner_id)
            connection.execute(
                """INSERT INTO assistant_model_consents
                (id, user_id, model_id, policy_version, accepted_terms,
                 data_collection_opt_in, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    consent_id,
                    owner_id,
                    model_id.strip(),
                    policy_version.strip(),
                    int(accepted_terms),
                    int(data_collection_opt_in),
                    timestamp,
                ),
            )
            self._verify_database_limit(connection)
            connection.commit()
        result = self.current_consent(owner_id, model_id.strip(), policy_version.strip())
        if result is None:
            raise AssistantStorageError("assistant consent could not be read")
        return result

    def current_consent(
        self, user_id: int, model_id: str, policy_version: str
    ) -> dict[str, object] | None:
        """Return only the latest consent record for an exact owner/model/policy pair."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT id, model_id, policy_version, accepted_terms,
                    data_collection_opt_in, recorded_at
                FROM assistant_model_consents
                WHERE user_id = ? AND model_id = ? AND policy_version = ?
                ORDER BY rowid DESC LIMIT 1""",
                (owner_id, model_id, policy_version),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["accepted_terms"] = bool(result["accepted_terms"])
        result["data_collection_opt_in"] = bool(result["data_collection_opt_in"])
        return result

    def consent_summaries(self, user_id: int) -> list[dict[str, object]]:
        """Return one latest consent result per model and policy without exposing identifiers."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            rows = connection.execute(
                """SELECT consent.id, consent.model_id, consent.policy_version,
                    consent.accepted_terms, consent.data_collection_opt_in, consent.recorded_at
                FROM assistant_model_consents AS consent
                WHERE consent.user_id = ? AND consent.id = (
                    SELECT latest.id FROM assistant_model_consents AS latest
                    WHERE latest.user_id = consent.user_id
                      AND latest.model_id = consent.model_id
                      AND latest.policy_version = consent.policy_version
                    ORDER BY latest.rowid DESC LIMIT 1
                ) ORDER BY consent.model_id, consent.policy_version""",
                (owner_id,),
            ).fetchall()
        return [
            {
                **dict(row),
                "accepted_terms": bool(row["accepted_terms"]),
                "data_collection_opt_in": bool(row["data_collection_opt_in"]),
            }
            for row in rows
        ]

    def create_turn(
        self,
        user_id: int,
        conversation_id: str,
        *,
        prompt: str,
        model_id: str,
        policy_version: str,
        context: Mapping[str, object],
        context_version: str,
        session_id: str,
        session_token_hash: str,
        capability: str,
        now: datetime,
        expires_at: datetime,
    ) -> dict[str, object]:
        """Atomically claim one global/user slot and persist a prompt plus execution lease."""

        owner_id = self._require_owner(user_id)
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 8192:
            raise ValueError("prompt must be 1-8192 characters")
        if not session_id or not 16 <= len(session_id) <= 128:
            raise ValueError("session_id is invalid")
        if not isinstance(session_token_hash, str) or len(session_token_hash) != 64:
            raise ValueError("session_token_hash is invalid")
        if not isinstance(capability, str) or not 32 <= len(capability) <= 256:
            raise ValueError("execution capability is invalid")
        if not isinstance(model_id, str) or not 1 <= len(model_id) <= 160:
            raise ValueError("model_id is invalid")
        if not isinstance(policy_version, str) or not 1 <= len(policy_version) <= 80:
            raise ValueError("policy_version is invalid")
        context_json = self._json(context)
        if len(context_json.encode("utf-8")) > 8192:
            raise ValueError("assistant context is too large")
        created_text = self._timestamp(now)
        expires_text = self._timestamp(expires_at)
        turn_id = self._new_id()
        execution_id = uuid4().hex
        message_id = self._new_id()
        capability_hash = hashlib.sha256(capability.encode("utf-8")).hexdigest()
        session_hash = session_token_hash
        user_bytes = (
            len(prompt.strip().encode("utf-8"))
            + len(model_id.encode("utf-8"))
            + len(policy_version.encode("utf-8"))
            + len(context_json.encode("utf-8"))
            + 1000
        )
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(connection, owner_id, user_bytes)
            self._repository._ensure_owner_can_write(connection, owner_id)
            active_user = connection.execute(
                """SELECT COUNT(*) FROM assistant_turns
                WHERE user_id = ? AND status IN ('queued', 'running')""",
                (owner_id,),
            ).fetchone()
            active_global = connection.execute(
                """SELECT COUNT(*) FROM assistant_turns
                WHERE status IN ('queued', 'running')"""
            ).fetchone()
            if int(active_user[0]) >= ASSISTANT_ACTIVE_PER_USER:
                raise AssistantStorageBusy("user")
            if int(active_global[0]) >= ASSISTANT_ACTIVE_GLOBAL:
                raise AssistantStorageBusy("global")
            conversation = connection.execute(
                "SELECT 1 FROM assistant_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, owner_id),
            ).fetchone()
            if conversation is None:
                raise AssistantStorageNotFound()
            user_sequence = int(
                connection.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_messages
                    WHERE conversation_id = ?""",
                    (conversation_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """INSERT INTO assistant_turns
                (id, conversation_id, user_id, status, model_id, policy_version,
                 context_json, context_version, created_at)
                VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
                (
                    turn_id,
                    conversation_id,
                    owner_id,
                    model_id,
                    policy_version,
                    context_json,
                    context_version,
                    created_text,
                ),
            )
            connection.execute(
                """INSERT INTO assistant_messages
                (id, conversation_id, turn_id, user_id, sequence, role, content, created_at)
                VALUES (?, ?, ?, ?, ?, 'user', ?, ?)""",
                (
                    message_id,
                    conversation_id,
                    turn_id,
                    owner_id,
                    user_sequence,
                    prompt.strip(),
                    created_text,
                ),
            )
            connection.execute(
                """INSERT INTO assistant_execution_leases
                (execution_id, conversation_id, turn_id, user_id, session_id, session_token_hash,
                 capability_hash, app_id, context_version, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'signal-ledger', ?, 'active', ?, ?)""",
                (
                    execution_id,
                    conversation_id,
                    turn_id,
                    owner_id,
                    session_id,
                    session_hash,
                    capability_hash,
                    context_version,
                    created_text,
                    expires_text,
                ),
            )
            connection.execute(
                """UPDATE assistant_conversations
                SET revision = revision + 1, updated_at = ?
                WHERE id = ? AND user_id = ?""",
                (created_text, conversation_id, owner_id),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "id": turn_id,
            "execution_id": execution_id,
            "message_id": message_id,
            "status": "queued",
            "created_at": created_text,
            "expires_at": expires_text,
        }

    def get_turn(self, user_id: int, conversation_id: str, turn_id: str) -> dict[str, object]:
        """Read one turn only through the owner/conversation composite identity."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT id, conversation_id, user_id, status, model_id, policy_version,
                    context_json, context_version, created_at, started_at, completed_at, error_code
                FROM assistant_turns
                WHERE id = ? AND conversation_id = ? AND user_id = ?""",
                (turn_id, conversation_id, owner_id),
            ).fetchone()
        if row is None:
            raise AssistantStorageNotFound()
        return dict(row)

    def conversation_history(
        self,
        user_id: int,
        conversation_id: str,
        *,
        exclude_turn_id: str,
        max_messages: int = 12,
        max_bytes: int = 32 * 1024,
    ) -> tuple[dict[str, str], ...]:
        """Load a small owner-only transcript window from canonical SQLite for a fresh runtime."""

        owner_id = self._require_owner(user_id)
        if not 1 <= max_messages <= 20 or not 1024 <= max_bytes <= 32 * 1024:
            raise ValueError("assistant transcript window exceeds its fixed bound")
        with self._repository.connect() as connection:
            rows = connection.execute(
                """SELECT role, content FROM assistant_messages
                WHERE user_id = ? AND conversation_id = ? AND turn_id != ?
                ORDER BY sequence DESC LIMIT ?""",
                (owner_id, conversation_id, exclude_turn_id, max_messages),
            ).fetchall()
        selected: list[dict[str, str]] = []
        used = 0
        for row in reversed(rows):
            role = str(row["role"])
            content = str(row["content"])
            encoded_size = len(content.encode("utf-8"))
            if role not in {"user", "assistant"} or used + encoded_size > max_bytes:
                continue
            selected.append({"role": role, "text": content})
            used += encoded_size
        return tuple(selected)

    def set_turn_status(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        status: str,
        now: datetime,
        error_code: str | None = None,
    ) -> bool:
        """Apply one allowed lifecycle transition and append no terminal data on a lost race."""

        owner_id = self._require_owner(user_id)
        if status not in {"running", "completed", "cancelled", "failed", "timed_out"}:
            raise ValueError("assistant turn status is not supported")
        timestamp = self._timestamp(now)
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT status FROM assistant_turns
                WHERE id = ? AND conversation_id = ? AND user_id = ?""",
                (turn_id, conversation_id, owner_id),
            ).fetchone()
            if row is None:
                raise AssistantStorageNotFound()
            if row[0] in {"completed", "cancelled", "failed", "timed_out"}:
                connection.rollback()
                return False
            if status == "running":
                cursor = connection.execute(
                    """UPDATE assistant_turns SET status = 'running', started_at = ?
                    WHERE id = ? AND conversation_id = ? AND user_id = ? AND status = 'queued'""",
                    (timestamp, turn_id, conversation_id, owner_id),
                )
            else:
                cursor = connection.execute(
                    """UPDATE assistant_turns SET status = ?, completed_at = ?, error_code = ?
                    WHERE id = ? AND conversation_id = ? AND user_id = ?
                      AND status IN ('queued', 'running')""",
                    (status, timestamp, error_code, turn_id, conversation_id, owner_id),
                )
            connection.commit()
        return cursor.rowcount == 1

    def append_message(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        role: str,
        content: str,
        now: datetime,
    ) -> dict[str, object]:
        """Append one bounded assistant completion after all runtime events are normalized."""

        owner_id = self._require_owner(user_id)
        if (
            role != "assistant"
            or not isinstance(content, str)
            or len(content.encode("utf-8")) > 65_536
        ):
            raise ValueError("assistant message is invalid")
        timestamp = self._timestamp(now)
        message_id = self._new_id()
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(connection, owner_id, len(content.encode("utf-8")) + 100)
            turn = connection.execute(
                """SELECT 1 FROM assistant_turns
                WHERE id = ? AND conversation_id = ? AND user_id = ? AND status = 'running'""",
                (turn_id, conversation_id, owner_id),
            ).fetchone()
            if turn is None:
                raise AssistantStorageConflict("turn_not_running")
            sequence = int(
                connection.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_messages
                    WHERE conversation_id = ?""",
                    (conversation_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """INSERT INTO assistant_messages
                (id, conversation_id, turn_id, user_id, sequence, role, content, created_at)
                VALUES (?, ?, ?, ?, ?, 'assistant', ?, ?)""",
                (message_id, conversation_id, turn_id, owner_id, sequence, content, timestamp),
            )
            connection.execute(
                """UPDATE assistant_conversations SET revision = revision + 1, updated_at = ?
                WHERE id = ? AND user_id = ?""",
                (timestamp, conversation_id, owner_id),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "id": message_id,
            "turn_id": turn_id,
            "sequence": sequence,
            "role": "assistant",
            "text": content,
            "created_at": timestamp,
        }

    def append_event(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        event_type: str,
        data: Mapping[str, object],
        now: datetime,
    ) -> dict[str, object]:
        """Persist one normalized SSE event under the current owner's turn sequence."""

        owner_id = self._require_owner(user_id)
        if event_type not in _EVENT_TYPES:
            raise ValueError("assistant event type is not supported")
        payload_json = self._json(data)
        payload_bytes = len(payload_json.encode("utf-8"))
        if payload_bytes > 16_384:
            raise ValueError("assistant event payload is too large")
        timestamp = self._timestamp(now)
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(
                connection, owner_id, payload_bytes + len(event_type.encode()) + 64
            )
            turn = connection.execute(
                """SELECT 1 FROM assistant_turns
                WHERE id = ? AND conversation_id = ? AND user_id = ?""",
                (turn_id, conversation_id, owner_id),
            ).fetchone()
            if turn is None:
                raise AssistantStorageNotFound()
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_events WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """INSERT INTO assistant_events
                (conversation_id, turn_id, user_id, sequence, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (conversation_id, turn_id, owner_id, sequence, event_type, payload_json, timestamp),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "sequence": sequence,
            "type": event_type,
            "data": dict(data),
            "created_at": timestamp,
        }

    def append_tool_receipt(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        data: Mapping[str, object],
        sources: Sequence[Mapping[str, object]],
        now: datetime,
    ) -> dict[str, object]:
        """Atomically persist a compact MCP receipt with its bounded public citations."""

        owner_id = self._require_owner(user_id)
        if len(sources) > 5:
            raise ValueError("assistant tool sources exceed the per-call bound")
        timestamp = self._timestamp(now)
        source_records: list[dict[str, object]] = []
        additional = 0
        for source in sources:
            title = source.get("title")
            url = source.get("url")
            source_ref = source.get("source_ref")
            retrieved = source.get("retrieved_at", now)
            as_of = source.get("as_of")
            if (
                not isinstance(title, str)
                or not 1 <= len(title) <= 300
                or not isinstance(url, str)
                or not 1 <= len(url) <= 2048
                or (
                    source_ref is not None
                    and (not isinstance(source_ref, str) or len(source_ref) > 256)
                )
                or not isinstance(retrieved, datetime)
                or (as_of is not None and not isinstance(as_of, datetime))
            ):
                raise ValueError("assistant source receipt is invalid")
            source_id = self._new_id()
            retrieved_text = self._timestamp(retrieved)
            as_of_text = self._timestamp(as_of) if isinstance(as_of, datetime) else None
            source_event = {
                "source_id": source_id,
                "title": title,
                "url": url,
                "source_type": "market_news",
                "retrieved_at": retrieved_text,
                "as_of": as_of_text,
            }
            source_event_json = self._json(source_event)
            source_records.append(
                {
                    "id": source_id,
                    "title": title,
                    "url": url,
                    "source_ref": source_ref,
                    "retrieved_at": retrieved_text,
                    "as_of": as_of_text,
                    "event_json": source_event_json,
                }
            )
            additional += (
                sum(
                    len(value.encode("utf-8"))
                    for value in (title, url, source_ref or "", "{}", source_event_json, "source")
                )
                + 128
            )

        event_data = dict(data)
        event_data["source_ids"] = [str(source["id"]) for source in source_records]
        event_json = self._json(event_data)
        if len(event_json.encode("utf-8")) > 16_384:
            raise ValueError("assistant tool receipt is too large")
        additional += len(event_json.encode("utf-8")) + len("tool") + 64
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(connection, owner_id, additional)
            turn = connection.execute(
                """SELECT 1 FROM assistant_turns
                WHERE id = ? AND conversation_id = ? AND user_id = ?""",
                (turn_id, conversation_id, owner_id),
            ).fetchone()
            if turn is None:
                raise AssistantStorageNotFound()
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_events WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()[0]
            )
            for source in source_records:
                connection.execute(
                    """INSERT INTO assistant_sources
                    (id, conversation_id, turn_id, user_id, source_type, title, url, source_ref,
                     retrieved_at, as_of, metadata_json)
                    VALUES (?, ?, ?, ?, 'market_news', ?, ?, ?, ?, ?, '{}')""",
                    (
                        source["id"],
                        conversation_id,
                        turn_id,
                        owner_id,
                        source["title"],
                        source["url"],
                        source["source_ref"],
                        source["retrieved_at"],
                        source["as_of"],
                    ),
                )
                connection.execute(
                    """INSERT INTO assistant_events
                    (conversation_id, turn_id, user_id, sequence, event_type, payload_json,
                     created_at)
                    VALUES (?, ?, ?, ?, 'source', ?, ?)""",
                    (
                        conversation_id,
                        turn_id,
                        owner_id,
                        sequence,
                        source["event_json"],
                        timestamp,
                    ),
                )
                sequence += 1
            connection.execute(
                """INSERT INTO assistant_events
                (conversation_id, turn_id, user_id, sequence, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, 'tool', ?, ?)""",
                (conversation_id, turn_id, owner_id, sequence, event_json, timestamp),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {"sequence": sequence, "type": "tool", "data": event_data, "created_at": timestamp}

    def events_after(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        after: int,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Return replayable events after a numeric stream cursor for this owner only."""

        owner_id = self._require_owner(user_id)
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("event cursor or limit is invalid")
        with self._repository.connect() as connection:
            rows = connection.execute(
                """SELECT event.sequence, event.event_type, event.payload_json, event.created_at
                FROM assistant_events AS event
                JOIN assistant_turns AS turn
                  ON turn.id = event.turn_id AND turn.conversation_id = event.conversation_id
                 AND turn.user_id = event.user_id
                WHERE event.user_id = ? AND event.conversation_id = ? AND event.turn_id = ?
                  AND event.sequence > ?
                ORDER BY event.sequence LIMIT ?""",
                (owner_id, conversation_id, turn_id, after, limit),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            try:
                payload = json.loads(str(item.pop("payload_json")))
            except json.JSONDecodeError as exc:
                raise AssistantStorageError("assistant event storage is invalid") from exc
            if not isinstance(payload, dict):
                raise AssistantStorageError("assistant event storage is invalid")
            result.append(
                {
                    "sequence": int(item["sequence"]),
                    "type": item["event_type"],
                    "data": cast(dict[str, object], payload),
                    "created_at": item["created_at"],
                }
            )
        return result

    def has_useful_turn_output(self, user_id: int, conversation_id: str, turn_id: str) -> bool:
        """Recognize durable citations/actions as a response when no assistant text exists."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT
                    EXISTS(SELECT 1 FROM assistant_sources
                           WHERE user_id = ? AND conversation_id = ? AND turn_id = ?)
                    OR EXISTS(SELECT 1 FROM assistant_proposed_actions
                              WHERE user_id = ? AND conversation_id = ? AND turn_id = ?)""",
                (owner_id, conversation_id, turn_id, owner_id, conversation_id, turn_id),
            ).fetchone()
        return bool(row and row[0])

    def latest_event_sequence(self, user_id: int, conversation_id: str, turn_id: str) -> int:
        """Read a single owner's highest durable SSE cursor for reconnect handling."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT COALESCE(MAX(sequence), 0) FROM assistant_events
                WHERE user_id = ? AND conversation_id = ? AND turn_id = ?""",
                (owner_id, conversation_id, turn_id),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def execution_lease(self, execution_id: str) -> dict[str, object] | None:
        """Read one private lease by execution identifier for runtime tool authorization."""

        if not isinstance(execution_id, str) or len(execution_id) != 32:
            return None
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT execution_id, conversation_id, turn_id, user_id, session_id,
                    session_token_hash, capability_hash, app_id, context_version,
                    private_read_seen, tool_calls, status, created_at, expires_at, closed_at
                FROM assistant_execution_leases WHERE execution_id = ?""",
                (execution_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def execution_for_turn(
        self, user_id: int, conversation_id: str, turn_id: str
    ) -> dict[str, object] | None:
        """Resolve the one owner-bound ephemeral lease used to cancel a persisted turn."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT execution_id, status FROM assistant_execution_leases
                WHERE user_id = ? AND conversation_id = ? AND turn_id = ?""",
                (owner_id, conversation_id, turn_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def active_conversation_executions(self, user_id: int, conversation_id: str) -> list[str]:
        """Return only active execution IDs needed to stop and erase deleted chat sessions."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            rows = connection.execute(
                """SELECT execution_id FROM assistant_execution_leases
                WHERE user_id = ? AND conversation_id = ? AND status = 'active'""",
                (owner_id, conversation_id),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def authorize_tool_call(
        self,
        execution_id: str,
        capability: str,
        *,
        now: datetime,
        marks_private_read: bool,
    ) -> dict[str, object]:
        """Consume one bounded tool-call slot and return the persisted session binding."""

        timestamp = self._timestamp(now)
        capability_hash = hashlib.sha256(capability.encode("utf-8")).hexdigest()
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT execution_id, conversation_id, turn_id, user_id, session_id,
                    session_token_hash, capability_hash, app_id, context_version,
                    private_read_seen, tool_calls, status, created_at, expires_at
                FROM assistant_execution_leases WHERE execution_id = ?""",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise AssistantStorageNotFound()
            lease = dict(row)
            if lease["status"] != "active" or str(lease["expires_at"]) <= timestamp:
                raise AssistantStorageConflict("execution_expired")
            stored_hash = lease.get("capability_hash")
            if not isinstance(stored_hash, str) or not hmac.compare_digest(
                stored_hash, capability_hash
            ):
                raise AssistantStorageNotFound()
            count = int(lease["tool_calls"])
            if count >= ASSISTANT_TOOLS_PER_TURN:
                raise AssistantStorageQuotaExceeded("tool_calls")
            cursor = connection.execute(
                """UPDATE assistant_execution_leases
                SET tool_calls = tool_calls + 1,
                    private_read_seen = CASE WHEN ? THEN 1 ELSE private_read_seen END
                WHERE execution_id = ? AND status = 'active' AND tool_calls = ?""",
                (int(marks_private_read), execution_id, count),
            )
            if cursor.rowcount != 1:
                raise AssistantStorageConflict("execution_race")
            connection.commit()
        lease["tool_calls"] = count + 1
        if marks_private_read:
            lease["private_read_seen"] = 1
        return lease

    def validate_execution_capability(
        self,
        execution_id: str,
        capability: str,
        *,
        now: datetime,
    ) -> dict[str, object]:
        """Authenticate one MCP request without consuming a tool-call slot.

        Discovery, initialization, and notifications still require the same per-turn bearer
        capability as a tool call. Keeping this separate from ``authorize_tool_call`` means
        harmless protocol setup cannot exhaust the eight actual application operations.
        """

        if not isinstance(capability, str) or not 32 <= len(capability) <= 128:
            raise AssistantStorageNotFound()
        timestamp = self._timestamp(now)
        capability_hash = hashlib.sha256(capability.encode("utf-8")).hexdigest()
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT execution_id, conversation_id, turn_id, user_id, session_id,
                    session_token_hash, capability_hash, app_id, context_version,
                    private_read_seen, tool_calls, status, expires_at
                FROM assistant_execution_leases WHERE execution_id = ?""",
                (execution_id,),
            ).fetchone()
        if row is None:
            raise AssistantStorageNotFound()
        lease = dict(row)
        stored_hash = lease.get("capability_hash")
        if (
            lease.get("status") != "active"
            or str(lease.get("expires_at", "")) <= timestamp
            or lease.get("app_id") != "signal-ledger"
            or not isinstance(stored_hash, str)
            or not hmac.compare_digest(stored_hash, capability_hash)
        ):
            raise AssistantStorageNotFound()
        return lease

    def close_execution(self, execution_id: str, *, now: datetime, revoked: bool = False) -> None:
        """Revoke the lease so no tool request can continue after the turn completes."""

        timestamp = self._timestamp(now)
        target = "revoked" if revoked else "closed"
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE assistant_execution_leases
                SET status = ?, closed_at = ?
                WHERE execution_id = ? AND status = 'active'""",
                (target, timestamp, execution_id),
            )
            connection.commit()

    def interrupt_active_turns(self, *, now: datetime) -> list[dict[str, object]]:
        """Mark process-lost work interrupted at boot; transcript data is retained."""

        timestamp = self._timestamp(now)
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT id, conversation_id, user_id FROM assistant_turns
                WHERE status IN ('queued', 'running')"""
            ).fetchall()
            interrupted = [dict(row) for row in rows]
            connection.execute(
                """UPDATE assistant_turns SET status = 'failed', completed_at = ?,
                    error_code = 'runtime_restarted'
                WHERE status IN ('queued', 'running')""",
                (timestamp,),
            )
            connection.execute(
                """UPDATE assistant_execution_leases SET status = 'closed', closed_at = ?
                WHERE status = 'active'""",
                (timestamp,),
            )
            connection.commit()
        return interrupted

    def create_source(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        source_type: str,
        title: str,
        url: str | None,
        source_ref: str | None,
        retrieved_at: datetime,
        as_of: datetime | None,
        metadata: Mapping[str, object],
    ) -> dict[str, object]:
        """Append a bounded provenance receipt after tool-specific URL validation."""

        owner_id = self._require_owner(user_id)
        metadata_json = self._json(metadata)
        timestamp = self._timestamp(retrieved_at)
        as_of_text = self._timestamp(as_of) if as_of is not None else None
        source_id = self._new_id()
        row = {
            "id": source_id,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "user_id": owner_id,
            "source_type": source_type,
            "title": title,
            "url": url,
            "source_ref": source_ref,
            "retrieved_at": timestamp,
            "as_of": as_of_text,
            "metadata_json": metadata_json,
        }
        additional = sum(
            len(value.encode("utf-8"))
            for value in (source_type, title, url or "", source_ref or "", metadata_json)
        )
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(connection, owner_id, additional)
            connection.execute(
                """INSERT INTO assistant_sources
                (id, conversation_id, turn_id, user_id, source_type, title, url, source_ref,
                 retrieved_at, as_of, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_id,
                    conversation_id,
                    turn_id,
                    owner_id,
                    source_type,
                    title,
                    url,
                    source_ref,
                    timestamp,
                    as_of_text,
                    metadata_json,
                ),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {key: value for key, value in row.items() if key != "metadata_json"} | {
            "metadata": dict(metadata)
        }

    def create_action(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        *,
        action_type: str,
        payload: Mapping[str, object],
        action_version: int,
        session_id: str,
        context_version: str,
        execution_id: str,
        confirmation_phrase: str,
        now: datetime,
        expires_at: datetime,
    ) -> dict[str, object]:
        """Persist an immutable typed proposal; only browser confirmation can move it forward."""

        owner_id = self._require_owner(user_id)
        payload_json = self._json(payload)
        if len(payload_json.encode("utf-8")) > 8192:
            raise ValueError("assistant action preview is too large")
        action_id = self._new_id()
        timestamp = self._timestamp(now)
        expiry = self._timestamp(expires_at)
        if not isinstance(session_id, str) or not 16 <= len(session_id) <= 128:
            raise ValueError("assistant action session binding is invalid")
        if not isinstance(context_version, str) or len(context_version) != 64:
            raise ValueError("assistant action context binding is invalid")
        confirmation_phrase = f"CONFIRM {action_id[-8:]}"
        phrase_hash = hashlib.sha256(confirmation_phrase.encode("utf-8")).hexdigest()
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(
                connection, owner_id, len(action_type.encode()) + len(payload_json.encode()) + 256
            )
            lease = connection.execute(
                """SELECT 1 FROM assistant_execution_leases
                WHERE execution_id = ? AND turn_id = ? AND conversation_id = ?
                  AND user_id = ? AND session_id = ? AND context_version = ?
                  AND status = 'active' AND expires_at > ?""",
                (
                    execution_id,
                    turn_id,
                    conversation_id,
                    owner_id,
                    session_id,
                    context_version,
                    timestamp,
                ),
            ).fetchone()
            if lease is None:
                raise AssistantStorageConflict("action_execution_stale")
            connection.execute(
                """INSERT INTO assistant_proposed_actions
                (id, conversation_id, turn_id, user_id, session_id, context_version,
                 action_type, payload_json,
                 action_version, confirmation_phrase_hash, status, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    action_id,
                    conversation_id,
                    turn_id,
                    owner_id,
                    session_id,
                    context_version,
                    action_type,
                    payload_json,
                    action_version,
                    phrase_hash,
                    expiry,
                    timestamp,
                ),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "id": action_id,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "action_type": action_type,
            "session_id": session_id,
            "context_version": context_version,
            "payload": dict(payload),
            "action_version": action_version,
            "status": "pending",
            "expires_at": expiry,
            "created_at": timestamp,
            "confirmation_phrase": confirmation_phrase,
        }

    def get_action(self, user_id: int, action_id: str) -> dict[str, object]:
        """Read one immutable proposal only for its owning account."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT id, conversation_id, turn_id, user_id, session_id,
                    context_version, action_type, payload_json,
                    action_version, confirmation_phrase_hash, status, expires_at, created_at,
                    completed_at
                FROM assistant_proposed_actions WHERE id = ? AND user_id = ?""",
                (action_id, owner_id),
            ).fetchone()
        if row is None:
            raise AssistantStorageNotFound()
        action = dict(row)
        try:
            payload = json.loads(str(action.pop("payload_json")))
        except json.JSONDecodeError as exc:
            raise AssistantStorageError("assistant action storage is invalid") from exc
        action["payload"] = payload if isinstance(payload, dict) else {}
        action["confirmation_phrase"] = f"CONFIRM {str(action_id)[-8:]}"
        return action

    def get_action_receipt(self, user_id: int, action_id: str) -> dict[str, object] | None:
        """Read one owner-scoped finalized action receipt after an ambiguous commit result."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT id, action_id, outcome, result_json, created_at
                FROM assistant_action_receipts WHERE action_id = ? AND user_id = ?""",
                (action_id, owner_id),
            ).fetchone()
        if row is None:
            return None
        receipt = dict(row)
        try:
            result = json.loads(str(receipt.pop("result_json")))
        except json.JSONDecodeError as exc:
            raise AssistantStorageError("assistant action receipt storage is invalid") from exc
        if not isinstance(result, dict):
            raise AssistantStorageError("assistant action receipt storage is invalid")
        receipt["result"] = result
        return receipt

    def claim_action(
        self,
        user_id: int,
        action_id: str,
        *,
        action_version: int,
        confirmation_phrase: str,
        session_id: str,
        context_version: str,
        now: datetime,
    ) -> dict[str, object]:
        """Consume one pending action before the dispatcher performs its exact typed mutation."""

        owner_id = self._require_owner(user_id)
        timestamp = self._timestamp(now)
        supplied_hash = hashlib.sha256(confirmation_phrase.encode("utf-8")).hexdigest()
        reserved_json = self._json(
            {
                "message": "The confirmed action is executing.",
                "_reserve": "x" * 3800,
            }
        )
        if len(reserved_json.encode("utf-8")) > 4096:
            raise AssistantStorageError("assistant receipt reservation is invalid")
        receipt_id = self._new_id()
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id, conversation_id, turn_id, user_id, session_id,
                    context_version, action_type, payload_json,
                    action_version, confirmation_phrase_hash, status, expires_at, created_at
                FROM assistant_proposed_actions WHERE id = ? AND user_id = ?""",
                (action_id, owner_id),
            ).fetchone()
            if row is None:
                raise AssistantStorageNotFound()
            action = dict(row)
            if action["status"] != "pending":
                raise AssistantStorageConflict("action_replayed")
            if str(action["expires_at"]) <= timestamp:
                connection.execute(
                    """UPDATE assistant_proposed_actions
                    SET status = 'expired', completed_at = ? WHERE id = ?""",
                    (timestamp, action_id),
                )
                connection.commit()
                raise AssistantStorageConflict("action_expired")
            if int(action["action_version"]) != action_version:
                raise AssistantStorageConflict("action_version")
            if (
                action.get("session_id") != session_id
                or action.get("context_version") != context_version
            ):
                raise AssistantStorageConflict("action_context_stale")
            stored_hash = action.get("confirmation_phrase_hash")
            if not isinstance(stored_hash, str) or not hmac.compare_digest(
                stored_hash, supplied_hash
            ):
                raise AssistantStorageConflict("action_confirmation")
            # Reserve the terminal receipt and its bounded database/history space before a
            # domain service can commit a mutation. Finalizing this row only shrinks its payload.
            self._ensure_capacity(connection, owner_id, len(reserved_json.encode("utf-8")) + 192)
            cursor = connection.execute(
                """UPDATE assistant_proposed_actions SET status = 'executing'
                WHERE id = ? AND user_id = ? AND status = 'pending' AND action_version = ?""",
                (action_id, owner_id, action_version),
            )
            if cursor.rowcount != 1:
                raise AssistantStorageConflict("action_replayed")
            connection.execute(
                """INSERT INTO assistant_action_receipts
                (id, action_id, conversation_id, user_id, outcome, result_json, created_at)
                VALUES (?, ?, ?, ?, 'executing', ?, ?)""",
                (
                    receipt_id,
                    action_id,
                    str(action["conversation_id"]),
                    owner_id,
                    reserved_json,
                    timestamp,
                ),
            )
            self._verify_database_limit(connection)
            connection.commit()
        try:
            payload = json.loads(str(action.pop("payload_json")))
        except json.JSONDecodeError as exc:
            raise AssistantStorageError("assistant action storage is invalid") from exc
        action["payload"] = payload if isinstance(payload, dict) else {}
        return action

    def deny_action(
        self,
        user_id: int,
        action_id: str,
        *,
        action_version: int,
        session_id: str,
        context_version: str,
        now: datetime,
    ) -> dict[str, object]:
        """Record an explicit browser decline without requiring mutation confirmation text."""

        owner_id = self._require_owner(user_id)
        timestamp = self._timestamp(now)
        receipt_id = self._new_id()
        result_json = self._json({"message": "The proposed action was declined."})
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT conversation_id, session_id, context_version, action_version,
                status, expires_at
                FROM assistant_proposed_actions WHERE id = ? AND user_id = ?""",
                (action_id, owner_id),
            ).fetchone()
            if row is None:
                raise AssistantStorageNotFound()
            if row["status"] != "pending":
                raise AssistantStorageConflict("action_replayed")
            if int(row["action_version"]) != action_version:
                raise AssistantStorageConflict("action_version")
            if row["session_id"] != session_id or row["context_version"] != context_version:
                raise AssistantStorageConflict("action_context_stale")
            if str(row["expires_at"]) <= timestamp:
                connection.execute(
                    "UPDATE assistant_proposed_actions SET status = 'expired', completed_at = ? "
                    "WHERE id = ? AND user_id = ? AND status = 'pending'",
                    (timestamp, action_id, owner_id),
                )
                connection.commit()
                raise AssistantStorageConflict("action_expired")
            connection.execute(
                """UPDATE assistant_proposed_actions SET status = 'denied', completed_at = ?
                WHERE id = ? AND user_id = ? AND status = 'pending' AND action_version = ?""",
                (timestamp, action_id, owner_id, action_version),
            )
            connection.execute(
                """INSERT INTO assistant_action_receipts
                (id, action_id, conversation_id, user_id, outcome, result_json, created_at)
                VALUES (?, ?, ?, ?, 'denied', ?, ?)""",
                (
                    receipt_id,
                    action_id,
                    str(row["conversation_id"]),
                    owner_id,
                    result_json,
                    timestamp,
                ),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "id": receipt_id,
            "action_id": action_id,
            "outcome": "denied",
            "result": {"message": "The proposed action was declined."},
            "created_at": timestamp,
        }

    def finish_action(
        self,
        user_id: int,
        action_id: str,
        *,
        outcome: str,
        result: Mapping[str, object],
        now: datetime,
    ) -> dict[str, object]:
        """Persist one bounded non-secret execution receipt for a claimed action."""

        owner_id = self._require_owner(user_id)
        if outcome not in {"applied", "handed_off", "denied", "failed"}:
            raise ValueError("action result is not supported")
        result_json = self._json(result)
        if len(result_json.encode("utf-8")) > 4096:
            raise ValueError("assistant action receipt is too large")
        timestamp = self._timestamp(now)
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = connection.execute(
                """SELECT conversation_id FROM assistant_proposed_actions
                WHERE id = ? AND user_id = ? AND status = 'executing'""",
                (action_id, owner_id),
            ).fetchone()
            if action is None:
                raise AssistantStorageConflict("action_not_executing")
            receipt = connection.execute(
                """SELECT id FROM assistant_action_receipts
                WHERE action_id = ? AND user_id = ? AND outcome = 'executing'""",
                (action_id, owner_id),
            ).fetchone()
            if receipt is None:
                raise AssistantStorageConflict("action_receipt_missing")
            receipt_id = str(receipt[0])
            next_status = outcome
            connection.execute(
                """UPDATE assistant_proposed_actions SET status = ?, completed_at = ?
                WHERE id = ? AND user_id = ? AND status = 'executing'""",
                (next_status, timestamp, action_id, owner_id),
            )
            connection.execute(
                """UPDATE assistant_action_receipts
                SET outcome = ?, result_json = ?, created_at = ?
                WHERE id = ? AND action_id = ? AND user_id = ? AND outcome = 'executing'""",
                (outcome, result_json, timestamp, receipt_id, action_id, owner_id),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "id": receipt_id,
            "action_id": action_id,
            "outcome": outcome,
            "result": dict(result),
            "created_at": timestamp,
        }

    def mark_action_unknown(
        self, user_id: int, action_id: str, *, now: datetime
    ) -> dict[str, object]:
        """Finalize an interrupted/uncertain mutation without claiming success or no change."""

        owner_id = self._require_owner(user_id)
        timestamp = self._timestamp(now)
        message = "The outcome is unknown. Inspect the app state before retrying."
        result_json = self._json({"message": message})
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id FROM assistant_action_receipts
                WHERE action_id = ? AND user_id = ? AND outcome = 'executing'""",
                (action_id, owner_id),
            ).fetchone()
            if row is None:
                raise AssistantStorageConflict("action_receipt_missing")
            connection.execute(
                """UPDATE assistant_proposed_actions SET status = 'unknown', completed_at = ?
                WHERE id = ? AND user_id = ? AND status = 'executing'""",
                (timestamp, action_id, owner_id),
            )
            connection.execute(
                """UPDATE assistant_action_receipts
                SET outcome = 'unknown', result_json = ?, created_at = ?
                WHERE id = ? AND action_id = ? AND user_id = ? AND outcome = 'executing'""",
                (result_json, timestamp, str(row[0]), action_id, owner_id),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "id": str(row[0]),
            "action_id": action_id,
            "outcome": "unknown",
            "result": {"message": message},
            "created_at": timestamp,
        }

    def reconcile_interrupted_actions(self, *, now: datetime) -> int:
        """Mark every process-left executing action unknown; never make it replayable."""

        timestamp = self._timestamp(now)
        message = "The outcome is unknown. Inspect the app state before retrying."
        result_json = self._json({"message": message})
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT action.id, receipt.id AS receipt_id
                FROM assistant_proposed_actions AS action
                JOIN assistant_action_receipts AS receipt ON receipt.action_id = action.id
                WHERE action.status = 'executing' AND receipt.outcome = 'executing'
                ORDER BY action.id"""
            ).fetchall()
            for row in rows:
                connection.execute(
                    """UPDATE assistant_proposed_actions SET status = 'unknown', completed_at = ?
                    WHERE id = ? AND status = 'executing'""",
                    (timestamp, str(row["id"])),
                )
                connection.execute(
                    """UPDATE assistant_action_receipts
                    SET outcome = 'unknown', result_json = ?, created_at = ?
                    WHERE id = ? AND outcome = 'executing'""",
                    (result_json, timestamp, str(row["receipt_id"])),
                )
            if rows:
                self._verify_database_limit(connection)
            connection.commit()
        return len(rows)

    def create_search_preview(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        execution_id: str,
        *,
        query_text: str,
        context_version: str,
        confirmation_phrase: str,
        now: datetime,
        expires_at: datetime,
    ) -> dict[str, object]:
        """Hold one exact web query until the authenticated browser approves it."""

        owner_id = self._require_owner(user_id)
        if not isinstance(query_text, str) or not 1 <= len(query_text.encode("utf-8")) <= 1000:
            raise ValueError("search query is invalid")
        preview_id = self._new_id()
        confirmation_phrase = f"SEARCH {preview_id[-8:]}"
        phrase_hash = hashlib.sha256(confirmation_phrase.encode("utf-8")).hexdigest()
        created_text = self._timestamp(now)
        expiry = self._timestamp(expires_at)
        additional = len(query_text.encode("utf-8")) + 256
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_capacity(connection, owner_id, additional)
            lease = connection.execute(
                """SELECT 1 FROM assistant_execution_leases
                WHERE execution_id = ? AND conversation_id = ? AND turn_id = ?
                  AND user_id = ? AND context_version = ? AND status = 'active'
                  AND expires_at > ?""",
                (execution_id, conversation_id, turn_id, owner_id, context_version, created_text),
            ).fetchone()
            if lease is None:
                raise AssistantStorageNotFound()
            connection.execute(
                """INSERT INTO assistant_search_previews
                (id, conversation_id, turn_id, user_id, execution_id, query_text,
                 context_version, confirmation_phrase_hash, status, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    preview_id,
                    conversation_id,
                    turn_id,
                    owner_id,
                    execution_id,
                    query_text,
                    context_version,
                    phrase_hash,
                    expiry,
                    created_text,
                ),
            )
            self._verify_database_limit(connection)
            connection.commit()
        return {
            "id": preview_id,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "execution_id": execution_id,
            "query": query_text,
            "context_version": context_version,
            "confirmation_phrase": confirmation_phrase,
            "status": "pending",
            "expires_at": expiry,
            "created_at": created_text,
        }

    def resolve_search_preview(
        self,
        user_id: int,
        conversation_id: str,
        turn_id: str,
        preview_id: str,
        *,
        context_version: str,
        confirmation_phrase: str,
        allow: bool,
        now: datetime,
    ) -> dict[str, object]:
        """Consume one preview decision and reveal its exact approved query to the active turn."""

        owner_id = self._require_owner(user_id)
        timestamp = self._timestamp(now)
        supplied_hash = hashlib.sha256(confirmation_phrase.encode("utf-8")).hexdigest()
        with self._repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id, conversation_id, turn_id, user_id, execution_id, query_text,
                    context_version, confirmation_phrase_hash, status, expires_at
                FROM assistant_search_previews
                WHERE id = ? AND conversation_id = ? AND turn_id = ? AND user_id = ?""",
                (preview_id, conversation_id, turn_id, owner_id),
            ).fetchone()
            if row is None:
                raise AssistantStorageNotFound()
            preview = dict(row)
            if preview["status"] != "pending":
                raise AssistantStorageConflict("search_preview_replayed")
            if str(preview["expires_at"]) <= timestamp:
                connection.execute(
                    """UPDATE assistant_search_previews
                    SET status = 'expired', completed_at = ? WHERE id = ?""",
                    (timestamp, preview_id),
                )
                connection.commit()
                raise AssistantStorageConflict("search_preview_expired")
            if preview["context_version"] != context_version:
                raise AssistantStorageConflict("search_context_stale")
            phrase_hash = preview.get("confirmation_phrase_hash")
            if allow and (
                not isinstance(phrase_hash, str)
                or not hmac.compare_digest(phrase_hash, supplied_hash)
            ):
                raise AssistantStorageConflict("search_preview_confirmation")
            next_status = "approved" if allow else "denied"
            cursor = connection.execute(
                """UPDATE assistant_search_previews SET status = ?, completed_at = ?
                WHERE id = ? AND user_id = ? AND status = 'pending'""",
                (next_status, timestamp, preview_id, owner_id),
            )
            if cursor.rowcount != 1:
                raise AssistantStorageConflict("search_preview_replayed")
            connection.commit()
        preview["status"] = next_status
        return preview

    def get_search_preview(
        self, user_id: int, conversation_id: str, turn_id: str, preview_id: str
    ) -> dict[str, object]:
        """Read an owner's pending query card for reconnect without exposing another turn."""

        owner_id = self._require_owner(user_id)
        with self._repository.connect() as connection:
            row = connection.execute(
                """SELECT id, conversation_id, turn_id, user_id, execution_id, query_text,
                    context_version, status, expires_at, created_at
                FROM assistant_search_previews
                WHERE id = ? AND conversation_id = ? AND turn_id = ? AND user_id = ?""",
                (preview_id, conversation_id, turn_id, owner_id),
            ).fetchone()
        if row is None:
            raise AssistantStorageNotFound()
        preview = dict(row)
        preview["confirmation_phrase"] = f"SEARCH {preview_id[-8:]}"
        preview["query"] = preview.pop("query_text")
        return preview
