import unittest
from datetime import UTC, datetime, timedelta

from moonphase import PHASES, SYNODIC_MONTH_DAYS, moon_age_days, moon_phase

# Principal moon phases of 2026 from USNO (aa.usno.navy.mil), in UT.
USNO_2026 = """
01-03 10:03 full; 01-10 15:48 last; 01-18 19:52 new; 01-26 04:47 first
02-01 22:09 full; 02-09 12:43 last; 02-17 12:01 new; 02-24 12:27 first
03-03 11:38 full; 03-11 09:38 last; 03-19 01:23 new; 03-25 19:18 first
04-02 02:12 full; 04-10 04:51 last; 04-17 11:52 new; 04-24 02:32 first
05-01 17:23 full; 05-09 21:10 last; 05-16 20:01 new; 05-23 11:11 first
05-31 08:45 full; 06-08 10:00 last; 06-15 02:54 new; 06-21 21:55 first
06-29 23:56 full; 07-07 19:29 last; 07-14 09:43 new; 07-21 11:05 first
07-29 14:36 full; 08-06 02:21 last; 08-12 17:37 new; 08-20 02:46 first
08-28 04:18 full; 09-04 07:51 last; 09-11 03:27 new; 09-18 20:44 first
09-26 16:49 full; 10-03 13:25 last; 10-10 15:50 new; 10-18 16:12 first
10-26 04:12 full; 11-01 20:28 last; 11-09 07:02 new; 11-17 11:48 first
11-24 14:53 full; 12-01 06:08 last; 12-09 00:52 new; 12-17 05:42 first
12-24 01:28 full; 12-30 18:59 last
"""
NAMES = {"new": "new", "first": "first_quarter", "full": "full", "last": "last_quarter"}
FRACTION = {"new": 0.0, "first": 0.25, "full": 0.5, "last": 0.75}


def usno_events():
    for chunk in USNO_2026.replace("\n", ";").split(";"):
        if chunk.strip():
            day, hhmm, kind = chunk.split()
            yield datetime.fromisoformat(f"2026-{day}T{hhmm}+00:00"), kind


class MoonPhaseTest(unittest.TestCase):
    def test_phase_names_match_the_layer_files(self):
        self.assertEqual(
            [f"moon_{p}.png" for p in PHASES],
            [
                "moon_new.png",
                "moon_waxing_crescent.png",
                "moon_first_quarter.png",
                "moon_waxing_gibbous.png",
                "moon_full.png",
                "moon_waning_gibbous.png",
                "moon_last_quarter.png",
                "moon_waning_crescent.png",
            ],
        )

    def test_every_2026_principal_phase_lands_in_its_bucket(self):
        events = list(usno_events())
        self.assertEqual(len(events), 50)
        for when, kind in events:
            with self.subTest(when=when, kind=kind):
                self.assertEqual(moon_phase(when), NAMES[kind])

    def test_the_mean_month_stays_within_a_day_of_the_real_phases(self):
        for when, kind in usno_events():
            expected = FRACTION[kind] * SYNODIC_MONTH_DAYS
            error = (
                moon_age_days(when) - expected + SYNODIC_MONTH_DAYS / 2
            ) % SYNODIC_MONTH_DAYS - SYNODIC_MONTH_DAYS / 2
            with self.subTest(when=when, kind=kind):
                self.assertLess(abs(error), 1.0)

    def test_between_the_principal_phases(self):
        new = datetime(2026, 10, 10, 15, 50, tzinfo=UTC)
        quarter = SYNODIC_MONTH_DAYS / 4
        expected = ["waxing_crescent", "waxing_gibbous", "waning_gibbous", "waning_crescent"]
        for i, phase in enumerate(expected):
            with self.subTest(phase=phase):
                self.assertEqual(moon_phase(new + timedelta(days=quarter * (i + 0.5))), phase)

    def test_age_wraps_within_one_month(self):
        when = datetime(2026, 10, 17, 12, tzinfo=UTC)
        age = moon_age_days(when)
        self.assertTrue(0 <= age < SYNODIC_MONTH_DAYS)
        self.assertAlmostEqual(moon_age_days(when + timedelta(days=SYNODIC_MONTH_DAYS)), age, places=6)

    def test_naive_datetimes_are_rejected(self):
        with self.assertRaises(ValueError):
            moon_phase(datetime(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
