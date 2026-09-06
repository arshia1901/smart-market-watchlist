"""The add-a-stock lifecycle, end to end against the real store.

This test exists because an earlier judgement call - "add/remove just exercises the
ORM, not worth testing" - was wrong. The ORM is not the point. The *lifecycle* is the
product behaviour the design describes:

    searchable  ->  added  ->  tracked  ->  collecting  ->  rated

and every arrow in that chain is a place it can silently stop.

Skipped automatically when there is no database, so the fast suite stays fast.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.ports import Quote

BASE_DSN = os.getenv("DATABASE_URL", "postgresql://watchlist:watchlist@localhost:55432/watchlist")
TEST_DB = "watchlist_test"


def _test_dsn(base: str) -> str:
    """Same server, a DIFFERENT database.

    These tests write real quotes. An earlier version ran them against the live
    database and left a fake price of 100, timestamped 'now', on a real stock - which
    then caused every genuine quote for it to be rejected as late. Tests do not get
    to touch the database the product serves from.
    """
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    d = conninfo_to_dict(base)
    d["dbname"] = TEST_DB
    return make_conninfo(**d)


@pytest.fixture(scope="module")
def store():
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from app.adapters.store_postgres import PostgresStore
    from app.fixtures.build_reference import load as load_reference

    admin = conninfo_to_dict(BASE_DSN); admin["dbname"] = "postgres"
    try:
        with psycopg.connect(make_conninfo(**admin), autocommit=True) as c:
            if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DB,)).fetchone():
                c.execute(f'CREATE DATABASE "{TEST_DB}"')
    except psycopg.Error:
        pytest.skip("no database available; run inside compose")

    s = PostgresStore(_test_dsn(BASE_DSN))
    s.migrate()
    s.seed_catalogue(load_reference()[:80])       # a real slice of the real catalogue
    return s


@pytest.fixture
def candidate(store):
    """A real instrument from the catalogue that nobody is tracking.

    Hermetic on purpose. Tracking is sticky by design (one user removing a stock does
    not stop collection for everyone), so a test that tracks a real symbol and walks
    away leaves the live ingestion leg polling BSE for its leftovers - and an earlier
    version of this fixture did exactly that, then ran out of candidates and skipped
    the whole suite. So: a pool of thousands, and teardown puts things back.
    """
    rows = store.search_instruments("limited", 2000)
    tracked = {r["symbol"] for r in store.tracked()}
    pick = next((r["symbol"] for r in rows if r["symbol"] not in tracked), None)
    if pick is None:
        pytest.skip("no untracked candidate in the catalogue")

    def pristine() -> None:
        """Never collected, on nobody's list. The test DB persists between runs, and a
        quote_latest row left by a previous run made 'a fresh add has no baseline'
        false - correctly, under the adding-is-checking rule. Start clean, end clean."""
        with store._conn() as c:
            for table in ("quote_latest", "quote_snapshot", "symbol_stats"):
                c.execute(f"DELETE FROM {table} WHERE instrument_id = "
                          f"(SELECT id FROM instrument WHERE symbol = %s)", (pick,))
            c.execute("DELETE FROM watchlist_item WHERE instrument_id = "
                      "(SELECT id FROM instrument WHERE symbol = %s)", (pick,))
            c.execute("UPDATE instrument SET is_tracked = FALSE WHERE symbol = %s", (pick,))

    pristine()
    yield pick
    pristine()


def test_a_new_stock_is_searchable_before_it_is_tracked(store, candidate):
    """The catalogue is the universe; the tracked set is what we actually fetch."""
    found = {r["symbol"] for r in store.search_instruments(candidate.lower(), 20)}
    assert candidate in found
    assert candidate not in {r["symbol"] for r in store.tracked()}


def test_adding_it_starts_collection(store, candidate):
    """The design's config-driven tracking: adding a stock begins fetching it,
    going forward. Without this the row would sit on the watchlist forever with no
    price and no explanation."""
    store.add("_lifecycle_test", candidate)

    assert candidate in {r["symbol"] for r in store.tracked()}, \
        "adding to a watchlist must move a symbol into the ingestion array"
    assert candidate in {r.symbol for r in store.watchlist("_lifecycle_test")}


def test_it_has_a_scripcode_so_it_can_actually_be_quoted(store, candidate):
    """Tracking something we cannot fetch would be a promise we cannot keep."""
    store.add("_lifecycle_test", candidate)
    row = next(r for r in store.tracked() if r["symbol"] == candidate)
    assert row["bse_code"], f"{candidate} is tracked but has no way to be quoted"


def test_it_renders_new_until_it_has_a_baseline(store, candidate):
    """A stock nobody has ever collected has no price to anchor to, so it is NEW - the
    same mechanism as 'changed', not a special case."""
    store.add("_lifecycle_test", candidate)
    row = next(r for r in store.watchlist("_lifecycle_test") if r.symbol == candidate)
    assert row.baseline is None


def test_adding_anchors_the_baseline_at_the_last_known_price(store, candidate):
    """Adding is checking. If the stock already has a last-known price (someone else is
    collecting it), that price is the baseline from this instant - so the row reads
    +0.00% until something changes, never a move the user did not watch. This is the
    rule that replaced a previous-close fallback that showed +0.74% on a Saturday."""
    from datetime import datetime, timezone
    store.put_quote(Quote(candidate, 250.0, datetime.now(timezone.utc), "test"))
    store.add("_lifecycle_test", candidate)
    row = next(r for r in store.watchlist("_lifecycle_test") if r.symbol == candidate)
    assert row.baseline == 250.0


def test_it_stays_unrated_until_the_window_fills(store, candidate):
    """A stock with no history gets no sigma, and is never given a default."""
    store.add("_lifecycle_test", candidate)
    stats = store.latest_stats([candidate])
    assert candidate not in stats or stats[candidate].sigma is None


def test_a_quote_for_it_survives_write_if_newer(store, candidate):
    """The first quote lands; an older one behind it does not."""
    store.add("_lifecycle_test", candidate)
    now = datetime.now(timezone.utc)

    assert store.put_quote(Quote(candidate, 100.0, now, "test")) is True
    assert store.put_quote(Quote(candidate, 50.0, now - timedelta(minutes=5), "test")) is False, \
        "a late arrival must not rewind a newly tracked stock's price"

    assert store.latest_quotes([candidate])[candidate].price == 100.0


def test_removing_it_from_the_last_list_stops_tracking(store, candidate):
    """Tracking ends when nobody holds the stock - there is no one left to collect
    for. But one user's removal must not blank another user's list."""
    store.add("_lifecycle_test", candidate)
    store.add("_lifecycle_other", candidate)

    assert store.remove("_lifecycle_test", candidate) is False       # someone still holds it
    assert candidate in {r["symbol"] for r in store.tracked()}

    assert store.remove("_lifecycle_other", candidate) is True       # last holder gone
    assert candidate not in {r["symbol"] for r in store.tracked()}
    assert candidate not in {r.symbol for r in store.watchlist("_lifecycle_other")}


def test_sessions_are_sequential(store):
    """Sign in while signed in is refused; Sign out makes the next Sign in possible.
    A second sign-in used to silently re-anchor every baseline."""
    from datetime import datetime, timezone
    import secrets
    user, now = "_session_test", datetime.now(timezone.utc)
    with store._conn() as c:
        c.execute("DELETE FROM session WHERE user_id = %s", (user,))

    assert store.open_session(user) is None
    t1 = secrets.token_urlsafe(8)
    store.create_session(t1, user, now)
    assert store.open_session(user)["token"] == t1          # the API refuses login here

    assert store.end_session("not-a-token", now) is None     # unknown token: nothing closed
    assert store.end_session(t1, now) == user
    assert store.open_session(user) is None                   # next Sign in allowed
    assert store.end_session(t1, now) is None                 # already closed: idempotent


def test_refresh_never_moves_the_anchor(store, candidate):
    """The bug a page refresh exposed. Sign-in promotes the previous session's price to
    the baseline and records today's; reading the watchlist any number of times in
    between changes nothing. Three sign-ins at 100, 110, 120 must compare against
    100 (first), 100 (second - previous session started at 100), 110 (third)."""
    from datetime import datetime, timezone, timedelta
    user = "_shift_test"
    with store._conn() as c:
        c.execute("DELETE FROM watchlist_item WHERE user_id = %s", (user,))
        c.execute("DELETE FROM user_login WHERE user_id = %s", (user,))
    t0 = datetime.now(timezone.utc)
    store.put_quote(Quote(candidate, 100.0, t0, "test"))
    store.add(user, candidate)                                   # adding is checking: 100

    def baseline(): return next(r for r in store.watchlist(user) if r.symbol == candidate).baseline

    store.advance_baselines(user, t0, {candidate: 100.0})         # sign-in 1
    assert baseline() == 100.0
    assert baseline() == 100.0                                   # a refresh: unchanged
    assert store.logins(user) == (None, t0)

    store.advance_baselines(user, t0 + timedelta(hours=1), {candidate: 110.0})   # sign-in 2
    assert baseline() == 100.0, "session 2 compares against where session 1 started"
    assert baseline() == 100.0                                   # refresh mid-session: unchanged
    assert store.logins(user)[0] == t0

    store.advance_baselines(user, t0 + timedelta(hours=2), {candidate: 120.0})   # sign-in 3
    assert baseline() == 110.0, "session 3 compares against where session 2 started"
