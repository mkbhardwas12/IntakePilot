"""Cost-of-delay pricing — deterministic, from the requester's own words.

"Our monthly vendor report takes 3 days to compile by hand" already contains
its own business case: 3 days × 12 times a year = 288 hours of doing
nothing about it. No intake tool prices that pain; this one puts it on the
ticket so queues can sort their backlog by value instead of by noise.

Deliberately NOT an LLM call: pricing must be explainable arithmetic. It
only fires when the ask contains BOTH a duration and a cadence; otherwise
the slot stays empty rather than inventing a number.
"""
from __future__ import annotations

import re

UNIT_HOURS = {"minute": 1 / 60, "hour": 1.0, "day": 8.0, "week": 40.0}

FREQUENCIES: list[tuple[str, str, int]] = [
    # (regex, name, occurrences per year — working-time conventions)
    (r"\b(daily|every day|each day|every morning|every night)\b", "daily", 250),
    (r"\b(weekly|every week|each week)\b", "weekly", 52),
    (r"\b(monthly|every month|each month|month-end|monthend)\b", "monthly", 12),
    (r"\b(quarterly|every quarter|each quarter|quarter-end)\b", "quarterly", 4),
    (r"\b(yearly|annually|every year|year-end)\b", "yearly", 1),
]

_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(minutes?|hours?|days?|weeks?)\b")


def extract_cost_of_delay(text: str) -> dict | None:
    low = text.lower()
    duration = _DURATION.search(low)
    if not duration:
        return None
    frequency = next(((name, per_year) for pattern, name, per_year in FREQUENCIES
                      if re.search(pattern, low)), None)
    if not frequency:
        return None  # a duration without a cadence cannot be annualized
    qty = float(duration.group(1))
    unit = duration.group(2).rstrip("s")
    hours = qty * UNIT_HOURS[unit]
    name, per_year = frequency
    return {
        "hours_per_occurrence": round(hours, 2),
        "frequency": name,
        "occurrences_per_year": per_year,
        "annual_hours": round(hours * per_year, 1),
        "basis": "deterministic: duration × cadence from the requester's own words",
    }


def describe(cod: dict) -> str:
    """One human line for renders and tickets."""
    return (f"~{cod['annual_hours']:g} hours/year of doing nothing "
            f"({cod['hours_per_occurrence']:g} h per occurrence, "
            f"{cod['frequency']}, {cod['occurrences_per_year']}×/year)")
