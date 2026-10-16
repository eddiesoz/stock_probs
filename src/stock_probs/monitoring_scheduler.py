"""Run persisted price checks through one bounded, restartable service loop."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import uuid4

from .monitoring_domain import MonitoringError, PriceObservation, instant, price
from .monitoring_store import (
    MAX_JOB_BATCH,
    MAX_LEASE_SECONDS,
    MonitoringConflictError,
    MonitoringStore,
    MonitoringStoreError,
)
from .notification_delivery import MAX_NOTIFICATION_BATCH
from .provider import YAHOO_PROVIDER_NAME

LOGGER = logging.getLogger(__name__)
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_CHECK_INTERVAL = timedelta(minutes=15)
DEFAULT_LEASE_SECONDS = 60
DEFAULT_BATCH_SIZE = 2
DEFAULT_CLOSE_SECONDS = 10.0
MAX_POLL_SECONDS = 30.0
MAX_CLOSE_SECONDS = 30.0
MAX_QUOTE_LABEL_BYTES = 512


class ForecastProvider(Protocol):
    """Expose only the shared bounded lookup and quote capabilities used by monitoring."""

    def lookup(self, query: str, limit: int = 5) -> object: ...

    def quote_snapshot(self, symbol: str, asset_type: str) -> object: ...


class OutcomeCollector(Protocol):
    """Expose bounded daily-outcome work to the existing monitoring worker."""

    def run_once(
        self,
        now: datetime,
        *,
        worker_id: str,
        limit: int,
        cancelled: Callable[[], bool],
    ) -> Mapping[str, int]: ...


class NotificationDelivery(Protocol):
    """Expose the bounded email batch without giving the scheduler SMTP internals."""

    def run_due(
        self,
        worker_id: str,
        now: datetime,
        *,
        limit: int,
        lease_seconds: int,
        cancelled: Callable[[], bool],
    ) -> object: ...


class _InvalidProviderResponse(ValueError):
    """Mark malformed or simulated provider data without retaining the raw response."""


class MonitoringScheduler:
    """Process persisted price and optional daily-outcome jobs in one serial loop.

    Construction performs no database, thread, or provider work. The application lifespan owns
    the explicit asynchronous start and close calls; persisted leases make process restarts safe.
    """

    def __init__(
        self,
        store: MonitoringStore,
        service: ForecastProvider,
        *,
        outcome_collector: OutcomeCollector | None = None,
        notification_delivery: NotificationDelivery | None = None,
        clock: Callable[[], datetime] | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        worker_id: str | None = None,
    ) -> None:
        if not isinstance(store, MonitoringStore):
            raise TypeError("store must be a MonitoringStore")
        if not callable(getattr(service, "lookup", None)) or not callable(
            getattr(service, "quote_snapshot", None)
        ):
            raise TypeError("service must provide lookup and quote_snapshot")
        if outcome_collector is not None and not callable(
            getattr(outcome_collector, "run_once", None)
        ):
            raise TypeError("outcome_collector must provide run_once")
        if notification_delivery is not None and not callable(
            getattr(notification_delivery, "run_due", None)
        ):
            raise TypeError("notification_delivery must provide run_due")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, int | float)
            or not math.isfinite(float(poll_interval_seconds))
            or not 0.05 <= float(poll_interval_seconds) <= MAX_POLL_SECONDS
        ):
            raise ValueError("poll interval is outside its bound")
        if type(batch_size) is not int or not 1 <= batch_size <= min(4, MAX_JOB_BATCH):
            raise ValueError("price job batch size is outside its bound")
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= MAX_LEASE_SECONDS:
            raise ValueError("price job lease is outside its bound")
        if worker_id is not None and (
            not isinstance(worker_id, str)
            or not 1 <= len(worker_id) <= 80
            or any(
                not (character.isascii() and (character.isalnum() or character in "_.:-"))
                for character in worker_id
            )
        ):
            raise ValueError("worker identifier is invalid")
        self.store = store
        self.service = service
        self.outcome_collector = outcome_collector
        self.notification_delivery = notification_delivery
        self.clock = clock or (lambda: datetime.now(UTC))
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.worker_id = worker_id or f"monitor-{uuid4()}"
        self._stop = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False
        self._closed = False
        self._next_work_kind = "price"

    async def start(self) -> None:
        """Start the single polling thread once, without doing provider work inline."""

        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("a closed monitoring scheduler cannot be restarted")
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="stock-probs-monitoring",
                daemon=True,
            )
            self._started = True
            self._thread.start()

    async def close(self, timeout_seconds: float = DEFAULT_CLOSE_SECONDS) -> None:
        """Stop polling and wait asynchronously for the bounded active provider call to return."""

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not math.isfinite(float(timeout_seconds))
            or not 0.0 <= float(timeout_seconds) <= MAX_CLOSE_SECONDS
        ):
            raise ValueError("close timeout is outside its bound")
        with self._lifecycle_lock:
            thread = self._thread
            self._stop.set()
        if thread is None:
            with self._lifecycle_lock:
                self._closed = True
            return
        deadline = time.monotonic() + float(timeout_seconds)
        while thread.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        thread.join(timeout=0)
        if thread.is_alive():
            raise TimeoutError("the active monitoring provider call has not returned")
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None
            self._closed = True

    def status(self) -> dict[str, bool]:
        """Report whether the explicit application-lifespan worker is currently alive."""

        thread = self._thread
        return {"running": bool(thread is not None and thread.is_alive())}

    def run_once(self) -> int:
        """Process one bounded batch synchronously for deterministic local verification."""

        if not self._run_lock.acquire(blocking=False):
            return 0
        try:
            if self._stop.is_set():
                return 0
            now = self._now()
            if not self.store.get_control()["enabled"]:
                return 0
            completed = 0
            if self.outcome_collector is not None:
                work_kind = self._next_work_kind
                self._next_work_kind = "outcome" if work_kind == "price" else "price"
                if work_kind == "outcome":
                    completed = self._process_outcome_batch(now)
                else:
                    completed = self._process_price_batch(now)
            else:
                completed = self._process_price_batch(now)
            self._run_notification_delivery(now)
            return completed
        finally:
            self._run_lock.release()

    def _process_price_batch(self, now: datetime) -> int:
        """Run one ordinary bounded price batch before any optional email work."""
        claims = self.store.claim_due_price_jobs(
            self.worker_id,
            now,
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        completed = 0
        for claim in claims:
            if self._stop.is_set():
                break
            if self._process_claim(claim):
                completed += 1
        return completed

    def _run_notification_delivery(self, now: datetime) -> None:
        """Dispatch one serial, four-message maximum batch under live stop/control checks."""
        consumer = self.notification_delivery
        if consumer is None or self._notification_delivery_cancelled():
            return
        try:
            consumer.run_due(
                self.worker_id,
                now,
                limit=MAX_NOTIFICATION_BATCH,
                lease_seconds=30,
                cancelled=self._notification_delivery_cancelled,
            )
        except Exception:
            # A mail transport failure must not interrupt price checks or the local app.
            LOGGER.error("The monitoring notification delivery iteration failed.")

    def _notification_delivery_cancelled(self) -> bool:
        """Fail closed on scheduler stop, disabled global control, or unavailable control read."""
        if self._stop.is_set():
            return True
        try:
            return self.store.get_control().get("enabled") is not True
        except Exception:
            return True

    def _process_outcome_batch(self, now: datetime) -> int:
        """Run one bounded outcome batch without allowing its failures to stop price checks."""
        if self._stop.is_set() or self.outcome_collector is None:
            return 0
        try:
            result = self.outcome_collector.run_once(
                now,
                worker_id=self.worker_id,
                limit=self.batch_size,
                cancelled=self._stop.is_set,
            )
        except Exception:
            LOGGER.error("The daily outcome collection iteration failed.")
            return 0
        if not isinstance(result, Mapping):
            LOGGER.error("The daily outcome collector returned an invalid batch summary.")
            return 0
        recorded = result.get("recorded", 0)
        unchanged = result.get("unchanged", 0)
        if type(recorded) is not int or type(unchanged) is not int or recorded < 0 or unchanged < 0:
            LOGGER.error("The daily outcome collector returned an invalid batch summary.")
            return 0
        return recorded + unchanged

    def _run_loop(self) -> None:
        """Keep one bounded worker alive without exposing provider exceptions in logs."""

        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                LOGGER.error("The monitoring iteration failed.")
            if self._stop.wait(self.poll_interval_seconds):
                break

    def _process_claim(self, claim: Mapping[str, object]) -> bool:
        owner = claim.get("owner_user_id")
        alert_id = claim.get("resource_id")
        if type(owner) is not int or not isinstance(alert_id, str):
            return False
        try:
            initial = self._claim_context(owner, alert_id, claim)
        except MonitoringStoreError:
            return False
        config = initial.get("config")
        if not isinstance(config, Mapping):
            return False
        symbol = config.get("symbol")
        currency = config.get("currency")
        if not isinstance(symbol, str) or not isinstance(currency, str):
            return False
        try:
            self._claim_context(owner, alert_id, claim)
            if self._stop.is_set():
                return False
            lookup = self.service.lookup(symbol, 1)
        except Exception:
            return self._record_failure(owner, alert_id, claim, "provider_unavailable")
        try:
            identity = self._validated_identity(lookup, symbol, currency)
        except _InvalidProviderResponse:
            return self._record_failure(owner, alert_id, claim, "provider_response_invalid")
        try:
            self._claim_context(owner, alert_id, claim)
            if self._stop.is_set():
                return False
            quote = self.service.quote_snapshot(symbol, identity["asset_type"])
        except Exception:
            return self._record_failure(owner, alert_id, claim, "provider_unavailable")
        try:
            observation = self._validated_observation(quote, identity, symbol, currency)
        except _InvalidProviderResponse:
            return self._record_failure(owner, alert_id, claim, "provider_response_invalid")
        if self._stop.is_set():
            return False
        received = self._now()
        try:
            self._claim_context(owner, alert_id, claim, at=received)
            self.store.record_price_observation(
                owner,
                alert_id,
                claim,
                observation,
                received,
                received,
                next_due_at=received + DEFAULT_CHECK_INTERVAL,
            )
        except MonitoringConflictError:
            return False
        return True

    def _claim_context(
        self,
        owner: int,
        alert_id: str,
        claim: Mapping[str, object],
        *,
        at: datetime | None = None,
    ) -> dict[str, object]:
        if self._stop.is_set():
            raise MonitoringConflictError("The scheduler is stopping.")
        return self.store.get_price_claim_context(owner, alert_id, claim, at or self._now())

    def _record_failure(
        self,
        owner: int,
        alert_id: str,
        claim: Mapping[str, object],
        failure_code: str,
    ) -> bool:
        if self._stop.is_set():
            return False
        now = self._now()
        try:
            self._claim_context(owner, alert_id, claim, at=now)
            self.store.record_price_failure(
                owner,
                alert_id,
                claim,
                failure_code,
                now,
                next_due_at=now + DEFAULT_CHECK_INTERVAL,
            )
        except MonitoringStoreError:
            return False
        return True

    @staticmethod
    def _validated_identity(
        response: object,
        symbol: str,
        currency: str,
    ) -> dict[str, str]:
        if not isinstance(response, Mapping):
            raise _InvalidProviderResponse
        identities = response.get("items")
        if not isinstance(identities, list) or len(identities) != 1:
            raise _InvalidProviderResponse
        identity = identities[0]
        if not isinstance(identity, Mapping):
            raise _InvalidProviderResponse
        canonical_symbol = identity.get("canonical_symbol")
        identity_currency = identity.get("currency")
        asset_type = identity.get("asset_type")
        provider = identity.get("provider")
        if (
            not isinstance(canonical_symbol, str)
            or canonical_symbol != symbol
            or not isinstance(identity_currency, str)
            or identity_currency != currency
            or not isinstance(asset_type, str)
            or asset_type not in {"stock", "etf"}
            or not isinstance(provider, str)
            or provider != YAHOO_PROVIDER_NAME
        ):
            raise _InvalidProviderResponse
        _parse_provider_timestamp(identity.get("provider_as_of"))
        return {
            "symbol": canonical_symbol,
            "currency": identity_currency,
            "asset_type": asset_type,
            "provider": provider,
        }

    def _validated_observation(
        self,
        response: object,
        identity: Mapping[str, str],
        symbol: str,
        currency: str,
    ) -> PriceObservation:
        if not isinstance(response, Mapping):
            raise _InvalidProviderResponse
        quote_symbol = response.get("symbol")
        quote_currency = response.get("currency")
        provider = response.get("provider")
        label = response.get("label")
        delayed = response.get("delayed")
        delay_minutes = response.get("delay_minutes")
        try:
            label_size = len(label.encode("utf-8")) if isinstance(label, str) else 0
        except UnicodeError as error:
            raise _InvalidProviderResponse from error
        if (
            quote_symbol != symbol
            or quote_symbol != identity["symbol"]
            or quote_currency != currency
            or quote_currency != identity["currency"]
            or provider != identity["provider"]
            or not isinstance(label, str)
            or not 1 <= label_size <= MAX_QUOTE_LABEL_BYTES
            or not label.isprintable()
            or "simulat" in label.casefold()
            or type(delayed) is not bool
            or (
                delay_minutes is not None
                and (type(delay_minutes) is not int or not 0 <= delay_minutes <= 1440)
            )
        ):
            raise _InvalidProviderResponse
        observed_at = _parse_provider_timestamp(response.get("as_of"))
        now = self._now()
        if observed_at > now or now - observed_at > timedelta(days=7):
            raise _InvalidProviderResponse
        raw_price = response.get("price")
        if isinstance(raw_price, bool) or not isinstance(raw_price, int | float):
            raise _InvalidProviderResponse
        try:
            numeric_price = float(raw_price)
        except (OverflowError, ValueError) as error:
            raise _InvalidProviderResponse from error
        if not math.isfinite(numeric_price):
            raise _InvalidProviderResponse
        try:
            decimal_price = Decimal(str(raw_price))
            price_text = format(decimal_price, "f")
            price(price_text)
        except (InvalidOperation, MonitoringError) as error:
            raise _InvalidProviderResponse from error
        if len(price_text) > 64:
            raise _InvalidProviderResponse
        return PriceObservation(
            symbol=symbol,
            price=price_text,
            currency=currency,
            observed_at=observed_at,
            provider=identity["provider"],
        )

    def _now(self) -> datetime:
        try:
            return instant(self.clock())
        except MonitoringError as error:
            raise ValueError("scheduler clock must return a timezone-aware datetime") from error


def _parse_provider_timestamp(value: object) -> datetime:
    """Parse the provider's offset-bearing ISO timestamp without assuming a local timezone."""

    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        raise _InvalidProviderResponse
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        return instant(parsed)
    except (ValueError, MonitoringError) as error:
        raise _InvalidProviderResponse from error
