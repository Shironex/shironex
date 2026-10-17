import unittest
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from activity import CONTRIBUTIONS_QUERY, activity_number, contributions_on, local_day_bounds

WARSAW = ZoneInfo("Europe/Warsaw")


def calendar(days: dict[str, int]) -> dict:
    return {
        "user": {
            "contributionsCollection": {
                "contributionCalendar": {
                    "weeks": [{"contributionDays": [{"date": d, "contributionCount": c} for d, c in days.items()]}]
                }
            }
        }
    }


class FakeApi:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, query, variables, token):
        self.calls.append((query, variables, token))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class DayBoundsTest(unittest.TestCase):
    def test_ordinary_day_is_24_hours(self):
        start, end = local_day_bounds(date(2026, 10, 17), WARSAW)
        self.assertEqual(end.astimezone(UTC) - start.astimezone(UTC), timedelta(hours=24))

    def test_dst_days_are_23_and_25_hours(self):
        for day, hours in ((date(2026, 3, 29), 23), (date(2026, 10, 25), 25)):
            start, end = local_day_bounds(day, WARSAW)
            with self.subTest(day=day):
                self.assertEqual(end.astimezone(UTC) - start.astimezone(UTC), timedelta(hours=hours))


class ContributionsTest(unittest.TestCase):
    def test_sends_the_warsaw_day_with_its_offset_and_reads_that_day(self):
        api = FakeApi(calendar({"2026-10-16": 0, "2026-10-17": 9}))
        self.assertEqual(contributions_on(date(2026, 10, 17), WARSAW, "Shironex", "tok", post=api), 9)
        query, variables, token = api.calls[0]
        self.assertEqual(query, CONTRIBUTIONS_QUERY)
        self.assertEqual(token, "tok")
        self.assertEqual(
            variables, {"login": "Shironex", "from": "2026-10-17T00:00:00+02:00", "to": "2026-10-17T23:59:59+02:00"}
        )

    def test_offsets_on_the_dst_switch_days(self):
        api = FakeApi(calendar({}))
        contributions_on(date(2026, 10, 25), WARSAW, "Shironex", "tok", post=api)
        contributions_on(date(2026, 3, 29), WARSAW, "Shironex", "tok", post=api)
        self.assertEqual(
            [(v["from"], v["to"]) for _, v, _ in api.calls],
            [
                ("2026-10-25T00:00:00+02:00", "2026-10-25T23:59:59+01:00"),
                ("2026-03-29T00:00:00+01:00", "2026-03-29T23:59:59+02:00"),
            ],
        )

    def test_a_day_missing_from_the_calendar_counts_as_zero(self):
        api = FakeApi(calendar({"2026-10-16": 4}))
        self.assertEqual(contributions_on(date(2026, 10, 17), WARSAW, "Shironex", "tok", post=api), 0)

    def test_unknown_user_is_an_error(self):
        with self.assertRaises(RuntimeError):
            contributions_on(date(2026, 10, 17), WARSAW, "nobody", "tok", post=FakeApi({"user": None}))

    def test_activity_number_uses_the_warsaw_date_not_utc(self):
        # 23:30 UTC on the 16th is already 01:30 on the 17th in Warsaw.
        api = FakeApi(calendar({"2026-10-16": 5, "2026-10-17": 2}))
        now = datetime(2026, 10, 16, 23, 30, tzinfo=UTC)
        self.assertEqual(activity_number(now, WARSAW, "Shironex", "tok", post=api), 2)


if __name__ == "__main__":
    unittest.main()
