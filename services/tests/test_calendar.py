from datetime import date, datetime, timedelta

import pytest

from app.config import IST
from app.domain.calendar import Freshness, freshness, is_market_open, trading_buckets_between

NONE: frozenset[date] = frozenset()


def dt(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


# 2026-09-03 is a Thursday, 09-04 Friday, 09-05 Saturday, 09-07 Monday.

def test_one_trading_hour_is_60_buckets():
    assert trading_buckets_between(dt(2026, 9, 3, 10, 0), dt(2026, 9, 3, 11, 0), NONE) == 60


def test_a_full_session_is_375_buckets():
    assert trading_buckets_between(dt(2026, 9, 3, 9, 15), dt(2026, 9, 3, 15, 30), NONE) == 375


def test_overnight_contributes_nothing():
    assert trading_buckets_between(dt(2026, 9, 3, 15, 30), dt(2026, 9, 4, 9, 15), NONE) == 0


def test_the_weekend_case_that_would_blank_monday_morning():
    """Spec 9. Wall clock is ~3,945 buckets; only Monday's first hour is real trading."""
    n = trading_buckets_between(dt(2026, 9, 4, 15, 30), dt(2026, 9, 7, 10, 15), NONE)
    assert n == 60


def test_holidays_contribute_nothing():
    holidays = frozenset({date(2026, 9, 4)})
    assert trading_buckets_between(dt(2026, 9, 3, 15, 30), dt(2026, 9, 4, 15, 30), holidays) == 0


def test_reversed_or_empty_ranges_are_zero_never_negative():
    assert trading_buckets_between(dt(2026, 9, 3, 11, 0), dt(2026, 9, 3, 10, 0), NONE) == 0
    assert trading_buckets_between(dt(2026, 9, 3, 10, 0), dt(2026, 9, 3, 10, 0), NONE) == 0


@pytest.mark.parametrize("age,expected", [
    (30, Freshness.LIVE),
    (119, Freshness.LIVE),
    (300, Freshness.DELAYED),
    (900, Freshness.DELAYED),      # a 15-minute delayed feed reads DELAYED, honestly
    (1799, Freshness.DELAYED),
    (1801, Freshness.STALE),
])
def test_freshness_inside_an_open_session(age, expected):
    now = dt(2026, 9, 3, 12, 0)
    assert freshness(now - timedelta(seconds=age), now, NONE) == expected


def test_saturday_reads_market_closed_not_stale():
    """Spec 5.4: the case that must not read as 'broken'."""
    assert freshness(dt(2026, 9, 4, 15, 30), dt(2026, 9, 5, 14, 0), NONE) == Freshness.MARKET_CLOSED


def test_before_the_open_reads_market_closed():
    assert freshness(dt(2026, 9, 2, 15, 30), dt(2026, 9, 3, 8, 0), NONE) == Freshness.MARKET_CLOSED


def test_the_session_boundaries_themselves():
    assert is_market_open(dt(2026, 9, 3, 9, 15), NONE) is True
    assert is_market_open(dt(2026, 9, 3, 9, 14, 59), NONE) is False
    assert is_market_open(dt(2026, 9, 3, 15, 29, 59), NONE) is True
    assert is_market_open(dt(2026, 9, 3, 15, 30), NONE) is False


def test_container_timezone_trap():
    """Spec 9. The same instant expressed in UTC must classify identically.

    Containers default to UTC while the market is IST. A naive timestamp shifts by
    5h30m only inside Docker, so the market reads closed while it is open - and it
    works perfectly outside Docker, which is the worst possible failure shape.
    """
    from datetime import timezone
    ist_noon = dt(2026, 9, 3, 12, 0)
    same_instant_utc = ist_noon.astimezone(timezone.utc)
    assert is_market_open(same_instant_utc, NONE) is True
    assert trading_buckets_between(
        dt(2026, 9, 3, 10, 0).astimezone(timezone.utc), same_instant_utc, NONE
    ) == 120
