"""Owner-scoped thesis revisions and immutable, provider-bound comparisons."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from stock_probs.auth import AuthContext
from stock_probs.auth_write_guard import AuthWriteAuthorizationError, authorize_current_write
from stock_probs.domain import DomainError
from stock_probs.repository import Repository


class ResearchStore:
    """Use the canonical repository's coordinated connections and owner guards."""

    def __init__(self, repository: Repository, *, allow_development_noauth: bool = False) -> None:
        """Create a research store with an opt-in for configured local no-auth use."""
        if type(allow_development_noauth) is not bool:
            raise TypeError("allow_development_noauth must be a boolean")
        self.repository = repository
        self.allow_development_noauth = allow_development_noauth

    def _authorize_write(
        self,
        connection: Any,
        owner: int,
        auth_context: AuthContext | None,
    ) -> None:
        """Recheck the exact request session while its serialized write transaction is held."""
        if auth_context is None:
            if not self.allow_development_noauth:
                raise DomainError(
                    "authentication_required",
                    "The active session is unavailable; sign in again.",
                    status_code=401,
                )
            self.repository._ensure_owner_can_write(connection, owner)  # noqa: SLF001
            return
        try:
            authorize_current_write(connection, auth_context, owner, datetime.now(UTC))
        except AuthWriteAuthorizationError as error:
            raise DomainError(
                error.code.lower(), error.message, status_code=error.status_code
            ) from None

    @staticmethod
    def _ensure_capacity(connection: Any, owner: int, additional: int) -> None:
        """Bound retained research bytes inside the same serialized write transaction."""
        totals = connection.execute(
            "SELECT COALESCE(SUM(bytes), 0), "
            "COALESCE(SUM(CASE WHEN owner_user_id = ? THEN bytes ELSE 0 END), 0) "
            "FROM (SELECT owner_user_id, length(CAST(payload_json AS BLOB)) AS bytes "
            "FROM research_theses "
            "UNION ALL SELECT owner_user_id, length(CAST(payload_json AS BLOB)) "
            "FROM research_thesis_revisions "
            "UNION ALL SELECT owner_user_id, length(CAST(payload_json AS BLOB)) "
            "FROM research_comparisons)",
            (owner,),
        ).fetchone()
        if totals[0] + additional > 20 * 1024 * 1024 or totals[1] + additional > 5 * 1024 * 1024:
            raise DomainError(
                "research_capacity",
                "Research storage is full. Export your records before adding more.",
                status_code=409,
            )

    def list(self, owner: int, kind: str, page: int, page_size: int) -> dict[str, Any]:
        """Return one bounded owner page using a code-owned table allowlist."""
        table = {"theses": "research_theses", "comparisons": "research_comparisons"}[kind]
        with self.repository.connect() as connection:
            self.repository._ensure_user_exists(connection, owner)  # noqa: SLF001
            total = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE owner_user_id = ?",  # noqa: S608
                (owner,),
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE owner_user_id = ? "  # noqa: S608
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (owner, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "items": [self._item(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": page * page_size < total,
        }

    @staticmethod
    def _item(row: Any) -> dict[str, Any]:
        item = dict(row)
        item.pop("owner_user_id", None)
        item.pop("idempotency_key", None)
        item.pop("request_sha256", None)
        item["data"] = json.loads(item.pop("payload_json"))
        return item

    def get(self, owner: int, kind: str, item_id: str) -> dict[str, Any] | None:
        """Cross-owner IDs have the same absent result as unknown IDs."""
        table = {"theses": "research_theses", "comparisons": "research_comparisons"}[kind]
        with self.repository.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ? AND owner_user_id = ?",  # noqa: S608
                (item_id, owner),
            ).fetchone()
        return self._item(row) if row else None

    def export_theses(self, owner: int) -> dict[str, Any]:
        """Export the bounded owner collection and all retained revisions from one snapshot."""
        with self.repository.connect() as connection:
            connection.execute("BEGIN")
            self.repository._ensure_user_exists(connection, owner)  # noqa: SLF001
            current = connection.execute(
                "SELECT * FROM research_theses WHERE owner_user_id = ? ORDER BY created_at, id",
                (owner,),
            ).fetchall()
            revisions = connection.execute(
                "SELECT thesis_id, revision, payload_json, recorded_at "
                "FROM research_thesis_revisions "
                "WHERE owner_user_id = ? ORDER BY thesis_id, revision",
                (owner,),
            ).fetchall()
        return {
            "format_version": 1,
            "items": [self._item(row) for row in current],
            "revisions": [
                {
                    "thesis_id": row[0],
                    "revision": row[1],
                    "data": json.loads(row[2]),
                    "recorded_at": row[3],
                }
                for row in revisions
            ],
        }

    def save_thesis(
        self,
        owner: int,
        payload: dict[str, Any],
        now: datetime,
        *,
        thesis_id: str | None = None,
        revision: int | None = None,
        idempotency_key: str | None = None,
        request_sha256: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        """Atomically validate attachments and append the new reviewed revision."""
        payload = copy.deepcopy(payload)
        text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        request_sha256 = request_sha256 or hashlib.sha256(text.encode()).hexdigest()
        if len(text.encode()) > 32768:
            raise DomainError("thesis_too_large", "Reduce the thesis text.", status_code=422)
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._authorize_write(connection, owner, auth_context)
            previous_evidence: list[dict[str, Any]] = []
            if thesis_id is not None:
                previous = connection.execute(
                    "SELECT revision, payload_json FROM research_theses "
                    "WHERE id = ? AND owner_user_id = ?",
                    (thesis_id, owner),
                ).fetchone()
                if previous is None:
                    raise DomainError(
                        "thesis_unavailable", "The thesis is unavailable.", status_code=404
                    )
                if previous[0] != revision:
                    raise DomainError(
                        "revision_conflict",
                        "Reload this thesis before saving your changes.",
                        status_code=409,
                    )
                previous_evidence = json.loads(previous[1])["evidence"]
            if thesis_id is None and idempotency_key is not None:
                existing = connection.execute(
                    "SELECT * FROM research_theses WHERE owner_user_id = ? AND idempotency_key = ?",
                    (owner, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if existing["request_sha256"] != request_sha256:
                        raise DomainError(
                            "idempotency_conflict",
                            "This save key belongs to a different thesis.",
                            status_code=409,
                        )
                    return self._item(existing)
            for evidence in payload["evidence"]:
                # A captured, unchanged excerpt survives deletion of its original saved chat.
                if evidence["kind"] == "assistant" and evidence in previous_evidence:
                    continue
                if evidence["kind"] == "forecast":
                    row = connection.execute(
                        "SELECT 1 FROM search_event_owners AS owner "
                        "JOIN search_events AS event ON event.id = owner.event_id "
                        "JOIN forecast_inputs AS input ON input.run_id = event.run_id "
                        "JOIN forecast_results AS result ON result.input_id = input.id "
                        "JOIN forecast_result_owners AS result_owner "
                        "ON result_owner.result_id = result.id "
                        "WHERE owner.event_id = ? AND owner.owner_user_id = ? "
                        "AND result_owner.owner_user_id = ? "
                        "AND event.status IN ('successful', 'repeated') LIMIT 1",
                        (evidence["reference"], owner, owner),
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT content FROM assistant_messages "
                        "WHERE id = ? AND user_id = ? AND role = 'assistant'",
                        (evidence["reference"], owner),
                    ).fetchone()
                if row is None:
                    raise DomainError(
                        "evidence_unavailable",
                        "An attached record is unavailable.",
                        status_code=404,
                    )
                if evidence["kind"] == "assistant":
                    excerpt = evidence.get("excerpt")
                    if excerpt is not None and excerpt != row[0][:6000]:
                        raise DomainError(
                            "evidence_changed",
                            "Reload the selected reply before saving.",
                            status_code=409,
                        )
                    evidence["excerpt"] = row[0][:6000]
            text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
            if len(text.encode()) > 32768:
                raise DomainError(
                    "thesis_too_large",
                    "Reduce the thesis text or attached excerpts.",
                    status_code=422,
                )
            if thesis_id is None:
                self._ensure_capacity(connection, owner, len(text.encode()) * 2)
                count = connection.execute(
                    "SELECT COUNT(*) FROM research_theses WHERE owner_user_id = ?", (owner,)
                ).fetchone()[0]
                if count >= 100:
                    raise DomainError(
                        "thesis_capacity",
                        "The 100-thesis storage limit has been reached.",
                        status_code=409,
                    )
                thesis_id, revision = str(uuid4()), 1
                connection.execute(
                    "INSERT INTO research_theses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        thesis_id,
                        owner,
                        idempotency_key or str(uuid4()),
                        request_sha256,
                        revision,
                        text,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            else:
                row = connection.execute(
                    "SELECT revision, length(CAST(payload_json AS BLOB)) FROM research_theses "
                    "WHERE id = ? AND owner_user_id = ?",
                    (thesis_id, owner),
                ).fetchone()
                if row is None:
                    raise DomainError(
                        "thesis_unavailable", "The thesis is unavailable.", status_code=404
                    )
                if row[0] != revision:
                    raise DomainError(
                        "revision_conflict",
                        "Reload this thesis before saving your changes.",
                        status_code=409,
                    )
                self._ensure_capacity(connection, owner, len(text.encode()) * 2 - row[1])
                revision = int(revision or 0) + 1
                if revision > 1000:
                    raise DomainError(
                        "revision_capacity",
                        "The thesis revision limit has been reached.",
                        status_code=409,
                    )
                connection.execute(
                    "UPDATE research_theses SET revision = ?, payload_json = ?, updated_at = ? "
                    "WHERE id = ? AND owner_user_id = ?",
                    (revision, text, now.isoformat(), thesis_id, owner),
                )
            connection.execute(
                "INSERT INTO research_thesis_revisions VALUES (?, ?, ?, ?, ?)",
                (thesis_id, owner, revision, text, now.isoformat()),
            )
            connection.commit()
        return self.get(owner, "theses", thesis_id) or {}

    def revisions(self, owner: int, thesis_id: str, page: int, page_size: int) -> dict[str, Any]:
        """Retain all revisions while exposing only one bounded page."""
        if self.get(owner, "theses", thesis_id) is None:
            raise DomainError("thesis_unavailable", "The thesis is unavailable.", status_code=404)
        with self.repository.connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM research_thesis_revisions "
                "WHERE thesis_id = ? AND owner_user_id = ?",
                (thesis_id, owner),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT revision, payload_json, recorded_at FROM research_thesis_revisions "
                "WHERE thesis_id = ? AND owner_user_id = ? ORDER BY revision DESC LIMIT ? OFFSET ?",
                (thesis_id, owner, page_size, (page - 1) * page_size),
            ).fetchall()
        return {
            "items": [
                {"revision": row[0], "data": json.loads(row[1]), "recorded_at": row[2]}
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": page * page_size < total,
        }

    def save_comparison(
        self,
        owner: int,
        key: str,
        payload: dict[str, Any] | None,
        now: datetime,
        *,
        preview_id: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        """Save only a server-generated snapshot; repeated keys return the same record."""
        if preview_id is None and payload is not None:
            candidate_preview_id = payload.get("preview_id")
            preview_id = candidate_preview_id if isinstance(candidate_preview_id, str) else None
        if preview_id is None:
            raise DomainError(
                "preview_expired", "Refresh the comparison before saving.", status_code=409
            )
        text = (
            json.dumps(payload, allow_nan=False, separators=(",", ":"))
            if payload is not None
            else None
        )
        if text is not None and len(text.encode()) > 262144:
            raise DomainError(
                "comparison_too_large", "The comparison exceeds its storage limit.", status_code=422
            )
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._authorize_write(connection, owner, auth_context)
            row = connection.execute(
                "SELECT * FROM research_comparisons "
                "WHERE owner_user_id = ? AND idempotency_key = ?",
                (owner, key),
            ).fetchone()
            if row:
                saved_preview_id = json.loads(row["payload_json"]).get("preview_id")
                if saved_preview_id != preview_id:
                    raise DomainError(
                        "idempotency_conflict",
                        "Use a new save operation for a different snapshot.",
                        status_code=409,
                    )
                return self._item(row)
            if text is None:
                raise DomainError(
                    "preview_expired", "Refresh the comparison before saving.", status_code=409
                )
            if (
                connection.execute(
                    "SELECT COUNT(*) FROM research_comparisons WHERE owner_user_id = ?", (owner,)
                ).fetchone()[0]
                >= 100
            ):
                raise DomainError(
                    "comparison_capacity",
                    "The 100-comparison limit has been reached.",
                    status_code=409,
                )
            self._ensure_capacity(connection, owner, len(text.encode()))
            item_id = str(uuid4())
            connection.execute(
                "INSERT INTO research_comparisons VALUES (?, ?, ?, ?, ?)",
                (item_id, owner, key, text, now.isoformat()),
            )
            connection.commit()
        return self.get(owner, "comparisons", item_id) or {}

    def thesis_for_key(
        self,
        owner: int,
        key: str,
        request_sha256: str,
        *,
        auth_context: AuthContext | None,
    ) -> dict[str, Any] | None:
        """Reauthorize and replay a durable creation before any provider work."""
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._authorize_write(connection, owner, auth_context)
            row = connection.execute(
                "SELECT * FROM research_theses WHERE owner_user_id = ? AND idempotency_key = ?",
                (owner, key),
            ).fetchone()
            connection.commit()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise DomainError(
                "idempotency_conflict",
                "This save key belongs to a different thesis.",
                status_code=409,
            )
        return self._item(row)

    def comparison_for_key(self, owner: int, key: str) -> dict[str, Any] | None:
        """Retain safe save retries after the temporary preview is released."""
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_comparisons "
                "WHERE owner_user_id = ? AND idempotency_key = ?",
                (owner, key),
            ).fetchone()
        return self._item(row) if row else None


def _action_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """Validate provider action evidence without treating an empty feed as proof of absence."""

    raw = item.get("action_evidence")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DomainError(
            "provider_market_data_invalid",
            "Corporate-action evidence is invalid.",
            status_code=502,
        )
    provider = item["source"]
    symbol = item["symbol"]
    requested_range = item["range"]
    series_as_of = item["as_of"]
    supplied_identity = (
        raw.get("provider", provider),
        raw.get("canonical_symbol", symbol),
        raw.get("requested_range", requested_range),
        raw.get("series_as_of", series_as_of),
    )
    if supplied_identity != (provider, symbol, requested_range, series_as_of):
        raise DomainError(
            "provider_market_data_invalid",
            "Corporate-action evidence does not match its chart response.",
            status_code=502,
        )
    available = raw.get("available_fields", [])
    if (
        not isinstance(available, list)
        or any(
            not isinstance(field, str) or field not in {"Dividends", "Stock Splits"}
            for field in available
        )
        or len(set(available)) != len(available)
    ):
        raise DomainError(
            "provider_market_data_invalid",
            "Corporate-action field provenance is invalid.",
            status_code=502,
        )
    supplied_events = raw.get("events", [])
    if not isinstance(supplied_events, list) or len(supplied_events) > 1000:
        raise DomainError(
            "provider_market_data_invalid",
            "Corporate-action event data is invalid.",
            status_code=502,
        )
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for supplied in supplied_events:
        if not isinstance(supplied, dict):
            raise DomainError(
                "provider_market_data_invalid",
                "Corporate-action event data is invalid.",
                status_code=502,
            )
        kind, event_day = supplied.get("kind"), supplied.get("date")
        if (
            not isinstance(kind, str)
            or kind not in {"split", "dividend"}
            or not isinstance(event_day, str)
        ):
            raise DomainError(
                "provider_market_data_invalid",
                "Corporate-action event data is invalid.",
                status_code=502,
            )
        try:
            if date.fromisoformat(event_day).isoformat() != event_day:
                raise ValueError("Noncanonical event date")
        except ValueError as error:
            raise DomainError(
                "provider_market_data_invalid",
                "Corporate-action event dates are invalid.",
                status_code=502,
            ) from error
        key = kind, event_day
        if key in seen:
            raise DomainError(
                "provider_market_data_invalid",
                "Corporate-action events are duplicated.",
                status_code=502,
            )
        seen.add(key)
        if kind == "split":
            value = supplied.get("new_shares_per_old_share")
            try:
                numeric_value = float(value)
            except (OverflowError, TypeError, ValueError) as error:
                raise DomainError(
                    "provider_market_data_invalid",
                    "Stock-split ratios are invalid.",
                    status_code=502,
                ) from error
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or "Stock Splits" not in available
                or not math.isfinite(numeric_value)
                or numeric_value <= 0
            ):
                raise DomainError(
                    "provider_market_data_invalid",
                    "Stock-split ratios are invalid.",
                    status_code=502,
                )
            events.append(
                {
                    "kind": kind,
                    "date": event_day,
                    "new_shares_per_old_share": numeric_value,
                }
            )
        else:
            amount = supplied.get("amount")
            currency = supplied.get("currency")
            try:
                numeric_amount = float(amount)
            except (OverflowError, TypeError, ValueError) as error:
                raise DomainError(
                    "provider_market_data_invalid",
                    "Dividend evidence is invalid.",
                    status_code=502,
                ) from error
            if (
                isinstance(amount, bool)
                or not isinstance(amount, int | float)
                or "Dividends" not in available
                or not math.isfinite(numeric_amount)
                or numeric_amount <= 0
                or (
                    currency is not None
                    and (
                        not isinstance(currency, str)
                        or len(currency) != 3
                        or not currency.isascii()
                        or not currency.isalpha()
                        or not currency.isupper()
                    )
                )
            ):
                raise DomainError(
                    "provider_market_data_invalid",
                    "Dividend evidence is invalid.",
                    status_code=502,
                )
            events.append(
                {"kind": kind, "date": event_day, "amount": numeric_amount, "currency": currency}
            )
    events.sort(key=lambda event: (event["date"], event["kind"]))
    return {
        "status": "provider_events_returned" if events else "no_reported_action_evidence",
        "provider": provider,
        "canonical_symbol": symbol,
        "requested_range": requested_range,
        "series_as_of": series_as_of,
        "available_fields": available,
        "events": events,
        "completeness": "not_established",
    }


def compare_series(series: list[dict[str, Any]]) -> dict[str, Any]:
    """Align daily observations without inventing sessions, returns, or total-return data."""
    if not 2 <= len(series) <= 4 or len({item["symbol"] for item in series}) != len(series):
        raise DomainError(
            "invalid_comparison", "Choose two to four distinct instruments.", status_code=422
        )
    mappings = []
    action_evidence = []
    for item in series:
        bars = item["bars"]
        if not 2 <= len(bars) <= 500:
            raise DomainError(
                "insufficient_history",
                "An instrument has insufficient daily history.",
                status_code=422,
            )
        mapped = {}
        for bar in bars:
            close = bar["close"]
            if (
                isinstance(close, bool)
                or not isinstance(close, int | float)
                or not math.isfinite(close)
                or close <= 0
            ):
                raise DomainError(
                    "provider_market_data_invalid",
                    "Chart observations are invalid.",
                    status_code=502,
                )
            try:
                observed_at = datetime.fromisoformat(bar["timestamp"])
                if observed_at.tzinfo is None:
                    raise ValueError("Missing observation timezone")
                day = observed_at.date().isoformat()
            except (ValueError, TypeError) as error:
                raise DomainError(
                    "provider_market_data_invalid",
                    "Chart observation dates are invalid.",
                    status_code=502,
                ) from error
            if day in mapped:
                raise DomainError(
                    "provider_market_data_invalid",
                    "Chart sessions are duplicated.",
                    status_code=502,
                )
            mapped[day] = close
        mappings.append(mapped)
        action_evidence.append(_action_evidence(item))
    common = sorted(set.intersection(*(set(item) for item in mappings)))
    if len(common) < 2:
        raise DomainError(
            "insufficient_common_history",
            "These instruments have too few common daily sessions.",
            status_code=422,
        )
    union_dates = {day for mapping in mappings for day in mapping if common[0] <= day <= common[-1]}
    instruments = []
    for item, mapped, evidence in zip(series, mappings, action_evidence, strict=True):
        dates = sorted(day for day in mapped if common[0] <= day <= common[-1])
        prices = [mapped[day] for day in dates]
        calendar_available, scheduled_gaps = _comparison_session_gaps(item, common[0], common[-1])
        missing_observations = (
            len(scheduled_gaps) if calendar_available else len(union_dates - set(dates))
        )
        normalized = [mapped[day] / mapped[common[0]] * 100 for day in common]
        if any(not math.isfinite(value) or value <= 0 for value in normalized):
            raise DomainError(
                "provider_market_data_invalid",
                "Chart prices cannot be normalized safely.",
                status_code=502,
            )
        returns = [
            math.log(value) - math.log(prices[index]) for index, value in enumerate(prices[1:])
        ]
        inferred_discontinuity = any(
            abs(prices[index + 1] / value - 1) >= 0.5 for index, value in enumerate(prices[:-1])
        )
        split_events = [
            event
            for event in evidence["events"]
            if event["kind"] == "split"
            and event["new_shares_per_old_share"] != 1
            and common[0] < event["date"] <= common[-1]
        ]
        discontinuity = inferred_discontinuity or bool(split_events)
        suppression_reason = None
        if split_events:
            event = split_events[0]
            suppression_reason = (
                "Unadjusted closes include a provider-reported split ratio of "
                f"{event['new_shares_per_old_share']:g} new shares per old share on "
                f"{event['date']}; price change, volatility, and drawdown are unavailable."
            )
        elif inferred_discontinuity:
            suppression_reason = (
                "A price discontinuity was inferred from unadjusted closes; "
                "price change, volatility, and drawdown are unavailable."
            )
        elif not calendar_available:
            suppression_reason = (
                "Scheduled-session completeness could not be established; "
                "volatility is unavailable."
            )
        elif missing_observations > 0:
            suppression_reason = (
                f"The supported market calendar identifies {missing_observations} missing "
                "scheduled session(s); volatility is unavailable."
            )
        peak, drawdown = prices[0], 0.0
        for value in prices:
            peak = max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
        instruments.append(
            {
                **{
                    key: item[key]
                    for key in (
                        "symbol",
                        "identity",
                        "source",
                        "as_of",
                        "adjustment_basis",
                        "label",
                    )
                },
                "currency": item["identity"]["currency"],
                "sample_count": len(prices),
                "excluded_chart_sessions": len(dates) - len(common),
                "common_sample_count": len(common),
                "missing_observations": missing_observations,
                "session_completeness": {
                    "status": (
                        "unavailable"
                        if not calendar_available
                        else "gaps_detected"
                        if missing_observations
                        else "complete"
                    ),
                    "missing_scheduled_sessions": (
                        missing_observations if calendar_available else None
                    ),
                },
                "normalized": [
                    {"date": day, "value": value}
                    for day, value in zip(common, normalized, strict=True)
                ],
                "price_change": None if discontinuity else prices[-1] / prices[0] - 1,
                "volatility": None
                if (
                    discontinuity
                    or not calendar_available
                    or missing_observations > 0
                    or len(returns) < 2
                )
                else statistics.stdev(returns) * math.sqrt(252),
                "max_drawdown": None if discontinuity else drawdown,
                "quality": (
                    "corporate_action_detected"
                    if split_events
                    else "discontinuity_detected"
                    if inferred_discontinuity
                    else "unadjusted_price_only"
                ),
                "metric_suppression_reason": suppression_reason,
                "action_evidence": evidence,
                "raw_bars": item["bars"],
            }
        )
    return {
        "instruments": instruments,
        "dates": common,
        "range": series[0]["range"],
        "basis": (
            "Unadjusted daily closes; not total return. "
            "Distributions and corporate actions may affect comparisons."
        ),
    }


def _comparison_session_gaps(
    item: dict[str, Any], common_start: str, common_end: str
) -> tuple[bool, set[str]]:
    """Read provider calendar evidence and restrict it to the shared comparison window."""

    evidence = item.get("session_completeness")
    if not isinstance(evidence, dict):
        return False, set()
    status = evidence.get("status")
    missing_dates = evidence.get("missing_dates")
    if status == "unavailable" and missing_dates is None:
        return False, set()
    if status != "available" or not isinstance(missing_dates, list):
        raise DomainError(
            "provider_market_data_invalid",
            "Scheduled-session completeness is invalid.",
            status_code=502,
        )
    gaps: set[str] = set()
    seen: set[str] = set()
    for value in missing_dates:
        if not isinstance(value, str):
            raise DomainError(
                "provider_market_data_invalid",
                "Scheduled-session dates are invalid.",
                status_code=502,
            )
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise DomainError(
                "provider_market_data_invalid",
                "Scheduled-session dates are invalid.",
                status_code=502,
            ) from error
        if parsed.isoformat() != value:
            raise DomainError(
                "provider_market_data_invalid",
                "Scheduled-session dates are invalid.",
                status_code=502,
            )
        if value in seen:
            raise DomainError(
                "provider_market_data_invalid",
                "Scheduled-session dates are duplicated.",
                status_code=502,
            )
        seen.add(value)
        if common_start <= value <= common_end:
            gaps.add(value)
    return True, gaps
