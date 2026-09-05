"""Blenheim: the listing is the only place a date appears.

`discover` on an event page returns "no dates in the DOM at all" — no
JSON-LD, no <time>, no date-classed element, not one date-looking phrase.
The what's-on cards carry them in prose instead, and the corpus below is
every `.date-attr` the page held on 5 Sep 2026, so a change to the parser
is measured against the whole listing rather than a chosen example.
"""

import sqlite3
import unittest
from datetime import date

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.blenheim import (
    LISTING, Blenheim, date_range, parse_listing)

from schema import SCHEMA

TODAY = date(2026, 9, 5)


def card(title, when, href="whats-on/events/x/", classes="f-2026"):
    date_attr = f'<small class="date-attr">{when}</small>' if when else ""
    return (f'<div class="portfolio-item yes mb-4 {classes}">'
            f'<div class="fbox-desc"><h2><a href="{href}">{title}</a></h2>'
            f'{date_attr}<p>Some prose.</p></div></div>')


PAGE = "<html><body>" + "".join([
    card("Life Through a Royal Lens Exhibition",
         "Sunday 12th July - Sunday 27th September",
         "whats-on/events/life-through-a-royal-lens/"),
    card("Christmas 2026", "Friday 13th November 2026 - Sunday 3rd January 2027",
         "whats-on/events/christmas/"),
    card("Salon Privé", "Wednesday 2nd - Sunday 6th September 2026",
         "whats-on/events/salon-prive-supercar/"),
    card("Armchair Talks", "Tuesday 29th September at 18.00",
         "whats-on/events/armchair-talks/"),
    card("Family Treasures Collection", "Open daily 10.30 - 16.45",
         "whats-on/events/family-treasures-collection/", classes=""),
    card("The Glow Up", "", "whats-on/events/the-glow-up/"),
]) + "</body></html>"


class FakeFetcher:
    def __init__(self, body=PAGE):
        self.body = body
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.body


class TestEveryDateOnTheListing(unittest.TestCase):
    """All 24 cards as the page had them."""

    CORPUS = [
        # A range with no year at all: the commonest shape here.
        ("Tuesday 1st September - Wednesday 11th November",
         ("2026-09-01", "2026-11-11")),
        ("Thursday 22nd October - Sunday 1st November",
         ("2026-10-22", "2026-11-01")),
        ("Sunday 12th July - Sunday 27th September",
         ("2026-07-12", "2026-09-27")),
        ("Monday 10th August - Sunday 1st November",
         ("2026-08-10", "2026-11-01")),
        ("Tuesday 1st September - Sunday 4th October",
         ("2026-09-01", "2026-10-04")),
        ("Sunday 2nd August - Thursday 15th October",
         ("2026-08-02", "2026-10-15")),

        # A year on the end, or on both ends.
        ("Saturday 24th October - Sunday 1st November 2026",
         ("2026-10-24", "2026-11-01")),
        ("Friday 13th November 2026 - Sunday 3rd January 2027",
         ("2026-11-13", "2027-01-03")),
        ("Friday 11th June - Sunday 13th June 2027",
         ("2027-06-11", "2027-06-13")),

        # The month named once, at the end, for both days.
        ("Wednesday 2nd - Sunday 6th September 2026",
         ("2026-09-02", "2026-09-06")),
        ("Thursday 17th - Sunday 20th September 2026",
         ("2026-09-17", "2026-09-20")),
        ("Saturday 3rd - Sunday 4th October 2026",
         ("2026-10-03", "2026-10-04")),
        ("Saturday 29th - Monday 31st May 2027", ("2027-05-29", "2027-05-31")),
        ("Saturday 5th - Sunday 6th June 2027", ("2027-06-05", "2027-06-06")),
        ("Friday 23rd - Sunday 25th July 2027", ("2027-07-23", "2027-07-25")),

        # One day, with and without a time.
        ("Tuesday 29th September at 18.00", ("2026-09-29", "2026-09-29")),
        ("Tuesday 29th September", ("2026-09-29", "2026-09-29")),

        # A range qualified by prose. The qualification is lost — it runs
        # weekends only — but the span is right, and the alternative is
        # dropping a real event.
        ("Weekends from Saturday 25th July - Sunday 6th September",
         ("2026-07-25", "2026-09-06")),

        # Not dates. "Returning in 2027" has a year and no day, which is
        # exactly the shape that would tempt a looser parser.
        ("Open daily 10.15 - 17.15", None),
        ("Open daily 10.30 - 16.45", None),
        ("Learn More", None),
        ("Returning in 2027", None),
        ("", None),
        (None, None),
    ]

    def test_every_date_the_page_carried(self):
        for text, expected in self.CORPUS:
            self.assertEqual(date_range(text, TODAY), expected, repr(text))

    def test_the_corpus_is_the_whole_listing(self):
        self.assertEqual(len(self.CORPUS), 24)


