"""End-to-end scraper tests against fixture pages — no network involved.

Run from scraper/:  python -m unittest discover tests
"""

import sqlite3
import unittest

from daysout_scraper import db as dbmod
from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.national_trust import NationalTrust

# Mirror of the schema the Go server applies (backend/store/schema.go);
# keep in sync if the schema changes.
SCHEMA = """
CREATE TABLE destinations (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
    postcode TEXT NOT NULL DEFAULT '', lat REAL NOT NULL, lon REAL NOT NULL,
    source TEXT NOT NULL, source_id TEXT NOT NULL,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    UNIQUE (source, source_id));
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    destination_id INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '', start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    source TEXT NOT NULL, source_id TEXT NOT NULL, last_seen TEXT NOT NULL,
    UNIQUE (source, source_id));
CREATE TABLE postcodes (postcode TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL);
CREATE TABLE scrape_runs (
    id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, ok INTEGER, message TEXT NOT NULL DEFAULT '');
"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.nationaltrust.org.uk/visit/wiltshire/stourhead</loc></url>
  <url><loc>https://www.nationaltrust.org.uk/visit/wiltshire/stourhead/events/garden-walk</loc></url>
  <url><loc>https://www.nationaltrust.org.uk/some/other/page</loc></url>
</urlset>"""

PLACE_PAGE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "TouristAttraction",
 "name": "Stourhead", "description": "Landscape garden and Palladian house",
 "url": "https://www.nationaltrust.org.uk/visit/wiltshire/stourhead",
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
        "https://www.nationaltrust.org.uk/sitemap.xml": SITEMAP,
        "https://www.nationaltrust.org.uk/visit/wiltshire/stourhead": PLACE_PAGE,
        "https://www.nationaltrust.org.uk/visit/wiltshire/stourhead/events/garden-walk": EVENT_PAGE,
    })


class ScraperTest(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def test_full_run(self):
        ok, message = run_source(self.db, fixture_fetcher(), NationalTrust())
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
        run_source(self.db, fixture_fetcher(), NationalTrust())
        run_source(self.db, fixture_fetcher(), NationalTrust())
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_stale_rows_purged(self):
        run_source(self.db, fixture_fetcher(), NationalTrust())

        # Next run the event page has vanished from the sitemap.
        fetcher = fixture_fetcher()
        fetcher.pages["https://www.nationaltrust.org.uk/sitemap.xml"] = \
            SITEMAP.replace(
                "<url><loc>https://www.nationaltrust.org.uk/visit/wiltshire/stourhead/events/garden-walk</loc></url>", "")
        run_source(self.db, fetcher, NationalTrust())

        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_seed_purged_after_real_data(self):
        self.db.execute(
            "INSERT INTO destinations (name, category, lat, lon, source, source_id,"
            " first_seen, last_seen) VALUES ('Demo', 'garden', 1, 1, 'seed', 'demo',"
            " '2026-01-01', '2026-01-01')")
        run_source(self.db, fixture_fetcher(), NationalTrust())
        dbmod.purge_seed(self.db)
        remaining = self.db.execute("SELECT source FROM destinations").fetchall()
        self.assertEqual(remaining, [("national_trust",)])


if __name__ == "__main__":
    unittest.main()
