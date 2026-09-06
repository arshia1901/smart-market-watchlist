from datetime import datetime

from app.config import IST
from app.domain.clock import ReplayClock


def test_replay_clock_steps_by_the_grid():
    c = ReplayClock(datetime(2026, 9, 3, 9, 15, tzinfo=IST), step_seconds=60)
    assert c.now() == datetime(2026, 9, 3, 9, 15, tzinfo=IST)
    c.advance()
    assert c.now() == datetime(2026, 9, 3, 9, 16, tzinfo=IST)
    c.advance(14)
    assert c.now() == datetime(2026, 9, 3, 9, 30, tzinfo=IST)


def test_a_whole_trading_day_replays_instantly():
    """375 buckets is a full session. This must be free, or there is no demo."""
    c = ReplayClock(datetime(2026, 9, 3, 9, 15, tzinfo=IST), step_seconds=60)
    c.advance(375)
    assert c.now() == datetime(2026, 9, 3, 15, 30, tzinfo=IST)
