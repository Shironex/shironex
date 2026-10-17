import contextlib
import io
import unittest
import urllib.error

from blogfeed import latest_title, parse_latest_title

# The shape of https://shirone.blog/rss.xml: items in slug order, not by date, and two posts on one day.
SHIRONE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>shirone.blog</title>
<item><title>Building an Activity Feed Without Opening a Single Port</title><pubDate>Mon, 16 Mar 2026 12:00:00 GMT</pubDate></item>
<item><title>Green Is Not Evidence: How I Keep AI-Written Code Honest</title><pubDate>Wed, 23 Sep 2026 00:00:00 GMT</pubDate></item>
<item><title>Hello, World</title><pubDate>Tue, 10 Mar 2026 00:00:00 GMT</pubDate></item>
<item><title>Swapping the Engine Mid-Flight: Shiranami 2 and a 186k-Line Merge</title><pubDate>Wed, 23 Sep 2026 00:00:00 GMT</pubDate></item>
<item><title>Taming 12 Terminals: How I Stopped the UI from Freezing</title><pubDate>Mon, 16 Mar 2026 14:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>blog</title>
<entry><title>Older</title><updated>2026-01-01T10:00:00Z</updated></entry>
<entry><title type="html">Newer &amp;amp; &lt;b&gt;bold&lt;/b&gt;</title><updated>2026-02-01T10:00:00+01:00</updated></entry>
</feed>"""


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


class ParseTest(unittest.TestCase):
    def test_newest_by_date_not_feed_order_and_ties_go_to_the_last_listed(self):
        self.assertEqual(
            parse_latest_title(SHIRONE_RSS), "Swapping the Engine Mid-Flight: Shiranami 2 and a 186k-Line Merge"
        )

    def test_atom_with_escaped_markup(self):
        self.assertEqual(parse_latest_title(ATOM), "Newer & bold")

    def test_cdata_and_whitespace(self):
        rss = b"<rss><channel><item><title><![CDATA[  Tom &amp; Jerry\n  ]]></title></item></channel></rss>"
        self.assertEqual(parse_latest_title(rss), "Tom & Jerry")

    def test_undated_items_rank_below_dated_ones(self):
        rss = b"""<rss><channel>
        <item><title>Dated</title><pubDate>Wed, 23 Sep 2026 00:00:00 GMT</pubDate></item>
        <item><title>Undated</title></item>
        <item><title>Bad date</title><pubDate>someday</pubDate></item>
        </channel></rss>"""
        self.assertEqual(parse_latest_title(rss), "Dated")

    def test_no_entries(self):
        self.assertIsNone(parse_latest_title(b"<rss><channel><title>x</title></channel></rss>"))


class FallbackTest(unittest.TestCase):
    def test_uses_the_feed_when_it_works(self):
        self.assertEqual(
            latest_title("u", "old", fetch=lambda url: SHIRONE_RSS),
            ("Swapping the Engine Mid-Flight: Shiranami 2 and a 186k-Line Merge", "feed"),
        )

    def test_network_errors_fall_back(self):
        def down(url):
            raise urllib.error.URLError("blog is down")

        self.assertEqual(quiet(latest_title, "u", "Last known", fetch=down), ("Last known", "fallback"))

    def test_timeouts_fall_back(self):
        def slow(url):
            raise TimeoutError("timed out")

        self.assertEqual(quiet(latest_title, "u", "Last known", fetch=slow), ("Last known", "fallback"))

    def test_broken_xml_falls_back(self):
        self.assertEqual(
            quiet(latest_title, "u", "Last known", fetch=lambda url: b"<html>502 Bad Gateway"),
            ("Last known", "fallback"),
        )

    def test_empty_feed_falls_back(self):
        empty = b"<rss><channel></channel></rss>"
        self.assertEqual(quiet(latest_title, "u", "Last known", fetch=lambda url: empty), ("Last known", "fallback"))


if __name__ == "__main__":
    unittest.main()
