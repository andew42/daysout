"""Table-driven feed sources: venue creation, postcode extraction, kinds."""

import sqlite3
import unittest

from daysout_scraper import db as dbmod
from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.feeds import FeedSource, find_postcode, load_enabled
from schema import SCHEMA

ICAL_FEED = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:fair-1
SUMMARY:Spring Craft Fair
DTSTART;VALUE=DATE:20260905
DTEND;VALUE=DATE:20260906
LOCATION:Corsham Town Hall\\, High Street\\, Corsham\\, SN13 0HB
END:VEVENT
BEGIN:VEVENT
UID:fair-2
SUMMARY:Fair at an unknown venue
DTSTART;VALUE=DATE:20260906
LOCATION:A Field Somewhere
END:VEVENT
END:VCALENDAR
"""

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Festival","name":"Corsham Food Festival",
 "startDate":"2026-09-12","endDate":"2026-09-13",
 "location":{"@type":"Place","name":"Corsham Town Hall",
             "address":{"@type":"PostalAddress","postalCode":"SN13 0HB"}}}
</script></head><body></body></html>"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, api=False):
        return self.pages[url]


class PostcodeTest(unittest.TestCase):

    def test_finds_postcodes_in_free_text(self):
        self.assertEqual(find_postcode("Corsham Town Hall, Corsham, SN13 0HB"), "SN13 0HB")
        self.assertEqual(find_postcode("no postcode", "later text W1J 7NT here"), "W1J 7NT")
        self.assertEqual(find_postcode("lowercase sn13 0hb"), "SN13 0HB")
        self.assertEqual(find_postcode("nothing here at all"), "")

    def test_does_not_invent_postcodes(self):
        # Bare numbers and words must not be mistaken for a postcode.
        self.assertEqual(find_postcode("Open 10 30 to 16 00, 2026"), "")


class FeedSourceTest(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        # The venue's postcode must resolve locally for a venue to be made.
        self.db.execute("INSERT INTO postcodes VALUES ('SN130HB', 51.4333, -2.1833)")
        self.db.commit()

    def test_ical_source_creates_its_venue(self):
        source = FeedSource((1, "craft-feed", "https://example.org/f.ics", "ical", "craft"))
        ok, message = run_source(
            self.db, FakeFetcher({"https://example.org/f.ics": ICAL_FEED}), source)
        self.assertTrue(ok, message)

        venue = self.db.execute(
            "SELECT name, category, postcode, lat, lon FROM destinations").fetchone()
        self.assertEqual(venue[0], "Corsham Town Hall")
        self.assertEqual(venue[1], "craft")
        self.assertEqual(venue[2], "SN13 0HB")
        self.assertAlmostEqual(venue[3], 51.4333)

        event = self.db.execute(
            "SELECT title, start_date, end_date, category FROM events").fetchone()
        self.assertEqual(event, ("Spring Craft Fair", "2026-09-05", "2026-09-05", "craft"))

    def test_event_without_a_locatable_venue_is_skipped(self):
        source = FeedSource((1, "craft-feed", "https://example.org/f.ics", "ical", "craft"))
        run_source(self.db, FakeFetcher({"https://example.org/f.ics": ICAL_FEED}), source)
        titles = [r[0] for r in self.db.execute("SELECT title FROM events")]
        self.assertEqual(titles, ["Spring Craft Fair"])

    def test_jsonld_source(self):
        source = FeedSource((2, "food-feed", "https://example.org/food", "jsonld", "food"))
        ok, message = run_source(
            self.db, FakeFetcher({"https://example.org/food": JSONLD_PAGE}), source)
        self.assertTrue(ok, message)
        event = self.db.execute("SELECT title, category FROM events").fetchone()
        self.assertEqual(event, ("Corsham Food Festival", "food"))

    def test_rerun_does_not_duplicate_venue_or_event(self):
        source = FeedSource((1, "craft-feed", "https://example.org/f.ics", "ical", "craft"))
        fetcher = FakeFetcher({"https://example.org/f.ics": ICAL_FEED})
        run_source(self.db, fetcher, source)
        run_source(self.db, fetcher, source)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_sitemap_source_crawls_newest_event_pages(self):
        """Listing pages carry no events; the individual pages do."""
        sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://fairs.example/e/old-fair</loc><lastmod>2024-05-01</lastmod></url>
  <url><loc>https://fairs.example/e/new-fair</loc><lastmod>2026-08-27</lastmod></url>
</urlset>"""
        event_page = """<html><head><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Event","name":"Autumn Craft Fair",
         "startDate":"2026-09-05","endDate":"2026-09-05",
         "location":{"@type":"Place","name":"Corsham Town Hall",
                     "address":{"@type":"PostalAddress","postalCode":"SN13 0HB"}}}
        </script></head><body></body></html>"""
        stale_page = """<html><head><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Event","name":"Fair From 2024",
         "startDate":"2024-05-04","location":{"@type":"Place","name":"Corsham Town Hall",
         "address":{"@type":"PostalAddress","postalCode":"SN13 0HB"}}}
        </script></head><body></body></html>"""

        fetcher = FakeFetcher({
            "https://fairs.example/sitemap.xml": sitemap,
            "https://fairs.example/e/new-fair": event_page,
            "https://fairs.example/e/old-fair": stale_page,
        })
        source = FeedSource(
            (3, "fairs", "https://fairs.example/sitemap.xml", "sitemap", "craft"))

        # Budget of one page: it must spend it on the current event.
        ok, message = run_source(self.db, fetcher, source, max_pages=1)
        self.assertTrue(ok, message)
        titles = [r[0] for r in self.db.execute("SELECT title FROM events")]
        self.assertEqual(titles, ["Autumn Craft Fair"])

        # And the venue came with it.
        venue = self.db.execute("SELECT name, category FROM destinations").fetchone()
        self.assertEqual(venue, ("Corsham Town Hall", "craft"))

    def test_links_to_a_destination_another_source_found(self):
        """An event listing rarely repeats the postcode of a known place."""
        # Wikidata already gave us this garden, with coordinates.
        self.db.execute(
            """INSERT INTO destinations
                 (name, category, lat, lon, source, source_id, first_seen, last_seen)
               VALUES ('RHS Garden Wisley', 'garden', 51.312, -0.474,
                       'wikidata', 'Q1319441', 'x', 'x')""")
        self.db.commit()

        page = """<html><head><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Event","name":"Flower Show",
         "startDate":"2026-09-10","endDate":"2026-09-12",
         "location":{"@type":"Place","name":"RHS Garden Wisley"}}
        </script></head><body></body></html>"""
        source = FeedSource((4, "rhs", "https://rhs.example/e", "jsonld", "garden"))
        ok, message = run_source(
            self.db, FakeFetcher({"https://rhs.example/e": page}), source)
        self.assertTrue(ok, message)

        row = self.db.execute(
            "SELECT e.title, d.name, d.source FROM events e "
            "JOIN destinations d ON d.id = e.destination_id").fetchone()
        self.assertEqual(row, ("Flower Show", "RHS Garden Wisley", "wikidata"))
        # No duplicate venue was invented for it.
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)

    def test_load_enabled_skips_disabled_rows(self):
        self.db.execute(
            "INSERT INTO sources (name, url, kind, category, enabled, added) "
            "VALUES ('on', 'https://a', 'ical', 'craft', 1, 'now')")
        self.db.execute(
            "INSERT INTO sources (name, url, kind, category, enabled, added) "
            "VALUES ('off', 'https://b', 'ical', 'craft', 0, 'now')")
        names = [s.name for s in load_enabled(self.db)]
        self.assertEqual(names, ["on"])


if __name__ == "__main__":
    unittest.main()
