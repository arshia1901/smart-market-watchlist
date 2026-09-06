"""Trading sessions, bucket counting, and freshness.

Two jobs with very different precision requirements (spec 3.5):

  * counting buckets for N may be approximate - sqrt(N) is a common factor across
    every row in a payload and therefore cannot change the ranking.
  * freshness may NOT be approximate. Spec 5.4 depends on it to tell "market closed"
    apart from "broken", and that distinction is visible to the user.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import StrEnum

from app.config import (
    FRESH_DELAYED_SECONDS,
    FRESH_LIVE_SECONDS,
    GRID_SECONDS,
    IST,
    SESSION_CLOSE,
    SESSION_OPEN,
)


class Freshness(StrEnum):
    LIVE = "live"
    DELAYED = "delayed"
    STALE = "stale"
    MARKET_CLOSED = "market_closed"


def is_trading_day(day: date, holidays: frozenset[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def is_market_open(at: datetime, holidays: frozenset[date]) -> bool:
    local = at.astimezone(IST)
    return is_trading_day(local.date(), holidays) and SESSION_OPEN <= local.time() < SESSION_CLOSE


def _session_overlap_seconds(day: date, start: datetime, end: datetime) -> float:
    opens = datetime.combine(day, SESSION_OPEN, tzinfo=IST)
    closes = datetime.combine(day, SESSION_CLOSE, tzinfo=IST)
    lo, hi = max(start, opens), min(end, closes)
    return max(0.0, (hi - lo).total_seconds())


def trading_buckets_between(start: datetime, end: datetime, holidays: frozenset[date]) -> int:
    """Grid buckets of *trading* time in [start, end]. Never negative.

    Counting wall clock instead would make a Monday-morning N about 3,945 buckets
    against zero of real trading, so every stock would score as noise and the view
    that matters most would go blank (spec 9).
    """
    if end <= start:
        return 0
    start, end = start.astimezone(IST), end.astimezone(IST)
    seconds = 0.0
    day = start.date()
    while day <= end.date():
        if is_trading_day(day, holidays):
            seconds += _session_overlap_seconds(day, start, end)
        day += timedelta(days=1)
    return int(seconds // GRID_SECONDS)


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


def recent_trading_days(count: int, ending: date, holidays: frozenset[date]) -> list[date]:
    """The `count` most recent trading days at or before `ending`, oldest first.

    The fixture is rebased onto these at boot. A fixture with hardcoded dates would
    be correct today and read as 'market closed, data six days old' if a judge ran it
    next Thursday.
    """
    days: list[date] = []
    day = ending
    while len(days) < count:
        if is_trading_day(day, holidays):
            days.append(day)
        day -= timedelta(days=1)
    return list(reversed(days))
