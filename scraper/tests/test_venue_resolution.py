"""Placing an event at a venue, against the two shapes that lost events.

Both cases below came from real deploy logs, not imagination: English
Heritage published a venue whose postcode was inside the address line and
under a field name the pipeline never read, and RHS published a postcode
with no venue name at all. Each silently dropped every event it affected
while the run still reported success.
"""

import sqlite3
import unittest

from daysout_scraper import db as dbmod
from daysout_scraper import pipeline
from tests.schema import SCHEMA


class FakeSource:
    name = "test-source"

    def __init__(self, items):
        self.items = items

    def scrape(self, fetcher, max_pages=0):
        return iter(self.items)

    def link_event(self, event):
        return None


def open_db():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO postcodes (postcode, lat, lon) VALUES (?, ?, ?)",
                   [("M25PD", 53.4784, -2.2445), ("WR136NW", 52.1050, -2.3300)])
    db.commit()
    return db


class TestVenueFields(unittest.TestCase):
    """_venue reads both spellings and digs the postcode out of prose."""

    def test_code_source_shape(self):
        name, postcode, label = pipeline._venue({
            "title": "Members' Event: Manchester Dynasties",
            "location_name": "Manchester Central Library, St Peters Square, "
                             "Manchester M2 5PD",
            "location_postcode": "",
        })
        self.assertEqual(name, "Manchester Central Library")
        self.assertEqual(postcode, "M2 5PD")
        self.assertEqual(label, "Manchester Central Library")

    def test_feed_source_shape(self):
        name, postcode, _ = pipeline._venue({
            "title": "Whatever",
            "location_name": "Bolsover Castle",
            "venue_full": "Bolsover Castle, Castle Street, Bolsover, S44 6PR",
            "venue_postcode": "S44 6PR",
        })
        self.assertEqual(name, "Bolsover Castle")
        self.assertEqual(postcode, "S44 6PR")

    def test_postcode_without_a_venue_name_falls_back_to_the_title(self):
        name, postcode, label = pipeline._venue({
            "title": "RHS Malvern Spring Festival",
            "location_name": "",
            "location_postcode": "WR13 6NW",
        })
        self.assertEqual(name, "")
        self.assertEqual(postcode, "WR13 6NW")
        self.assertEqual(label, "RHS Malvern Spring Festival")

    def test_no_postcode_means_no_invented_venue(self):
        # Without somewhere to put it, a title is not a venue.
        _, _, label = pipeline._venue({"title": "A talk", "location_name": ""})
        self.assertEqual(label, "")


class TestPlacement(unittest.TestCase):
    """End to end: these events reach the database with coordinates."""

    def run_events(self, events):
        db = open_db()
        ok, message = pipeline.run_source(
            db, None, FakeSource([("event", e) for e in events]))
        rows = db.execute(
            "SELECT e.title, d.name, d.postcode, d.lat FROM events e "
            "JOIN destinations d ON d.id = e.destination_id").fetchall()
        return ok, message, rows

    def test_postcode_in_the_address_line_places_the_event(self):
        ok, _, rows = self.run_events([{
            "source_id": "dynasties",
            "title": "Manchester Dynasties",
            "start_date": "2026-09-05",
            "end_date": "2026-09-05",
            "location_name": "Manchester Central Library, St Peters Square, "
                             "Manchester M2 5PD",
        }])
        self.assertTrue(ok)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "Manchester Central Library")
        self.assertEqual(rows[0][2], "M2 5PD")

    def test_named_venue_missing_places_the_event_at_its_postcode(self):
        ok, _, rows = self.run_events([{
            "source_id": "malvern",
            "title": "RHS Malvern Spring Festival",
            "start_date": "2026-09-05",
            "end_date": "2026-09-07",
            "location_name": "",
            "location_postcode": "WR13 6NW",
        }])
        self.assertTrue(ok)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "RHS Malvern Spring Festival")
        self.assertAlmostEqual(rows[0][3], 52.1050, places=3)

    def test_an_event_with_nowhere_to_go_is_still_not_invented(self):
        ok, _, rows = self.run_events([{
            "source_id": "nowhere",
            "title": "A talk somewhere",
            "start_date": "2026-09-05",
            "end_date": "2026-09-05",
            "location_name": "",
        }])
        self.assertTrue(ok)
        self.assertEqual(rows, [])


