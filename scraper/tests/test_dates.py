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
from daysout_scraper.text import plain

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


class TestWordPressTextIsDecodedTwice(unittest.TestCase):
    """The other half of the Stonor lesson, which outlived its engine.

    These arrived with a WordPress events API that no longer has a reader
    here, but the escaping is not WordPress's alone: anywhere text comes
    out of somebody's template, assume it is escaped once too often.
    "Medieval Jousting &amp;#8211; 2nd to 4th May" survives one decode as
    "&#8211;", which is what reached the page.
    """

    def test_a_double_encoded_entity_is_decoded(self):
        self.assertEqual(
            plain({"rendered": "Medieval Jousting &amp;#8211; 2nd to 4th May"}),
            "Medieval Jousting – 2nd to 4th May")

    def test_markup_is_stripped(self):
        self.assertEqual(plain({"rendered": "<p>A <b>fine</b> fair</p>"}),
                         "A fine fair")

    def test_nothing_at_all(self):
        self.assertEqual(plain(None), "")
        self.assertEqual(plain({}), "")


class TestUnpaddedISO(unittest.TestCase):
    """UK Craft Fairs publishes "2026-9-6T10:00:00" — a real date that is
    not zero-padded. Slicing ten characters off it yields "2026-9-6T1",
    which is the right length and not a date, so it reaches the database
    looking plausible and matches no query."""

    def test_a_single_digit_month_and_day(self):
        self.assertEqual(dates.to_iso("2026-9-6T10:00:00"), "2026-09-06")
        self.assertEqual(dates.to_iso("2026-9-6"), "2026-09-06")

    def test_padded_dates_are_unaffected(self):
        self.assertEqual(dates.to_iso("2026-08-29T10:00:00+01:00"), "2026-08-29")

    def test_day_first_is_still_read_day_first(self):
        # The year-first shape above must not make "02-05-2026" ambiguous.
        self.assertEqual(dates.to_iso("02-05-2026"), "2026-05-02")

    def test_nonsense_is_still_refused(self):
        self.assertEqual(dates.to_iso("2026-13-40"), "")


class TestJsonLdDatesAreParsedNotSliced(unittest.TestCase):

    def test_the_unpadded_shape(self):
        from daysout_scraper import jsonld
        self.assertEqual(jsonld._date("2026-9-6T10:00:00"), "2026-09-06")

    def test_a_day_first_datetime_is_read_rather_than_stored_raw(self):
        from daysout_scraper import jsonld
        self.assertEqual(jsonld._date("02/05/2026 10:00:00"), "2026-05-02")

