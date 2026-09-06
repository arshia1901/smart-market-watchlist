"""Rolling sigma: the standard deviation of a stock's 1-minute returns.

Spec 3.2. One number per stock over a fixed 750-bucket window (two trading days),
the same window length for every stock.

Two spec-9 edge cases are handled here, and a third is designed out:

  * sigma -> 0 on an untraded stock would divide by zero. Floored.
  * one bad tick would otherwise inflate sigma for two full days and silently
    suppress genuine signals. Returns are winsorised against a *robust* scale
    (median absolute deviation) rather than against sigma itself, which would be
    circular - the outlier is already in the estimate you would be clipping with.
  * accumulator drift cannot occur, because nothing is accumulated: the estimate
    is recomputed across the whole buffer each time. At 750 floats that is
    microseconds, so the edge case is designed out rather than mitigated.
"""
from __future__ import annotations

from collections import deque
from statistics import fmean, median

from app.config import SIGMA_FLOOR, SIGMA_WINDOW, WINSOR_K

_MAD_TO_SIGMA = 1.4826   # scales MAD onto a standard deviation for a normal sample


class RollingSigma:
    """A fixed-length window of *prices*; sigma is the spread of the returns inside it.

    The window is counted in buckets, not returns, because that is what "two trading
    days" means and what the ingestion stream actually delivers. 750 buckets imply
    749 returns, which is the correct relationship rather than an off-by-one.
    """

    __slots__ = ("_prices", "_window")

    def __init__(self, window: int = SIGMA_WINDOW) -> None:
        self._window = window
        self._prices: deque[float] = deque(maxlen=window)

    def observe(self, price: float) -> None:
        self._prices.append(price)

    def extend(self, prices: list[float]) -> None:
        self._prices.extend(prices)

    @property
    def observations(self) -> int:
        return len(self._prices)

    @property
    def ready(self) -> bool:
        """Spec 4.7: below a full window the stock is *unrated*, never given a default."""
        return len(self._prices) >= self._window

    def value(self) -> float | None:
        if not self.ready:
            return None
        return sigma_of(returns_from_prices(list(self._prices)))


def sigma_of(returns: list[float]) -> float:
    """Winsorised standard deviation, floored. Pure, so it is directly testable."""
    if len(returns) < 2:
        return SIGMA_FLOOR

    centre = median(returns)
    scale = _MAD_TO_SIGMA * median([abs(r - centre) for r in returns])

    if scale > 0.0:
        lo, hi = centre - WINSOR_K * scale, centre + WINSOR_K * scale
        returns = [min(max(r, lo), hi) for r in returns]

    mean = fmean(returns)
    variance = fmean([(r - mean) ** 2 for r in returns])
    return max(variance ** 0.5, SIGMA_FLOOR)


def returns_from_prices(prices: list[float]) -> list[float]:
    """Simple returns. Prices are not stationary; returns are (spec 3.2)."""
    return [
        (b - a) / a
        for a, b in zip(prices, prices[1:])
        if a > 0.0
    ]
