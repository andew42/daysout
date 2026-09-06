"""Chenies: a clean listing, and one date shape the shared parser misreads.

Both dates on a card carry their year, so nothing here is inferred. What
needs pinning is that "3 May 2027 – 31 May 2027" is not one date:
`dates.parse_range` reads exactly that string as ('2027-05-03',
'2027-05-03') and reports no error, because its pattern is built for
"5 - 6 December 2026" with the year written once. A month-long festival
would have become a one-day event with nothing looking wrong.
"""

import sqlite3
import unittest

from daysout_scraper import dates
from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.chenies import (
    LISTING, Chenies, date_range, parse_listing)

from schema import SCHEMA

BASE = "https://www.cheniesmanorhouse.co.uk"


def card(title, when, slug, excerpt="A day out in the gardens."):
    dates_html = f'<p class="ce-card__dates">{when}</p>' if when else ""
    return (f'<a href="{BASE}/event/{slug}/" class="ce-card ">'
            f'<div class="ce-card__image"></div>'
            f'<div class="ce-card__body">'
            f'<h2 class="ce-card__title">{title}</h2>{dates_html}'
            f'<p class="ce-card__excerpt">{excerpt}</p>'
            f'<span class="ce-card__link">Find Out More →</span>'
            f'</div></a>')


# The four cards the page carried, plus the duplicate it renders in a
# second section and one with no dates at all.
PAGE = '<html><body><div class="ce-events-list">' + "".join([
    card("Tulip Festival", "3 May 2027 – 31 May 2027", "tulip-festival"),
    card("Dog Show", "31 May 2027", "dog-show"),
    card("Plant Fair", "18 July 2027", "plant-fair"),
    card("Dahlia Festival", "31 August 2026 – 30 September 2026",
         "dahlia-festival"),
    card("Tulip Festival", "3 May 2027 – 31 May 2027", "tulip-festival"),
    card("Christmas Opening", "", "christmas"),
]) + "</div></body></html>"


class FakeFetcher:
    def __init__(self, body=PAGE):
        self.body = body
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.body


class TestTheDateShapeTheSharedParserMisreads(unittest.TestCase):

    def test_parse_range_really_does_truncate_this(self):
        # Not a hypothetical: this is why date_range exists, and if
        # parse_range ever learns the shape this test says so.
        self.assertEqual(dates.parse_range("3 May 2027 – 31 May 2027"),
                         ("2027-05-03", "2027-05-03"))

    def test_both_ends_are_read(self):
        self.assertEqual(date_range("3 May 2027 – 31 May 2027"),
                         ("2027-05-03", "2027-05-31"))

    def test_a_range_across_two_months(self):
        self.assertEqual(date_range("31 August 2026 – 30 September 2026"),
                         ("2026-08-31", "2026-09-30"))

    def test_one_day_is_the_same_date_twice(self):
        self.assertEqual(date_range("31 May 2027"), ("2027-05-31", "2027-05-31"))

    def test_any_dash_the_site_might_use(self):
        for text in ["3 May 2027 - 31 May 2027", "3 May 2027 — 31 May 2027",
                     "3 May 2027 to 31 May 2027"]:
            self.assertEqual(date_range(text), ("2027-05-03", "2027-05-31"), text)

    def test_the_year_written_once_still_works(self):
        # parse_range's own shape, reached by the fallback.
        self.assertEqual(date_range("3 - 31 May 2027"),
                         ("2027-05-03", "2027-05-31"))

    def test_a_range_that_runs_backwards_is_refused(self):
        self.assertIsNone(date_range("31 May 2027 – 3 May 2027"))

    def test_nothing_readable(self):
        for text in ["", None, "Open daily", "Dates to be confirmed"]:
            self.assertIsNone(date_range(text), repr(text))


class TestTheCards(unittest.TestCase):

    def test_a_card_repeated_in_two_sections_is_one_event(self):
        titles = [title for title, _ in parse_listing(PAGE)]
        self.assertEqual(titles.count("Tulip Festival"), 1)

    def test_a_card_with_no_dates_is_reported_not_dropped_silently(self):
        found = dict(parse_listing(PAGE))
        self.assertIsNone(found["Christmas Opening"])

    def test_the_card_carries_its_link_and_excerpt(self):
        found = dict(parse_listing(PAGE))
        tulip = found["Tulip Festival"]
        self.assertEqual(tulip["url"], f"{BASE}/event/tulip-festival/")
        self.assertEqual(tulip["description"], "A day out in the gardens.")

    def test_an_annual_festival_keeps_its_years_apart(self):
        found = dict(parse_listing(PAGE))
        self.assertTrue(found["Tulip Festival"]["source_id"].endswith("2027-05-03"))


class TestTheRun(unittest.TestCase):

    def test_only_the_listing_is_fetched(self):
        # The API knows the events and none of their dates, so the
        # listing is the whole source and costs one request.
        f = FakeFetcher()
        list(Chenies().scrape(f))
        self.assertEqual(f.fetched, [LISTING])

    def test_the_events_reach_the_database_at_the_manor(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('WD36ER', 51.688, -0.532)")
        ok, message = run_source(db, FakeFetcher(), Chenies())
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("Dahlia Festival", "2026-08-31", "2026-09-30"),
             ("Tulip Festival", "2027-05-03", "2027-05-31"),
             ("Dog Show", "2027-05-31", "2027-05-31"),
             ("Plant Fair", "2027-07-18", "2027-07-18")])
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Chenies Manor House", "WD3 6ER")])


if __name__ == "__main__":
    unittest.main()
