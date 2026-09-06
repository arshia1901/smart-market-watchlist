# Smart Market Watchlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A watchlist that ranks stocks by how *unusual* their move is since the user last logged in, rather than by raw percentage change.

**Architecture:** Six containers. Ingestion walks a 10-symbol catalogue on a 1-minute grid and writes quotes write-if-newer; an async statistics engine maintains one `sigma` per stock over a fixed 750-bucket window; the API serves raw materials only; the Angular client computes `magnitude = |r| / (sigma * sqrt(N))` and ranks. Nothing on the request path computes, blocks, or fails.

**Tech Stack:** Python 3.13 / FastAPI · Angular / TypeScript · Postgres · Redis · Docker Compose · pytest · Vitest

**Spec:** `docs/superpowers/specs/2026-09-05-smart-market-watchlist-design.md`

## Global Constraints

- **Grid:** `GRID_SECONDS = 60`, matching what free feeds actually publish (spec 3.6).
- **Sigma window:** `SIGMA_WINDOW = 750` buckets = 2 trading days. Constant for every stock.
- **Trading day:** NSE 09:15-15:30 IST = 22,500s = **375 buckets**. IST = UTC+5:30.
- **Measure:** `MEASURE = price`, a single system parameter. Not an array, no UI (spec 3.7).
- **Bands are half-open:** `[0,1)` noise · `[1,2)` mild · `[2,3)` notable · `[3,inf)` extreme.
- **Corporate action threshold:** `magnitude > 10` -> flagged, excluded from ranking.
- **`sigma` is seeded from the replay fixture** — 750 buckets is 12.5h of market time and polling cannot produce it at boot (spec 3.6).
- **The grid clock is injected, never global.** Replaying two trading days must take seconds.
- **Session token lives in `localStorage`** — not memory, not `sessionStorage` (spec 4.3).
- **`PROVIDER=replay` is the default.** Live requires explicit opt-in.
- **Test budget:** `pytest` under 10s, `vitest` under 3s. Enforced, not aspirational.
- **No numpy.** Pure Python throughout; 750 floats does not need a C extension.

---

## File Structure

```
run.sh                              start | stop | status | logs
docker-compose.yml
README.md · PITCH.md
docs/DESIGN.md · DECISIONS.md · ASSUMPTIONS.md · EDGE-CASES.md

backend/watchlist/
  config.py                         all constants above, one file
  ports.py                          EVERY protocol — the whole seam map, readable in 90s
  domain/
    clock.py                        Clock protocol + RealClock + ReplayClock
    calendar.py                     sessions · trading-bucket counting · freshness
    statistics.py                   RollingSigma — ring buffer, MAD winsorise, floor
    magnitude.py                    magnitude + band  (Python reference implementation)
  adapters/
    provider_replay.py · provider_live.py
    cache_redis.py · store_postgres.py · bus_redis.py
  engines/
    ingestion.py · statistics_engine.py
  api/app.py · api/routes.py
  fixtures/generate.py · fixtures/market.csv.gz · fixtures/market.sha256
backend/tests/

frontend/src/app/
  domain/                           NO @angular imports — enforced by a test
    magnitude.ts · bands.ts · rank.ts
  core/  api.service.ts · session.service.ts · quotes.service.ts
  watchlist/                        the one route
```

**Why `ports.py` is one file:** Appendix A claims every component is a real boundary. One file
means a judge can read the entire inter-component contract in ninety seconds and check that
claim rather than take it on trust.

---

## Task 1: Config, clock, and the seam map

**Files:**
- Create: `backend/watchlist/config.py`, `backend/watchlist/domain/clock.py`, `backend/watchlist/ports.py`
- Test: `backend/tests/test_clock.py`

**Interfaces:**
- Produces: `Clock` protocol with `now() -> datetime`; `ReplayClock(start, step_seconds)` with `advance(n=1)`; `RealClock`. All constants from Global Constraints as module-level names in `config.py`.

This task exists first because **everything downstream depends on the clock being injectable.**
A hardcoded `asyncio.sleep(5)` anywhere in the ingestion loop makes replaying two trading days
take two trading days, and there is then no test harness and no demo.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_clock.py
from datetime import datetime, timezone, timedelta
from watchlist.domain.clock import ReplayClock

IST = timezone(timedelta(hours=5, minutes=30))

def test_replay_clock_advances_by_grid_step():
    c = ReplayClock(datetime(2026, 9, 3, 9, 15, tzinfo=IST), step_seconds=60)
    assert c.now() == datetime(2026, 9, 3, 9, 15, tzinfo=IST)
    c.advance()
    assert c.now() == datetime(2026, 9, 3, 9, 16, tzinfo=IST)
    c.advance(14)
    assert c.now() == datetime(2026, 9, 3, 9, 30, tzinfo=IST)

