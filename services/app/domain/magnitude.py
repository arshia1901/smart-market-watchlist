"""How unusual is this move, in units of the stock's own volatility?

Spec 3.2:   magnitude = |r| / (sigma * sqrt(N))

This module is the Python reference implementation. The Angular client computes the
same thing (spec 6.3), and both are pinned to one shared golden fixture so the two
halves of the formula cannot drift apart across the language boundary.
"""
from __future__ import annotations

import math
from enum import StrEnum

from app.config import BAND_EDGES, CORPORATE_ACTION_RETURN


class Band(StrEnum):
    NOISE = "noise"
    MILD = "mild"
    NOTABLE = "notable"
    EXTREME = "extreme"
    NEW = "new"                          # spec 4.7: no baseline to compare against
    UNRATED = "unrated"                  # spec 4.7: the stock has no sigma yet
    CORPORATE_ACTION = "corporate_action" # spec 9: flagged, never ranked


def simple_return(baseline: float, observed: float) -> float:
    return (observed - baseline) / baseline


def magnitude(baseline: float | None, observed: float | None,
              sigma: float | None, n: int) -> float | None:
    """None whenever the inputs cannot support a ranking, never a faked default.

    Spec 4.7 is honest that the ranking layer is where the two NULLs stop being
    free: storage treats them uniformly, arithmetic cannot.
    """
    if baseline is None or observed is None or sigma is None:
        return None
    if baseline <= 0.0 or sigma <= 0.0 or n <= 0:
        return None
    expected = sigma * math.sqrt(n)
    return abs(simple_return(baseline, observed)) / expected


def is_corporate_action(r: float | None) -> bool:
    """Keyed off the return, which does not move with N.

    An earlier draft tested `magnitude > 10`. Magnitude scales with sqrt(N), so a
    user logging in twice within a few minutes would see ordinary moves labelled
    corporate actions - and banding would depend on N, contradicting spec 3.5.
    """
    return r is not None and abs(r) >= CORPORATE_ACTION_RETURN


def band(m: float | None, *, has_baseline: bool, has_sigma: bool,
         r: float | None = None) -> Band:
    """Half-open intervals, so every boundary value lands in exactly one band."""
    if not has_baseline:
        return Band.NEW
    if is_corporate_action(r):
        # A 1:10 split is -90% and would otherwise top every watchlist forever.
        return Band.CORPORATE_ACTION
    if not has_sigma:
        return Band.UNRATED
    if m is None:
        return Band.UNRATED
    mild, notable, extreme = BAND_EDGES
    if m >= extreme:
        return Band.EXTREME
    if m >= notable:
        return Band.NOTABLE
    if m >= mild:
        return Band.MILD
    return Band.NOISE


def annualised(sigma_per_bucket: float, buckets_per_day: int, trading_days: int = 250) -> float:
    """Sanity check, not decoration.

    Any sigma we quote has to survive this conversion; figures that annualise to
    150%+ mean the example was arithmetic rather than a market (spec 3.3).
    """
    return sigma_per_bucket * math.sqrt(buckets_per_day * trading_days)
