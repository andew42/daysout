"""A sitemap of dated event pages, and a site that is one venue.

Shuttleworth's sitemap was added as a source and produced nothing: the
URL given was the sitemap itself, which probing treated as a web page and
found nothing in, and its event pages carry their date in the address
rather than in structured data. Both are common shapes.
"""

import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.feeds import FeedSource

from schema import SCHEMA

SITEMAP_URL = "https://venue.example.org/sitemap.xml"
SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://venue.example.org/whats-on/evening-airshow-6-september-2026</loc>
       <lastmod>2026-08-28</lastmod></url>
  <url><loc>https://venue.example.org/whats-on/race-day-19-to-20-september-2026</loc>
       <lastmod>2026-08-27</lastmod></url>
  <url><loc>https://venue.example.org/visit/tickets-and-prices</loc>
       <lastmod>2026-08-26</lastmod></url>
</urlset>"""

EVENT_PAGE = """<html><head><title>Evening Airshow | The Venue</title></head>
<body><h1>Evening Airshow</h1><p>Gates open at 4pm.</p></body></html>"""

RACE_PAGE = """<html><head><title>Race Day</title></head>
<body><h1>Race Day</h1></body></html>"""

TICKETS = "<html><body><h1>Tickets and prices</h1></body></html>"


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, api=False, render=False, fresh=False):
        self.requested.append(url)
        if url not in self.pages:
            raise OSError("404 Not Found")
        return self.pages[url]


def fetcher():
    return FakeFetcher({
        SITEMAP_URL: SITEMAP,
        "https://venue.example.org/whats-on/evening-airshow-6-september-2026": EVENT_PAGE,
        "https://venue.example.org/whats-on/race-day-19-to-20-september-2026": RACE_PAGE,
        "https://venue.example.org/visit/tickets-and-prices": TICKETS,
    })


def source(kind="auto", venue=("The Venue", "SG18 9EP")):
    # row: (id, name, url, kind, category, venue_name, venue_postcode)
    return FeedSource((1, "venue", SITEMAP_URL, kind, "airfield", *venue))


class TestDatedUrlSitemap(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                        " VALUES ('SG189EP', 52.0855, -0.3230)")
        self.db.commit()

    def events(self):
        return self.db.execute(
            "SELECT e.title, e.start_date, e.end_date, d.name, d.postcode"
            " FROM events e JOIN destinations d ON d.id = e.destination_id"
            " ORDER BY e.start_date").fetchall()

    def test_a_sitemap_url_is_recognised_and_crawled(self):
        # The whole failure: someone pastes ".../sitemap.xml" and probing
        # it as a web page finds nothing, which reads as an empty site.
        ok, message = run_source(self.db, fetcher(), source())
        self.assertTrue(ok, message)
        self.assertEqual(self.events(), [
            ("Evening Airshow", "2026-09-06", "2026-09-06", "The Venue", "SG18 9EP"),
            ("Race Day", "2026-09-19", "2026-09-20", "The Venue", "SG18 9EP"),
        ])

    def test_pages_with_no_date_in_the_url_are_not_events(self):
        run_source(self.db, fetcher(), source())
        titles = [row[0] for row in self.events()]
        self.assertNotIn("Tickets And Prices", titles)
        self.assertNotIn("Tickets and prices", titles)

    def test_the_page_heading_beats_the_slug(self):
        # "evening-airshow" would title-case to the same thing here, but a
        # heading is the site's own wording and should win.
        run_source(self.db, fetcher(), source())
        self.assertEqual(self.events()[0][0], "Evening Airshow")

    def test_without_a_venue_the_events_have_nowhere_to_go(self):
        # An attraction's own pages rarely repeat its address, so without
        # the source's venue there is nothing to geocode — and inventing
        # one would be worse than dropping the event.
        ok, _ = run_source(self.db, fetcher(), source(venue=("", "")))
        self.assertTrue(ok)
        self.assertEqual(self.events(), [])
