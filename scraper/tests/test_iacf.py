"""IACF: three showground fairs, read from their iCal feeds.

No new parser — the site publishes .ics, which is the nicest thing a
source can be: offered for subscription, machine-readable by design, and
nothing to guess at. So these are `sources` rows of kind 'ical', and what
these tests pin is the path from a row to a stored event.

The feed shape below is what the house server actually received on
31 Aug 2026, and the surprise in it is that **a two-day fair is published
as two one-day events**: "…Fair: 10-11 December" arrives twice, dated the
10th and the 11th. Left alone that shows every fair twice on the events
list, each copy claiming a single day while its own title says otherwise.
The runs are joined back together, and the feed's order is not relied on
— Newark lists December before October.

Two more things about the format bite, and are pinned below: an all-day
DTEND is *exclusive*, and long lines are folded with one inserted space.
A WordPress export also leaves HTML entities in SUMMARY and DESCRIPTION.
"""

import sqlite3
import unittest

from daysout_scraper import ical
from daysout_scraper.pipeline import run_source
from daysout_scraper.sources import seed_sources
from daysout_scraper.sources.feeds import FeedSource

from schema import SCHEMA

FEED_URL = "https://www.iacf.co.uk/?feed=iacf-newark-events-ical"
NEWARK = "Newark Showground, Newark, Nottinghamshire, NG24 2NY"


def vevent(uid, summary, start, end, location=NEWARK, extra=""):
    return ("BEGIN:VEVENT\r\n"
            f"UID:{uid}@www.iacf.co.uk\r\n"
            f"SUMMARY:{summary}\r\n"
            f"DTSTART;VALUE=DATE:{start}\r\n"
            f"DTEND;VALUE=DATE:{end}\r\n"
            f"LOCATION:{location}\r\n"
            f"{extra}"
            "END:VEVENT\r\n")


# Verbatim in shape: one VEVENT per day, December before October, the
# title carrying the real range, and the SUMMARY still HTML-escaped the
# way a WordPress export leaves it.
DECEMBER = "Newark International Antiques &amp; Collectors Fair: 10-11 December"
OCTOBER = "Newark International Antiques &amp; Collectors Fair: 15-16 October"

FEED = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//IACF - ECPv6.0//NONSGML v1.0//EN\r\n"
    "X-WR-CALNAME:IACF Newark\r\n"
    + vevent("26501", DECEMBER, "20261210", "20261211",
             extra="URL:https://www.iacf.co.uk/event/newark-december-2026/\r\n"
                   # Folded mid-word: unfolding removes the CRLF *and* the
                   # one inserted space (RFC 5545 3.1), so a fold at a word
                   # gap carries two spaces. Splitting a word says which.
                   "DESCRIPTION:Europe&#8217;s largest antiques fair\\, up to"
                   " 2500 stalls across the show\r\n ground.\r\n")
    + vevent("26502", DECEMBER, "20261211", "20261212")
    + vevent("26503", OCTOBER, "20261015", "20261016")
    + vevent("26504", OCTOBER, "20261016", "20261017")
    # A fair at a venue that does not repeat its address, which is what
    # the row's venue_postcode is for.
    + vevent("26505", "Newark Winter Antiques Market", "20270115", "20270116",
             location="Newark Showground")
    + "END:VCALENDAR\r\n"
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
    return FeedSource((1, "iacf-newark", FEED_URL, "ical", "antiques",
                       venue_name, venue_postcode))


class TestJoiningTheDaysOfOneFair(unittest.TestCase):
    """The feed's own shape: one VEVENT per day of a multi-day fair."""

    def events(self):
        return [event for _, event in source().scrape(FakeFetcher())]

    def test_a_two_day_fair_is_one_event(self):
        # Four VEVENTs for December and October become two fairs.
        events = self.events()
        self.assertEqual(len(events), 3)

    def test_the_span_matches_what_the_title_says(self):
        spans = {event["title"]: (event["start_date"], event["end_date"])
                 for event in self.events()}
        self.assertEqual(
            spans["Newark International Antiques & Collectors Fair: 10-11 December"],
            ("2026-12-10", "2026-12-11"))
        self.assertEqual(
            spans["Newark International Antiques & Collectors Fair: 15-16 October"],
            ("2026-10-15", "2026-10-16"))

    def test_the_feeds_order_is_not_relied_on(self):
        # December is listed before October, so a merge that only looked
        # at neighbours in feed order would still work — but one that
        # assumed ascending dates would not.
        october = [e for e in self.events() if "October" in e["title"]][0]
        self.assertEqual(october["start_date"], "2026-10-15")

    def test_a_single_day_fair_is_left_alone(self):
        single = [e for e in self.events() if "Winter" in e["title"]][0]
        self.assertEqual((single["start_date"], single["end_date"]),
                         ("2027-01-15", "2027-01-15"))

    def test_separate_fairs_at_one_venue_are_not_run_together(self):
        # Same venue, months apart: two fairs, not one long one.
        starts = sorted(e["start_date"] for e in self.events())
        self.assertEqual(starts, ["2026-10-15", "2026-12-10", "2027-01-15"])


