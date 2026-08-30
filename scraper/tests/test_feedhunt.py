"""Finding a route a site actually sanctions.

The point of the hunt is to answer one question honestly: is there
anything here we are allowed to read that carries event dates? The
sitemap is the interesting case — a site hands it over precisely so that
automated clients can discover what it holds — but it is only useful if
the dates are in the URLs, so that is what these tests pin.
"""

import io
import unittest
from contextlib import redirect_stdout

from daysout_scraper import feedhunt

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.org/visit/wiltshire/stourhead</loc>
       <lastmod>2026-08-01</lastmod></url>
  <url><loc>https://example.org/visit/wiltshire/stourhead/events/joust-29-to-31-aug</loc>
       <lastmod>2026-08-27</lastmod></url>
  <url><loc>https://example.org/visit/wiltshire/stourhead/events/lantern-walk-5-october</loc>
       <lastmod>2026-08-28</lastmod></url>
  <url><loc>https://example.org/visit/wiltshire/stourhead/events/undated-open-day</loc>
       <lastmod>2026-08-20</lastmod></url>
  <url><loc>https://example.org/events.ics</loc></url>
</urlset>"""


class FakeSession:
    def __init__(self, robots):
        self.robots = robots

    def get(self, url, timeout=None):
        class Response:
            ok = True
            status_code = 200
            text = self.robots
        return Response()


class FakeFetcher:
    def __init__(self, pages, robots=""):
        self.pages = pages
        self.session = FakeSession(robots)
        self.requested = []

    def get(self, url, api=False, render=False):
        self.requested.append(url)
        if url not in self.pages:
            raise OSError("404 Not Found")
        return self.pages[url]

    def _allowed(self, url):
        return True


def capture(function, *args):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        function(*args)
    return buffer.getvalue()


class TestSlugDates(unittest.TestCase):
    """Whether a URL alone carries the field an events view needs."""

    def test_dates_in_slugs_are_recognised(self):
        for slug in ("joust-29-to-31-aug", "lantern-walk-5-october",
                     "fair-2026-09-12", "sept-14-open-day"):
            self.assertTrue(feedhunt.SLUG_DATE_RE.search(slug), slug)

    def test_a_slug_without_a_date_is_not_claimed_as_dated(self):
        for slug in ("undated-open-day", "guided-tours", "family-trail"):
            self.assertIsNone(feedhunt.SLUG_DATE_RE.search(slug), slug)


class TestSitemapReport(unittest.TestCase):

    def report(self):
        fetcher = FakeFetcher({"https://example.org/sitemap.xml": SITEMAP})
        return capture(feedhunt.sitemap_report, fetcher,
                       ["https://example.org/sitemap.xml"])

    def test_counts_what_a_url_list_would_give_us(self):
        output = self.report()
        self.assertIn("5 URL(s)", output)
        self.assertIn("event-shaped URLs: 3", output)
        # Two of the three carry their dates; the third does not.
        self.assertIn("carry a date in the slug: 2", output)
        # The property page and the .ics file are not individual events.
        self.assertNotIn("event-shaped URLs: 5", output)

    def test_feed_shaped_urls_are_surfaced(self):
        self.assertIn("https://example.org/events.ics", self.report())


class TestRobotsReport(unittest.TestCase):

    def test_declared_sitemaps_are_followed_up(self):
        robots = ("User-agent: *\nDisallow: /search\n"
                  "Sitemap: https://example.org/sitemap-events.xml\n")
        fetcher = FakeFetcher({}, robots=robots)
        output = capture(feedhunt.robots_report, fetcher, "https://example.org/")
        self.assertIn("sitemap-events.xml", output)


class TestFeedProbes(unittest.TestCase):

    def test_a_real_calendar_is_reported_as_found(self):
        ical = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        fetcher = FakeFetcher({"https://example.org/events.ics": ical})
        output = capture(feedhunt.probe_conventional_feeds, fetcher,
                         "https://example.org/")
        self.assertIn("FOUND: iCal", output)

    def test_a_challenge_is_not_mistaken_for_a_feed(self):
        challenge = "<html><head><title>Radware Page</title></head><body></body></html>"
        fetcher = FakeFetcher({"https://example.org/feed": challenge})
        output = capture(feedhunt.probe_conventional_feeds, fetcher,
                         "https://example.org/")
        self.assertIn("bot-protection challenge", output)
        self.assertNotIn("FOUND", output)
