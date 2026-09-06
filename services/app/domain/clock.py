"""The clock is injected, never read globally.

Spec 6.1 component 3. A hardcoded sleep in the grid loop would mean replaying two
trading days takes two trading days - no test harness, and no demo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ReplayClock:
    """Stepped by hand, so a trading day replays in milliseconds."""

    def __init__(self, start: datetime, step_seconds: int) -> None:
        self._t = start
        self._step = timedelta(seconds=step_seconds)

    def now(self) -> datetime:
        return self._t

    def advance(self, ticks: int = 1) -> None:
        self._t += self._step * ticks