class TestVenueLink(unittest.TestCase):
    """A venue created from an event needs something to link to.

    Its map pin showed the name, the drive time and nothing else, because
    ensure_venue never recorded a URL.
    """

    def setUp(self):
        self.db = open_db()

    def venue_url(self):
        return self.db.execute("SELECT url FROM destinations").fetchone()[0]

    def run_with(self, url):
        pipeline.run_source(self.db, None, FakeSource([("event", {
            "source_id": "e1",
            "title": "Garden tour",
            "start_date": "2026-09-05",
            "end_date": "2026-09-05",
            "url": url,
            "location_name": "",
            "location_postcode": "M2 5PD",
        })]))

    def test_the_venue_links_to_the_site_not_the_event_page(self):
        # A venue outlives the event that introduced it, so linking it at
        # one event's page would rot.
        self.run_with("https://www.stonor.com/whats-on/garden-tour-5-sept/")
        self.assertEqual(self.venue_url(), "https://www.stonor.com/")

    def test_an_event_with_no_url_leaves_the_venue_without_one(self):
        self.run_with("")
        self.assertEqual(self.venue_url(), "")

    def test_a_venue_created_before_this_gains_a_link(self):
        self.run_with("")
        self.assertEqual(self.venue_url(), "")
        self.run_with("https://www.stonor.com/whats-on/garden-tour-5-sept/")
        self.assertEqual(self.venue_url(), "https://www.stonor.com/")


class TestExistingVenueGainsALink(unittest.TestCase):
    """The case the tests above missed, and the site showed.

    Those events name no venue, so they fall back into ensure_venue every
    run and the link fix appeared to work. A named venue is found by the
    resolver instead, ensure_venue is never reached, and the pin stayed
    bare — which is every venue we already hold, i.e. all of them after
    the first scrape.
    """

    def setUp(self):
        self.db = open_db()

    def event(self, url):
        return ("event", {
            "source_id": "e1",
            "title": "Garden tour",
            "start_date": "2026-09-05",
            "end_date": "2026-09-05",
            "url": url,
            "location_name": "Stonor Park",
            "location_postcode": "M2 5PD",
        })

    def venue_url(self):
        return self.db.execute(
            "SELECT url FROM destinations WHERE name = 'Stonor Park'").fetchone()[0]

    def test_a_named_venue_we_already_hold_gains_a_link(self):
        # First run creates it with no link, as earlier scrapes did.
        pipeline.run_source(self.db, None, FakeSource([self.event("")]))
        self.assertEqual(self.venue_url(), "")

        # Second run resolves the venue by name, so ensure_venue is never
        # called; the link has to be filled in on that path too.
        pipeline.run_source(
            self.db, None,
            FakeSource([self.event("https://www.stonor.com/whats-on/tour/")]))
        self.assertEqual(self.venue_url(), "https://www.stonor.com/")

    def test_a_link_the_source_published_is_not_overwritten(self):
        pipeline.run_source(
            self.db, None,
            FakeSource([self.event("https://www.stonor.com/whats-on/tour/")]))
        self.db.execute(
            "UPDATE destinations SET url = 'https://stonor.example/official'"
            " WHERE name = 'Stonor Park'")
        pipeline.run_source(
            self.db, None,
            FakeSource([self.event("https://www.stonor.com/whats-on/other/")]))
        self.assertEqual(self.venue_url(), "https://stonor.example/official")


class TestRunMessage(unittest.TestCase):
    """What the Sources page shows for a source that publishes only events.

    "0 places, 5/5 events linked" reads as a failure — it led off with a
    zero for something this kind of source never has.
    """

    def setUp(self):
        self.db = open_db()

    def test_a_feed_source_reports_its_venues_not_zero_places(self):
        ok, message = pipeline.run_source(self.db, None, FakeSource([
            ("event", {
                "source_id": f"e{n}",
                "title": f"Event {n}",
                "start_date": "2026-09-05",
                "end_date": "2026-09-05",
                "url": "https://www.stonor.com/whats-on/tour/",
                "location_name": "Stonor Park",
                "location_postcode": "M2 5PD",
            }) for n in range(5)]))
        self.assertTrue(ok)
        self.assertEqual(message, "5/5 events linked at 1 venue")
        self.assertNotIn("0 places", message)
