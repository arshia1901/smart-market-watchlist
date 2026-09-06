"""The canary's provider leg, with a stub store. Pure; no database."""
from datetime import datetime, timezone

import pytest

from app.adapters.provider_live import BseProvider, LiveProvider, TestProvider
from app.config import TEST_SYMBOLS
from app.ports import ProviderUnavailable, Quote


class StubStore:
    def __init__(self, quotes): self._q = quotes
    def test_quotes(self): return self._q


def test_the_canary_is_served_from_the_table_and_nothing_else():
    now = datetime.now(timezone.utc)
    store = StubStore({"ARSHIA": Quote("ARSHIA", 101.5, now, "test"),
                       "RELIANCE": Quote("RELIANCE", 1.0, now, "test")})   # poisoning attempt
    got = TestProvider(store).fetch(["ARSHIA", "RELIANCE"])
    assert [q.symbol for q in got] == ["ARSHIA"], "a real stock must never be served from the test table"
    assert got[0].price == 101.5 and got[0].source == "test"


def test_live_provider_routes_each_symbol_to_the_right_leg():
    now = datetime.now(timezone.utc)
    store = StubStore({"ARSHIA": Quote("ARSHIA", 100.0, now, "test")})

    class FakeBse(BseProvider):
        def fetch(self, symbols):
            assert "ARSHIA" not in symbols, "the canary must not reach the exchange leg"
            return [Quote(s, 42.0, now, "bse") for s in symbols]

    live = LiveProvider(FakeBse({"RELIANCE": "500325"}), TestProvider(store))
    got = {q.symbol: q for q in live.fetch(["RELIANCE", "ARSHIA"])}
    assert got["RELIANCE"].source == "bse" and got["ARSHIA"].source == "test"


def test_canary_still_served_when_the_exchange_leg_is_down():
    now = datetime.now(timezone.utc)
    store = StubStore({"ARSHIA": Quote("ARSHIA", 100.0, now, "test")})

    class DeadBse(BseProvider):
        def fetch(self, symbols): raise ProviderUnavailable("offline")

    got = LiveProvider(DeadBse({"RELIANCE": "x"}), TestProvider(store)).fetch(["RELIANCE", "ARSHIA"])
    assert [q.symbol for q in got] == ["ARSHIA"]


def test_only_configured_symbols_are_test_symbols():
    assert "ARSHIA" in TEST_SYMBOLS and "RELIANCE" not in TEST_SYMBOLS