def test_replay_clock_covers_a_trading_day_instantly():
    c = ReplayClock(datetime(2026, 9, 3, 9, 15, tzinfo=IST), step_seconds=60)
    c.advance(375)
    assert c.now() == datetime(2026, 9, 3, 15, 30, tzinfo=IST)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python -m pytest tests/test_clock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchlist.domain.clock'`

- [ ] **Step 3: Implement**

```python
# backend/watchlist/domain/clock.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    """Injected everywhere. Nothing in this system reads the wall clock directly."""
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ReplayClock:
    """Deterministic clock stepped by hand, so two trading days replay in milliseconds."""

    def __init__(self, start: datetime, step_seconds: int) -> None:
        self._t = start
        self._step = timedelta(seconds=step_seconds)

    def now(self) -> datetime:
        return self._t

    def advance(self, ticks: int = 1) -> None:
        self._t += self._step * ticks
```

```python
# backend/watchlist/config.py
"""Every system parameter, in one file. Spec: Global Constraints."""
from datetime import time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

MEASURE = "price"          # spec 3.7 — a parameter, not an array
GRID_SECONDS = 60          # spec 3.6 — matches what free feeds publish

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
BUCKETS_PER_TRADING_DAY = 375
SIGMA_WINDOW = 750         # 2 trading days, constant for every stock

SIGMA_FLOOR = 1e-6         # spec 9 — prevents division by zero on an untraded stock
WINSOR_K = 5.0             # clip returns beyond k robust deviations before estimating
CORPORATE_ACTION_MAGNITUDE = 10.0

BAND_EDGES = (1.0, 2.0, 3.0)   # half-open: [0,1) [1,2) [2,3) [3,inf)

FRESH_LIVE_SECONDS = 120   # two grid cycles
FRESH_DELAYED_SECONDS = 1800  # a 15-min delayed feed must read DELAYED, not STALE

PROVIDER = "replay"        # spec 11 — live is explicit opt-in, never the default
```

- [ ] **Step 4: Run and watch it pass**

Run: `cd backend && python -m pytest tests/test_clock.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/watchlist/config.py backend/watchlist/domain/clock.py backend/tests/test_clock.py
git commit -m "feat: injectable clock and system parameters"
```

---

## Task 2: Market calendar

**Files:**
- Create: `backend/watchlist/domain/calendar.py`
- Test: `backend/tests/test_calendar.py`

**Interfaces:**
- Consumes: `config.IST`, `SESSION_OPEN`, `SESSION_CLOSE`, `GRID_SECONDS`, `FRESH_*`
- Produces:
  - `trading_buckets_between(start: datetime, end: datetime, holidays: frozenset[date]) -> int`
  - `Freshness` str-enum: `LIVE`, `DELAYED`, `STALE`, `MARKET_CLOSED`
  - `freshness(as_of: datetime, now: datetime, holidays: frozenset[date]) -> Freshness`

Spec 3.5 says ranking is immune to errors in `N`, so bucket counting can be approximate.
Freshness cannot — spec 5.4 calls it "the part of the calendar that genuinely has to be right".
Test accordingly: a handful of cases for `N`, thorough cases for freshness.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_calendar.py
from datetime import date, datetime, timedelta
import pytest
from watchlist.config import IST
from watchlist.domain.calendar import Freshness, freshness, trading_buckets_between

NO_HOLIDAYS: frozenset[date] = frozenset()
def dt(y, m, d, hh, mm, ss=0): return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


def test_one_trading_hour_is_60_buckets():
    assert trading_buckets_between(dt(2026, 9, 3, 10, 0), dt(2026, 9, 3, 11, 0), NO_HOLIDAYS) == 60

def test_a_full_session_is_375_buckets():
    assert trading_buckets_between(dt(2026, 9, 3, 9, 15), dt(2026, 9, 3, 15, 30), NO_HOLIDAYS) == 375

def test_time_outside_the_session_does_not_count():
    # 15:30 Thu -> 09:15 Fri crosses 17h45m of wall clock and zero trading time
    assert trading_buckets_between(dt(2026, 9, 3, 15, 30), dt(2026, 9, 4, 9, 15), NO_HOLIDAYS) == 0

def test_the_weekend_case_that_would_blank_monday_morning():
    # Spec 9. Wall clock is ~3,945 buckets; only Monday's first hour is real trading.
    n = trading_buckets_between(dt(2026, 9, 4, 15, 30), dt(2026, 9, 7, 10, 15), NO_HOLIDAYS)
    assert n == 60, "weekend must contribute zero buckets"

