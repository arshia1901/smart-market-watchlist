"""Statistics service entrypoint.

Rebuilds every sigma window from the time series before tailing the stream, which is
what makes `docker compose stop statistics` safe: the durable record is the time
series, not the message backlog.
"""
from __future__ import annotations

import logging
import os
import signal

from app.adapters.bus_redis import RedisStreamBus
from app.adapters.cache_redis import RedisCache
from app.adapters.store_postgres import PostgresStore
from app.config import DATABASE_URL, REDIS_URL
from app.engines.statistics_engine import StatisticsEngine

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("statistics")

_running = True


def _stop(signum, _frame):
    global _running
    _running = False
    log.info("signal %s received, stopping cleanly", signum)


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    store = PostgresStore(DATABASE_URL)
    cache = RedisCache(REDIS_URL)
    bus = RedisStreamBus(REDIS_URL)

    engine = StatisticsEngine(store, cache, bus, [r["symbol"] for r in store.tracked()])
    engine.rebuild_from_history()
    log.info("tailing the quote stream")

    import time
    while _running:
        started = time.time()
        consumed = engine.drain(block_ms=1000)
        rated = sum(1 for w in engine._windows.values() if w.ready)
        cache.beat("statistics", {
            "last_run": started,
            "duration_ms": round((time.time() - started) * 1000),
            "consumed": consumed,
            "windows": len(engine._windows),
            "rated": rated,
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
