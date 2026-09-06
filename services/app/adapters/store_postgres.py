"""Relational adapter: the OLTP store and the time series (spec 6.1 #6, #8).

Also serves as the Read API's fallback when the cache is unreachable, which is what
keeps the Caching Engine an accelerator rather than a dependency (spec 5.5).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import psycopg
from psycopg.rows import dict_row

from app.config import TEST_SYMBOLS
from app.ports import Quote, Stat, WatchRow

MIGRATIONS = Path(__file__).parent.parent / "migrations"


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _conn(self):
        return psycopg.connect(self._dsn, row_factory=dict_row, autocommit=True)

    # ------------------------------------------------------------ schema

    def migrate(self) -> list[str]:
        applied = []
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                      "(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())")
            done = {r["name"] for r in c.execute("SELECT name FROM schema_migrations")}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.name in done:
                    continue
                c.execute(path.read_text())
                c.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
                applied.append(path.name)
        return applied

    # ------------------------------------------------------------ catalogue

    def upsert_instrument(self, symbol: str, name: str, band_limit: str,
                          tracked_since: datetime) -> int:
        with self._conn() as c:
            row = c.execute(
                """INSERT INTO instrument (symbol, name, band_limit, tracked_since)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (symbol) DO UPDATE
                     SET name = EXCLUDED.name, band_limit = EXCLUDED.band_limit
                   RETURNING id""",
                (symbol, name, band_limit, tracked_since)).fetchone()
            return row["id"]

    def set_previous_close(self, closes: dict[str, float]) -> None:
        with self._conn() as c, c.cursor() as cur:
            cur.executemany("UPDATE instrument SET previous_close = %s WHERE symbol = %s",
                            [(p, s) for s, p in closes.items()])

    def previous_closes(self) -> dict[str, float]:
        with self._conn() as c:
            return {r["symbol"]: r["previous_close"] for r in
                    c.execute("SELECT symbol, previous_close FROM instrument "
                              "WHERE previous_close IS NOT NULL")}

    def seed_catalogue(self, rows: list[dict]) -> int:
        """Bulk-insert the real NSE universe. Idempotent."""
        with self._conn() as c, c.cursor() as cur:
            cur.executemany(
                """INSERT INTO instrument (symbol, name, band_limit, isin, bse_code)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (symbol) DO UPDATE
                     SET name = EXCLUDED.name, band_limit = EXCLUDED.band_limit,
                         isin = EXCLUDED.isin, bse_code = EXCLUDED.bse_code""",
                [(r["symbol"], r["name"], r["band"], r["isin"], r["bse_code"]) for r in rows])
        return len(rows)

    # ---- the canary's quote source
    def set_test_quote(self, symbol: str, price: float, as_of: datetime) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO test_quote (symbol, price, as_of) VALUES (%s, %s, %s)
                   ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price, as_of = EXCLUDED.as_of""",
                (symbol, price, as_of))

    def test_quotes(self) -> dict[str, Quote]:
        with self._conn() as c:
            return {r["symbol"]: Quote(r["symbol"], r["price"], r["as_of"], "test")
                    for r in c.execute("SELECT symbol, price, as_of FROM test_quote")}

    def set_tracked(self, symbols: list[str]) -> None:
        with self._conn() as c:
            c.execute("UPDATE instrument SET is_tracked = TRUE WHERE symbol = ANY(%s)",
                      (symbols,))

    def tracked(self) -> list[dict]:
        """The ingestion array. Re-read every cycle, so a newly added stock is picked
        up on the next tick rather than at the next restart."""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT symbol, bse_code FROM instrument WHERE is_tracked ORDER BY symbol")]

    def instrument_ids(self) -> dict[str, int]:
        with self._conn() as c:
            return {r["symbol"]: r["id"] for r in c.execute("SELECT symbol, id FROM instrument")}

    def tracked_symbols(self) -> list[str]:
        with self._conn() as c:
            return [r["symbol"] for r in
                    c.execute("SELECT symbol FROM instrument ORDER BY symbol")]

    def search_instruments(self, query: str, limit: int = 20) -> list[dict]:
        like = f"%{query.lower()}%"
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                """SELECT symbol, name, band_limit, is_tracked FROM instrument
                   WHERE (lower(symbol) LIKE %s OR lower(name) LIKE %s)
                     AND (bse_code IS NOT NULL OR symbol = ANY(%s))
                   ORDER BY (lower(symbol) LIKE %s) DESC, symbol LIMIT %s""",
                (like, like, list(TEST_SYMBOLS), f"{query.lower()}%", limit))]

    # ------------------------------------------------------------ watchlist

    def watchlist(self, user: str) -> list[WatchRow]:
        with self._conn() as c:
            return [WatchRow(r["symbol"], r["name"], r["added_at"],
                             r["baseline_value"], r["band_limit"])
                    for r in c.execute(
                        """SELECT i.symbol, i.name, i.band_limit, w.added_at, w.baseline_value
                           FROM watchlist_item w JOIN instrument i ON i.id = w.instrument_id
                           WHERE w.user_id = %s ORDER BY w.added_at""", (user,))]

    def add(self, user: str, symbol: str) -> None:
        """Adding a stock also starts collection for it, going forward.

        This is the config-driven tracking the design describes: the catalogue is the
        searchable universe, the tracked set is what ingestion actually fetches, and
        demand moves a symbol from one to the other.
        """
        with self._conn() as c:
            # Adding is checking. If a last-known price exists right now (the stock is
            # already being collected for someone else), that price is the baseline
            # from this instant - so the row reads +0.00% until something actually
            # changes, rather than showing a move the user never watched happen.
            # A stock nobody has collected yet gets its baseline from its first price
            # (ingestion warm-up); until then it is honestly NEW.
            c.execute(
                """INSERT INTO watchlist_item (user_id, instrument_id, baseline_value, session_value)
                   SELECT %s::text, i.id, q.price, q.price
                   FROM instrument i LEFT JOIN quote_latest q ON q.instrument_id = i.id
                   WHERE i.symbol = %s
                   ON CONFLICT DO NOTHING""", (user, symbol))
            c.execute("UPDATE instrument SET is_tracked = TRUE WHERE symbol = %s", (symbol,))

    def remove(self, user: str, symbol: str) -> bool:
        """Remove from this user's list. When no list holds the stock any more, stop
        collecting it - there is no one left to collect for. Returns True if tracking
        ended. History already gathered is kept; re-adding does not re-fetch bars."""
        with psycopg.connect(self._dsn) as c, c.cursor() as cur:   # one transaction
            cur.execute(
                """DELETE FROM watchlist_item
                   WHERE user_id = %s
                     AND instrument_id = (SELECT id FROM instrument WHERE symbol = %s)""",
                (user, symbol))
            cur.execute(
                """UPDATE instrument SET is_tracked = FALSE
                   WHERE symbol = %s
                     AND NOT EXISTS (SELECT 1 FROM watchlist_item w WHERE w.instrument_id = instrument.id)
                   RETURNING symbol""", (symbol,))
            ended = cur.fetchone() is not None
            c.commit()
            return ended

    # ------------------------------------------------------------ sessions

    def logins(self, user: str) -> tuple[datetime | None, datetime | None]:
        """(previous session start, current session start). N and the comparison label
        use the previous; the session chip uses the current."""
        with self._conn() as c:
            row = c.execute("SELECT previous_login_at, last_login_at FROM user_login WHERE user_id = %s",
                            (user,)).fetchone()
            return (row["previous_login_at"], row["last_login_at"]) if row else (None, None)

    def last_login(self, user: str) -> datetime | None:
        return self.logins(user)[0]

    def advance_baselines(self, user: str, now: datetime, prices: dict[str, float]) -> None:
        """Spec 4.1. One transaction: a half-applied advance corrupts baselines
        silently, and spec 4.6 makes the old values unrecoverable."""
        with psycopg.connect(self._dsn) as c:          # autocommit off -> one transaction
            with c.cursor() as cur:
                # The shift: previous <- current, current <- now.
                cur.execute(
                    """INSERT INTO user_login (user_id, previous_login_at, last_login_at)
                       VALUES (%s, NULL, %s)
                       ON CONFLICT (user_id) DO UPDATE
                         SET previous_login_at = user_login.last_login_at,
                             last_login_at = EXCLUDED.last_login_at""",
                    (user, now))
                # Same shift per stock: the price recorded at the previous sign-in becomes
                # the thing this session compares against; today's price is recorded for
                # the next one. A stock with no recorded session price (added mid-session)
                # keeps its add-time baseline - that is when the user last checked it.
                for symbol, price in prices.items():
                    cur.execute(
                        """UPDATE watchlist_item w
                           SET baseline_value = COALESCE(w.session_value, w.baseline_value, %s),
                               session_value  = %s
                           FROM instrument i
                           WHERE i.id = w.instrument_id AND w.user_id = %s AND i.symbol = %s""",
                        (price, price, user, symbol))
            c.commit()

    def set_baseline_if_missing(self, symbol: str, price: float) -> int:
        """First price for a newly tracked stock becomes its baseline on every list it is
        on. Only fills NULLs - an existing baseline is a real comparison point."""
        with self._conn() as c:
            return c.execute(
                """UPDATE watchlist_item w
                   SET baseline_value = COALESCE(w.baseline_value, %s),
                       session_value  = COALESCE(w.session_value,  %s)
                   FROM instrument i
                   WHERE i.id = w.instrument_id AND i.symbol = %s
                     AND (w.baseline_value IS NULL OR w.session_value IS NULL)""",
                (price, price, symbol)).rowcount

    def open_session(self, user: str) -> dict | None:
        """The user's currently open session, if any. Sessions are sequential: while
        one is open, Sign in is refused rather than silently re-anchoring baselines."""
        with self._conn() as c:
            row = c.execute("SELECT token, started_at FROM session WHERE user_id = %s "
                            "AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1", (user,)).fetchone()
            return dict(row) if row else None

    def end_session(self, token: str, now: datetime) -> str | None:
        """Sign out. Returns the user whose session was closed, or None if the token was
        unknown or already closed."""
        with self._conn() as c:
            row = c.execute("UPDATE session SET ended_at = %s WHERE token = %s AND ended_at IS NULL "
                            "RETURNING user_id", (now, token)).fetchone()
            return row["user_id"] if row else None

    def create_session(self, token: str, user: str, now: datetime) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO session (token, user_id, started_at) VALUES (%s, %s, %s)",
                      (token, user, now))

    def session_user(self, token: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT user_id FROM session WHERE token = %s", (token,)).fetchone()
            return row["user_id"] if row else None

    # ------------------------------------------------------------ quotes

    def put_quote(self, quote: Quote) -> bool:
        """Write-if-newer (spec 5.3). A late packet must not rewind the price."""
        with self._conn() as c:
            row = c.execute(
                """INSERT INTO quote_latest (instrument_id, price, as_of, source)
                   SELECT id, %s, %s, %s FROM instrument WHERE symbol = %s
                   ON CONFLICT (instrument_id) DO UPDATE
                     SET price = EXCLUDED.price, as_of = EXCLUDED.as_of,
                         source = EXCLUDED.source, received_at = now()
                   WHERE quote_latest.as_of < EXCLUDED.as_of
                   RETURNING instrument_id""",
                (quote.price, quote.as_of, quote.source, quote.symbol)).fetchone()
            return row is not None

    def latest_quotes(self, symbols: list[str] | None = None) -> dict[str, Quote]:
        sql = """SELECT i.symbol, q.price, q.as_of, q.source
                 FROM quote_latest q JOIN instrument i ON i.id = q.instrument_id"""
        params: tuple = ()
        if symbols:
            sql += " WHERE i.symbol = ANY(%s)"
            params = (symbols,)
        with self._conn() as c:
            return {r["symbol"]: Quote(r["symbol"], r["price"], r["as_of"], r["source"])
                    for r in c.execute(sql, params)}

    def append(self, quotes: Iterable[Quote], synthetic: bool = False) -> None:
        rows = [(q.symbol, q.as_of, q.price) for q in quotes]
        if not rows:
            return
        with self._conn() as c, c.cursor() as cur:
            cur.executemany(
                """INSERT INTO quote_snapshot (instrument_id, bucket_ts, price, synthetic)
                   SELECT id, %s, %s, %s FROM instrument WHERE symbol = %s
                   ON CONFLICT DO NOTHING""",
                [(ts, price, synthetic, sym) for sym, ts, price in rows])

    def snapshot_count(self, symbol: str) -> int:
        with self._conn() as c:
            return c.execute(
                """SELECT count(*) AS n FROM quote_snapshot s
                   JOIN instrument i ON i.id = s.instrument_id WHERE i.symbol = %s""",
                (symbol,)).fetchone()["n"]

    def provisional_symbols(self, window: int) -> set[str]:
        """Symbols whose sigma still rests on any back-filled bucket."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT symbol FROM (
                     SELECT i.symbol, s.synthetic,
                            row_number() OVER (PARTITION BY s.instrument_id
                                               ORDER BY s.bucket_ts DESC) AS rn
                     FROM quote_snapshot s JOIN instrument i ON i.id = s.instrument_id
                   ) t WHERE rn <= %s AND synthetic
                   GROUP BY symbol""", (window,)).fetchall()
            return {r["symbol"] for r in rows}

    def recent_prices(self, symbol: str, limit: int) -> list[float]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT s.price FROM quote_snapshot s JOIN instrument i ON i.id = s.instrument_id
                   WHERE i.symbol = %s ORDER BY s.bucket_ts DESC LIMIT %s""",
                (symbol, limit)).fetchall()
            return [r["price"] for r in reversed(rows)]

    # ------------------------------------------------------------ stats

    def put_stat(self, stat: Stat) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO symbol_stats (instrument_id, sigma, observations, updated_at)
                   SELECT id, %s, %s, %s FROM instrument WHERE symbol = %s
                   ON CONFLICT (instrument_id) DO UPDATE
                     SET sigma = EXCLUDED.sigma, observations = EXCLUDED.observations,
                         updated_at = EXCLUDED.updated_at""",
                (stat.sigma, stat.observations, stat.updated_at, stat.symbol))

    def latest_stats(self, symbols: list[str] | None = None) -> dict[str, Stat]:
        sql = """SELECT i.symbol, s.sigma, s.observations, s.updated_at
                 FROM symbol_stats s JOIN instrument i ON i.id = s.instrument_id"""
        params: tuple = ()
        if symbols:
            sql += " WHERE i.symbol = ANY(%s)"
            params = (symbols,)
        with self._conn() as c:
            return {r["symbol"]: Stat(r["symbol"], r["sigma"], r["observations"], r["updated_at"])
                    for r in c.execute(sql, params)}
