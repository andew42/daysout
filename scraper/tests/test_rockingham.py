"""Rockingham: three cards, three ways of writing when.

Every one of them is on the live page, and reading any as another puts a
visitor at a shut castle — the Tuesdays are a fortnight apart and the
Halloween days are consecutive, and both are written with the same kind of
punctuation between the numbers.
"""

import sqlite3
import unittest
from datetime import date

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.rockingham import (
    LISTING, Rockingham, date_runs, parse_listing)

from schema import SCHEMA

TODAY = date(2026, 9, 6)
BASE = "https://rockinghamcastle.com"


def card(title, when, slug, description="Something to do."):
    meta = f'<div class="entry-meta cf">{when}</div>' if when else ""
    return (f'<div class="post wow zoomIn">'
            f'<a href="{BASE}/event/{slug}/" title="{title}"><div class="block">'
            f'<div class="details"><h2 class="title st1 cl1 sz1">{title}</h2>'
            f'{meta}<div class="description"><p>{description}</p></div>'
            f'</div></div></a></div>')


PAGE = ('<html><body><div id="events-category"><div class="post-list v2">'
        + "".join([
            card("Autumn Artisan Fair",
                 "Saturday 26th &amp; Sunday 27th September",
                 "artisan-market-2"),
            card("October Garden Mornings",
                 "Tuesdays ~ 6th, 13th &amp; 20th October - 10am - 2pm",
                 "octobergarden"),
            card("Halloween Fun at Rockingham Castle",
                 "Wednesday 28th - Saturday 31st October", "halloween-fun"),
            card("Christmas Opening", "", "christmas"),
        ]) + "</div></div></body></html>")


class FakeFetcher:
    def __init__(self, body=PAGE):
        self.body = body
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.body


class TestTheThreeWaysOfWritingWhen(unittest.TestCase):

    def test_two_days_joined_by_an_ampersand_that_happen_to_touch(self):
        self.assertEqual(
            date_runs("Saturday 26th & Sunday 27th September", TODAY),
            [("2026-09-26", "2026-09-27")])

    def test_days_a_fortnight_apart_are_separate_events(self):
        # The castle is shut on the 7th. A range would say otherwise.
        self.assertEqual(
            date_runs("Tuesdays ~ 6th, 13th & 20th October - 10am - 2pm", TODAY),
            [("2026-10-06", "2026-10-06"), ("2026-10-13", "2026-10-13"),
             ("2026-10-20", "2026-10-20")])

    def test_a_dash_includes_the_days_between(self):
        # The weekday sitting inside the gap — "28th - Saturday 31st" —
        # is what made this read as two single days.
        self.assertEqual(date_runs("Wednesday 28th - Saturday 31st October", TODAY),
                         [("2026-10-28", "2026-10-31")])

    def test_a_range_across_a_month_boundary(self):
        self.assertEqual(
            date_runs("Friday 30th October - Sunday 1st November", TODAY),
            [("2026-10-30", "2026-11-01")])

    def test_a_time_is_not_a_range_of_days(self):
        # "10am - 2pm" is a dash between two numbers.
        self.assertEqual(date_runs("Saturday 26th September 10am - 2pm", TODAY),
                         [("2026-09-26", "2026-09-26")])

    def test_a_day_with_no_month_is_not_a_date(self):
        self.assertEqual(date_runs("Saturday 26th", TODAY), [])

    def test_nothing_readable(self):
        for text in ["", None, "Open daily", "Dates to be confirmed"]:
            self.assertEqual(date_runs(text, TODAY), [], repr(text))

    def test_a_date_well_past_is_next_years(self):
        self.assertEqual(date_runs("Saturday 7th March", TODAY),
                         [("2027-03-07", "2027-03-07")])


class TestTheCards(unittest.TestCase):

    def test_a_card_can_be_more_than_one_event(self):
        found = dict(parse_listing(PAGE, TODAY))
        self.assertEqual(len(found["October Garden Mornings"]), 3)
        self.assertEqual(len(found["Autumn Artisan Fair"]), 1)

    def test_three_tuesdays_do_not_overwrite_each_other(self):
        found = dict(parse_listing(PAGE, TODAY))
        ids = {e["source_id"] for e in found["October Garden Mornings"]}
        self.assertEqual(len(ids), 3)

    def test_a_card_with_no_date_yields_nothing(self):
        found = dict(parse_listing(PAGE, TODAY))
        self.assertEqual(found["Christmas Opening"], [])

    def test_the_card_keeps_its_link_and_description(self):
        found = dict(parse_listing(PAGE, TODAY))
        fair, = found["Autumn Artisan Fair"]
        self.assertEqual(fair["url"], f"{BASE}/event/artisan-market-2/")
        self.assertEqual(fair["description"], "Something to do.")


class TestTheRun(unittest.TestCase):

    def test_only_the_listing_is_fetched(self):
        # The API knows the events and none of their dates.
        f = FakeFetcher()
        list(Rockingham(TODAY).scrape(f))
        self.assertEqual(f.fetched, [LISTING])

    def test_the_events_reach_the_database_at_the_castle(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('LE168TH', 52.523, -0.727)")
        ok, message = run_source(db, FakeFetcher(), Rockingham(TODAY))
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("Autumn Artisan Fair", "2026-09-26", "2026-09-27"),
             ("October Garden Mornings", "2026-10-06", "2026-10-06"),
             ("October Garden Mornings", "2026-10-13", "2026-10-13"),
             ("October Garden Mornings", "2026-10-20", "2026-10-20"),
             ("Halloween Fun at Rockingham Castle", "2026-10-28", "2026-10-31")])
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Rockingham Castle", "LE16 8TH")])


if __name__ == "__main__":
    unittest.main()
