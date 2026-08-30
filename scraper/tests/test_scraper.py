"""End-to-end tests of the sitemap+JSON-LD engine, against fixture pages.

These exercise the engine itself — crawl order, upserts, purging, bounded
runs — so they use a fixture source rather than a real one. National Trust
stood in here once, and changing what that source chooses to crawl broke a
dozen tests that were never about National Trust.

Run from scraper/:  python -m unittest discover tests
"""

import re
import sqlite3
import unittest

from daysout_scraper import db as dbmod
from daysout_scraper.pipeline import run_source
from daysout_scraper.sitemap_source import SitemapJsonLdSource, sitemap_urls

from schema import SCHEMA  # the Go server's schema, read from source

class FixtureSource(SitemapJsonLdSource):
    """The classic shape: a page per property, and event pages beneath it."""

    name = "fixture"
    sitemaps = ("https://houses.example.org/sitemap.xml",)

    PLACE_RE = re.compile(r"^https://houses\.example\.org/visit/[^/]+/([^/]+)/?$")
    EVENT_RE = re.compile(r"^https://houses\.example\.org/visit/[^/]+/([^/]+)/events/[^/]+/?$")

    def classify(self, url):
        if self.PLACE_RE.match(url):
            return "place"
        if self.EVENT_RE.match(url):
            return "event"
        return None

    def category(self, place):
        text = place["name"] + " " + place["description"]
        return "garden" if "garden" in text.lower() else "historic-house"

    def link_event(self, event):
        match = self.EVENT_RE.match(event.get("page_url", ""))
        return match.group(1) if match else None


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://houses.example.org/visit/wiltshire/stourhead</loc></url>
  <url><loc>https://houses.example.org/visit/wiltshire/stourhead/events/garden-walk</loc></url>
  <url><loc>https://houses.example.org/some/other/page</loc></url>
</urlset>"""

PLACE_PAGE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "TouristAttraction",
 "name": "Stourhead", "description": "Landscape garden and Palladian house",
 "url": "https://houses.example.org/visit/wiltshire/stourhead",
 "geo": {"@type": "GeoCoordinates", "latitude": 51.1054, "longitude": -2.3187},
 "address": {"@type": "PostalAddress", "postalCode": "BA12 6QF"}}
</script></head><body></body></html>"""

EVENT_PAGE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Event",
 "name": "Guided garden walk", "startDate": "2026-09-05T10:30:00+01:00",
 "endDate": "2026-09-05T12:00:00+01:00",
 "location": {"@type": "Place", "name": "Stourhead"}}
</script></head><body></body></html>"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url):
        return self.pages[url.rstrip("/")]


def fixture_fetcher():
    return FakeFetcher({
        "https://houses.example.org/sitemap.xml": SITEMAP,
        "https://houses.example.org/visit/wiltshire/stourhead": PLACE_PAGE,
        "https://houses.example.org/visit/wiltshire/stourhead/events/garden-walk": EVENT_PAGE,
    })


