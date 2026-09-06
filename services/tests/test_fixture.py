"""The replay fixture is the demo, the cold-start data, and the integration harness.

If it is wrong, everything downstream is wrong in ways that look like working
software. So it is checked against ground truth: we planted the sigmas, so the
estimator has something to be right about.
"""
import csv
import gzip
from collections import defaultdict
from pathlib import Path

import pytest

from app.config import BUCKETS_PER_TRADING_DAY as BPD
from app.domain.magnitude import Band, band, magnitude
from app.domain.statistics import returns_from_prices, sigma_of
from app.fixtures.catalogue import BY_SYMBOL

FIXTURE = Path(__file__).parent.parent / "app" / "fixtures" / "market.csv.gz"


@pytest.fixture(scope="module")
def rows():
    with gzip.open(FIXTURE, "rt") as fh:
        return [
            (r["symbol"], int(r["day"]), int(r["bucket"]), float(r["price"]))
            for r in csv.DictReader(fh)
        ]


@pytest.fixture(scope="module")
def warmup_prices(rows):
    """Days 0-1 in event order - the 750 buckets that fill the sigma window."""
    out = defaultdict(list)
    for sym, day, bucket, price in rows:
        if day < 2:
            out[sym].append(((day, bucket), price))
    return {s: [p for _, p in sorted(v)] for s, v in out.items()}


@pytest.fixture(scope="module")
def demo_prices(rows):
    """Day 2 in EVENT order, last-write-wins - i.e. after write-if-newer."""
    out = defaultdict(dict)
    for sym, day, bucket, price in rows:
        if day == 2:
            out[sym][bucket] = price
    return {s: [v[k] for k in sorted(v)] for s, v in out.items()}


def test_sigma_is_recovered_from_the_planted_value(warmup_prices):
    """We chose each stock's volatility, so the estimator can be checked, not just run."""
    for symbol, prices in warmup_prices.items():
        planted = BY_SYMBOL[symbol].sigma
        if BY_SYMBOL[symbol].scenario == "flatline" or len(prices) < 750:
            continue
        estimated = sigma_of(returns_from_prices(prices))
        error = abs(estimated - planted) / planted
        assert error < 0.15, f"{symbol}: planted {planted:.5f}, estimated {estimated:.5f}"


def test_the_thesis_a_bigger_move_ranks_lower(warmup_prices, demo_prices):
    """Spec 3.3, end to end on the real fixture.

    HINDUNILVR moves MORE in percentage terms than RELIANCE and must rank BELOW it,
    because its own volatility makes that move ordinary. This is the entire product.
    """
    results = {}
    for symbol in ("RELIANCE", "HINDUNILVR"):
        sigma = sigma_of(returns_from_prices(warmup_prices[symbol]))
        baseline, observed = demo_prices[symbol][0], demo_prices[symbol][-1]
        results[symbol] = {
            "pct": (observed - baseline) / baseline * 100.0,
            "mag": magnitude(baseline, observed, sigma, BPD),
        }

    r, h = results["RELIANCE"], results["HINDUNILVR"]
    assert h["pct"] > r["pct"], "HINDUNILVR must have the bigger raw move"
    assert r["mag"] > h["mag"], "...and RELIANCE must still rank above it"
    assert band(r["mag"], has_baseline=True, has_sigma=True) in (Band.NOTABLE, Band.EXTREME)
    assert band(h["mag"], has_baseline=True, has_sigma=True) in (Band.NOISE, Band.MILD)


def test_late_ticks_are_present_and_would_rewind_the_price(rows):
    """Spec 5.3. If the fixture has no out-of-order arrivals, write-if-newer is untested."""
    seen_max, late = -1, 0
    for sym, day, bucket, _ in rows:
        if sym != "SBIN" or day != 2:
            continue
        if bucket < seen_max:
            late += 1
        seen_max = max(seen_max, bucket)
    assert late >= 2, "SBIN must carry genuinely out-of-order arrivals"


def test_the_stale_symbol_stops_printing(demo_prices):
    assert len(demo_prices["ICICIBANK"]) < BPD // 2 + 5
    assert len(demo_prices["RELIANCE"]) == BPD


def test_the_corporate_action_is_a_tenfold_discontinuity(demo_prices):
    prices = demo_prices["LT"]
    ratios = [b / a for a, b in zip(prices, prices[1:])]
    assert min(ratios) < 0.15, "expected a 1:10 split"


def test_the_flatline_has_no_variance_and_is_floored(demo_prices):
    prices = demo_prices["ITC"]
    assert len(set(prices)) == 1
    assert sigma_of(returns_from_prices(prices)) > 0.0     # floored, never zero


def test_the_circuit_stock_pins_at_its_upper_band(demo_prices):
    prices = demo_prices["SMALLCAP"]
    limit = prices[0] * 1.20            # the band is set against the previous close
    assert prices[-1] == pytest.approx(limit, rel=0.03)
    assert prices.count(prices[-1]) > BPD // 3, "a pinned price, not a passing touch"


def test_the_new_listing_has_no_warmup_and_is_unrated(warmup_prices, demo_prices):
    assert "NEWLIST" not in warmup_prices
    assert len(demo_prices["NEWLIST"]) == BPD
    assert band(None, has_baseline=True, has_sigma=False) == Band.UNRATED


def test_every_catalogued_instrument_appears(demo_prices):
    assert set(demo_prices) == set(BY_SYMBOL)
