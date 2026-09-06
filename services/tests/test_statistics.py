import random
from statistics import pstdev

from app.config import SIGMA_FLOOR
from app.domain.statistics import RollingSigma, returns_from_prices, sigma_of


def test_sigma_recovers_a_known_standard_deviation():
    """The estimator must be right, not merely stable. Ground truth from a seeded sample."""
    rng = random.Random(42)
    true_sigma = 0.0007
    sample = [rng.gauss(0.0, true_sigma) for _ in range(5000)]
    assert abs(sigma_of(sample) - true_sigma) / true_sigma < 0.05


def test_a_flatline_is_floored_not_zero():
    """Spec 9: an untraded stock has zero variance, and would divide by zero."""
    assert sigma_of([0.0] * 750) == SIGMA_FLOOR
    assert sigma_of([0.0] * 750) > 0.0


def test_one_bad_tick_does_not_inflate_sigma():
    """Spec 9. Unwinsorised, a single spike would suppress real signals for two days."""
    rng = random.Random(7)
    clean = [rng.gauss(0.0, 0.0007) for _ in range(750)]
    spiked = list(clean)
    spiked[300] = 0.35                      # a 500-sigma "tick"

    naive_damage = pstdev(spiked) / pstdev(clean)
    robust_damage = sigma_of(spiked) / sigma_of(clean)

    assert naive_damage > 5.0, "the naive estimator should be wrecked, or this proves nothing"
    assert robust_damage < 1.10, f"winsorised sigma moved {robust_damage:.2f}x"


def test_sigma_is_none_until_the_window_fills():
    """Spec 4.7: below a full window a stock is *unrated*, never given a default.

    The window is 750 buckets, which imply 749 returns - counted in buckets because
    that is what "two trading days" means and what the stream delivers.
    """
    rng = random.Random(3)
    prices = [100.0]
    for _ in range(749):
        prices.append(prices[-1] * (1 + rng.gauss(0, 0.0007)))

    r = RollingSigma(window=750)
    r.extend(prices[:749])
    assert r.ready is False
    assert r.value() is None
    r.observe(prices[749])
    assert r.ready is True
    assert r.value() is not None


def test_the_window_slides_and_forgets():
    r = RollingSigma(window=10)
    r.extend([100.0 * (1.05 if i % 2 else 0.95) for i in range(10)])   # volatile
    loud = r.value()
    r.extend([100.0 * (1.0005 if i % 2 else 0.9995) for i in range(10)])  # calm
    assert r.value() < loud
    assert r.observations == 10


def test_returns_are_computed_from_prices_not_prices_themselves():
    assert returns_from_prices([100.0, 101.0, 99.0]) == [0.01, (99.0 - 101.0) / 101.0]


def test_zero_prices_do_not_divide():
    assert returns_from_prices([0.0, 100.0, 101.0]) == [0.01]
