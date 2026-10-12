"""Daily cache, failed attempt and dated observation fixtures do not call a live service."""

from datetime import UTC, date, datetime, timedelta

import pytest

from stock_probs.portfolio_fx import IndicativeFX, latest_usd
from stock_probs.portfolio_ledger import LedgerError
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def observations():
    return {
        "observations": [
            {"d": "2026-10-09", "FXUSDCAD": {"v": "1.4271"}},
            {"d": "2026-10-08", "FXUSDCAD": {"v": "1.4240"}},
        ]
    }


def test_daily_attempt_persists_across_objects_and_keeps_dated_prior_rate_on_failure(tmp_path):
    repository = Repository(tmp_path / "fx.db")
    repository.migrate()
    calls = []

    def fetch():
        calls.append(1)
        return observations()

    rates = IndicativeFX(repository, fetch).rates(NOW)
    assert rates["rates"]["USD"]["publication_date"] == "2026-10-09"
    assert rates["rates"]["USD"]["value"] == "1.4271"
    assert rates["rates"]["USD"]["publication_age_days"] == 2
    assert IndicativeFX(repository, fetch).rates(NOW) == rates and len(calls) == 1

    def failed():
        calls.append(1)
        raise LedgerError("Unavailable")

    next_day = NOW + timedelta(days=1)
    stale = IndicativeFX(repository, failed).rates(next_day)
    assert stale["last_attempt_failed"] and stale["status"] == "available"
    assert stale["rates"]["USD"]["publication_date"] == "2026-10-09"
    assert IndicativeFX(repository, failed).rates(next_day) == stale and len(calls) == 2
    unavailable = IndicativeFX(repository, failed).rates(NOW + timedelta(days=35))
    assert unavailable["status"] == "unavailable" and "USD" not in unavailable["rates"]


@pytest.mark.parametrize(
    "row",
    [
        {"d": "2026-10-12", "FXUSDCAD": {"v": "1.4"}},
        {"d": "2026-08-01", "FXUSDCAD": {"v": "1.4"}},
        {"d": "2026-10-09", "FXUSDCAD": {"v": "NaN"}},
        {"d": "2026-10-09", "FXUSDCAD": {"v": "0"}},
        {"d": "2026-10-09", "FXUSDCAD": {"v": "10001"}},
        {"d": "2026-10-09"},
    ],
)
def test_future_stale_nonfinite_or_missing_rates_are_unavailable(row):
    with pytest.raises(LedgerError):
        latest_usd({"observations": [row]}, date(2026, 10, 11))