class TestTheFormatsOwnTraps(unittest.TestCase):

    def events(self):
        return [event for _, event in source().scrape(FakeFetcher())]

    def test_an_all_day_dtend_is_exclusive(self):
        # DTEND 20261211 on the event dated the 10th means one day, not two.
        events = list(ical.parse(
            "BEGIN:VCALENDAR\r\n"
            + vevent("x", "One Day Fair", "20260902", "20260903")
            + "END:VCALENDAR\r\n"))
        self.assertEqual((events[0]["start_date"], events[0]["end_date"]),
                         ("2026-09-02", "2026-09-02"))

    def test_html_entities_are_decoded(self):
        # The frontend escapes what it interpolates, so an entity stored
        # here is one the reader sees.
        titles = [event["title"] for event in self.events()]
        self.assertIn(
            "Newark International Antiques & Collectors Fair: 10-11 December",
            titles)

    def test_a_folded_description_is_rejoined(self):
        december = [e for e in self.events() if "December" in e["title"]][0]
        self.assertEqual(
            december["description"],
            "Europe’s largest antiques fair, up to 2500 stalls"
            " across the showground.")

    def test_the_postcode_comes_from_the_feed_when_it_has_one(self):
        december = [e for e in self.events() if "December" in e["title"]][0]
        self.assertEqual(december["venue_postcode"], "NG24 2NY")

    def test_the_venue_name_is_the_first_part_of_the_address(self):
        december = [e for e in self.events() if "December" in e["title"]][0]
        self.assertEqual(december["location_name"], "Newark Showground")

    def test_the_rows_venue_covers_a_feed_that_omits_the_address(self):
        winter = [e for e in self.events() if "Winter" in e["title"]][0]
        self.assertEqual(winter["venue_postcode"], "NG24 2NY")

    def test_without_a_row_venue_such_an_event_has_no_postcode(self):
        events = [e for _, e in source(venue_postcode="").scrape(FakeFetcher())]
        winter = [e for e in events if "Winter" in e["title"]][0]
        self.assertEqual(winter["venue_postcode"], "")

    def test_the_feed_is_fetched_once_and_not_rendered(self):
        fetcher = FakeFetcher()
        list(source().scrape(fetcher))
        self.assertEqual(fetcher.fetched, [FEED_URL])

    def test_a_valid_but_empty_feed_is_not_an_error(self):
        # IACF's Shepton Mallet feed is 264 valid bytes listing no fairs.
        empty = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
        with self.assertLogs("daysout_scraper.sources.feeds", "INFO") as logged:
            events = list(source().scrape(FakeFetcher(empty)))
        self.assertEqual(events, [])
        self.assertIn("lists no events", "\n".join(logged.output))


class TestTheEventsReachTheDatabase(unittest.TestCase):

    def test_the_fairs_land_at_the_showground_once_each(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('NG242NY', 53.0977, -0.7693)")

        ok, message = run_source(db, FakeFetcher(), source())
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("2026-10-15", "2026-10-16"),
             ("2026-12-10", "2026-12-11"),
             ("2027-01-15", "2027-01-15")])

        self.assertEqual(
            db.execute("SELECT name, postcode, category FROM destinations")
              .fetchall(),
            [("Newark Showground", "NG24 2NY", "antiques")])


class TestTheSeededRows(unittest.TestCase):

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
        self.assertEqual(row, (FEED_URL, "ical", "antiques",
                               "Newark Showground", "NG24 2NY"))

    def test_all_three_fairs_are_seeded(self):
        rows = self.db().execute(
            "SELECT name, category FROM sources WHERE name LIKE 'iacf-%'"
            " ORDER BY name").fetchall()
        self.assertEqual(rows, [("iacf-ardingly", "antiques"),
                                ("iacf-newark", "antiques"),
                                ("iacf-shepton-mallet", "antiques")])

    def test_the_link_shown_is_the_site_not_the_feed(self):
        # The Sources page offered the "?feed=..." address as the link,
        # which is right to fetch and no use to click.
        for name in ("iacf-newark", "iacf-ardingly", "iacf-shepton-mallet"):
            site, url = self.db().execute(
                "SELECT site_url, url FROM sources WHERE name = ?",
                (name,)).fetchone()
            self.assertEqual(site, "https://www.iacf.co.uk/")
            self.assertIn("?feed=", url)

    def test_a_row_seeded_before_the_category_existed_is_corrected(self):
        # ensure() only ever inserts, so without CATEGORY_FIXES the row
        # seeded as 'craft' would keep it for ever.
        db = self.db()
        db.execute("UPDATE sources SET category = 'craft'"
                   " WHERE name = 'iacf-newark'")
        seed_sources.ensure(db)
        self.assertEqual(
            db.execute("SELECT category FROM sources"
                       " WHERE name = 'iacf-newark'").fetchone()[0],
            "antiques")

    def test_a_hand_chosen_category_is_left_alone(self):
        db = self.db()
        db.execute("UPDATE sources SET category = 'venue'"
                   " WHERE name = 'iacf-newark'")
        seed_sources.ensure(db)
        self.assertEqual(
            db.execute("SELECT category FROM sources"
                       " WHERE name = 'iacf-newark'").fetchone()[0],
            "venue")


if __name__ == "__main__":
    unittest.main()
