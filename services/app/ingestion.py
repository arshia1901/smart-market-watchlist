"""Ingestion service entrypoint.

Publishes its own notion of "now" to the cache each tick. In replay mode that IS the
system's clock - the design says the clock is injected and never global, and the read
path has to honour the same rule or a replayed Friday session would read "market
closed" all weekend and no freshness state would ever be visible.

Nothing is hidden by this: the UI displays the replay clock explicitly.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime

from app.adapters.bus_redis import RedisStreamBus
from app.adapters.cache_redis import RedisCache
from app.adapters.provider_live import build_provider
from app.adapters.store_postgres import PostgresStore
from app.config import DATABASE_URL, GRID_SECONDS, IST, PROVIDER, REDIS_URL
from app.domain.calendar import recent_trading_days

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingestion")


_running = True


def _stop(signum, _frame):
    global _running
    _running = False
    log.info("signal %s received, stopping cleanly", signum)


def warm_up(symbol: str, scripcode: str | None, store, cache, bus, sessions) -> None:
    """Give a newly tracked stock a sigma window NOW, from one real session.

    Without this a stock added from the search box sits *unrated* for two trading days
    - the product's thesis invisible for exactly the stock the user just asked about.
    The fill resamples the stock's own intraday returns so it carries the right
    volatility, ends exactly at the current price so the live stream continues from
    it, and is marked synthetic so the UI can call the result provisional.
    """
    from app.adapters.provider_live import header_quote, intraday_bars
    from app.config import SIGMA_WINDOW
    from app.domain.backfill import bucket_times_back, synthesize
    from app.domain.statistics import returns_from_prices, sigma_of
    from app.ports import ProviderUnavailable, Quote

    # "Has some rows" is not "has history". A stray bucket or two must not block the
    # fill - that exact case silently skipped a warm-up once. Fill whenever the stock is
    # short of a full window; the (instrument, bucket_ts) primary key keeps every real
    # bucket and lets synthetic ones land only in empty grid slots.
    if not scripcode:
        return
    if store.snapshot_count(symbol) >= SIGMA_WINDOW:
        # History already exists (tracked before, or by someone else). No fill needed -
        # but a list that just gained this stock still needs its baseline anchored at
        # the price it had when added, or the row shows a move nobody watched.
        held = store.latest_quotes([symbol]).get(symbol)
        if held is not None:
            store.set_baseline_if_missing(symbol, held.price)
        return

    # Preferred: the stock's own real 1-minute bars for today, so the fill carries
    # its real spread. Fallback, when that history is not available: fill the past
    # at the CURRENT price - the same level, with the market's typical deviation
    # rather than literally zero, because 750 identical prices have no spread at
    # all, sigma collapses to its floor, and the first real move reads *extreme*.
    try:
        bars = intraday_bars(scripcode)
    except ProviderUnavailable as exc:
        log.warning("warm-up %s: no intraday bars (%s) - falling back to a flat fill "
                    "at the current price", symbol, exc)
        bars = []

    # The last-known value is anchored at what the live loop will see every minute -
    # the quote endpoint's own price and stamp - never at the last intraday bar.
    header = header_quote(scripcode) if scripcode else None

    if len(bars) >= 2:
        real_prices = [p for _, p in bars]
        real_returns = returns_from_prices(real_prices)
        if header:
            anchor_price, anchor_ts, _ = header
        else:
            anchor_ts, anchor_price = bars[-1]
            anchor_ts = anchor_ts.replace(second=0, microsecond=0)
        fill_kind = f"{len(bars)} real bars"
    else:
        held = store.latest_quotes([symbol]).get(symbol) or cache.get_quotes([symbol]).get(symbol)
        if held is None:
            log.warning("warm-up %s: no bars and no current price yet - will retry next cycle",
                        symbol)
            return
        real_returns = []
        anchor_ts, anchor_price = held.as_of, held.price
        fill_kind = "flat fill at the current price (no 1-minute history available)"

    # The market's typical sigma stands in only when the session is too thin to speak.
    typical = sorted(s.sigma for s in store.latest_stats().values() if s.sigma) or [0.0007]
    prices = synthesize(real_returns, anchor_price, SIGMA_WINDOW,
                        seed=hash(symbol) & 0xFFFF, fallback_sigma=typical[len(typical) // 2])
    times = bucket_times_back(anchor_ts, SIGMA_WINDOW, sessions)
    n = min(len(prices), len(times))
    quotes = [Quote(symbol, p, t, "backfill") for p, t in zip(prices[-n:], times[-n:])]

    store.append(quotes, synthetic=True)
    bus.publish(quotes)                      # statistics fills the window and publishes sigma
    cache.put_quote(Quote(symbol, anchor_price, anchor_ts, "bse"))
    store.put_quote(Quote(symbol, anchor_price, anchor_ts, "bse"))
    if header and header[2]:
        store.set_previous_close({symbol: header[2]})
    # Adding a stock IS checking it. Its baseline is the first price it gets, so the
    # very next login shows a delta - not the one after that.
    store.set_baseline_if_missing(symbol, anchor_price)
    measured = f"sigma {sigma_of(real_returns) * 100:.4f}%" if real_returns else "typical sigma"
    log.info("warm-up %s: %s -> %s -> %d buckets back-filled to %.2f "
             "(provisional until real history replaces it)",
             symbol, fill_kind, measured, n, anchor_price)


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    store = PostgresStore(DATABASE_URL)
    cache = RedisCache(REDIS_URL)
    bus = RedisStreamBus(REDIS_URL)

    sessions = recent_trading_days(3, datetime.now(IST).date(), frozenset())

    def tracked() -> tuple[list[str], dict[str, str]]:
        """Re-read each cycle, so a stock added from the UI is picked up on the next
        tick rather than at the next restart."""
        rows = store.tracked()
        return ([r["symbol"] for r in rows],
                {r["symbol"]: r["bse_code"] for r in rows if r["bse_code"]})

    symbols, codes = tracked()
    provider = build_provider(PROVIDER, sessions[2], codes, store=store)

    # Anything tracked but short of a sigma window gets warmed at startup too - a
    # stock added before this code existed, or added while ingestion was down.
    for symbol in symbols:
        warm_up(symbol, codes.get(symbol), store, cache, bus, sessions)

    from app.engines.ingestion import IngestionEngine
    engine = IngestionEngine(provider, cache, store, bus, symbols)

    # Resume where a previous run left off rather than replaying from the open.
    if hasattr(provider, "fast_forward_past"):
        held = store.latest_quotes(symbols)
        newest = max((q.as_of for q in held.values()), default=None)
        skipped = provider.fast_forward_past(newest)
        if skipped:
            log.info("resuming: skipped %d ticks already ingested (up to %s)",
                     skipped, newest.strftime("%H:%M") if newest else "-")

    # One cadence, the real one, with no multiplier left in the code to leak. Twice now
    # a replay-speed factor ended up driving a real API at two-second intervals - once
    # from compose, once from a code default after the compose line was removed. It is
    # gone: there is nothing to speed up in a live system.
    interval = GRID_SECONDS
    log.info("ingesting %d symbols via %s | tick every %.1fs | session %s",
             len(symbols), provider.name, interval, sessions[2])

    _replay_done = False
    while _running:
        # Pick up anything added since the last cycle.
        symbols, codes = tracked()
        if len(symbols) != len(engine._symbols):
            added = sorted(set(symbols) - set(engine._symbols))
            gone = sorted(set(engine._symbols) - set(symbols))
            if added:
                log.info("now tracking %s (added from the UI) - collecting from here on",
                         ", ".join(added))
            if gone:
                log.info("no longer tracking %s (removed from every list) - collection stops",
                         ", ".join(gone))
            engine._symbols = symbols
            if hasattr(provider, "scripcodes"):
                provider.scripcodes = codes
            for symbol in added:
                warm_up(symbol, codes.get(symbol), store, cache, bus, sessions)

        started = time.time()
        applied = engine.tick()

        cache.beat("ingestion", {
            "last_run": started,
            "duration_ms": round((time.time() - started) * 1000),
            "interval_seconds": interval,
            "next_run": started + interval,
            "tracked": len(symbols),
            "applied": applied,
            "applied_total": engine.applied,
            "unchanged": engine.unchanged,
            "dropped_late": engine.dropped_late,
            "provider": provider.name,
            "replay_done": _replay_done,
        })

        # Publish the system clock so the read path classifies freshness against the
        # same timeline the data came from.
        latest = cache.get_quotes(symbols)
        if latest:
            cache.set_clock(max(q.as_of for q in latest.values()))

        # The fixture running out is not the end of ingestion. The live leg still
        # serves anything a user has added, so the loop must keep turning - an
        # earlier version parked here and a newly tracked stock could never be
        # collected once the replay finished.
        if getattr(provider, "exhausted", False) and not _replay_done:
            _replay_done = True
            log.info("replay fixture complete (%d ticks). Seeded stocks now hold their "
                     "last known values and age; anything added from the UI keeps "
                     "collecting live.", provider.progress[1])

        if applied:
            log.debug("tick applied=%d dropped_late=%d", applied, engine.dropped_late)
        time.sleep(interval)

    log.info("stopped. applied=%d dropped_late=%d", engine.applied, engine.dropped_late)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
