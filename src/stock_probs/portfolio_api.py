"""Typed portfolio routes; financial previews and commits are separate actions."""

from __future__ import annotations

import csv
import hashlib
import io
import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, Literal, TypeVar
from uuid import UUID, uuid4

from fastapi import FastAPI, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from stock_probs.auth import AuthContext
from stock_probs.domain import DomainError
from stock_probs.portfolio_import import csv_template, parse_import
from stock_probs.portfolio_ledger import Entry, LedgerError, currency_code, decimal
from stock_probs.portfolio_market import PortfolioMarket
from stock_probs.portfolio_store import PortfolioStore, encoded

_Result = TypeVar("_Result")
MAX_BASELINE_EXPORT_BYTES = 270_336


class PortfolioModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountCreate(PortfolioModel):
    label: str = Field(min_length=1, max_length=80)
    account_type: Literal["tfsa", "rrsp", "taxable", "other"]
    idempotency_key: UUID


class AccountEdit(PortfolioModel):
    label: str = Field(min_length=1, max_length=80)
    account_type: Literal["tfsa", "rrsp", "taxable", "other"]
    archived: bool
    revision: int = Field(ge=1)


class TransactionDraft(PortfolioModel):
    account_id: UUID
    effective_date: date
    kind: Literal[
        "opening_cash",
        "opening_position",
        "buy",
        "sell",
        "deposit",
        "withdrawal",
        "dividend",
        "interest",
        "fee",
        "split",
        "exchange",
        "transfer",
        "reversal",
    ]
    currency: str = Field(default="CAD", min_length=3, max_length=3)
    symbol: str | None = Field(default=None, min_length=1, max_length=15)
    asset_type: Literal["stock", "etf"] = "stock"
    quantity: str = Field(default="0", max_length=48)
    price: str = Field(default="0", max_length=48)
    amount: str = Field(default="0", max_length=48)
    fee: str = Field(default="0", max_length=48)
    book_cost: str | None = Field(default=None, max_length=48)
    split_ratio: str = Field(default="1", max_length=48)
    destination_account: UUID | None = None
    destination_currency: str | None = Field(default=None, min_length=3, max_length=3)
    received_amount: str = Field(default="0", max_length=48)
    replaces: UUID | None = None

    @field_validator("effective_date", mode="before")
    @classmethod
    def unambiguous_date(cls, value: Any) -> Any:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise ValueError("Use an original calendar date in YYYY-MM-DD form.")
        return value

    @model_validator(mode="after")
    def financial_fields(self) -> TransactionDraft:
        if not currency_code(self.currency) or (
            self.destination_currency and not currency_code(self.destination_currency)
        ):
            raise ValueError("Use uppercase three-letter currencies.")
        if self.symbol:
            self.symbol = self.symbol.strip().upper()
            if not self.symbol.isascii() or any(
                not character.isalnum() and character not in ".^-" for character in self.symbol
            ):
                raise ValueError("Invalid instrument symbol.")
        for field in (
            "quantity",
            "price",
            "amount",
            "fee",
            "book_cost",
            "split_ratio",
            "received_amount",
        ):
            value = getattr(self, field)
            if value is not None:
                decimal(value)
        if self.book_cost is not None and self.kind != "opening_position":
            raise ValueError("Only an opening position accepts an explicit original book cost.")
        if self.destination_currency is not None and self.kind != "exchange":
            raise ValueError("Only a currency exchange accepts a destination currency.")
        if self.destination_account is not None and self.kind != "transfer":
            raise ValueError("Only a linked transfer accepts another account.")
        return self

    def entry(self) -> Entry:
        data = self.model_dump(mode="json", exclude={"account_id", "effective_date"})
        return Entry(str(uuid4()), str(self.account_id), self.effective_date, **data)


class BatchPreview(PortfolioModel):
    transactions: list[TransactionDraft] = Field(min_length=1, max_length=200)


class ImportPreview(PortfolioModel):
    account_id: UUID
    csv_text: str = Field(min_length=1, max_length=65536)
    field_mapping: dict[str, str] = Field(min_length=1, max_length=16)


class BatchCommit(PortfolioModel):
    preview_id: UUID
    idempotency_key: UUID
    approved_duplicate_ids: list[UUID] = Field(default_factory=list, max_length=200)


class PriceShock(PortfolioModel):
    symbol: str = Field(min_length=1, max_length=15)
    asset_type: Literal["stock", "etf"]
    percent: str = Field(max_length=24)


