"""Shared cache for last-known quotes and sigma (spec 6.1 #7).

Two rules make this safe:

  * write-if-newer on the quote's own event time (spec 5.3), applied atomically in
    Lua so two ingestion workers cannot interleave a read and a write.
  * NO TTL on quote or sigma keys (spec 9). With one, the watchlist would go *blank*
    when ingestion stops rather than ageing - demonstrating the opposite of the
    thesis on the one behaviour we chose to showcase. Staleness is computed from the
    stored `as_of`, never from key expiry.
"""
from __future__ import annotations

import json
from datetime import datetime

import redis

from app.ports import Quote, Stat

# Compare-and-set on event time. 1 = applied, 2 = same event time (nothing new
# traded - the normal case every minute on a closed market), 0 = genuinely older.
# The distinction matters for what the UI says: "unchanged since Fri 16:00" is the
# truth; "late tick dropped" reads as a fault.
_WRITE_IF_NEWER = """
local existing = redis.call('HGET', KEYS[1], 'as_of')
if existing then
  local e = tonumber(existing); local n = tonumber(ARGV[2])
  if e > n then return 0 end
  if e == n then return 2 end
end
redis.call('HSET', KEYS[1], 'price', ARGV[1], 'as_of', ARGV[2], 'source', ARGV[3])
return 1
"""

APPLIED, LATE, UNCHANGED = 1, 0, 2


class RedisCache:
    def __init__(self, url: str) -> None:
        self._r = redis.from_url(url, decode_responses=True)
        self._put = self._r.register_script(_WRITE_IF_NEWER)

    def healthy(self) -> bool:
        try:
            return bool(self._r.ping())
        except redis.RedisError:
            return False

    def put_quote(self, quote: Quote) -> int:
        """APPLIED, UNCHANGED (same event time) or LATE (older event time)."""
        return int(self._put(keys=[f"quote:{quote.symbol}"],
                             args=[quote.price, quote.as_of.timestamp(), quote.source]))

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if not symbols:
            return {}
        pipe = self._r.pipeline()
        for s in symbols:
            pipe.hgetall(f"quote:{s}")
        out: dict[str, Quote] = {}
        for symbol, raw in zip(symbols, pipe.execute()):
            if raw:
                out[symbol] = Quote(symbol, float(raw["price"]),
                                    datetime.fromtimestamp(float(raw["as_of"])).astimezone(),
                                    raw.get("source", "cache"))
        return out

    # The system clock. In replay mode this is the timeline the data came from, and
    # the read path must classify freshness against it - otherwise a replayed Friday
    # session reads "market closed" all weekend and no freshness state is ever seen.
    def set_clock(self, moment: datetime) -> None:
        self._r.set("clock:now", moment.timestamp())

    def get_clock(self) -> datetime | None:
        raw = self._r.get("clock:now")
        return datetime.fromtimestamp(float(raw)).astimezone() if raw else None

    # Batch heartbeats. A scheduled pipeline that reports nothing is
    # indistinguishable from a stalled one, so each engine says when it last ran,
    # what it did, and when it is due again.
    def beat(self, service: str, payload: dict) -> None:
        self._r.set(f"beat:{service}", json.dumps(payload))

    def beats(self) -> dict[str, dict]:
        keys = self._r.keys("beat:*")
        if not keys:
            return {}
        return {k.split(":", 1)[1]: json.loads(v)
                for k, v in zip(keys, self._r.mget(keys)) if v}

    def put_stat(self, stat: Stat) -> None:
        self._r.set(f"sigma:{stat.symbol}", json.dumps({
            "sigma": stat.sigma,
            "observations": stat.observations,
            "updated_at": stat.updated_at.timestamp(),
        }))

    def get_stats(self, symbols: list[str]) -> dict[str, Stat]:
        if not symbols:
            return {}
        raws = self._r.mget([f"sigma:{s}" for s in symbols])
        out: dict[str, Stat] = {}
        for symbol, raw in zip(symbols, raws):
            if raw:
                d = json.loads(raw)
                out[symbol] = Stat(symbol, d["sigma"], d["observations"],
                                   datetime.fromtimestamp(d["updated_at"]).astimezone())
        return out
