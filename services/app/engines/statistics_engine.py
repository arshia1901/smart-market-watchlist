"""Statistics Engine (spec 6.1 #5).

Asynchronous and allowed to lag. Maintains one sigma per stock over a fixed
750-bucket window, the same window for every stock.

On boot it rebuilds every window from the time series before tailing the stream.
That is what makes stopping this container safe: the durable record is the time
series, not the message backlog, so a restart catches up rather than resuming with
a hole in sigma.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import SIGMA_WINDOW
from app.domain.statistics import RollingSigma
from app.ports import Stat

log = logging.getLogger("statistics")
GROUP = "statistics"


class StatisticsEngine:
    def __init__(self, store, cache, bus, symbols: list[str]) -> None:
        self._store = store
        self._cache = cache
        self._bus = bus
        self._windows: dict[str, RollingSigma] = {s: RollingSigma(SIGMA_WINDOW) for s in symbols}

    def rebuild_from_history(self) -> int:
        """Recompute every window from the time series. Idempotent, and the reason a
        restart cannot leave sigma subtly wrong."""
        rebuilt = 0
        for symbol, window in self._windows.items():
            prices = self._store.recent_prices(symbol, SIGMA_WINDOW)
            if prices:
                window.extend(prices)
                rebuilt += 1
            self._publish(symbol)
        log.info("rebuilt %d sigma windows from the time series", rebuilt)
        return rebuilt

    def observe(self, symbol: str, price: float, publish: bool = True) -> None:
        window = self._windows.get(symbol)
        if window is None:
            window = self._windows[symbol] = RollingSigma(SIGMA_WINDOW)
        window.observe(price)
        if publish:
            self._publish(symbol)

    def _publish(self, symbol: str) -> None:
        window = self._windows[symbol]
        stat = Stat(symbol, window.value(), window.observations,
                    datetime.now(timezone.utc))
        self._cache.put_stat(stat)
        self._store.put_stat(stat)

    def drain(self, block_ms: int = 1000) -> int:
        """Observe everything in the batch, then publish once per touched symbol.

        A warm-up back-fill delivers 750 quotes for one stock at once. Publishing per
        quote meant 750 sigma recomputations and 750 database writes to say one
        thing - which is why a freshly warmed stock sat at sigma NULL for a while.
        """
        quotes = self._bus.consume(GROUP, "statistics-1", block_ms=block_ms)
        touched: set[str] = set()
        for q in quotes:
            self.observe(q.symbol, q.price, publish=False)
            touched.add(q.symbol)
        for symbol in touched:
            self._publish(symbol)
        return len(quotes)
