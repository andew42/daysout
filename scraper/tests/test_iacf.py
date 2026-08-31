"""IACF Newark: an iCal feed, read by the table-driven runner.

No new parser — the site publishes .ics, which is the nicest thing a
source can be: offered for subscription, machine-readable by design, and
nothing to guess at. So this is a `sources` row of kind 'ical', and what
these tests pin is the path from that row to a stored event.

Two things about the format bite here and are covered below: an all-day
DTEND is *exclusive*, so a fair running the 2nd to the 3rd is published
as ending on the 4th; and long lines are folded, so a DESCRIPTION or
LOCATION can be split across lines with a leading space.

The feed's own LOCATION is preferred for the venue. The row's venue is
only a fallback for a feed that does not repeat its address, since
without a postcode the pipeline cannot place the event and drops it.
"""

import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources import seed_sources
from daysout_scraper.sources.feeds import FeedSource

from schema import SCHEMA

FEED_URL = "https://www.iacf.co.uk/?feed=iacf-newark-events-ical"

# The shape The Events Calendar exports: all-day VALUE=DATE events, an
# exclusive DTEND, escaped commas in LOCATION, and a folded line.
FEED = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//IACF - ECPv6.0//NONSGML v1.0//EN\r\n"
    "X-WR-CALNAME:IACF Newark\r\n"
    "BEGIN:VEVENT\r\n"
    "DTSTART;VALUE=DATE:20260902\r\n"
    "DTEND;VALUE=DATE:20260904\r\n"
    "UID:26501-1756684800@www.iacf.co.uk\r\n"
    "SUMMARY:IACF Newark International Antiques & Collectors Fair\r\n"
    # Folded mid-word: unfolding removes the CRLF *and* the one inserted
    # space (RFC 5545 3.1), so a fold at a word gap carries two spaces on
    # the continuation line. Splitting a word says which happened.
    "DESCRIPTION:Europe's largest antiques fair\\, with up to 2500 stalls"
    " across the show\r\n"
    " ground.\r\n"
    "URL:https://www.iacf.co.uk/event/newark-september-2026/\r\n"
    "LOCATION:Newark Showground\\, Lincoln Road\\, Coddington\\, Newark\\, NG24 2NY\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "DTSTART;VALUE=DATE:20261202\r\n"
    "DTEND;VALUE=DATE:20261204\r\n"
    "UID:26502-1764633600@www.iacf.co.uk\r\n"
    "SUMMARY:IACF Newark Winter Fair\r\n"
    # This one names the venue without repeating the address, which is
    # what the row's venue_postcode is for.
    "LOCATION:Newark Showground\r\n"
    "URL:https://www.iacf.co.uk/event/newark-december-2026/\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


class FakeFetcher:
    def __init__(self, text=FEED):
        self.text = text
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.text


def source(venue_name="Newark Showground", venue_postcode="NG24 2NY"):
    # (id, name, url, kind, category, venue_name, venue_postcode)
    return FeedSource((1, "iacf-newark", FEED_URL, "ical", "craft",
                       venue_name, venue_postcode))


class TestReadingTheFeed(unittest.TestCase):

    def events(self):
        return [event for _, event in source().scrape(FakeFetcher())]

    def test_both_fairs_are_read(self):
        self.assertEqual([event["title"] for event in self.events()],
                         ["IACF Newark International Antiques & Collectors Fair",
                          "IACF Newark Winter Fair"])

    def test_an_all_day_dtend_is_exclusive(self):
        # Published as ending on the 4th; the fair runs the 2nd to the 3rd.
        event = self.events()[0]
        self.assertEqual(event["start_date"], "2026-09-02")
        self.assertEqual(event["end_date"], "2026-09-03")

    def test_a_folded_description_is_rejoined(self):
        self.assertEqual(
            self.events()[0]["description"],
            "Europe's largest antiques fair, with up to 2500 stalls"
            " across the showground.")

    def test_the_postcode_comes_from_the_feed_when_it_has_one(self):
        self.assertEqual(self.events()[0]["venue_postcode"], "NG24 2NY")

    def test_the_venue_name_is_the_first_part_of_the_address(self):
        self.assertEqual(self.events()[0]["location_name"], "Newark Showground")

    def test_the_rows_venue_covers_a_feed_that_omits_the_address(self):
        self.assertEqual(self.events()[1]["venue_postcode"], "NG24 2NY")

    def test_without_a_row_venue_such_an_event_has_no_postcode(self):
        # Which is why the row carries one: the pipeline drops these.
        events = [e for _, e in source(venue_postcode="").scrape(FakeFetcher())]
        self.assertEqual(events[1]["venue_postcode"], "")

    def test_the_event_keeps_its_own_link(self):
        self.assertEqual(self.events()[0]["url"],
                         "https://www.iacf.co.uk/event/newark-september-2026/")

    def test_the_feed_is_fetched_once_and_not_rendered(self):
        fetcher = FakeFetcher()
        list(source().scrape(fetcher))
        self.assertEqual(fetcher.fetched, [FEED_URL])


class TestTheEventsReachTheDatabase(unittest.TestCase):

    def test_both_fairs_land_at_the_showground(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('NG242NY', 53.0761, -0.7737)")

        ok, message = run_source(db, FakeFetcher(), source())
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("IACF Newark International Antiques & Collectors Fair",
              "2026-09-02", "2026-09-03"),
             ("IACF Newark Winter Fair", "2026-12-02", "2026-12-03")])

        self.assertEqual(
            db.execute("SELECT name, postcode, category FROM destinations")
              .fetchall(),
            [("Newark Showground", "NG24 2NY", "craft")])


class TestTheSeededRow(unittest.TestCase):

    def db(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        seed_sources.ensure(db)
        return db

    def test_it_is_seeded_as_ical_with_its_venue(self):
        # 'auto' would probe the "?feed=..." URL as a web page.
        row = self.db().execute(
            "SELECT url, kind, category, venue_name, venue_postcode"
            " FROM sources WHERE name = 'iacf-newark'").fetchone()
        self.assertEqual(row, (FEED_URL, "ical", "craft",
                               "Newark Showground", "NG24 2NY"))

    def test_a_hand_corrected_venue_is_left_alone(self):
        # ensure() runs every scrape; it must not undo a fix.
        db = self.db()
        db.execute("UPDATE sources SET venue_postcode = 'NG24 4TB'"
                   " WHERE name = 'iacf-newark'")
        seed_sources.ensure(db)
        self.assertEqual(
            db.execute("SELECT venue_postcode FROM sources"
                       " WHERE name = 'iacf-newark'").fetchone()[0],
            "NG24 4TB")


if __name__ == "__main__":
    unittest.main()
