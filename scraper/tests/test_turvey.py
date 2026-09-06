"""Turvey: a hand-typed page that does not clear itself.

Every block below is one the page carried on 6 Sep 2026, and the two that
matter most are the ones that must *not* become events: a cancellation
notice that ends with the dates being cancelled, and the "Previous Events
Include" list.

The date rule is the opposite of Blenheim's and the difference is the
page. This one was still advertising four August dates a month after they
happened, so a year left off is read as this year and dropped once past.
Rolling it forward would not recover a future event, it would invent one.
"""

import sqlite3
import unittest
from datetime import date

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.turvey import (
    LISTING, Turvey, date_range, parse_listing)

from schema import SCHEMA

TODAY = date(2026, 9, 6)


def block(lines, href=None):
    body = "<br>".join(lines)
    if href:
        body += f'<br><a href="{href}">Book Tickets Here</a>'
    return f'<div data-testid="richTextElement"><h1>{body}</h1></div>'


PAGE = "<html><body>" + "".join([
    block(["WHAT'S ON"]),
    # Dates and a link, but the name is in an image.
    block(["25th April &amp; 25th July 2026", "mlvintage.co.uk"]),
    # Over a month past, and still on the page.
    block(["Outdoor Theatre: Kaspar Prince of Cats", "Sunday 2nd August 2-3PM"],
          "https://www.tickettailor.com/events/x"),
    block(["Wild Canvas Camping",
           "Tuesday 6th August - Monday 31st August", "wildcanvas.uk"]),
    # Still to come.
    block(["Backyard Ultra Solo", "Saturday 10th October",
           "backyard-ultra.co.uk"],
          "https://polkadotevents.eventrac.co.uk/e/loop-til-you-drop"),
    # A cancellation, ending with the dates it cancels.
    block(["CANCELLED.",
           "We regret to inform that the Outdoor Film Club have cancelled "
           "their dates at Turvey House this August.",
           "Friday 21st - Sunday 23rd August"]),
    # The "previous events" list: names, no dates.
    block(["Previous Events Include:"]),
    block(["Steam Fayre"]),
    block(["Large Car Shows"]),
    # The footer address.
    block(["Turvey, Bedfordshire, MK43 8EL", "07747 046 398",
           "info@turveyhouse.co.uk"]),
]) + "</body></html>"


class FakeFetcher:
    def __init__(self, body=PAGE):
        self.body = body
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.body


class TestTheYearIsNotRolledForward(unittest.TestCase):

    def test_a_date_still_to_come_is_this_year(self):
        self.assertEqual(date_range("Saturday 10th October", TODAY),
                         ("2026-10-10", "2026-10-10"))

    def test_a_date_a_month_past_is_stale_not_next_years(self):
        # The page still advertises it. Rolling it to 2027 would put a
        # show on the map that nobody has scheduled.
        self.assertIsNone(date_range("Sunday 2nd August 2-3PM", TODAY))

    def test_a_year_written_on_the_page_is_believed(self):
        # Even a past one: it says what it means, and the pipeline drops
        # what has already ended.
        self.assertEqual(date_range("25th July 2026", TODAY),
                         ("2026-07-25", "2026-07-25"))

    def test_a_range_naming_its_month_once(self):
        self.assertEqual(date_range("Friday 21st - Sunday 23rd November", TODAY),
                         ("2026-11-21", "2026-11-23"))

    def test_a_time_is_not_a_day(self):
        self.assertEqual(date_range("Sunday 11th October 2-3PM", TODAY),
                         ("2026-10-11", "2026-10-11"))

    def test_prose_with_no_date(self):
        for text in ["", "We run simulated shoot days throughout May/ June",
                     "Previous Events Include:", "Steam Fayre"]:
            self.assertIsNone(date_range(text, TODAY), repr(text))


class TestWhatIsNotAnEvent(unittest.TestCase):

    def test_a_cancellation_notice_is_not_an_event(self):
        # It ends with the dates being cancelled, so a parser looking only
        # for dates would publish exactly the thing that is not happening.
        titles = [e["title"] for e in parse_listing(PAGE, TODAY)]
        self.assertFalse([t for t in titles if "CANCEL" in t.upper()])
        self.assertFalse([t for t in titles if "regret" in t.lower()])

    def test_the_previous_events_list_is_not_a_listing(self):
        titles = [e["title"] for e in parse_listing(PAGE, TODAY)]
        for name in ["Steam Fayre", "Large Car Shows", "Previous Events Include:"]:
            self.assertNotIn(name, titles)

    def test_the_footer_address_is_not_an_event(self):
        titles = [e["title"] for e in parse_listing(PAGE, TODAY)]
        self.assertFalse([t for t in titles if "MK43" in t])

    def test_a_block_with_dates_and_no_title_is_skipped(self):
        # The name is in an image; a link label is not a title.
        titles = [e["title"] for e in parse_listing(PAGE, TODAY)]
        self.assertNotIn("mlvintage.co.uk", titles)


class TestTheRun(unittest.TestCase):

    def test_only_what_is_still_to_come(self):
        events = parse_listing(PAGE, TODAY)
        self.assertEqual([e["title"] for e in events], ["Backyard Ultra Solo"])

    def test_the_booking_link_is_kept(self):
        event, = parse_listing(PAGE, TODAY)
        self.assertEqual(event["url"],
                         "https://polkadotevents.eventrac.co.uk/e/loop-til-you-drop")

    def test_only_the_listing_is_fetched(self):
        f = FakeFetcher()
        list(Turvey(TODAY).scrape(f))
        self.assertEqual(f.fetched, [LISTING])

    def test_the_event_reaches_the_database_at_turvey(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('MK438EL', 52.163, -0.601)")
        ok, message = run_source(db, FakeFetcher(), Turvey(TODAY))
        self.assertTrue(ok, message)
        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events").fetchall(),
            [("Backyard Ultra Solo", "2026-10-10", "2026-10-10")])
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Turvey House", "MK43 8EL")])


if __name__ == "__main__":
    unittest.main()
