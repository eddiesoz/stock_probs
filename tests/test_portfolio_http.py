"""Exercise real application routing, local fixture authentication and reviewed ledger commits."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.provider import FixtureProvider


@pytest.fixture
def portfolio_client(settings):
    now = datetime.now(UTC)
    app = create_app(
        replace(settings, portfolio_features_enabled=True, portfolio_features_canary_only=False),
        FixtureProvider(),
        lambda: now,
    )
    with TestClient(app) as client:
        yield client


def account(client, label="TFSA"):
    response = client.post(
        "/api/v1/portfolio/accounts",
        json={
            "label": label,
            "account_type": "tfsa",
            "idempotency_key": str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def preview(client, identifier, **fields):
    row = {
        "account_id": identifier,
        "kind": "deposit",
        "amount": "1000",
        "effective_date": "2026-10-01",
        **fields,
    }
    response = client.post("/api/v1/portfolio/transactions/preview", json={"transactions": [row]})
    assert response.status_code == 200, response.text
    return response.json()


def commit(client, reviewed, key=None):
    response = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "preview_id": reviewed["preview_id"],
            "idempotency_key": key or str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_real_routes_preview_commit_retry_and_atomic_unfunded_rejection(portfolio_client):
    client = portfolio_client
    identifier = account(client)
    reviewed = preview(client, identifier)
    assert client.get("/api/v1/portfolio/balances").json()["book"]["cash"] == []
    key = str(uuid4())
    first = commit(client, reviewed, key)
    assert commit(client, reviewed, key)["batch_id"] == first["batch_id"]
    invalid = client.post(
        "/api/v1/portfolio/transactions/preview",
        json={
            "transactions": [
                {
                    "account_id": identifier,
                    "effective_date": "2026-10-02",
                    "kind": "withdrawal",
                    "amount": "2000",
                },
            ]
        },
    )
    assert invalid.status_code == 422
    assert client.get("/api/v1/portfolio/transactions").json()["total"] == 1
    assert client.get("/api/v1/portfolio/balances").json()["book"]["cash"][0]["amount"] == "1000"


def test_baseline_and_scenario_replay_are_provider_free_and_do_not_commit(portfolio_client):
    client = portfolio_client
    identifier = account(client)
    commit(client, preview(client, identifier))
    payload = {
        "idempotency_key": str(uuid4()),
        "additional_instruments": [
            {"symbol": "SPY", "asset_type": "etf"},
        ],
    }
    saved = client.post("/api/v1/portfolio/snapshots", json=payload)
    assert saved.status_code == 201, saved.text
    baseline = saved.json()
    assert baseline["data"]["fx"]["USD"]["provider"] == "Deterministic simulated FX"
    provider = client.app.state.service.provider

    def forbidden(*args, **kwargs):
        raise AssertionError("Saved reads and durable retries must not call the quote provider")

    provider.quote_snapshot = forbidden
    assert client.post("/api/v1/portfolio/snapshots", json=payload).json() == baseline
    assumptions = {
        "price_shocks": [{"symbol": "SPY", "asset_type": "etf", "percent": "-20"}],
        "usd_cad_percent": "1.25",
        "reallocations": [
            {
                "account_id": identifier,
                "symbol": "SPY",
                "asset_type": "etf",
                "amount": "100",
                "funding_currency": "CAD",
            }
        ],
    }
    scenario = client.post(
        "/api/v1/scenarios",
        json={
            "baseline_id": baseline["id"],
            "title": "My cash-funded simulation",
            "assumptions": assumptions,
            "idempotency_key": str(uuid4()),
        },
    )
    assert scenario.status_code == 201, scenario.text
    assert scenario.json()["result"]["label"] == "Simulation only"
    assert client.get(f"/api/v1/scenarios/{scenario.json()['id']}").json() == scenario.json()
    assert client.get(f"/api/v1/portfolio/snapshots/{baseline['id']}").json() == baseline
    assert client.get("/api/v1/portfolio/transactions").json()["total"] == 1
    assert client.get("/api/v1/portfolio/balances").json()["book"]["cash"][0]["amount"] == "1000"


def test_import_body_mapping_duplicates_formula_export_and_preview_capacity(portfolio_client):
    client = portfolio_client
    identifier = account(client, '=HYPERLINK("https://example.com")')
    payload = {
        "account_id": identifier,
        "csv_text": "Date,Type,Amount\n2026-10-01,deposit,100\n",
        "field_mapping": {"Date": "effective_date", "Type": "kind", "Amount": "amount"},
    }
    first = client.post("/api/v1/portfolio/imports/preview", json=payload)
    assert first.status_code == 200, first.text
    commit(client, first.json())
    opening = preview(
        client, identifier, kind="opening_position", symbol="-BAD", quantity="0.125", amount="0"
    )
    commit(client, opening)
    duplicate = client.post("/api/v1/portfolio/imports/preview", json=payload)
    assert duplicate.status_code == 200 and len(duplicate.json()["duplicate_ids"]) == 1
    refused = client.post(
        "/api/v1/portfolio/transactions",
        json={
            "preview_id": duplicate.json()["preview_id"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert refused.status_code == 409
    for _ in range(3):
        assert client.post("/api/v1/portfolio/imports/preview", json=payload).status_code == 200
    assert client.post("/api/v1/portfolio/imports/preview", json=payload).status_code == 503
    assert client.get("/api/v1/portfolio/transactions").json()["total"] == 2
    exported = client.get("/api/v1/portfolio/transactions/export?format=csv")
    assert exported.status_code == 200 and "'-BAD" in exported.text


def test_csv_import_rejects_explicit_buy_cost_without_partial_commit(portfolio_client):
    client = portfolio_client
    identifier = account(client)
    response = client.post(
        "/api/v1/portfolio/imports/preview",
        json={
            "account_id": identifier,
            "csv_text": (
                "Date,Type,Currency,Symbol,Asset type,Quantity,Price,Amount,Book cost\n"
                "2026-10-01,opening_cash,CAD,,,,,1000,\n"
                "2026-10-01,buy,CAD,ABC,stock,1,10,,999\n"
            ),
            "field_mapping": {
                "Date": "effective_date",
                "Type": "kind",
                "Currency": "currency",
                "Symbol": "symbol",
                "Asset type": "asset_type",
                "Quantity": "quantity",
                "Price": "price",
                "Amount": "amount",
                "Book cost": "book_cost",
            },
        },
    )

    assert response.status_code == 422
    assert "Row 3: only an opening position" in response.text
    assert client.get("/api/v1/portfolio/transactions").json()["total"] == 0
    assert client.get("/api/v1/portfolio/balances").json()["book"]["cash"] == []


def test_csv_import_rejects_wrong_transaction_destination_fields_atomically(portfolio_client):
    client = portfolio_client
    identifier = account(client)
    mapping = {
        "Date": "effective_date",
        "Type": "kind",
        "Currency": "currency",
        "Symbol": "symbol",
        "Quantity": "quantity",
        "Price": "price",
        "Amount": "amount",
        "Destination currency": "destination_currency",
        "Destination account": "destination_account",
    }
    invalid_csv_rows = (
        (
            "Date,Type,Currency,Symbol,Quantity,Price,Amount,"
            "Destination currency,Destination account\n"
            "2026-10-01,opening_cash,CAD,,,,1000,,\n"
            "2026-10-01,buy,CAD,ABC,1,10,,USD,\n",
            "destination currency",
        ),
        (
            "Date,Type,Currency,Symbol,Quantity,Price,Amount,"
            "Destination currency,Destination account\n"
            "2026-10-01,opening_cash,CAD,,,,1000,,\n"
            "2026-10-01,buy,CAD,ABC,1,10,,,rrsp\n",
            "linked transfer",
        ),
    )

    for csv_text, row_error in invalid_csv_rows:
        response = client.post(
            "/api/v1/portfolio/imports/preview",
            json={"account_id": identifier, "csv_text": csv_text, "field_mapping": mapping},
        )
        assert response.status_code == 422
        assert "Row 3" in response.text and row_error in response.text
        assert client.get("/api/v1/portfolio/transactions").json()["total"] == 0
        assert client.get("/api/v1/portfolio/balances").json()["book"]["cash"] == []


def test_manual_conversion_unknown_cost_is_explicit_atomic_and_single_use(portfolio_client):
    client = portfolio_client
    identifier = account(client)
    added = client.post(
        "/api/v1/lists",
        json={
            "kind": "portfolio",
            "item": {
                "symbol": "SPY",
                "asset_type": "etf",
                "quantity": 1.25,
            },
        },
    )
    assert added.status_code == 201, added.text
    source = client.get("/api/v1/portfolio/manual-holdings").json()["items"][0]
    payload = {
        "account_id": identifier,
        "effective_date": "2026-10-01",
        "holdings": [
            {
                "provider": source["provider"],
                "symbol": source["canonical_symbol"],
                "asset_type": source["asset_type"],
                "currency": "USD",
            }
        ],
    }
    reviewed = client.post("/api/v1/portfolio/manual-holdings/preview", json=payload)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["after"]["positions"][0]["book_cost"] is None
    commit(client, reviewed.json())
    again = client.post("/api/v1/portfolio/manual-holdings/preview", json=payload)
    assert again.status_code == 200
    assert (
        client.post(
            "/api/v1/portfolio/transactions",
            json={
                "preview_id": again.json()["preview_id"],
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 409
    )
    assert client.get("/api/v1/portfolio/manual-holdings").json()["items"][0]["quantity"] == 1.25
    assert (
        client.get("/api/v1/portfolio/balances").json()["book"]["positions"][0]["quantity"]
        == "1.25"
    )


def test_real_local_fixture_sessions_enforce_owner_csrf_and_canary(settings):
    now = datetime.now(UTC)
    config = replace(
        settings,
        auth_mode="local",
        environment="test",
        auth_public_origin="http://testserver",
        portfolio_features_enabled=True,
        portfolio_features_canary_only=False,
        bootstrap_username="fixture-admin",
        bootstrap_password="fixture-admin-password-123",  # noqa: S106
        bootstrap_member_username="fixture-member",
        bootstrap_member_password="fixture-member-password-123",  # noqa: S106
    )
    app = create_app(config, FixtureProvider(), lambda: now)
    with TestClient(app) as admin, TestClient(app) as member:
        assert admin.get("/api/v1/portfolio/accounts").status_code == 401
        for client, username, password in (
            (admin, "fixture-admin", "fixture-admin-password-123"),
            (member, "fixture-member", "fixture-member-password-123"),
        ):
            login = client.post(
                "/api/v1/auth/local/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200, login.text
            client.headers["x-csrf-token"] = login.json()["csrf_token"]
        identifier = account(admin)
        assert member.get("/api/v1/portfolio/accounts").json()["items"] == []
        assert (
            member.get(f"/api/v1/portfolio/transactions?account_id={identifier}").status_code == 404
        )
        assert (
            member.post(
                "/api/v1/portfolio/transactions/preview",
                json={
                    "transactions": [
                        {
                            "account_id": identifier,
                            "kind": "deposit",
                            "amount": "1",
                            "effective_date": "2026-10-01",
                        }
                    ]
                },
            ).status_code
            == 422
        )
        denied = admin.post(
            "/api/v1/portfolio/accounts",
            headers={"x-csrf-token": "wrong"},
            json={"label": "Denied", "account_type": "tfsa", "idempotency_key": str(uuid4())},
        )
        assert denied.status_code == 403
        assert admin.get("/api/v1/portfolio/accounts").json()["total"] == 1
