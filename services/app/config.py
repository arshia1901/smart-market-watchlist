"""Every system parameter, in one file.

Spec: docs/superpowers/specs/2026-09-05-smart-market-watchlist-design.md
"""
from __future__ import annotations

import os
from datetime import time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")

# --- the measure (spec 3.7). A parameter, not an array, and no UI to change it.
MEASURE = os.getenv("MEASURE", "price")

# --- the grid (spec 3.6). 1 minute, matching what free feeds actually publish.
GRID_SECONDS = int(os.getenv("GRID_SECONDS", "60"))

# The live provider's own cadence, deliberately independent of REPLAY_SPEED. Replay
# is local and can be stepped fast; a real API cannot. Polling a 1-minute feed faster
# returns the same event timestamp repeatedly - motion without information, and the
# quickest route to a rate-limit ban.
LIVE_POLL_SECONDS = int(os.getenv("LIVE_POLL_SECONDS", "60"))

# --- the trading session (spec 3.2). NSE 09:15-15:30 IST.
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
SESSION_SECONDS = 22_500
BUCKETS_PER_TRADING_DAY = SESSION_SECONDS // GRID_SECONDS          # 375

# --- sigma (spec 3.2). Two trading days, the same window for every stock.
SIGMA_WINDOW = int(os.getenv("SIGMA_WINDOW", str(BUCKETS_PER_TRADING_DAY * 2)))   # 750
SIGMA_FLOOR = 1e-7          # spec 9: an untraded stock must not divide by zero
WINSOR_K = 5.0              # spec 9: one bad tick must not inflate sigma for two days

# --- bands (spec 3.4). Half-open, so every boundary value has exactly one band.
BAND_EDGES = (1.0, 2.0, 3.0)
# Spec 9. Keyed off the RETURN, not the magnitude: magnitude scales with sqrt(N),
# so a magnitude threshold would classify an ordinary move as a corporate action
# whenever a user logged in twice in quick succession - and would make banding
# N-dependent, contradicting 3.5. A 1:10 split is -90%, a 1:2 split is -50%, and
# NSE circuit bands cap a real session move at 20%.
CORPORATE_ACTION_RETURN = 0.40

# --- freshness (spec 5.4), tuned to the 1-minute grid
FRESH_LIVE_SECONDS = 120            # two grid cycles
FRESH_DELAYED_SECONDS = 1800        # a 15-min delayed feed must read DELAYED, not STALE

# --- provider. Live is the default. The replay adapter remains only as a test harness.
PROVIDER = os.getenv("PROVIDER", "live")
LIVE_TIMEOUT_SECONDS = 4.0
LIVE_FAILURES_BEFORE_BREAKER = 3

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://watchlist:watchlist@localhost:5432/watchlist")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# --- the canary. Quotes for these symbols come from the test_quote table, never an
# exchange. Searchable, labelled "test" everywhere, and the only symbols the
# /api/test/* endpoints will accept.
TEST_SYMBOLS = frozenset({"ARSHIA"})

# --- users (spec 12). Hardcoded on purpose. Not auth, and we say so.
USERS = {"asha": "asha", "ravi": "ravi", "meera": "meera"}
