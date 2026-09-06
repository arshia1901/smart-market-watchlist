"""Read API (spec 6.1 #9).

Serves stored values and does no per-user arithmetic: the magnitude and the ranking
are computed by the client (spec 6.3). Nothing here computes, blocks, or fails.

The split between the two payloads is enforced by the API shape rather than by
discipline (spec 8): /api/quotes carries no per-user data at all, so it can be cached
once and served to arbitrarily many viewers.
"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.adapters.bus_redis import RedisStreamBus
from app.adapters.cache_redis import RedisCache
from app.adapters.store_postgres import PostgresStore
from app.config import (
    BUCKETS_PER_TRADING_DAY, DATABASE_URL, GRID_SECONDS, IST, MEASURE, PROVIDER,
    REDIS_URL, SIGMA_WINDOW, TEST_SYMBOLS, USERS,
)
from app.domain.calendar import freshness, is_market_open, trading_buckets_between

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")

store = PostgresStore(DATABASE_URL)
cache = RedisCache(REDIS_URL)
HOLIDAYS: frozenset = frozenset()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("read api up | provider=%s measure=%s grid=%ss window=%s",
             PROVIDER, MEASURE, GRID_SECONDS, SIGMA_WINDOW)
    yield


app = FastAPI(title="Smart Market Watchlist", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ---------------------------------------------------------------- helpers

def _tracked() -> list[str]:
    """Re-read every call. An earlier version cached this once per process on the
    grounds that the catalogue is static - true, but the TRACKED set is not: adding a
    stock changes it, and a stale cache served quotes for whatever happened to be
    tracked when the API booted. One indexed query, behind a 2-second edge cache."""
    return [r["symbol"] for r in store.tracked()]


def _quotes(symbols: list[str]) -> tuple[dict, str]:
    """Cache first, relational store second.

    Spec 5.5: the cache is an accelerator, never the source of truth. Without this
    fallback the cache would sit INSIDE the read path and become the single point of
    failure the design claims not to have.
    """
    wanted = symbols or _tracked()
    if cache.healthy():
        found = cache.get_quotes(wanted)
        if found:
            return found, "cache"
    return store.latest_quotes(wanted), "store"


def _now() -> datetime:
    """The system's now.

    In replay mode the ingestion engine publishes the timeline the data came from,
    and freshness is classified against that - the clock is injected here too, not
    read globally. Wall clock is the fallback, and the UI always shows which.
    """
    if PROVIDER == "replay" and cache.healthy():
        clock = cache.get_clock()
        if clock is not None:
            return clock
    return datetime.now().astimezone()


def _stats(symbols: list[str]) -> dict:
    wanted = symbols or _tracked()
    if cache.healthy():
        found = cache.get_stats(wanted)
        if found:
            return found
    return store.latest_stats(wanted)


# ---------------------------------------------------------------- models

class LoginRequest(BaseModel):
    username: str
    password: str | None = None


class LogoutRequest(BaseModel):
    token: str


# ---------------------------------------------------------------- routes

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "provider": PROVIDER,
        "cache": "up" if cache.healthy() else "degraded",
        "measure": MEASURE,
        "grid_seconds": GRID_SECONDS,
        "sigma_window": SIGMA_WINDOW,
    }


@app.get("/api/status")
def status():
    """What the scheduled pipeline is doing, so the UI can show it.

    A batch system that reports nothing looks identical to a stalled one - and the
    resilience demo depends on a viewer being able to tell the difference.
    """
    beats = cache.beats() if cache.healthy() else {}
    return {
        "now": datetime.now().astimezone().timestamp(),
        "grid_seconds": GRID_SECONDS,
        "provider": PROVIDER,
        "cache": "up" if cache.healthy() else "down",
        "services": beats,
    }


@app.get("/api/quotes")
def quotes():
    """Shared and identical for every user, so it caches once and serves everyone.

    Carries no per-user data whatsoever - that is the whole scaling argument, made
    structural rather than aspirational.
    """
    found, served_by = _quotes([])
    now = _now()
    return {
        "as_of": now.isoformat(),
        "served_by": served_by,
        "clock": "replay" if PROVIDER == "replay" else "wall",
        # Said explicitly, not implied. A page that shows plausible-looking prices
        # without saying where they came from is the exact failure this whole design
        # argues against.
        "data_source": "simulated" if PROVIDER == "replay" else "live",
        "market_open": is_market_open(now, HOLIDAYS),
        "quotes": [
            {"symbol": q.symbol, "price": q.price, "as_of": q.as_of.isoformat(),
             "source": q.source,
             "freshness": freshness(q.as_of, now, HOLIDAYS).value}
            for q in sorted(found.values(), key=lambda q: q.symbol)
        ],
    }


@app.post("/api/session")
def login(req: LoginRequest):
    """The ONLY endpoint that advances baselines (spec 4.1).

    Auth is deliberately not engineered (spec 12). Hardcoded users, and a ?user=x
    bypass on the client. Its only job is demonstrating multi-user behaviour.
    """
    user = req.username.strip().lower()
    if user not in USERS:
        raise HTTPException(401, "unknown user")
    if req.password is None or USERS[user] != req.password:
        raise HTTPException(401, "bad password")

    # Sessions are sequential. A Sign in while one is open would silently re-anchor
    # every baseline - the exact thing that happened when ?user= acted as a hidden
    # login. Refuse it and say what to do instead.
    open_ = store.open_session(user)
    if open_ is not None:
        since = open_["started_at"].astimezone(timezone.utc).strftime("%H:%M UTC")
        raise HTTPException(409, f"{user} is already signed in (since {since}). "
                                 f"Sign out first; sessions are sequential.")

    now = _now()
    rows = store.watchlist(user)
    live, _ = _quotes([r.symbol for r in rows])

    # The shift happens here and ONLY here. Then the payload is built from stored
    # state - exactly what a refresh returns - so the two can never disagree. (An
    # earlier version read before advancing and handed the client an in-memory view
    # that a page refresh silently replaced with zeros.)
    store.advance_baselines(user, now, {s: q.price for s, q in live.items()})
    token = secrets.token_urlsafe(16)
    store.create_session(token, user, now)

    previous, current = store.logins(user)
    payload = _payload(user, store.watchlist(user), live, previous, now, session_started=current)
    payload["token"] = token
    return payload


@app.post("/api/session/logout")
def logout(req: LogoutRequest):
    """Ends the session the token opened. Baselines are untouched: they belong to the
    START of a session, and the next Sign in is what moves them."""
    user = store.end_session(req.token, _now())
    if user is None:
        raise HTTPException(404, "no open session for that token")
    return {"ok": True, "user": user}


@app.get("/api/watchlist")
def watchlist(user: str = Query(...)):
    """Current state WITHOUT advancing anything - the refresh path (spec 4.3).

    If this advanced baselines, F5 would wipe every highlight, which is the exact
    failure the session model exists to prevent.
    """
    user = user.strip().lower()
    if user not in USERS:
        raise HTTPException(401, "unknown user")
    if store.open_session(user) is None:
        raise HTTPException(401, "not signed in")       # a closed session's token is dead
    rows = store.watchlist(user)
    live, _ = _quotes([r.symbol for r in rows])
    previous, current = store.logins(user)
    return _payload(user, rows, live, previous, _now(), session_started=current)


def _payload(user: str, rows, live, previous, now, session_started=None) -> dict:
    """Raw materials only. The client computes magnitude and ranks (spec 6.3)."""
    n = (trading_buckets_between(previous, now, HOLIDAYS) if previous
         else BUCKETS_PER_TRADING_DAY)
    stats = _stats([r.symbol for r in rows])

    # No previous-close fallback any more. It was written for seeded watchlists,
    # where stocks appeared without the user adding them; it produced "+0.74%" on a
    # stock added on a Saturday - Friday's session move, which the user never watched.
    # Now every stock arrives by the user's action, adding IS checking, and the
    # baseline is the price at that instant. Until the first price lands the row is
    # NEW, which is the truth.
    provisional = store.provisional_symbols(SIGMA_WINDOW)

    return {
        "user": user,
        "n": max(n, 1),                    # the divisor; never zero on the wire
        "trading_minutes_elapsed": n,      # the truth; 0 on a weekend, and the UI says so
        "grid_seconds": GRID_SECONDS,      # so the client can render N as time
        "n_source": "since_last_login" if previous else "default_one_session",
        # Recorded and rendered in UTC. The market is IST; the record is not.
        "last_login": previous.astimezone(timezone.utc).isoformat() if previous else None,
        # When THIS session began - i.e. when the baselines last moved. Shown on the
        # page so a re-anchor is never invisible. On the login response this equals
        # server_time; on a refresh it is the open session's start.
        "session_started": session_started.astimezone(timezone.utc).isoformat() if session_started else None,
        "server_time": now.astimezone(timezone.utc).isoformat(),
        "rows": [
            {
                "symbol": r.symbol,
                "name": r.name,
                "baseline": r.baseline,
                # 'added'   = the price when this list gained the stock (no login since)
                # 'previous_session' = re-based at the user's last login
                "baseline_source": (None if r.baseline is None
                                    else "added" if previous is None or r.added_at >= previous
                                    else "previous_session"),
                "sigma": stats[r.symbol].sigma if r.symbol in stats else None,
                # Back-filled from one real session; provisional until 750 genuine
                # buckets have displaced the fill. Shown, never hidden.
                "sigma_provisional": r.symbol in provisional,
                "observations": stats[r.symbol].observations if r.symbol in stats else 0,
                "band_limit": r.band_limit,
                "added_at": r.added_at.isoformat(),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------- the canary
#
# /api/test/* feeds the one test instrument. Refuses every other symbol, so a real
# stock cannot be poisoned. Documented in the README for what it is.

def _canary_only(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if symbol not in TEST_SYMBOLS:
        raise HTTPException(400, f"{symbol} is not a test instrument; only {sorted(TEST_SYMBOLS)}")
    return symbol


@app.post("/api/test/quote")
def test_quote(symbol: str = Query(...), price: float = Query(..., gt=0), now: int = 0):
    """Set the canary's next quote. Ingestion picks it up on its next tick (<=60s),
    through exactly the path a real stock takes. `now=1` injects immediately instead -
    useful for UI checks, but it bypasses the ingestion container and says so."""
    symbol = _canary_only(symbol)
    from app.ports import Quote
    as_of = datetime.now(IST)
    store.set_test_quote(symbol, price, as_of)
    if not now:
        return {"ok": True, "symbol": symbol, "price": price, "as_of": as_of.isoformat(),
                "applied": "on the next ingestion tick"}
    q = Quote(symbol, price, as_of, "test")
    outcome = cache.put_quote(q)
    store.put_quote(q); store.append([q]); RedisStreamBus(REDIS_URL).publish([q])
    store.set_baseline_if_missing(symbol, price)
    return {"ok": True, "symbol": symbol, "price": price, "as_of": as_of.isoformat(),
            "applied": "immediately (ingestion bypassed)", "cache_outcome": outcome}


@app.post("/api/test/warmup")
def test_warmup(symbol: str = Query(...), price: float = Query(..., gt=0),
                sigma: float = Query(0.0007, gt=0, lt=0.1)):
    """Give the canary a sigma window: 750 buckets around `price` with the planted
    per-minute `sigma`, marked synthetic (badge: provisional). Same back-fill a real
    stock gets, minus the real bars it has none of."""
    symbol = _canary_only(symbol)
    from app.domain.backfill import bucket_times_back, synthesize
    from app.domain.calendar import recent_trading_days
    from app.ports import Quote
    now = datetime.now(IST)
    prices = synthesize([], price, SIGMA_WINDOW, seed=hash(symbol) & 0xFFFF, fallback_sigma=sigma)
    times = bucket_times_back(now, SIGMA_WINDOW, recent_trading_days(3, now.date(), HOLIDAYS))
    n = min(len(prices), len(times))
    quotes = [Quote(symbol, p, t, "test-backfill") for p, t in zip(prices[-n:], times[-n:])]
    store.append(quotes, synthetic=True)
    RedisStreamBus(REDIS_URL).publish(quotes)
    store.set_test_quote(symbol, price, now)
    anchor = Quote(symbol, price, now, "test")
    cache.put_quote(anchor); store.put_quote(anchor)
    store.set_baseline_if_missing(symbol, price)
    return {"ok": True, "symbol": symbol, "buckets": n, "planted_sigma": sigma, "anchor_price": price,
            "note": "sigma appears once the statistics engine drains the stream (seconds)"}


@app.get("/api/instruments")
def instruments(q: str = Query("", min_length=0), limit: int = 20):
    return {"results": store.search_instruments(q, limit)}


@app.post("/api/watchlist")
def add(user: str = Query(...), symbol: str = Query(...)):
    store.add(user.strip().lower(), symbol.strip().upper())
    return {"ok": True}


@app.delete("/api/watchlist")
def remove(user: str = Query(...), symbol: str = Query(...)):
    store.remove(user.strip().lower(), symbol.strip().upper())
    return {"ok": True}
