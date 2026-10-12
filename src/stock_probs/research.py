"""Owner-scoped thesis revisions and immutable, provider-bound comparisons."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
from datetime import datetime
from typing import Any
from uuid import uuid4

from stock_probs.domain import DomainError
from stock_probs.repository import Repository


class ResearchStore:
    """Use the canonical repository's coordinated connections and owner guards."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

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
    ) -> dict[str, Any]:
        """Atomically validate attachments and append the new reviewed revision."""
        payload = copy.deepcopy(payload)
        text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        request_sha256 = request_sha256 or hashlib.sha256(text.encode()).hexdigest()
        if len(text.encode()) > 32768:
            raise DomainError("thesis_too_large", "Reduce the thesis text.", status_code=422)
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._ensure_owner_can_write(connection, owner)  # noqa: SLF001
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
        self, owner: int, key: str, payload: dict[str, Any], now: datetime
    ) -> dict[str, Any]:
        """Save only a server-generated snapshot; repeated keys return the same record."""
        text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        if len(text.encode()) > 262144:
            raise DomainError(
                "comparison_too_large", "The comparison exceeds its storage limit.", status_code=422
            )
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._ensure_owner_can_write(connection, owner)  # noqa: SLF001
            row = connection.execute(
                "SELECT * FROM research_comparisons "
                "WHERE owner_user_id = ? AND idempotency_key = ?",
                (owner, key),
            ).fetchone()
            if row:
                if row["payload_json"] != text:
                    raise DomainError(
                        "idempotency_conflict",
                        "Use a new save operation for a different snapshot.",
                        status_code=409,
                    )
                return self._item(row)
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

    def thesis_for_key(self, owner: int, key: str, request_sha256: str) -> dict[str, Any] | None:
        """Replay a durable creation without depending on provider availability."""
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_theses WHERE owner_user_id = ? AND idempotency_key = ?",
                (owner, key),
            ).fetchone()
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


def compare_series(series: list[dict[str, Any]]) -> dict[str, Any]:
    """Align daily observations without inventing sessions, returns, or total-return data."""
    if not 2 <= len(series) <= 4 or len({item["symbol"] for item in series}) != len(series):
        raise DomainError(
            "invalid_comparison", "Choose two to four distinct instruments.", status_code=422
        )
    mappings = []
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
    common = sorted(set.intersection(*(set(item) for item in mappings)))
    if len(common) < 2:
        raise DomainError(
            "insufficient_common_history",
            "These instruments have too few common daily sessions.",
            status_code=422,
        )
    union_dates = {day for mapping in mappings for day in mapping if common[0] <= day <= common[-1]}
    instruments = []
    for item, mapped in zip(series, mappings, strict=True):
        dates = sorted(day for day in mapped if common[0] <= day <= common[-1])
        prices = [mapped[day] for day in dates]
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
        discontinuity = any(
            abs(prices[index + 1] / value - 1) >= 0.5 for index, value in enumerate(prices[:-1])
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
                "missing_observations": len(union_dates - set(dates)),
                "normalized": [
                    {"date": day, "value": value}
                    for day, value in zip(common, normalized, strict=True)
                ],
                "price_change": None if discontinuity else prices[-1] / prices[0] - 1,
                "volatility": None
                if discontinuity or len(returns) < 2
                else statistics.stdev(returns) * math.sqrt(252),
                "max_drawdown": None if discontinuity else drawdown,
                "quality": "discontinuity_detected" if discontinuity else "unadjusted_price_only",
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