class ScraperTest(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def test_full_run(self):
        ok, message = run_source(self.db, fixture_fetcher(), FixtureSource())
        self.assertTrue(ok, message)

        row = self.db.execute(
            "SELECT name, category, postcode, lat, lon, source_id "
            "FROM destinations").fetchone()
        self.assertEqual(row, ("Stourhead", "garden", "BA12 6QF",
                               51.1054, -2.3187, "stourhead"))

        event = self.db.execute(
            "SELECT e.title, e.start_date, e.end_date, d.name "
            "FROM events e JOIN destinations d ON d.id = e.destination_id").fetchone()
        self.assertEqual(event, ("Guided garden walk", "2026-09-05",
                                 "2026-09-05", "Stourhead"))

        run = self.db.execute("SELECT ok FROM scrape_runs").fetchone()
        self.assertEqual(run[0], 1)

    def test_rerun_updates_not_duplicates(self):
        run_source(self.db, fixture_fetcher(), FixtureSource())
        run_source(self.db, fixture_fetcher(), FixtureSource())
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_stale_rows_purged(self):
        run_source(self.db, fixture_fetcher(), FixtureSource())

        # Next run the event page has vanished from the sitemap.
        fetcher = fixture_fetcher()
        fetcher.pages["https://houses.example.org/sitemap.xml"] = \
            SITEMAP.replace(
                "<url><loc>https://houses.example.org/visit/wiltshire/stourhead/events/garden-walk</loc></url>", "")
        run_source(self.db, fetcher, FixtureSource())

        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_unreachable_sitemap_purges_nothing(self):
        run_source(self.db, fixture_fetcher(), FixtureSource())

        class DeadFetcher:
            def get(self, url):
                raise OSError("network unreachable")

        ok, _ = run_source(self.db, DeadFetcher(), FixtureSource())
        self.assertFalse(ok)
        # Everything from the good run survives the failed one.
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_bounded_run_visits_newest_pages(self):
        """A stale page first in the sitemap must not crowd out a current one."""
        sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://houses.example.org/visit/wiltshire/stourhead/events/old-fete</loc>
       <lastmod>2024-05-01</lastmod></url>
  <url><loc>https://houses.example.org/visit/wiltshire/stourhead/events/garden-walk</loc>
       <lastmod>2026-08-27</lastmod></url>
  <url><loc>https://houses.example.org/visit/wiltshire/stourhead</loc>
       <lastmod>2026-08-27</lastmod></url>
</urlset>"""
        stale_page = """<html><head><script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "WebPage", "name": "Old fete"}
        </script></head><body></body></html>"""

        fetcher = FakeFetcher({
            "https://houses.example.org/sitemap.xml": sitemap,
            "https://houses.example.org/visit/wiltshire/stourhead": PLACE_PAGE,
            "https://houses.example.org/visit/wiltshire/stourhead/events/garden-walk": EVENT_PAGE,
            "https://houses.example.org/visit/wiltshire/stourhead/events/old-fete": stale_page,
        })

        # Only one event page may be fetched: it must be the current one.
        ok, message = run_source(self.db, fetcher, FixtureSource(), max_pages=1)
        self.assertTrue(ok, message)
        titles = [r[0] for r in self.db.execute("SELECT title FROM events")]
        self.assertEqual(titles, ["Guided garden walk"])

    def test_sitemap_lastmod_orders_newest_first(self):
        sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://houses.example.org/visit/a/stale</loc>
       <lastmod>2024-01-02</lastmod></url>
  <url><loc>https://houses.example.org/visit/b/current</loc>
       <lastmod>2026-08-01</lastmod></url>
  <url><loc>https://houses.example.org/visit/c/undated</loc></url>
</urlset>"""

        class F:
            def get(self, url, api=False):
                return sitemap

        pairs = list(sitemap_urls(F(), "s", with_lastmod=True))
        self.assertEqual(len(pairs), 3)
        self.assertEqual(dict(pairs)["https://houses.example.org/visit/b/current"],
                         "2026-08-01")
        self.assertEqual(dict(pairs)["https://houses.example.org/visit/c/undated"], "")

        # The inspector keys on (lastmod, url) so a reverse sort is
        # newest-first; keyed the other way it would sort by URL instead.
        candidates = sorted(((mod, url) for url, mod in pairs), reverse=True)
        self.assertEqual(candidates[0][1],
                         "https://houses.example.org/visit/b/current")

    def test_seed_purged_after_real_data(self):
        self.db.execute(
            "INSERT INTO destinations (name, category, lat, lon, source, source_id,"
            " first_seen, last_seen) VALUES ('Demo', 'garden', 1, 1, 'seed', 'demo',"
            " '2026-01-01', '2026-01-01')")
        run_source(self.db, fixture_fetcher(), FixtureSource())
        dbmod.purge_seed(self.db)
        remaining = self.db.execute("SELECT source FROM destinations").fetchall()
        self.assertEqual(remaining, [("fixture",)])


if __name__ == "__main__":
    unittest.main()
