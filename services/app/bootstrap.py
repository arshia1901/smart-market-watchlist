"""One-shot bootstrap: migrate and seed the catalogue. Nothing else.

Deliberately empty at cold start. No fixture, no synthetic history, no pre-made
watchlists. The catalogue is ten real NSE large caps (real names, ISINs, circuit bands
and BSE scripcodes from official files). Nothing is tracked until a user adds it; the
moment they do, ingestion starts collecting it live and warms its sigma window from
that stock's own real intraday bars. See app/ingestion.py::warm_up.
"""
from __future__ import annotations

import logging
import sys

from app.adapters.bus_redis import RedisStreamBus
from app.adapters.store_postgres import PostgresStore
from app.config import DATABASE_URL, REDIS_URL, TEST_SYMBOLS
from app.fixtures.build_reference import load as load_reference

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("bootstrap")

# Ten real, liquid NSE large caps. Every one verified to return a live BSE quote and
# a full day of 1-minute bars from this machine.
CATALOGUE = ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
             "SBIN", "BHARTIARTL", "ITC", "LT", "HINDUNILVR")


def main() -> int:
    store = PostgresStore(DATABASE_URL)
    applied = store.migrate()
    log.info("migrations applied: %s", applied or "none (already current)")

    wanted = set(CATALOGUE)
    rows = [r for r in load_reference() if r["symbol"] in wanted]
    missing = wanted - {r["symbol"] for r in rows}
    if missing:
        log.error("catalogue symbols missing from the reference file: %s", sorted(missing))
        return 1
    store.seed_catalogue(rows)
    log.info("catalogue: %d real instruments, none tracked yet", len(rows))

    # The canary: one deliberately non-real instrument, named as such, whose quotes come
    # from the test_quote table. It exists so the whole pipeline can be exercised by
    # hand on a day the market is shut. Labelled "test" in every row it appears in.
    store.seed_catalogue([{"symbol": s, "name": f"{s} (test instrument)", "band": "No Band",
                           "isin": None, "bse_code": None} for s in sorted(TEST_SYMBOLS)])
    log.info("canary: %s", ", ".join(sorted(TEST_SYMBOLS)))
    for r in sorted(rows, key=lambda r: r["symbol"]):
        log.info("  %-11s %-36s BSE %s  band=%s", r["symbol"], r["name"][:36], r["bse_code"], r["band"])

    RedisStreamBus(REDIS_URL).ensure_group("statistics")
    log.info("bootstrap complete - empty, live, waiting for the first add")
    return 0


if __name__ == "__main__":
    sys.exit(main())
