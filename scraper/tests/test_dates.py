"""Dates are compared as text, so the wrong shape is an invisible event.

Stonor's five events were in the database, linked to a venue, reported
as "5/5 events linked" — and absent from the site, because they were
stored as "02/05/2026" and '0' sorts before '2', so every one of them
failed `end_date >= '2026-08-30'` before any filter ran.
"""

import sqlite3
import unittest

from daysout_scraper import dates
from daysout_scraper import db as dbmod
from daysout_scraper.sources.feeds import FeedSource

from schema import SCHEMA


class TestToIso(unittest.TestCase):

    def test_the_shape_stonors_api_actually_returns(self):
        self.assertEqual(dates.to_iso("02/05/2026 10:00:00"), "2026-05-02")
        self.assertEqual(dates.to_iso("28/08/2026 00:00:00"), "2026-08-28")

    def test_iso_passes_through_with_or_without_a_time(self):
        self.assertEqual(dates.to_iso("2026-05-02"), "2026-05-02")
        self.assertEqual(dates.to_iso("2026-05-02 10:00:00"), "2026-05-02")
        self.assertEqual(dates.to_iso("2026-05-02T10:00:00+01:00"), "2026-05-02")

    def test_slashed_dates_are_read_day_first(self):
        # A UK-only tool. Month-first would put this on 5 February.
        self.assertEqual(dates.to_iso("02/05/2026"), "2026-05-02")
        self.assertEqual(dates.to_iso("2/5/26"), "2026-05-02")

    def test_nonsense_is_empty_rather_than_approximate(self):
        # A wrong date puts a real event on a day nobody expects it.
        for value in ("", None, "not a date", "31/02/2026", "2026-13-01",
                      "soon", "2026"):
            self.assertEqual(dates.to_iso(value), "", repr(value))


class TestTheStoreRefusesABadDate(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.db.execute(
            "INSERT INTO destinations (id, name, category, description, url,"
            " postcode, lat, lon, source, source_id, first_seen, last_seen)"
            " VALUES (1, 'Stonor Park', 'historic-house', '', '', 'RG9 6HF',"
            " 51.59, -0.92, 's', 'stonor', '', '')")

    def event(self, start, end):
        return {"source_id": "e1", "title": "Medieval Jousting",
                "start_date": start, "end_date": end}

    def test_an_iso_event_is_stored(self):
        self.assertTrue(dbmod.upsert_event(
            self.db, "s", self.event("2026-05-02", "2026-05-04"), 1))

    def test_a_day_first_date_is_refused_not_stored_invisibly(self):
        self.assertFalse(dbmod.upsert_event(
            self.db, "s", self.event("02/05/2026", "04/05/2026"), 1))
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)


class TestTheApiRouteNormalises(unittest.TestCase):
    """The truncation that caused it: "02/05/2026 10:00:00"[:10] is ten
    characters, so the length check passed and the order was never read."""

    def source(self):
        return FeedSource((1, "stonor-whats-on", "https://www.stonor.com/",
                           "wpevents", "historic-house", "Stonor Park", "RG9 6HF"))

    def test_a_day_first_api_date_becomes_iso(self):
        event = self.source()._api_event({
            "id": 7,
            "title": {"rendered": "Medieval Jousting &amp;#8211; 2nd to 4th May"},
            "start_date": "02/05/2026 10:00:00",
            "end_date": "04/05/2026 17:00:00",
            "venue": {"venue": "Stonor Park", "zip": "rg9 6hf"},
        })
        self.assertEqual(event["start_date"], "2026-05-02")
        self.assertEqual(event["end_date"], "2026-05-04")

    def test_double_encoded_entities_are_decoded(self):
        # "Medieval Jousting &#8211; 2nd to 4th May" reached the page.
        event = self.source()._api_event({
            "id": 7,
            "title": {"rendered": "Medieval Jousting &amp;#8211; 2nd to 4th May"},
            "start_date": "02/05/2026 10:00:00",
            "venue": {"venue": "Stonor Park", "zip": "RG9 6HF"},
        })
        self.assertEqual(event["title"], "Medieval Jousting – 2nd to 4th May")

    def test_an_event_with_an_unusable_date_is_dropped_not_guessed_at(self):
        self.assertIsNone(self.source()._api_event({
            "id": 8, "title": "Mystery", "start_date": "soon",
            "venue": {"venue": "Stonor Park", "zip": "RG9 6HF"}}))
