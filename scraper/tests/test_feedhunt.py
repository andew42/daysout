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
  <url><loc>https://example.org/visit/wiltshire/stourhead/events</loc>
       <lastmod>2026-08-29</lastmod></url>
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
        self.assertIn("6 URL(s)", output)
        # Three individual events plus the property's own events listing.
        self.assertIn("event-shaped URLs: 4", output)
        # Two of the three carry their dates; the third does not.
        self.assertIn("carry a date in the slug: 2", output)
        # The property page itself is not about events.
        self.assertNotIn("event-shaped URLs: 6", output)

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

    def test_an_html_page_is_not_reported_as_a_feed(self):
        # A site with no feed at that path serves its 404 page. Calling
        # that a find sends someone off after nothing.
        fetcher = FakeFetcher({"https://example.org/events.ics":
                               "<!doctype html><html><body>Not found</body></html>"})
        output = capture(feedhunt.probe_conventional_feeds, fetcher,
                         "https://example.org/")
        self.assertNotIn("FOUND", output)
        self.assertIn("not a feed: HTML", output)

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


class TestFeedItems(unittest.TestCase):
    """A feed is only worth reading if its items carry the event's date."""

    RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Open Houses</title>
      <item><title>Fitzherbert Studio open weekend</title>
            <link>https://aoh.example/fitzherbert</link>
            <pubDate>Mon, 04 Aug 2026 09:00:00 +0000</pubDate>
            <description>Open 5-6 September, 11am to 5pm</description></item>
      <item><title>Beach Hut Artists</title>
            <link>https://aoh.example/beach-hut</link>
            <pubDate>Tue, 05 Aug 2026 09:00:00 +0000</pubDate></item>
    </channel></rss>"""

    def test_item_fields_are_shown_so_dates_can_be_judged(self):
        output = capture(feedhunt.describe_feed_items, self.RSS)
        self.assertIn("Fitzherbert Studio open weekend", output)
        # pubDate is when the post went up, not when the event runs — the
        # difference is the whole question, so name the date-ish fields.
        self.assertIn("date-ish fields: pubDate", output)

    def test_a_broken_feed_says_so_rather_than_crashing(self):
        output = capture(feedhunt.describe_feed_items, "not xml at all")
        self.assertIn("could not parse", output)