def test_holidays_contribute_nothing():
    holidays = frozenset({date(2026, 9, 4)})
    assert trading_buckets_between(dt(2026, 9, 3, 15, 30), dt(2026, 9, 4, 15, 30), holidays) == 0

def test_reversed_or_equal_range_is_zero_never_negative():
    assert trading_buckets_between(dt(2026, 9, 3, 11, 0), dt(2026, 9, 3, 10, 0), NO_HOLIDAYS) == 0
    assert trading_buckets_between(dt(2026, 9, 3, 10, 0), dt(2026, 9, 3, 10, 0), NO_HOLIDAYS) == 0


@pytest.mark.parametrize("age_seconds,expected", [
    (30,    Freshness.LIVE),
    (119,   Freshness.LIVE),
    (300,   Freshness.DELAYED),
    (900,   Freshness.DELAYED),   # a 15-min delayed feed reads DELAYED, honestly
    (1799,  Freshness.DELAYED),
    (1801,  Freshness.STALE),
])
def test_freshness_during_an_open_session(age_seconds, expected):
    now = dt(2026, 9, 3, 12, 0)
    assert freshness(now - timedelta(seconds=age_seconds), now, NO_HOLIDAYS) == expected

def test_saturday_reads_market_closed_not_stale():
    # Spec 5.4 — the case that must not read as "broken"
    now = dt(2026, 9, 5, 14, 0)                 # Saturday afternoon
    as_of = dt(2026, 9, 4, 15, 30)              # Friday's close
    assert freshness(as_of, now, NO_HOLIDAYS) == Freshness.MARKET_CLOSED

def test_before_the_open_reads_market_closed():
    now = dt(2026, 9, 3, 8, 0)
    assert freshness(dt(2026, 9, 2, 15, 30), now, NO_HOLIDAYS) == Freshness.MARKET_CLOSED
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python -m pytest tests/test_calendar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchlist.domain.calendar'`

- [ ] **Step 3: Implement**

```python
# backend/watchlist/domain/calendar.py
"""Trading sessions, bucket counting, and freshness.

Spec 3.5: bucket counting may be approximate — sqrt(N) is a common factor and cannot
change ranking. Freshness may not be: spec 5.4 depends on it to tell "market closed"
apart from "broken".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import StrEnum

from watchlist.config import (
    FRESH_DELAYED_SECONDS, FRESH_LIVE_SECONDS, GRID_SECONDS,
    IST, SESSION_CLOSE, SESSION_OPEN,
)


class Freshness(StrEnum):
    LIVE = "live"
    DELAYED = "delayed"
    STALE = "stale"
    MARKET_CLOSED = "market_closed"


def is_trading_day(d: date, holidays: frozenset[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def is_market_open(at: datetime, holidays: frozenset[date]) -> bool:
    local = at.astimezone(IST)
    return is_trading_day(local.date(), holidays) and SESSION_OPEN <= local.time() < SESSION_CLOSE


def _seconds_of_session(day: date, start: datetime, end: datetime) -> float:
    """Overlap, in seconds, between [start, end] and this day's trading session."""
    open_at = datetime.combine(day, SESSION_OPEN, tzinfo=IST)
    close_at = datetime.combine(day, SESSION_CLOSE, tzinfo=IST)
    lo, hi = max(start, open_at), min(end, close_at)
    return max(0.0, (hi - lo).total_seconds())


def trading_buckets_between(start: datetime, end: datetime, holidays: frozenset[date]) -> int:
    """Grid buckets of *trading* time in [start, end]. Never negative."""
    if end <= start:
        return 0
    start, end = start.astimezone(IST), end.astimezone(IST)
    total = 0.0
    day = start.date()
    while day <= end.date():
        if is_trading_day(day, holidays):
            total += _seconds_of_session(day, start, end)
        day += timedelta(days=1)
    return int(total // GRID_SECONDS)


def freshness(as_of: datetime, now: datetime, holidays: frozenset[date]) -> Freshness:
    """Age is meaningless while the market is shut, so that case is answered first."""
    if not is_market_open(now, holidays):
        return Freshness.MARKET_CLOSED
    age = (now - as_of).total_seconds()
    if age <= FRESH_LIVE_SECONDS:
        return Freshness.LIVE
    if age <= FRESH_DELAYED_SECONDS:
        return Freshness.DELAYED
    return Freshness.STALE
```

- [ ] **Step 4: Run and watch it pass**

Run: `cd backend && python -m pytest tests/test_calendar.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add backend/watchlist/domain/calendar.py backend/tests/test_calendar.py
git commit -m "feat: market calendar with trading-bucket counting and freshness states"
```

---

*Tasks 3 onward are appended once the Docker topology and provider verification land.*
