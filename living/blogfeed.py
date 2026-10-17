"""The latest post title from an RSS 2.0 or Atom feed.

The shirone.blog feed is not sorted by date, so the newest entry is picked by
its date. Entries with the same date go to the one listed last; entries
without a readable date rank below dated ones.
"""

from __future__ import annotations

import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

FEED_TIMEOUT_S = 10
MAX_FEED_BYTES = 2_000_000
ATOM = "{http://www.w3.org/2005/Atom}"
_TAG = re.compile(r"<[^>]+>")
_OLDEST = datetime.min.replace(tzinfo=UTC)


def _parse_date(text: str | None) -> datetime | None:
    if not text or not text.strip():
        return None
    text = text.strip()
    try:
        parsed = parsedate_to_datetime(text)  # RSS: RFC 822 dates
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))  # Atom: RFC 3339
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _clean_title(text: str | None) -> str:
    return " ".join(_TAG.sub("", html.unescape(text or "")).split())


def parse_latest_title(xml_bytes: bytes) -> str | None:
    """The title of the newest entry, or None when the feed has no titled entries."""
    root = ET.fromstring(xml_bytes)
    entries = []
    for item in root.iter("item"):
        entries.append((item.findtext("title"), item.findtext("pubDate")))
    for entry in root.iter(f"{ATOM}entry"):
        date = entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published")
        entries.append((entry.findtext(f"{ATOM}title"), date))
    ranked = [
        (_parse_date(date) or _OLDEST, position, _clean_title(title))
        for position, (title, date) in enumerate(entries)
        if _clean_title(title)
    ]
    return max(ranked)[2] if ranked else None


def fetch_feed(url: str, timeout: float = FEED_TIMEOUT_S) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "shironex-living-readme"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError(f"feed is larger than {MAX_FEED_BYTES} bytes")
    return data


def latest_title(url: str, fallback: str, fetch: Callable[[str], bytes] | None = None) -> tuple[str, str]:
    """(title, source): the newest title from the feed, or `fallback` when anything goes wrong."""
    try:
        title = parse_latest_title((fetch or fetch_feed)(url))
    except Exception as exc:  # any failure falls back: the blog must never break the build
        print(f"warning: could not read the feed {url}: {exc!r}", file=sys.stderr)
        return fallback, "fallback"
    if not title:
        print(f"warning: the feed {url} has no titled entries", file=sys.stderr)
        return fallback, "fallback"
    return title, "feed"
