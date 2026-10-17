"""The number on the sticky note: GitHub contributions today.

`activity_number` is the one place that decides what the note shows; change it
to show another metric.

GitHub keeps contributions in day buckets and the GraphQL API answers in whole
days: `contributionsCollection(from:, to:)` counts every day the range touches,
whatever the time of day. The day labels follow the offset written in `from`
and `to`, so the range is sent in Warsaw local time and the count is read from
the day labelled with today's Warsaw date.

The calendar counts are what the public profile graph shows: public
contributions, plus private ones when "Include private contributions on my
profile" is on. That is why the Action's own GITHUB_TOKEN is enough.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

GRAPHQL_URL = "https://api.github.com/graphql"
API_TIMEOUT_S = 15

CONTRIBUTIONS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""

PostGraphQL = Callable[[str, dict, str], dict]


def post_graphql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "shironex-living-readme",
        },
    )
    with urllib.request.urlopen(request, timeout=API_TIMEOUT_S) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError("; ".join(e.get("message", "unknown error") for e in payload["errors"]))
    return payload["data"]


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Start of `day` and start of the next day in `tz` (23 or 25 hours apart on DST switches)."""
    return datetime.combine(day, time(), tz), datetime.combine(day + timedelta(days=1), time(), tz)


def contributions_on(day: date, tz: ZoneInfo, login: str, token: str, post: PostGraphQL = post_graphql) -> int:
    start, end = local_day_bounds(day, tz)
    last_second = end - timedelta(seconds=1)  # wall-clock arithmetic: 23:59:59 local, right offset
    variables = {"login": login, "from": start.isoformat(), "to": last_second.isoformat()}
    data = post(CONTRIBUTIONS_QUERY, variables, token)
    if not data.get("user"):
        raise RuntimeError(f"no GitHub user {login!r}")
    weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    counts = {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}
    return int(counts.get(day.isoformat(), 0))


def activity_number(now: datetime, tz: ZoneInfo, login: str, token: str, post: PostGraphQL = post_graphql) -> int:
    """What the sticky note shows. Today: contributions on the current Warsaw date."""
    return contributions_on(now.astimezone(tz).date(), tz, login, token, post)
