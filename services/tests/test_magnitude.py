import math
import random

from app.config import BUCKETS_PER_TRADING_DAY
from app.domain.magnitude import (
    Band, annualised, band, is_corporate_action, magnitude, simple_return,
)


# ---------------------------------------------------------------- the thesis

def test_the_worked_example_from_the_design_document():
    """Spec 3.3 - 'the argument for the whole design', executable.

    Both stocks moved +2.7% since the user last looked, one trading day ago.
    Identical raw moves; one is news, one is Tuesday.
    """
    n = BUCKETS_PER_TRADING_DAY                     # 375
    large = magnitude(baseline=100.0, observed=102.7, sigma=0.00069, n=n)
    small = magnitude(baseline=100.0, observed=102.7, sigma=0.00207, n=n)

    assert round(large, 2) == 2.02
    assert round(small, 2) == 0.67
    assert band(large, has_baseline=True, has_sigma=True) == Band.NOTABLE
    assert band(small, has_baseline=True, has_sigma=True) == Band.NOISE
    assert large > small, "a percentage sort cannot tell these apart; this one must"


def test_the_sigmas_in_that_example_are_physically_plausible():
    """Figures that annualise to 150%+ mean the example was arithmetic, not a market."""
    assert 18 <= annualised(0.00069, BUCKETS_PER_TRADING_DAY) * 100 <= 24    # ~21%, large cap
    assert 55 <= annualised(0.00207, BUCKETS_PER_TRADING_DAY) * 100 <= 70    # ~63%, small cap


def test_ranking_is_invariant_to_n():
    """Spec 3.5, machine-checked.

    N is one number shared by every row in a payload, so sqrt(N) is a common factor
    and cannot reorder anything. This is why an imperfect market calendar cannot
    corrupt the list - only the band labels drift.
    """
    rng = random.Random(1234)
    for _ in range(500):
        rows = [(rng.uniform(-0.2, 0.2), rng.uniform(1e-5, 5e-3)) for _ in range(12)]
        by_ratio = sorted(range(len(rows)), key=lambda i: abs(rows[i][0]) / rows[i][1])
        for n in (1, 7, 60, 375, 750, 99_999):
            by_magnitude = sorted(
                range(len(rows)),
                key=lambda i: magnitude(100.0, 100.0 * (1 + rows[i][0]), rows[i][1], n),
            )
            assert by_magnitude == by_ratio, f"N={n} reordered the list"


# ---------------------------------------------------------------- bands

def test_band_boundaries_are_half_open():
    """Spec 3.4: every boundary value belongs to exactly one band."""
    k = dict(has_baseline=True, has_sigma=True)
    assert band(0.999, **k) == Band.NOISE
    assert band(1.0, **k) == Band.MILD
    assert band(1.999, **k) == Band.MILD
    assert band(2.0, **k) == Band.NOTABLE
    assert band(2.999, **k) == Band.NOTABLE
    assert band(3.0, **k) == Band.EXTREME


def test_a_ten_for_one_split_is_flagged_not_ranked_first():
    """Spec 9. -90% would be a magnitude near 50 and would top every watchlist."""
    r = simple_return(1000.0, 100.0)
    m = magnitude(baseline=1000.0, observed=100.0, sigma=0.0007, n=375)
    assert m > 10.0
    assert band(m, has_baseline=True, has_sigma=True, r=r) == Band.CORPORATE_ACTION


def test_the_corporate_action_flag_does_not_move_with_n():
    """The bug this test exists for: magnitude scales with sqrt(N), so a threshold
    written against magnitude made an ordinary +2.7% move read as a corporate action
    whenever a user logged in twice in quick succession."""
    r = simple_return(100.0, 102.7)
    for n in (1, 7, 60, 375, 750):
        m = magnitude(100.0, 102.7, 0.00069, n)
        assert band(m, has_baseline=True, has_sigma=True, r=r) != Band.CORPORATE_ACTION


def test_a_real_session_move_is_never_a_corporate_action():
    """NSE circuit bands cap a genuine session move at 20%."""
    assert not is_corporate_action(0.20)
    assert is_corporate_action(-0.50)      # a 1:2 split
    assert is_corporate_action(-0.90)      # a 1:10 split


# ---------------------------------------------------------------- the two NULLs

def test_no_baseline_is_new_and_never_divides():
    assert magnitude(None, 102.7, 0.0007, 375) is None
    assert band(None, has_baseline=False, has_sigma=True) == Band.NEW


def test_no_sigma_is_unrated_and_never_divides():
    assert magnitude(100.0, 102.7, None, 375) is None
    assert band(None, has_baseline=True, has_sigma=False) == Band.UNRATED


def test_a_symbol_added_mid_session_has_no_quote_yet():
    """Spec 5.1: present in the watchlist, absent from /api/quotes until the next cycle."""
    assert magnitude(100.0, None, 0.0007, 375) is None


def test_degenerate_inputs_return_none_rather_than_nan_or_infinity():
    assert magnitude(100.0, 102.7, 0.0, 375) is None          # sigma floored to zero
    assert magnitude(100.0, 102.7, 0.0007, 0) is None         # logged in twice in a row
    assert magnitude(0.0, 102.7, 0.0007, 375) is None         # baseline of zero
    for bad in (magnitude(100.0, 102.7, 0.0, 375), magnitude(100.0, 102.7, 0.0007, 0)):
        assert bad is None or math.isfinite(bad)
