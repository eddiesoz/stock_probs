"""Typed research routes share application authentication and provider capacity."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from stock_probs.config import Settings
from stock_probs.domain import DomainError
from stock_probs.research import ResearchStore, compare_series
from stock_probs.service import ForecastService


class ResearchModel(BaseModel):
    """Unknown fields cannot smuggle ownership, snapshots, or state into requests."""

    model_config = ConfigDict(extra="forbid")


class Evidence(ResearchModel):
    kind: Literal["forecast", "assistant"]
    reference: str = Field(min_length=1, max_length=36)
    excerpt: str | None = Field(default=None, max_length=6000)

    @model_validator(mode="after")
    def valid_reference(self) -> Evidence:
        if self.kind == "forecast":
            if self.excerpt is not None:
                raise ValueError(
                    "Forecast attachments use the immutable saved event, not assistant text."
                )
            if (
                not self.reference.isascii()
                or not self.reference.isdecimal()
                or int(self.reference) < 1
            ):
                raise ValueError("Choose a positive forecast event ID.")
            self.reference = str(int(self.reference))
        else:
            self.reference = str(UUID(self.reference))
        return self


class Thesis(ResearchModel):
    symbol: str = Field(min_length=1, max_length=15)
    asset_type: Literal["stock", "etf"]
    title: str = Field(min_length=1, max_length=160)
    reasoning: str = Field(max_length=6000)
    risks: str = Field(max_length=4000)
    invalidation: str = Field(max_length=4000)
    status: Literal["watching", "active", "archived"] = "watching"
    review_date: date | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    revision: int | None = Field(default=None, ge=1)
    idempotency_key: UUID | None = None


class ComparisonInstrument(ResearchModel):
    symbol: str = Field(min_length=1, max_length=15)
    asset_type: Literal["stock", "etf"]


class ComparisonRequest(ResearchModel):
    instruments: list[ComparisonInstrument] = Field(min_length=2, max_length=4)
    range: Literal["5d", "1mo", "3mo", "6mo", "1y"] = "1y"


class ComparisonSave(ResearchModel):
    preview_id: UUID
    idempotency_key: UUID


class ResearchRecord(ResearchModel):
    id: UUID
    revision: int | None = None
    created_at: datetime
    updated_at: datetime | None = None
    data: dict[str, Any]


class ResearchCollection(ResearchModel):
    items: list[ResearchRecord]
    page: int
    page_size: int
    total: int
    has_next: bool


class ThesisReview(ResearchModel):
    revision: int = Field(ge=1)
    next_review_date: date | None = None


def install_research_routes(
    app: FastAPI,
    config: Settings,
    service: ForecastService,
    owner_for_request: Callable[[Request], int | None],
    identity: Callable[..., dict[str, Any]],
    clock: Callable[[], datetime],
    documented_errors: Callable[..., dict[int | str, dict[str, Any]]],
    safe_csv_cell: Callable[[object], str],
) -> None:
    """Keep owner checks and preview/save boundaries inside the canonical application."""
    store = ResearchStore(service.repository)
    previews: dict[tuple[int, str], tuple[datetime, dict[str, Any]]] = {}
    preview_lock = threading.Lock()
    pending_previews: dict[int, int] = {}
    errors = documented_errors(400, 403, 404, 409, 411, 413, 422, 500, 502, 503)
    errors[401] = {**errors[403], "description": "Authentication required."}

    def allowed(request: Request) -> tuple[int, bool]:
        owner = owner_for_request(request)
        if owner is None:
            raise DomainError(
                "authentication_required", "Sign in to use research tools.", status_code=401
            )
        context = getattr(request.state, "auth_context", None)
        is_admin = context is not None and context.user.role == "admin"
        enabled = config.research_features_enabled and (
            not config.research_features_canary_only or is_admin
        )
        return owner, enabled

    def require_owner(request: Request) -> int:
        owner, enabled = allowed(request)
        if not enabled:
            raise DomainError(
                "research_features_disabled",
                "These research features are not enabled for this account.",
                status_code=503,
            )
        return owner

    @app.get("/api/v1/research/features", responses=errors)
    def features(request: Request) -> dict[str, Any]:
        _, enabled = allowed(request)
        return {
            "enabled": enabled,
            "release": 1,
            "features": ["theses", "comparisons"] if enabled else [],
        }

    @app.get("/api/v1/theses/draft", responses=errors)
    def assistant_draft(request: Request, message_id: UUID) -> dict[str, Any]:
        owner = require_owner(request)
        with service.repository.connect() as connection:
            row = connection.execute(
                "SELECT content FROM assistant_messages "
                "WHERE id = ? AND user_id = ? AND role = 'assistant'",
                (str(message_id), owner),
            ).fetchone()
        if row is None:
            raise DomainError(
                "evidence_unavailable", "The selected reply is unavailable.", status_code=404
            )
        excerpt = row[0][:6000]
        return {
            "reasoning": excerpt,
            "truncated": len(row[0]) > 6000,
            "evidence": [{"kind": "assistant", "reference": str(message_id), "excerpt": excerpt}],
        }

    @app.get("/api/v1/theses", response_model=ResearchCollection, responses=errors)
    def theses(
        request: Request,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        return store.list(require_owner(request), "theses", page, page_size)

    def thesis_payload(payload: Thesis) -> dict[str, Any]:
        data = payload.model_dump(mode="json", exclude={"revision", "idempotency_key"})
        data["identity"] = identity(payload.symbol, payload.asset_type)
        data["symbol"] = data["identity"]["canonical_symbol"]
        return data

    @app.post("/api/v1/theses", status_code=201, response_model=ResearchRecord, responses=errors)
    def create_thesis(request: Request, payload: Thesis) -> dict[str, Any]:
        owner = require_owner(request)
        if payload.revision is not None:
            raise DomainError("validation_error", "A new thesis cannot specify a revision.")
        if payload.idempotency_key is None:
            raise DomainError("idempotency_required", "A thesis save operation needs a unique key.")
        body = payload.model_dump(mode="json", exclude={"revision", "idempotency_key"})
        body["symbol"] = payload.symbol.strip().upper()
        request_sha256 = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = store.thesis_for_key(owner, str(payload.idempotency_key), request_sha256)
        if existing is not None:
            return existing
        return store.save_thesis(
            owner,
            thesis_payload(payload),
            clock(),
            idempotency_key=str(payload.idempotency_key),
            request_sha256=request_sha256,
        )

    @app.put("/api/v1/theses/{thesis_id}", response_model=ResearchRecord, responses=errors)
    def update_thesis(request: Request, thesis_id: UUID, payload: Thesis) -> dict[str, Any]:
        owner = require_owner(request)
        if payload.revision is None:
            raise DomainError("revision_required", "Specify the thesis revision you reviewed.")
        previous = store.get(owner, "theses", str(thesis_id))
        if previous is None:
            raise DomainError("thesis_unavailable", "The thesis is unavailable.", status_code=404)
        if (payload.symbol.strip().upper(), payload.asset_type) == (
            previous["data"]["symbol"],
            previous["data"]["asset_type"],
        ):
            data = payload.model_dump(mode="json", exclude={"revision", "idempotency_key"})
            data["symbol"] = previous["data"]["symbol"]
            data["identity"] = previous["data"]["identity"]
        else:
            data = thesis_payload(payload)
        if "reviewed_at" in previous["data"]:
            data["reviewed_at"] = previous["data"]["reviewed_at"]
        return store.save_thesis(
            owner,
            data,
            clock(),
            thesis_id=str(thesis_id),
            revision=payload.revision,
        )

    @app.post("/api/v1/theses/{thesis_id}/review", response_model=ResearchRecord, responses=errors)
    def review_thesis(request: Request, thesis_id: UUID, payload: ThesisReview) -> dict[str, Any]:
        owner = require_owner(request)
        saved = store.get(owner, "theses", str(thesis_id))
        if saved is None:
            raise DomainError("thesis_unavailable", "The thesis is unavailable.", status_code=404)
        data = {
            **saved["data"],
            "reviewed_at": clock().isoformat(),
            "review_date": payload.next_review_date.isoformat()
            if payload.next_review_date
            else None,
        }
        return store.save_thesis(
            owner, data, clock(), thesis_id=str(thesis_id), revision=payload.revision
        )

    @app.get("/api/v1/theses/export", responses=errors)
    def export_theses(request: Request, format: Literal["csv", "json"] = "json") -> Response:
        owner = require_owner(request)
        exported = store.export_theses(owner)
        if format == "json":
            return Response(
                json.dumps(exported, allow_nan=False),
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="signal-ledger-theses.json"'},
            )
        stream = io.StringIO()
        writer = csv.writer(stream)
        columns = (
            "symbol",
            "asset_type",
            "title",
            "reasoning",
            "risks",
            "invalidation",
            "status",
            "review_date",
            "reviewed_at",
        )
        writer.writerow(
            ("thesis_id", "revision", "recorded_at", *columns, "evidence_json", "identity_json")
        )
        for item in exported["revisions"]:
            writer.writerow(
                [
                    safe_csv_cell(item["thesis_id"]),
                    safe_csv_cell(item["revision"]),
                    safe_csv_cell(item["recorded_at"]),
                    *(safe_csv_cell(item["data"].get(column)) for column in columns),
                    safe_csv_cell(json.dumps(item["data"].get("evidence", []))),
                    safe_csv_cell(json.dumps(item["data"].get("identity", {}))),
                ]
            )
        return Response(
            stream.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="signal-ledger-theses.csv"'},
        )

    @app.get("/api/v1/theses/{thesis_id}", response_model=ResearchRecord, responses=errors)
    def get_thesis(request: Request, thesis_id: UUID) -> dict[str, Any]:
        item = store.get(require_owner(request), "theses", str(thesis_id))
        if item is None:
            raise DomainError("thesis_unavailable", "The thesis is unavailable.", status_code=404)
        return item

    @app.get("/api/v1/theses/{thesis_id}/revisions", responses=errors)
    def revisions(
        request: Request,
        thesis_id: UUID,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        return store.revisions(require_owner(request), str(thesis_id), page, page_size)

    @app.post("/api/v1/comparisons/preview", responses=errors)
    def preview(request: Request, payload: ComparisonRequest) -> dict[str, Any]:
        owner = require_owner(request)
        symbols = {(item.symbol.strip().upper(), item.asset_type) for item in payload.instruments}
        if len(symbols) != len(payload.instruments):
            raise DomainError("invalid_comparison", "Choose distinct instruments.", status_code=422)
        with preview_lock:
            expired = [key for key, value in previews.items() if value[0] <= clock()]
            for key in expired:
                del previews[key]
            if (
                len(previews) + sum(pending_previews.values()) >= 32
                or sum(key[0] == owner for key in previews) + pending_previews.get(owner, 0) >= 4
            ):
                raise DomainError(
                    "preview_capacity",
                    "Save a preview or wait for it to expire before creating another.",
                    status_code=503,
                )
            pending_previews[owner] = pending_previews.get(owner, 0) + 1
        try:
            series = []
            for instrument in payload.instruments:
                resolved = identity(instrument.symbol, instrument.asset_type)

                def fetch_bars(
                    now: datetime, resolved_identity: dict[str, Any] = resolved
                ) -> dict[str, object]:
                    return service.provider.historical_bars(
                        resolved_identity["canonical_symbol"],
                        resolved_identity["asset_type"],
                        now,
                        range=payload.range,
                    ).as_dict()

                bars = service._provider_capability(  # noqa: SLF001
                    fetch_bars,
                    "The chart provider is temporarily unavailable.",
                )
                series.append({**bars, "identity": resolved, "source": bars["provider"]})
            data = {**compare_series(series), "captured_at": clock().isoformat()}
            if len(json.dumps(data, allow_nan=False).encode()) > 262144:
                raise DomainError(
                    "comparison_too_large",
                    "The comparison exceeds its storage limit.",
                    status_code=422,
                )
            preview_id = str(uuid4())
            expires_at = clock() + timedelta(minutes=10)
            with preview_lock:
                previews[owner, preview_id] = (expires_at, data)
            return {"preview_id": preview_id, "expires_at": expires_at.isoformat(), "data": data}
        finally:
            with preview_lock:
                pending_previews[owner] -= 1
                if pending_previews[owner] == 0:
                    del pending_previews[owner]

    @app.post(
        "/api/v1/comparisons", status_code=201, response_model=ResearchRecord, responses=errors
    )
    def save(request: Request, payload: ComparisonSave) -> dict[str, Any]:
        owner = require_owner(request)
        with preview_lock:
            existing = store.comparison_for_key(owner, str(payload.idempotency_key))
            if existing is not None:
                if existing["data"].get("preview_id") != str(payload.preview_id):
                    raise DomainError(
                        "idempotency_conflict",
                        "This save key belongs to a different preview.",
                        status_code=409,
                    )
                return existing
            entry = previews.get((owner, str(payload.preview_id)))
            if entry is None or entry[0] <= clock():
                raise DomainError(
                    "preview_expired", "Refresh the comparison before saving.", status_code=409
                )
            saved = store.save_comparison(
                owner,
                str(payload.idempotency_key),
                {**entry[1], "preview_id": str(payload.preview_id)},
                clock(),
            )
            del previews[owner, str(payload.preview_id)]
            return saved

    @app.get("/api/v1/comparisons", response_model=ResearchCollection, responses=errors)
    def comparisons(
        request: Request,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        return store.list(require_owner(request), "comparisons", page, page_size)

    @app.get("/api/v1/comparisons/{comparison_id}", response_model=ResearchRecord, responses=errors)
    def comparison(request: Request, comparison_id: UUID) -> dict[str, Any]:
        item = store.get(require_owner(request), "comparisons", str(comparison_id))
        if item is None:
            raise DomainError(
                "comparison_unavailable", "The comparison is unavailable.", status_code=404
            )
        return item

    @app.get("/api/v1/comparisons/{comparison_id}/export", responses=errors)
    def export_comparison(
        request: Request, comparison_id: UUID, format: Literal["csv", "json"] = "json"
    ) -> Response:
        item = comparison(request, comparison_id)
        if format == "json":
            return Response(
                json.dumps(item, allow_nan=False),
                media_type="application/json",
                headers={
                    "Content-Disposition": 'attachment; filename="signal-ledger-comparison.json"'
                },
            )
        stream = io.StringIO()
        writer = csv.writer(stream)
        columns = (
            "symbol",
            "currency",
            "source",
            "as_of",
            "price_change",
            "volatility",
            "max_drawdown",
            "sample_count",
            "quality",
        )
        writer.writerow(("snapshot_id", "captured_at", *columns))
        for instrument in item["data"]["instruments"]:
            writer.writerow(
                [
                    safe_csv_cell(item["id"]),
                    safe_csv_cell(item["data"]["captured_at"]),
                    *(safe_csv_cell(instrument.get(column)) for column in columns),
                ]
            )
        return Response(
            stream.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="signal-ledger-comparison.csv"'},
        )
