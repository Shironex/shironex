import unittest
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from solar import SKIES, solar_elevation, sun_events, time_of_day

WARSAW = ZoneInfo("Europe/Warsaw")
LAT, LON = 52.2297, 21.0122

# USNO (aa.usno.navy.mil) sun times for Warsaw, in UTC, to the minute.
USNO = {
    "2026-12-21": ("06:02", "06:43", "14:25", "15:06"),
    "2026-06-21": ("01:25", "02:14", "19:01", "19:51"),
    "2026-03-29": ("03:44", "04:18", "17:05", "17:39"),
    "2026-10-25": ("04:44", "05:19", "15:21", "15:56"),
}
EVENTS = ("civil_dawn", "sunrise", "sunset", "civil_dusk")


def local(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=WARSAW)


def sky_at(text: str) -> str:
    return time_of_day(local(text), LAT, LON)


class SolarPositionTest(unittest.TestCase):
    def test_noon_elevation_at_the_solstices(self):
        # 90 - latitude +/- the obliquity of the ecliptic.
        summer = max(solar_elevation(datetime(2026, 6, 21, 10, m, tzinfo=UTC), LAT, LON) for m in range(0, 60))
        winter = max(solar_elevation(datetime(2026, 12, 21, 10, m, tzinfo=UTC), LAT, LON) for m in range(0, 60))
        self.assertAlmostEqual(summer, 90 - LAT + 23.44, delta=0.1)
        self.assertAlmostEqual(winter, 90 - LAT - 23.44, delta=0.1)

    def test_sun_events_match_usno_within_a_minute_and_a_half(self):
        for day, times in USNO.items():
            events = sun_events(date.fromisoformat(day), WARSAW, LAT, LON)
            for name, hhmm in zip(EVENTS, times, strict=True):
                expected = datetime.fromisoformat(f"{day}T{hhmm}:00+00:00")
                with self.subTest(day=day, event=name):
                    self.assertLess(abs(events[name] - expected), timedelta(minutes=1.5))

    def test_naive_datetimes_are_rejected(self):
        with self.assertRaises(ValueError):
            time_of_day(datetime(2026, 1, 1, 12), LAT, LON)


class TimeOfDayTest(unittest.TestCase):
    def test_winter_solstice(self):
        # Civil dawn 07:02, sunrise 07:43, sunset 15:25, civil dusk 16:06 (CET).
        cases = {
            "2026-12-21T03:00": "night",
            "2026-12-21T06:55": "night",
            "2026-12-21T07:10": "dawn",
            "2026-12-21T08:20": "dawn",
            "2026-12-21T08:35": "day",
            "2026-12-21T12:00": "day",
            "2026-12-21T14:35": "day",
            "2026-12-21T14:45": "dusk",
            "2026-12-21T16:00": "dusk",
            "2026-12-21T16:15": "night",
            "2026-12-21T23:59": "night",
        }
        for when, sky in cases.items():
            with self.subTest(when=when):
                self.assertEqual(sky_at(when), sky)

    def test_summer_solstice(self):
        # Civil dawn 03:25, sunrise 04:14, sunset 21:01, civil dusk 21:51 (CEST).
        cases = {
            "2026-06-21T00:30": "night",
            "2026-06-21T03:15": "night",
            "2026-06-21T03:35": "dawn",
            "2026-06-21T04:55": "dawn",
            "2026-06-21T05:05": "day",
            "2026-06-21T20:10": "day",
            "2026-06-21T20:20": "dusk",
            "2026-06-21T21:45": "dusk",
            "2026-06-21T21:58": "night",
        }
        for when, sky in cases.items():
            with self.subTest(when=when):
                self.assertEqual(sky_at(when), sky)

    def test_spring_forward_day(self):
        # 2026-03-29: clocks jump from 02:00 CET to 03:00 CEST.
        # Civil dawn 05:44, sunrise 06:18, sunset 19:05, civil dusk 19:39 (CEST).
        cases = {
            "2026-03-29T01:30": "night",  # still CET
            "2026-03-29T05:35": "night",
            "2026-03-29T05:50": "dawn",
            "2026-03-29T06:58": "dawn",
            "2026-03-29T07:08": "day",
            "2026-03-29T18:15": "day",
            "2026-03-29T18:25": "dusk",
            "2026-03-29T19:35": "dusk",
            "2026-03-29T19:45": "night",
        }
        for when, sky in cases.items():
            with self.subTest(when=when):
                self.assertEqual(sky_at(when), sky)

    def test_fall_back_day(self):
        # 2026-10-25: clocks go back from 03:00 CEST to 02:00 CET.
        # Civil dawn 05:44, sunrise 06:19, sunset 16:21, civil dusk 16:56 (CET).
        cases = {
            "2026-10-25T05:35": "night",
            "2026-10-25T05:50": "dawn",
            "2026-10-25T06:58": "dawn",
            "2026-10-25T07:10": "day",
            "2026-10-25T15:30": "day",
            "2026-10-25T15:42": "dusk",
            "2026-10-25T16:50": "dusk",
            "2026-10-25T17:02": "night",
        }
        for when, sky in cases.items():
            with self.subTest(when=when):
                self.assertEqual(sky_at(when), sky)

    def test_the_repeated_hour_is_night_both_times(self):
        first = datetime(2026, 10, 25, 2, 30, tzinfo=WARSAW, fold=0)
        second = datetime(2026, 10, 25, 2, 30, tzinfo=WARSAW, fold=1)
        self.assertEqual(second.astimezone(UTC) - first.astimezone(UTC), timedelta(hours=1))
        self.assertEqual(time_of_day(first, LAT, LON), "night")
        self.assertEqual(time_of_day(second, LAT, LON), "night")

    def test_boundaries_flip_exactly_at_the_computed_events(self):
        minute = timedelta(minutes=1)
        for day in ("2026-12-21", "2026-06-21", "2026-03-29", "2026-10-25", "2026-10-17"):
            e = sun_events(date.fromisoformat(day), WARSAW, LAT, LON)
            boundaries = [
                (e["civil_dawn"], "night", "dawn"),
                (e["sunrise"] + timedelta(minutes=45), "dawn", "day"),
                (e["sunset"] - timedelta(minutes=45), "day", "dusk"),
                (e["civil_dusk"], "dusk", "night"),
            ]
            for at, before, after in boundaries:
                with self.subTest(day=day, at=at):
                    self.assertEqual(time_of_day(at - minute, LAT, LON), before)
                    self.assertEqual(time_of_day(at + minute, LAT, LON), after)

    def test_every_minute_of_a_day_is_a_known_sky_in_order(self):
        start = datetime(2026, 10, 17, tzinfo=WARSAW)
        skies = [time_of_day(start + timedelta(minutes=m), LAT, LON) for m in range(24 * 60)]
        self.assertTrue(set(skies) <= set(SKIES))
        runs = [s for i, s in enumerate(skies) if i == 0 or skies[i - 1] != s]
        self.assertEqual(runs, ["night", "dawn", "day", "dusk", "night"])


if __name__ == "__main__":
    unittest.main()
