"""Subscription Engine as a persistent, replayable stream (spec 6.1 #4).

Deliberately NOT pub/sub. Pub/sub is fire-and-forget: stop the Statistics Engine,
restart it, and every message published in between is gone - sigma silently develops
a hole during the exact demo we want to run. A stream with a consumer group keeps the
backlog, so the engine catches up instead of losing history.
"""
from __future__ import annotations

from datetime import datetime, timezone

import redis

STREAM = "quotes"
MAXLEN = 50_000          # bounded: the time series is the durable record, not this


class RedisStreamBus:
    def __init__(self, url: str) -> None:
        self._r = redis.from_url(url, decode_responses=True)

    def publish(self, quotes: list) -> None:
        if not quotes:
            return
        pipe = self._r.pipeline()
        for q in quotes:
            pipe.xadd(STREAM,
                      {"symbol": q.symbol, "price": q.price,
                       "as_of": q.as_of.timestamp(), "source": q.source},
                      maxlen=MAXLEN, approximate=True)
        pipe.execute()

    def ensure_group(self, group: str) -> None:
        try:
            self._r.xgroup_create(STREAM, group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def consume(self, group: str, consumer: str, block_ms: int = 1000, count: int = 500) -> list:
        from app.ports import Quote
        self.ensure_group(group)
        batches = self._r.xreadgroup(group, consumer, {STREAM: ">"},
                                     count=count, block=block_ms)
        out = []
        for _stream, entries in batches or []:
            ids = []
            for entry_id, f in entries:
                out.append(Quote(f["symbol"], float(f["price"]),
                                 datetime.fromtimestamp(float(f["as_of"]), tz=timezone.utc),
                                 f.get("source", "bus")))
                ids.append(entry_id)
            if ids:
                self._r.xack(STREAM, group, *ids)
        return out
