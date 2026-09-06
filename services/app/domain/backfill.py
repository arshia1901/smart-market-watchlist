"""Bootstrap a sigma window from one real session, so a newly tracked stock is rankable
now rather than in two days.

The idea (and the constraint that makes it sound): the back-filled history must carry the
stock's OWN volatility. A fixed "small deviation" would give every new stock the same sigma
and collapse the ranking to a percentage sort - the exact thing this product exists to
avoid. So the fill is built by resampling the stock's real intraday returns, which
preserves their spread, and it is anchored to end exactly at the current price so the
live stream continues from it seamlessly.

Everything produced here is marked synthetic in storage and shown as *provisional* in the
UI until 750 real buckets have displaced it.
"""
from __future__ import annotations

import random
from datetime import date, datetime

from app.config import BUCKETS_PER_TRADING_DAY, GRID_SECONDS, IST, SESSION_OPEN
from datetime import timedelta

MIN_REAL_RETURNS = 30      # fewer than this and the sample says little about the stock


def synthesize(real_returns: list[float], anchor_price: float, length: int,
               seed: int, fallback_sigma: float | None = None) -> list[float]:
    """`length` prices ending exactly at `anchor_price`, with the input's volatility.

    Built backwards from the anchor by resampling real returns with replacement, so
    the spread of the fill matches the spread of the session it came from. Seeded per
    symbol, so a restart regenerates the identical history rather than a new one.
    """
    rng = random.Random(seed)
    if len(real_returns) >= MIN_REAL_RETURNS:
        draw = lambda: rng.choice(real_returns)
    elif fallback_sigma:
        draw = lambda: rng.gauss(0.0, fallback_sigma)
    else:
        raise ValueError("not enough real returns and no fallback sigma")

    prices = [anchor_price]
    while len(prices) < length:
        r = draw()
        prev = prices[-1] / (1.0 + r) if r > -0.99 else prices[-1]
        prices.append(round(prev, 2))
    prices.reverse()
    prices[-1] = anchor_price                     # exact, not rounded
    return prices


def bucket_times_back(anchor: datetime, length: int, sessions: list[date]) -> list[datetime]:
    """The last `length` trading-grid timestamps at or before `anchor`, oldest first.

    Laid on the real session grid rather than raw wall-clock minutes, so the synthetic
    rows sit where genuine ones would and the time series stays coherent.
    """
    grid: list[datetime] = []
    for day in sessions:
        opens = datetime.combine(day, SESSION_OPEN, tzinfo=IST)
        for i in range(BUCKETS_PER_TRADING_DAY):
            t = opens + timedelta(seconds=i * GRID_SECONDS)
            if t <= anchor:
                grid.append(t)
    return grid[-length:]
