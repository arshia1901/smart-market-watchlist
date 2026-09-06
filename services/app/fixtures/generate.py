"""Generate the deterministic replay fixture.

Spec 11. Three trading days per instrument:

    days 0-1 (750 buckets)  sigma warm-up - bulk loaded at boot, never replayed,
                            because 750 buckets is 12.5 hours of market time
    day  2   (375 buckets)  the demo day, replayed on the grid

Rows are written in EMIT order and carry their own event time as (day, bucket).
A row whose bucket index is lower than one already emitted is therefore a genuinely
late arrival, which is how spec 5.3's write-if-newer rule gets exercised for real
rather than simulated.

Determinism: stdlib `random` with a fixed seed. The generated file is the fixture of
record and is committed with its SHA-256; this script is documentation.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import math
import random
from pathlib import Path

from app.config import BUCKETS_PER_TRADING_DAY as BPD
from app.fixtures.catalogue import CATALOGUE, Instrument

SEED = 20260905
WARMUP_DAYS = 2
DEMO_DAY = 2
HERE = Path(__file__).parent
OUT = HERE / "market.csv.gz"


def _walk(rng: random.Random, start: float, sigma: float, n: int,
          total_return: float | None = None) -> list[float]:
    """A random path whose *destination* can be set deliberately.

    Left free, a 0.207% sigma drifts about 4% over a 375-bucket session, which
    swamps a planted 3% move and makes the demo a coin flip. So the per-bucket log
    returns are shifted by a constant to land the day exactly where we intend. The
    texture stays random; only the endpoint is chosen. Sigma is unaffected - a
    constant shift moves the mean, not the spread.
    """
    steps = [rng.gauss(0.0, sigma) for _ in range(n)]
    if total_return is not None:
        drift = (math.log1p(total_return) - sum(math.log1p(r) for r in steps)) / n
    else:
        drift = 0.0

    prices, p = [], start
    for r in steps:
        p *= math.exp(math.log1p(r) + drift)
        prices.append(round(p, 2))
    return prices


def _demo_day(rng: random.Random, inst: Instrument, open_price: float) -> list[tuple[int, float]]:
    """Returns (bucket, price) in EMIT order. May be non-monotonic on purpose."""
    rows: list[tuple[int, float]] = []

    # Where the day ends up. The path getting there is random; the destination is not.
    day_return = {
        "notable": 0.027,               # +2.7% on a calm stock  -> magnitude ~2.0
        "bigger_move_but_noise": 0.031, # +3.1%, a BIGGER raw move on a jumpy stock -> noise
        "extreme": 0.045,
        "mild": 0.014,
        "calm": 0.0,
        "goes_stale": 0.004,
        "late_ticks": 0.010,
        "outlier_tick": 0.012,
        "corporate_action": 0.0,
        "flatline": 0.0,
        "hits_circuit": 0.20,
    }[inst.scenario]

    prices = _walk(rng, open_price, inst.sigma, BPD, total_return=day_return)

    if inst.scenario == "flatline":
        # Untraded all day: zero variance, which would divide by zero unfloored.
        prices = [round(open_price, 2)] * BPD

    if inst.scenario == "corporate_action":
        # 1:10 split at midday. -90% is a magnitude near 50 and would top every list.
        for i in range(BPD // 2, BPD):
            prices[i] = round(prices[i] / 10.0, 2)

    if inst.scenario == "hits_circuit":
        # Pinned at the +20% upper band from midday: a suppressed move, not a small one.
        # The band is set against the previous close, which is where this day opens.
        limit = round(open_price * 1.20, 2)
        for i in range(BPD // 2, BPD):
            prices[i] = limit

    for bucket, price in enumerate(prices):
        # The feed simply stops. Freshness must walk live -> delayed -> stale.
        if inst.scenario == "goes_stale" and bucket > BPD // 2:
            break

        if inst.scenario == "outlier_tick" and bucket == BPD // 3:
            rows.append((bucket, round(price * 1.09, 2)))   # a fat-fingered print
            continue

        rows.append((bucket, price))

        if inst.scenario == "late_ticks" and bucket in (100, 240):
            # A delayed packet carrying an OLDER event time and a wild price.
            # Applied naively it rewinds the price and inverts r (spec 5.3).
            rows.append((bucket - 5, round(price * 0.94, 2)))

    return rows


def generate() -> Path:
    rng = random.Random(SEED)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(OUT, "wt", newline="", compresslevel=9) as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "day", "bucket", "price"])

        for inst in CATALOGUE:
            price = inst.base_price
            for day in range(WARMUP_DAYS + 1):
                if day < inst.tracked_from_day:
                    continue
                if day == DEMO_DAY:
                    for bucket, p in _demo_day(rng, inst, price):
                        w.writerow([inst.symbol, day, bucket, f"{p:.2f}"])
                else:
                    for bucket, p in enumerate(_walk(rng, price, inst.sigma, BPD)):
                        w.writerow([inst.symbol, day, bucket, f"{p:.2f}"])
                        price = p

    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    (HERE / "market.sha256").write_text(f"{digest}  {OUT.name}\n")
    return OUT


if __name__ == "__main__":
    path = generate()
    size = path.stat().st_size
    with gzip.open(path, "rt") as fh:
        rows = sum(1 for _ in fh) - 1
    print(f"{path.name}: {rows:,} rows, {size / 1024:.0f} KB gzipped")
    print((HERE / "market.sha256").read_text().strip())
