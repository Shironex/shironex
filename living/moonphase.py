"""Moon phase from the mean synodic month.

The age of the moon is the time since a known new moon, modulo the mean
synodic month. The real lunation wobbles around the mean by up to about 14
hours, which only matters within half a day of a bucket edge.

The eight phases split the month into equal eighths, each centred on its
phase: "new" covers the 1.85 days either side of new moon, "first_quarter"
the same around the first quarter, and so on.
"""

from __future__ import annotations

from datetime import UTC, datetime

SYNODIC_MONTH_DAYS = 29.530588853
# New moon of 2000-01-06 18:14 UT, the usual reference epoch.
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)

PHASES = (
    "new",
    "waxing_crescent",
    "first_quarter",
    "waxing_gibbous",
    "full",
    "waning_gibbous",
    "last_quarter",
    "waning_crescent",
)


def moon_age_days(when: datetime) -> float:
    """Days since the last mean new moon, in [0, SYNODIC_MONTH_DAYS)."""
    if when.tzinfo is None:
        raise ValueError("expected an aware datetime, got a naive one")
    days = (when - REFERENCE_NEW_MOON).total_seconds() / 86400
    return days % SYNODIC_MONTH_DAYS


def moon_phase(when: datetime) -> str:
    """One of PHASES, matching the moon_<phase>.png layer names."""
    eighths = moon_age_days(when) / SYNODIC_MONTH_DAYS * len(PHASES)
    return PHASES[int(eighths + 0.5) % len(PHASES)]
