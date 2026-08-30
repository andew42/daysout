"""Reading The Events Calendar's REST API.

A large share of UK venue and festival sites run this WordPress plugin,
and it publishes exactly what a planner needs — a title, real dates, and
a venue with a postcode — from a documented endpoint. No rendering, no
guessing at markup, and nothing that depends on a site's current theme.
"""

import json
import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.feeds import FeedSource

from schema import SCHEMA

API = "https://venue.example.org/wp-json/tribe/events/v1/events"


def api_event(identifier, title, start, end, venue="Corsham Town Hall",
              zip_code="SN13 0EZ"):
    return {
        "id": identifier,
        "title": {"rendered": title},
        "description": "<p>A <strong>good</strong> day out.</p>",
        "url": f"https://venue.example.org/event/{identifier}",
        "start_date": f"{start} 10:00:00",
        "end_date": f"{end} 17:00:00",
        "venue": {"venue": venue, "zip": zip_code},
    }


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, api=False, render=False):
        self.requested.append(url)
        for known, body in self.pages.items():
            if url.startswith(known):
                return body
        raise OSError("404 Not Found")


def source(kind="wpevents"):
    # row: (id, name, url, kind, category)
    return FeedSource((1, "venue", "https://venue.example.org/", kind, "craft"))


class TestEventsApi(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                        " VALUES ('SN130EZ', 51.4358, -2.1876)")
        self.db.commit()

    def fetcher(self, *events, **pages):
        body = json.dumps({"events": list(events), "total": len(events)})
        return FakeFetcher({API: body, **pages})

    def test_events_reach_the_database_with_their_venue(self):
        fetcher = self.fetcher(
            api_event(1, "Autumn Craft Fair", "2026-09-12", "2026-09-13"),
            api_event(2, "Winter Makers Market", "2026-11-28", "2026-11-29"))

        ok, message = run_source(self.db, fetcher, source())
        self.assertTrue(ok, message)

        rows = self.db.execute(
            "SELECT e.title, e.start_date, e.end_date, e.category,"
            " d.name, d.postcode, d.lat FROM events e"
            " JOIN destinations d ON d.id = e.destination_id"
            " ORDER BY e.start_date").fetchall()
        self.assertEqual(rows, [
            ("Autumn Craft Fair", "2026-09-12", "2026-09-13", "craft",
             "Corsham Town Hall", "SN13 0EZ", 51.4358),
            ("Winter Makers Market", "2026-11-28", "2026-11-29", "craft",
             "Corsham Town Hall", "SN13 0EZ", 51.4358),
        ])

    def test_html_in_titles_and_descriptions_is_stripped(self):
        fetcher = self.fetcher(api_event(1, "Fair &amp; Market", "2026-09-12",
                                         "2026-09-12"))
        run_source(self.db, fetcher, source())
        title, description = self.db.execute(
            "SELECT title, description FROM events").fetchone()
        self.assertEqual(title, "Fair & Market")
        self.assertEqual(description, "A good day out.")

    def test_a_record_without_a_usable_date_is_skipped(self):
        fetcher = self.fetcher(
            {"id": 9, "title": "Undated thing", "venue": {}},
            api_event(1, "Real event", "2026-09-12", "2026-09-12"))
        run_source(self.db, fetcher, source())
        titles = [r[0] for r in self.db.execute("SELECT title FROM events")]
        self.assertEqual(titles, ["Real event"])

    def test_paging_follows_the_api_rather_than_guessing(self):
        page_two = "https://venue.example.org/wp-json/tribe/events/v1/events?page=2"
        first = json.dumps({
            "events": [api_event(1, "First", "2026-09-12", "2026-09-12")],
            "next_rest_url": page_two})
        second = json.dumps({
            "events": [api_event(2, "Second", "2026-09-13", "2026-09-13")]})
        # The detection call and the first page share a prefix, so order
        # the map so the paged URL wins for its own request.
        fetcher = FakeFetcher({page_two: second, API: first})

        run_source(self.db, fetcher, source())
        titles = sorted(r[0] for r in self.db.execute("SELECT title FROM events"))
        self.assertEqual(titles, ["First", "Second"])

    def test_auto_detection_prefers_the_api(self):
        fetcher = self.fetcher(api_event(1, "Detected", "2026-09-12", "2026-09-12"))
        ok, message = run_source(self.db, fetcher, source(kind="auto"))
        self.assertTrue(ok, message)
        titles = [r[0] for r in self.db.execute("SELECT title FROM events")]
        self.assertEqual(titles, ["Detected"])

    def test_a_site_without_the_api_is_not_claimed_to_have_one(self):
        fetcher = FakeFetcher({"https://venue.example.org/":
                               "<html><body>no api here</body></html>"})
        self.assertEqual(source()._events_api_url(fetcher), "")
