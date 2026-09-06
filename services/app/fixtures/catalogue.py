"""The instrument catalogue (spec 6.1 component 1).

Twelve instruments: ten NSE large caps, plus two that exist so that edge cases are
*visible* rather than merely described. Base prices are real closes from 4 Sep 2026.

`scenario` is what the fixture generator plants on the demo day. Every row in the
spec's section 9 table that can be shown, is shown.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    base_price: float
    sigma: float          # per 1-minute bucket, planted so the estimator can be checked
    band: str             # NSE price band. "No Band" for every F&O-eligible stock.
    scenario: str
    tracked_from_day: int = 0


CATALOGUE: tuple[Instrument, ...] = (
    # --- the thesis pair. Adjacent on screen, and the whole argument (spec 3.3).
    Instrument("RELIANCE",   "Reliance Industries",      1322.00, 0.00069, "No Band", "notable"),
    Instrument("HINDUNILVR", "Hindustan Unilever",       1974.00, 0.00207, "No Band", "bigger_move_but_noise"),

    # --- ordinary behaviour, so the bands mean something by contrast
    Instrument("INFY",       "Infosys",                  1130.00, 0.00065, "No Band", "extreme"),
    Instrument("HDFCBANK",   "HDFC Bank",                 713.15, 0.00080, "No Band", "mild"),
    Instrument("TCS",        "Tata Consultancy Services", 2300.90, 0.00075, "No Band", "calm"),

    # --- one instrument per edge case in spec 9
    Instrument("ICICIBANK",  "ICICI Bank",               1423.00, 0.00090, "No Band", "goes_stale"),
    Instrument("SBIN",       "State Bank of India",      1017.00, 0.00110, "No Band", "late_ticks"),
    Instrument("BHARTIARTL", "Bharti Airtel",            1842.00, 0.00085, "No Band", "outlier_tick"),
    Instrument("LT",         "Larsen & Toubro",          3966.00, 0.00070, "No Band", "corporate_action"),
    Instrument("ITC",        "ITC",                       264.10, 0.00070, "No Band", "flatline"),

    # --- the two that exist to make a state visible
    Instrument("NEWLIST",    "Newly Listed Industries",   450.00, 0.00150, "No Band", "calm",
               tracked_from_day=2),
    Instrument("SMALLCAP",   "Smallcap Manufacturing",    799.30, 0.00260, "20%",     "hits_circuit"),
)

BY_SYMBOL = {i.symbol: i for i in CATALOGUE}