class Reallocation(PortfolioModel):
    account_id: UUID
    symbol: str = Field(min_length=1, max_length=15)
    asset_type: Literal["stock", "etf"]
    quantity: str | None = Field(default=None, max_length=48)
    amount: str | None = Field(default=None, max_length=48)
    funding_currency: str | None = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def one_funding_input(self) -> Reallocation:
        if (self.quantity is None) == (self.amount is None):
            raise ValueError("Choose a cash amount or units, not both.")
        if self.funding_currency and not currency_code(self.funding_currency):
            raise ValueError("Choose an uppercase three-letter funding currency.")
        return self


class Assumptions(PortfolioModel):
    price_shocks: list[PriceShock] = Field(default_factory=list, max_length=100)
    usd_cad_percent: str = Field(default="0", max_length=24)
    reallocations: list[Reallocation] = Field(default_factory=list, max_length=20)


class ScenarioSave(PortfolioModel):
    baseline_id: UUID
    title: str = Field(min_length=1, max_length=120)
    assumptions: Assumptions
    idempotency_key: UUID


class ScenarioPreview(PortfolioModel):
    assumptions: Assumptions


class BaselineInstrument(PortfolioModel):
    symbol: str = Field(min_length=1, max_length=15, pattern=r"^[A-Z0-9.^-]+$")
    asset_type: Literal["stock", "etf"]


class BaselineCreate(PortfolioModel):
    idempotency_key: UUID
    display_currency: Literal["CAD", "USD"] = "CAD"
    account_id: UUID | None = None
    additional_instruments: list[BaselineInstrument] = Field(default_factory=list, max_length=4)


class ManualHoldingSelection(BaselineInstrument):
    provider: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def original_currency(cls, value: str) -> str:
        if not currency_code(value):
            raise ValueError("Choose an original uppercase three-letter currency.")
        return value


class ManualHoldingConversion(PortfolioModel):
    account_id: UUID
    effective_date: date
    holdings: list[ManualHoldingSelection] = Field(min_length=1, max_length=100)

    @field_validator("effective_date", mode="before")
    @classmethod
    def original_date(cls, value: Any) -> Any:
        return TransactionDraft.unambiguous_date(value)


