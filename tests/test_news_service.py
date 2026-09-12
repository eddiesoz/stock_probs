"""News service tests pin ephemeral cache boundaries without persistence access."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread

import pytest

from stock_probs.domain import DomainError, NewsData, NewsItem
from stock_probs.service import (
    NEWS_MAX_CACHE_BYTES,
    NEWS_MAX_ENTRY_BYTES,
    NEWS_MAX_SYMBOLS,
    ForecastService,
)

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


class NoRepository:
    def __getattr__(self, name):
        raise AssertionError(f"news must not access persistence: {name}")


class MonotonicClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def news_item(index, *, large=False):
    suffix = str(index)
    return NewsItem(
        id=("i" * 120 + suffix) if large else f"story-{suffix}",
        title=("h" * 490 + suffix) if large else f"Headline {suffix}",
        publisher=("s" * 190 + suffix) if large else "Fixture News",
        published_at=NOW,
        url=(
            f"https://finance.yahoo.com/{'x' * 1990}/{suffix}"
            if large
            else f"https://finance.yahoo.com/news/{suffix}.html"
        ),
        related_symbols=(
            tuple(f"S{number:014d}" for number in range(32)) if large else ("SPY",)
        ),
    )


class NewsProvider:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.empty = False
        self.large = False

    def fetch_news(self, symbol, limit=5, now=None):
        self.calls.append((symbol, limit, now))
        if self.fail:
            raise DomainError("provider_unavailable", "fixture failed", status_code=502)
        items = (
            ()
            if self.empty
            else tuple(news_item(index, large=self.large) for index in range(limit))
        )
        return NewsData(symbol, "Fixture News", now, items)


def service(provider=None):
    clock = MonotonicClock()
    selected = provider or NewsProvider()
    return (
        ForecastService(
            NoRepository(),
            selected,
            clock=lambda: NOW,
            monotonic_clock=clock,
        ),
        selected,
        clock,
    )


def test_news_cache_hits_slice_and_larger_limits_retrieve():
    app, provider, _ = service()

    first = app.news(" spy ", 5)
    smaller = app.news("SPY", 2)
    larger = app.news("SPY", 6)

    assert first["cache_state"] == "miss"
    assert first["as_of"] == NOW.isoformat()
    assert smaller["cache_state"] == "hit" and len(smaller["items"]) == 2
    assert larger["cache_state"] == "miss" and len(larger["items"]) == 6
    assert [call[1] for call in provider.calls] == [5, 6]


def test_news_fresh_stale_failure_suppression_and_recovery_boundaries():
    app, provider, clock = service()
    original = app.news("SPY")
    provider.fail = True

    clock.value = 299.999
    assert app.news("SPY")["cache_state"] == "hit"
    clock.value = 300
    stale = app.news("SPY")
    assert stale["cache_state"] == "stale_fallback"
    assert stale["as_of"] == original["as_of"]
    assert stale["coverage"]["refresh_failed"] is True
    assert len(provider.calls) == 2

    clock.value = 329.999
    assert app.news("SPY")["cache_state"] == "stale_fallback"
    assert len(provider.calls) == 2
    provider.fail = False
    clock.value = 330
    assert app.news("SPY")["cache_state"] == "miss"
    assert len(provider.calls) == 3


def test_news_stale_ceiling_is_inclusive_but_expired_data_is_never_served():
    app, provider, clock = service()
    app.news("SPY")
    provider.fail = True

    clock.value = 1800
    assert app.news("SPY")["cache_state"] == "stale_fallback"
    clock.value = 1830.001
    with pytest.raises(DomainError) as failure:
        app.news("SPY")
    assert failure.value.status_code == 502


def test_empty_news_cache_expires_at_sixty_seconds():
    app, provider, clock = service()
    provider.empty = True

    assert app.news("EMPTY")["items"] == []
    clock.value = 59.999
    assert app.news("EMPTY")["cache_state"] == "hit"
    clock.value = 60
    assert app.news("EMPTY")["cache_state"] == "miss"
    assert len(provider.calls) == 2


def test_failure_without_cache_is_suppressed_for_thirty_seconds():
    app, provider, clock = service()
    provider.fail = True

    with pytest.raises(DomainError):
        app.news("SPY")
    clock.value = 29.999
    with pytest.raises(DomainError):
        app.news("SPY")
    assert len(provider.calls) == 1
    clock.value = 30
    with pytest.raises(DomainError):
        app.news("SPY")
    assert len(provider.calls) == 2


def test_news_has_one_active_retrieval_and_reports_busy():
    entered = Event()
    release = Event()

    class BlockingProvider(NewsProvider):
        def fetch_news(self, symbol, limit=5, now=None):
            entered.set()
            assert release.wait(2)
            return super().fetch_news(symbol, limit, now)

    app, provider, _ = service(BlockingProvider())
    result = []
    worker = Thread(target=lambda: result.append(app.news("SPY")))
    worker.start()
    assert entered.wait(1)
    try:
        with pytest.raises(DomainError) as busy:
            app.news("ACDC")
        assert busy.value.code == "provider_busy" and busy.value.status_code == 503
    finally:
        release.set()
        worker.join(2)
    assert result[0]["cache_state"] == "miss"
    assert len(provider.calls) == 1


def test_news_cache_evicts_lru_symbols_and_stays_within_all_bounds():
    app, provider, clock = service()
    for index in range(NEWS_MAX_SYMBOLS):
        clock.value = float(index)
        app.news(f"S{index}", 1)
    app.news("S0", 1)
    clock.value = float(NEWS_MAX_SYMBOLS)
    app.news(f"S{NEWS_MAX_SYMBOLS}", 1)

    assert len(provider.calls) == NEWS_MAX_SYMBOLS + 1
    assert len(app._news_cache) == NEWS_MAX_SYMBOLS
    assert "S0" in app._news_cache and "S1" not in app._news_cache
    assert all(entry.size <= NEWS_MAX_ENTRY_BYTES for entry in app._news_cache.values())
    assert sum(entry.size for entry in app._news_cache.values()) <= NEWS_MAX_CACHE_BYTES


def test_oversized_news_is_never_served_or_cached():
    app, provider, _ = service()
    provider.large = True

    with pytest.raises(DomainError) as failure:
        app.news("SPY", 10)
    assert failure.value.code == "provider_news_invalid"
    assert app._news_cache["SPY"].data is None


@pytest.mark.parametrize("limit", [0, 11, True])
def test_news_limit_validation_precedes_provider_access(limit):
    app, provider, _ = service()
    with pytest.raises(DomainError) as failure:
        app.news("SPY", limit)
    assert failure.value.code == "invalid_news_limit"
    assert provider.calls == []
