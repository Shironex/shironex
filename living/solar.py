"""Sun position and the four window skies.

The sun position uses the equations of the NOAA Solar Calculator spreadsheet
(after Meeus): equation of time and declination from Julian centuries, then the
hour angle and elevation. Sunrise and sunset land within about a minute of
published tables, which is plenty for picking a sky.

Sky boundaries, by the sun's elevation and the time around sunrise and sunset:

    night  sun below -6 degrees (darker than civil twilight)
    dawn   morning, from civil dawn (-6 degrees) until 45 minutes after sunrise
    day    from 45 minutes after sunrise until 45 minutes before sunset
    dusk   evening, from 45 minutes before sunset until civil dusk (-6 degrees)

Sunrise and sunset are the moments the sun's upper limb touches the horizon,
which with standard refraction is an elevation of -0.833 degrees.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CIVIL_TWILIGHT_DEG = -6.0
SUNRISE_DEG = -0.833
GOLDEN_WINDOW = timedelta(minutes=45)

SKIES = ("night", "dawn", "day", "dusk")


def _as_utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        raise ValueError("expected an aware datetime, got a naive one")
    return when.astimezone(UTC)


def _equation_of_time_and_declination(t: datetime) -> tuple[float, float]:
    """Equation of time in minutes and solar declination in radians (NOAA spreadsheet terms)."""
    julian_day = t.timestamp() / 86400 + 2440587.5
    c = (julian_day - 2451545.0) / 36525  # Julian centuries since J2000.0
    mean_long = math.radians((280.46646 + c * (36000.76983 + c * 0.0003032)) % 360)
    mean_anom = math.radians(357.52911 + c * (35999.05029 - 0.0001537 * c))
    ecc = 0.016708634 - c * (0.000042037 + 0.0000001267 * c)
    centre = (
        math.sin(mean_anom) * (1.914602 - c * (0.004817 + 0.000014 * c))
        + math.sin(2 * mean_anom) * (0.019993 - 0.000101 * c)
        + math.sin(3 * mean_anom) * 0.000289
    )
    omega = math.radians(125.04 - 1934.136 * c)
    apparent_long = math.radians(math.degrees(mean_long) + centre - 0.00569 - 0.00478 * math.sin(omega))
    mean_obliquity = 23 + (26 + (21.448 - c * (46.815 + c * (0.00059 - c * 0.001813))) / 60) / 60
    obliquity = math.radians(mean_obliquity + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(obliquity) * math.sin(apparent_long))
    y = math.tan(obliquity / 2) ** 2
    eqtime = 4 * math.degrees(
        y * math.sin(2 * mean_long)
        - 2 * ecc * math.sin(mean_anom)
        + 4 * ecc * y * math.sin(mean_anom) * math.cos(2 * mean_long)
        - 0.5 * y * y * math.sin(4 * mean_long)
        - 1.25 * ecc * ecc * math.sin(2 * mean_anom)
    )
    return eqtime, decl


def hour_angle(when: datetime, lon: float) -> float:
    """Solar hour angle in degrees, in [-180, 180): negative before solar noon."""
    t = _as_utc(when)
    eqtime, _ = _equation_of_time_and_declination(t)
    minutes = t.hour * 60 + t.minute + (t.second + t.microsecond / 1e6) / 60
    true_solar_time = minutes + eqtime + 4 * lon
    # ha = tst / 4 - 180, wrapped into [-180, 180).
    return (true_solar_time / 4) % 360 - 180


def solar_elevation(when: datetime, lat: float, lon: float) -> float:
    """Elevation of the sun's centre above the horizon, in degrees (no refraction)."""
    t = _as_utc(when)
    _, decl = _equation_of_time_and_declination(t)
    ha = math.radians(hour_angle(t, lon))
    phi = math.radians(lat)
    cos_zenith = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    zenith = math.acos(max(-1.0, min(1.0, cos_zenith)))
    return 90.0 - math.degrees(zenith)


def time_of_day(when: datetime, lat: float, lon: float) -> str:
    """One of SKIES for the given instant and place."""
    if solar_elevation(when, lat, lon) < CIVIL_TWILIGHT_DEG:
        return "night"
    if hour_angle(when, lon) < 0:
        # Morning: still dawn while the sun rose less than GOLDEN_WINDOW ago.
        risen_long_ago = solar_elevation(when - GOLDEN_WINDOW, lat, lon) >= SUNRISE_DEG
        return "day" if risen_long_ago else "dawn"
    # Afternoon: dusk once the sun sets within GOLDEN_WINDOW.
    sets_soon = solar_elevation(when + GOLDEN_WINDOW, lat, lon) < SUNRISE_DEG
    return "dusk" if sets_soon else "day"


def _solar_noon(day: date, tz: ZoneInfo, lon: float) -> datetime:
    noon = datetime.combine(day, time(12), tz).astimezone(UTC)
    for _ in range(3):
        noon -= timedelta(minutes=4 * hour_angle(noon, lon))
    return noon


def _crossing(lo: datetime, hi: datetime, lat: float, lon: float, deg: float) -> datetime | None:
    """Instant in [lo, hi] where the elevation crosses `deg`, by bisection."""
    lo_above = solar_elevation(lo, lat, lon) >= deg
    if lo_above == (solar_elevation(hi, lat, lon) >= deg):
        return None
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        if (solar_elevation(mid, lat, lon) >= deg) == lo_above:
            lo = mid
        else:
            hi = mid
    return lo + (hi - lo) / 2


def sun_events(day: date, tz: ZoneInfo, lat: float, lon: float) -> dict[str, datetime | None]:
    """Civil dawn, sunrise, sunset and civil dusk around the solar noon of a local date, in UTC.

    An event is None when the sun never crosses that elevation (polar day or night).
    """
    noon = _solar_noon(day, tz, lon)
    before, after = noon - timedelta(hours=12), noon + timedelta(hours=12)
    return {
        "civil_dawn": _crossing(before, noon, lat, lon, CIVIL_TWILIGHT_DEG),
        "sunrise": _crossing(before, noon, lat, lon, SUNRISE_DEG),
        "sunset": _crossing(noon, after, lat, lon, SUNRISE_DEG),
        "civil_dusk": _crossing(noon, after, lat, lon, CIVIL_TWILIGHT_DEG),
    }