class TestTheYearComesFromTheEnd(unittest.TestCase):

    def test_an_exhibition_running_now_is_not_thrown_to_next_year(self):
        # It opened eight weeks ago, which is past the month of grace.
        # Anchoring on the start would read this as July 2027 and invert
        # the range; the end says it is on until the 27th.
        self.assertEqual(
            date_range("Sunday 12th July - Sunday 27th September", TODAY),
            ("2026-07-12", "2026-09-27"))

    def test_a_range_crossing_the_new_year_without_saying_so(self):
        self.assertEqual(
            date_range("Friday 13th November - Sunday 3rd January", TODAY),
            ("2026-11-13", "2027-01-03"))

    def test_something_long_over_is_next_years(self):
        self.assertEqual(date_range("Saturday 7th - Sunday 8th March", TODAY),
                         ("2027-03-07", "2027-03-08"))

    def test_a_date_that_does_not_exist_is_refused(self):
        self.assertIsNone(date_range("Tuesday 31st September", TODAY))


class TestTheCards(unittest.TestCase):

    def test_the_f_year_class_is_not_read_as_the_year(self):
        # The card says f-2026 and the text says 2027. Only 14 of the 24
        # cards carry an f-year at all and it disagrees with the text
        # where both exist: it is a filter tag, not a date.
        page = "<html><body>" + card(
            "Game Fair", "Friday 23rd - Sunday 25th July 2027",
            classes="f-2026") + "</body></html>"
        (_, event), = parse_listing(page, TODAY)
        self.assertEqual(event["start_date"], "2027-07-23")

    def test_a_card_with_no_date_is_reported_undated_not_dropped_silently(self):
        found = dict(parse_listing(PAGE, TODAY))
        self.assertIsNone(found["The Glow Up"])
        self.assertIsNone(found["Family Treasures Collection"])

    def test_the_link_is_made_absolute(self):
        found = dict(parse_listing(PAGE, TODAY))
        self.assertEqual(
            found["Salon Privé"]["url"],
            "https://www.blenheimpalace.com/whats-on/events/salon-prive-supercar/")

    def test_an_annual_event_keeps_its_years_apart(self):
        found = dict(parse_listing(PAGE, TODAY))
        self.assertTrue(found["Christmas 2026"]["source_id"].endswith("2026-11-13"))


class TestTheRun(unittest.TestCase):

    def test_only_the_listing_is_fetched(self):
        # The event pages carry no dates, so following 24 links would
        # spend 24 requests to learn nothing.
        f = FakeFetcher()
        list(Blenheim(TODAY).scrape(f))
        self.assertEqual(f.fetched, [LISTING])

    def test_the_events_reach_the_database_at_the_palace(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('OX201PP', 51.841, -1.361)")
        ok, message = run_source(db, FakeFetcher(), Blenheim(TODAY))
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("Life Through a Royal Lens Exhibition", "2026-07-12", "2026-09-27"),
             ("Salon Privé", "2026-09-02", "2026-09-06"),
             ("Armchair Talks", "2026-09-29", "2026-09-29"),
             ("Christmas 2026", "2026-11-13", "2027-01-03")])
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Blenheim Palace", "OX20 1PP")])


if __name__ == "__main__":
    unittest.main()
