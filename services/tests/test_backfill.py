import random
from datetime import date, datetime

from app.config import IST
from app.domain.backfill import bucket_times_back, synthesize
from app.domain.statistics import returns_from_prices, sigma_of


def _session(sigma: float, n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, sigma) for _ in range(n)]


def test_backfill_preserves_the_stocks_own_volatility():
    """The point of the whole thing. A fixed deviation would fail this for any stock
    whose real sigma differs from it - and then the ranking is a percentage sort."""
    for true_sigma in (0.0004, 0.0007, 0.0021):
        real = _session(true_sigma, 374, seed=int(true_sigma * 1e6))
        filled = synthesize(real, anchor_price=1000.0, length=750, seed=1)
        est = sigma_of(returns_from_prices(filled))
        assert abs(est - true_sigma) / true_sigma < 0.15, f"{true_sigma}: got {est}"


def test_backfill_ends_exactly_at_the_current_price():
    """The live stream continues from the anchor; a gap there would be a fake move."""
    filled = synthesize(_session(0.0007, 374, 3), anchor_price=1381.67, length=750, seed=1)
    assert len(filled) == 750
    assert filled[-1] == 1381.67


def test_backfill_is_deterministic_per_seed():
    a = synthesize(_session(0.0007, 374, 3), 100.0, 750, seed=42)
    b = synthesize(_session(0.0007, 374, 3), 100.0, 750, seed=42)
    assert a == b


def test_too_little_real_data_falls_back_rather_than_fabricating_from_nothing():
    filled = synthesize([0.001] * 5, 100.0, 750, seed=1, fallback_sigma=0.0007)
    assert len(filled) == 750
    est = sigma_of(returns_from_prices(filled))
    assert abs(est - 0.0007) / 0.0007 < 0.15


def test_bucket_times_land_on_the_trading_grid():
    sessions = [date(2026, 9, 3), date(2026, 9, 4)]
    anchor = datetime(2026, 9, 4, 12, 0, tzinfo=IST)
    ts = bucket_times_back(anchor, 750, sessions)
    assert len(ts) == 375 + 166                # all of Thu + Fri 09:15..12:00 inclusive
    assert ts[-1] == anchor
    assert all(t.time() >= datetime(2000, 1, 1, 9, 15).time() for t in ts)
    assert all(t.time() <= datetime(2000, 1, 1, 15, 29).time() for t in ts)