def install_ledger_routes(
    app: FastAPI,
    store: PortfolioStore,
    owner_for_request: Callable[[Request], int | None],
    clock: Callable[[], datetime],
    enabled_for_request: Callable[[Request], bool],
    safe_csv_cell: Callable[[object], str],
    market: PortfolioMarket | None = None,
) -> None:
    """Closed-browser accounting storage shares auth, CSRF, owner and response boundaries."""
    previews: dict[tuple[int, str], tuple[datetime, list[Entry], dict[str, Any], str]] = {}
    conversions: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    pending_previews: dict[int, int] = {}
    lock = threading.Lock()

    @app.get("/api/v1/portfolio/features")
    def features(request: Request) -> dict[str, Any]:
        """Report rollout availability without requesting a quote or modifying a ledger."""
        if owner_for_request(request) is None:
            raise DomainError("authentication_required", "Sign in to continue.", status_code=401)
        enabled = enabled_for_request(request)
        return {
            "enabled": enabled,
            "features": ["portfolio", "transactions", "scenarios"] if enabled else [],
        }

    def owner(request: Request) -> int:
        value = owner_for_request(request)
        if value is None:
            raise DomainError(
                "authentication_required", "Sign in to use your portfolio.", status_code=401
            )
        if not enabled_for_request(request):
            raise DomainError(
                "portfolio_disabled",
                "These portfolio features are not enabled for this account.",
                status_code=503,
            )
        return value

    def auth_context(request: Request) -> AuthContext | None:
        """Return only the exact session context authenticated by outer middleware."""
        context = getattr(request.state, "auth_context", None)
        return context if isinstance(context, AuthContext) else None

    def safe(operation: Callable[[], _Result], *, status: int = 422) -> _Result:
        try:
            return operation()
        except LedgerError as error:
            raise DomainError("portfolio_validation", str(error), status_code=status) from error

    def retain_preview(user: int, entries: list[Entry], source: str) -> dict[str, Any]:
        """Reserve bounded preview capacity before replaying an expensive financial batch."""
        with lock:
            now = clock()
            for key in [key for key, value in previews.items() if value[0] <= now]:
                previews.pop(key)
                conversions.pop(key, None)
            if (
                len(previews) + sum(pending_previews.values()) >= 32
                or sum(key[0] == user for key in previews) + pending_previews.get(user, 0) >= 4
            ):
                raise DomainError(
                    "preview_capacity",
                    "Too many open previews. Wait for one to expire.",
                    status_code=503,
                )
            pending_previews[user] = pending_previews.get(user, 0) + 1
        try:
            return build_preview(user, entries, source)
        finally:
            with lock:
                pending_previews[user] -= 1
                if not pending_previews[user]:
                    pending_previews.pop(user)

    def build_preview(user: int, entries: list[Entry], source: str) -> dict[str, Any]:
        if any(
            entry.effective_date > clock().date() or entry.effective_date.year < 1900
            for entry in entries
        ):
            raise DomainError(
                "transaction_date", "Use an original date from 1900 through today.", status_code=422
            )
        result = safe(lambda: store.preview(user, entries))
        serialized = encoded(result)
        if len(serialized.encode()) > 262144:
            raise DomainError(
                "preview_limit", "This balance preview is too large.", status_code=422
            )
        identifier = str(uuid4())
        now = clock()
        with lock:
            for key in [key for key, value in previews.items() if value[0] <= now]:
                previews.pop(key)
                conversions.pop(key, None)
            if len(previews) >= 32 or sum(key[0] == user for key in previews) >= 4:
                raise DomainError(
                    "preview_capacity",
                    "Too many open previews. Wait for one to expire.",
                    status_code=503,
                )
            expires = now + timedelta(minutes=10)
            previews[user, identifier] = expires, entries, result, source
        rows = []
        for entry in entries:
            data = asdict(entry)
            data["effective_date"] = entry.effective_date.isoformat()
            rows.append(data)
        return {
            "preview_id": identifier,
            "expires_at": expires.isoformat(),
            "source": source,
            "transactions": rows,
            **result,
            "notice": "Review the resulting balances. No transactions have been committed.",
        }

    @app.get("/api/v1/portfolio/accounts")
    def accounts(
        request: Request,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        items = store.accounts(owner(request))
        return {
            "items": items[(page - 1) * page_size : page * page_size],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "has_next": page * page_size < len(items),
        }

    @app.post("/api/v1/portfolio/accounts", status_code=201)
    def create_account(request: Request, payload: AccountCreate) -> dict[str, Any]:
        return safe(
            lambda: store.create_account(
                owner(request),
                payload.label,
                payload.account_type,
                str(payload.idempotency_key),
                clock(),
                auth_context=auth_context(request),
            ),
            status=409,
        )

    @app.put("/api/v1/portfolio/accounts/{account_id}")
    def edit_account(request: Request, account_id: UUID, payload: AccountEdit) -> dict[str, Any]:
        return safe(
            lambda: store.update_account(
                owner(request),
                str(account_id),
                payload.revision,
                payload.label,
                payload.account_type,
                payload.archived,
                clock(),
                auth_context=auth_context(request),
            ),
            status=409,
        )

    @app.get("/api/v1/portfolio/balances")
    def balances(request: Request) -> dict[str, Any]:
        return safe(lambda: store.state(owner(request)))

    @app.post("/api/v1/portfolio/valuation")
    def current_valuation(
        request: Request,
        display_currency: Literal["CAD", "USD"] = "CAD",
        account_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Explicitly collect current inputs; this action does not save financial records."""
        user = owner(request)
        if market is None:
            raise DomainError(
                "prices_unavailable", "Portfolio prices are unavailable.", status_code=503
            )
        data, _ = safe(
            lambda: market.collect(user, display_currency, str(account_id) if account_id else None)
        )
        return data

    @app.get("/api/v1/portfolio/transactions")
    def transactions(
        request: Request,
        account_id: UUID | None = None,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        result = safe(
            lambda: store.transactions(
                owner(request), page, page_size, str(account_id) if account_id else None
            ),
            status=404,
        )
        result["items"] = [
            {
                **row["data"],
                "id": row["id"],
                "account": row["account_id"],
                "effective_date": row["effective_date"],
                "superseded": row["superseded"],
                "created_at": row["created_at"],
                "sequence": row["sequence"],
            }
            for row in result["items"]
        ]
        return result

    @app.post("/api/v1/portfolio/transactions/preview")
    def preview(request: Request, payload: BatchPreview) -> dict[str, Any]:
        return retain_preview(
            owner(request), [row.entry() for row in payload.transactions], "manual"
        )

    @app.post("/api/v1/portfolio/imports/preview")
    def import_preview(request: Request, payload: ImportPreview) -> dict[str, Any]:
        user = owner(request)
        entries = safe(
            lambda: parse_import(payload.csv_text, payload.field_mapping, str(payload.account_id))
        )
        return retain_preview(user, entries, "csv")

    @app.get("/api/v1/portfolio/manual-holdings")
    def manual_holdings(request: Request) -> dict[str, Any]:
        """Offer existing manual context for an explicit opening-position conversion."""
        user = owner(request)
        return {
            "items": store.repository.instrument_list_items(user, "portfolio"),
            "notice": "Choose original currency and an opening date. Unknown cost stays unknown.",
        }

    @app.post("/api/v1/portfolio/manual-holdings/preview")
    def convert_manual(request: Request, payload: ManualHoldingConversion) -> dict[str, Any]:
        """Prepare a reviewable conversion without editing existing manual holding context."""
        user = owner(request)
        existing = {
            (row["provider"], row["canonical_symbol"], row["asset_type"]): row
            for row in store.repository.instrument_list_items(user, "portfolio")
        }
        selected = set()
        entries, sources = [], {}
        for item in payload.holdings:
            key = (item.provider, item.symbol, item.asset_type)
            if key in selected or key not in existing or existing[key]["quantity"] is None:
                raise DomainError(
                    "holding_unavailable", "Select each existing holding once.", status_code=422
                )
            selected.add(key)
            row = existing[key]
            entry = Entry(
                str(uuid4()),
                str(payload.account_id),
                payload.effective_date,
                "opening_position",
                currency=item.currency,
                symbol=item.symbol,
                asset_type=item.asset_type,
                quantity=str(row["quantity"]),
                book_cost=None,
            )
            sources[entry.id] = {
                "provider": item.provider,
                "quantity": str(row["quantity"]),
                "added_at": row["added_at"],
            }
            entries.append(entry)
        result = retain_preview(user, entries, "manual_holdings_conversion")
        with lock:
            conversions[user, result["preview_id"]] = sources
        return result

    @app.get("/api/v1/portfolio/imports/template.csv")
    def template(request: Request) -> Response:
        owner(request)
        return Response(
            csv_template(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="signal-ledger-template.csv"'},
        )

    @app.post("/api/v1/portfolio/transactions", status_code=201)
    def commit(request: Request, payload: BatchCommit) -> dict[str, Any]:
        user = owner(request)
        identifier = str(payload.preview_id)
        approvals = {str(value) for value in payload.approved_duplicate_ids}
        existing = safe(
            lambda: store.batch_for_key(
                user,
                str(payload.idempotency_key),
                identifier,
                approvals,
                auth_context=auth_context(request),
            ),
            status=409,
        )
        if existing:
            return existing
        with lock:
            retained = previews.get((user, identifier))
            manual_sources = conversions.get((user, identifier))
        if retained is None or retained[0] <= clock():
            raise DomainError(
                "preview_expired",
                "Review a new balance preview before committing.",
                status_code=409,
            )
        _, entries, result, _ = retained
        if not approvals <= set(result["duplicate_ids"]):
            raise DomainError(
                "duplicate_decision",
                "Approve only duplicate rows in this reviewed preview.",
                status_code=422,
            )
        receipt = safe(
            lambda: store.commit(
                user,
                str(payload.idempotency_key),
                identifier,
                entries,
                result["account_revisions"],
                approvals,
                clock(),
                manual_openings=manual_sources,
                auth_context=auth_context(request),
            ),
            status=409,
        )
        with lock:
            previews.pop((user, identifier), None)
            conversions.pop((user, identifier), None)
        return receipt

    @app.get("/api/v1/portfolio/transactions/export")
    def export(request: Request, format: Literal["csv", "json"] = "json") -> Response:
        user = owner(request)
        with store.repository.connect() as connection:
            connection.execute("BEGIN")
            account_rows = store._accounts(connection, user)
            entries = store._entries(connection, user)
        records = []
        for entry in entries:
            data = asdict(entry)
            data["effective_date"] = entry.effective_date.isoformat()
            records.append(data)
        if format == "json":
            body = encoded({"format_version": 1, "accounts": account_rows, "transactions": records})
        else:
            output = io.StringIO()
            writer = csv.writer(output)
            fields = list(Entry.__dataclass_fields__)
            writer.writerow(fields)
            for row in records:
                writer.writerow([safe_csv_cell(row[field]) for field in fields])
            body = output.getvalue()
        return Response(
            body,
            media_type="application/json" if format == "json" else "text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="signal-ledger-transactions.{format}"'
            },
        )

    @app.get("/api/v1/portfolio/snapshots")
    def snapshots(
        request: Request,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        return store.list_snapshots(owner(request), page, page_size)

    @app.post("/api/v1/portfolio/snapshots", status_code=201)
    def freeze_baseline(request: Request, payload: BaselineCreate) -> dict[str, Any]:
        """Freeze identifiable balances, quotes and FX; durable retries preserve the original."""
        user = owner(request)
        request_hash = hashlib.sha256(
            encoded(payload.model_dump(mode="json", exclude={"idempotency_key"})).encode()
        ).hexdigest()
        previous = safe(
            lambda: store.snapshot_for_key(
                user,
                str(payload.idempotency_key),
                request_hash,
                auth_context=auth_context(request),
            ),
            status=409,
        )
        if previous:
            return previous
        if market is None:
            raise DomainError(
                "prices_unavailable", "Portfolio prices are unavailable.", status_code=503
            )
        data, revisions = safe(
            lambda: market.collect(
                user,
                payload.display_currency,
                str(payload.account_id) if payload.account_id else None,
                [(item.symbol, item.asset_type) for item in payload.additional_instruments],
            )
        )
        return safe(
            lambda: store.save_snapshot(
                user,
                str(payload.idempotency_key),
                request_hash,
                data,
                revisions,
                clock(),
                auth_context=auth_context(request),
            ),
            status=409,
        )

    @app.get("/api/v1/portfolio/snapshots/{baseline_id}")
    def baseline(request: Request, baseline_id: UUID) -> dict[str, Any]:
        row = store.snapshot(owner(request), str(baseline_id))
        if row is None:
            raise DomainError(
                "baseline_unavailable", "This baseline is unavailable.", status_code=404
            )
        return row

    @app.get("/api/v1/portfolio/snapshots/{baseline_id}/export")
    def export_baseline(request: Request, baseline_id: UUID) -> Response:
        """Download one owner-scoped immutable baseline with its capture provenance."""
        frozen = baseline(request, baseline_id)
        data = frozen.get("data")
        accounts = data.get("accounts") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("captured_at"), str)
            or not isinstance(accounts, list)
            or any(
                not isinstance(account, dict)
                or not isinstance(account.get("id"), str)
                or type(account.get("revision")) is not int
                or account["revision"] < 1
                for account in accounts
            )
        ):
            raise DomainError(
                "baseline_export_unavailable",
                "This saved baseline cannot be exported.",
                status_code=500,
            )
        export_data = {
            "format_version": 1,
            "record_type": "portfolio_baseline",
            "baseline_id": frozen["id"],
            "created_at": frozen["created_at"],
            "captured_at": data["captured_at"],
            "account_revisions": {account["id"]: account["revision"] for account in accounts},
            "data": data,
        }
        body = encoded(export_data)
        if len(body.encode("utf-8")) > MAX_BASELINE_EXPORT_BYTES:
            raise DomainError(
                "baseline_export_too_large",
                "The saved baseline exceeds the export size limit.",
                status_code=413,
            )
        return Response(
            body,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="signal-ledger-baseline.json"',
            },
        )

    @app.post("/api/v1/portfolio/snapshots/{baseline_id}/simulate")
    def scenario_preview(
        request: Request, baseline_id: UUID, payload: ScenarioPreview
    ) -> dict[str, Any]:
        from stock_probs.portfolio_scenarios import simulate

        row = baseline(request, baseline_id)
        return safe(
            lambda: simulate(
                {**row["data"], "id": row["id"]}, payload.assumptions.model_dump(mode="json")
            )
        )

    @app.get("/api/v1/scenarios")
    def scenarios(
        request: Request,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        return store.list_scenarios(owner(request), page, page_size)

    @app.post("/api/v1/scenarios", status_code=201)
    def save_scenario(request: Request, payload: ScenarioSave) -> dict[str, Any]:
        return safe(
            lambda: store.save_scenario(
                owner(request),
                str(payload.idempotency_key),
                str(payload.baseline_id),
                payload.title,
                payload.assumptions.model_dump(mode="json"),
                clock(),
                auth_context=auth_context(request),
            ),
            status=409,
        )

    @app.get("/api/v1/scenarios/{scenario_id}")
    def get_scenario(request: Request, scenario_id: UUID) -> dict[str, Any]:
        row = store.scenario(owner(request), str(scenario_id))
        if row is None:
            raise DomainError(
                "scenario_unavailable", "This scenario is unavailable.", status_code=404
            )
        return row

    @app.get("/api/v1/scenarios/{scenario_id}/export")
    def export_scenario(request: Request, scenario_id: UUID) -> Response:
        row = get_scenario(request, scenario_id)
        data = {**row, "baseline": store.snapshot(owner(request), row["baseline_id"])}
        return Response(
            encoded(data),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="signal-ledger-scenario.json"'},
        )
