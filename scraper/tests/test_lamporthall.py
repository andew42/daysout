"""Lamport Hall: read a date that never states its year.

The corpus in TestTheRealDateShapes is every one of the 18 timedatetext
strings the live site carried on 5 Sep 2026, so a change to the parser is
measured against the whole site rather than a chosen example. Three of
them name no day at all and must stay unread: a programme described as
"Selected dates throughout December" has no date to store, and inventing
one puts a visitor at a locked gate.
"""

import sqlite3
import unittest
from datetime import date

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.lamporthall import (
    LamportHall, date_runs, event_urls, parse_event)

from schema import SCHEMA

BASE = "https://www.lamporthall.co.uk"
INDEX = f"{BASE}/events/"
CONCERT = f"{BASE}/events/chf-concert/"
MARKET = f"{BASE}/events/christmas-market/"
SHOP = f"{BASE}/events/christmas-shop-and-cafe/"

# The site's own date, in the moment the corpus was taken.
TODAY = date(2026, 9, 5)

# The index links each event and carries no date of its own; the nav
# links the index itself, and other sections, from every page.
INDEX_PAGE = f"""<html><body>
  <ul class="level1Menu">
    <li><a href="{BASE}/events/" class="level1link">Events</a></li>
    <li><a href="/plan-your-visit/tearoom/">Stables Cafe</a></li>
  </ul>
  <a href="/events/chf-concert/"><h2>Concert</h2></a>
  <a href="/events/christmas-market/"><h2>Christmas Market</h2></a>
  <a href="/events/christmas-shop-and-cafe/"><h2>Christmas Shop</h2></a>
  <a href="/events/chf-concert/">the same event, pictured</a>
  <a href="/events/#scrolltop">Back to top</a>
  <a href="https://www.facebook.com/events/12345/">Follow us</a>
</body></html>"""


def page(title, when, body=""):
    """An event page in the shape the live site publishes."""
    return f"""<html><head><title>{title} - Lamport Hall &amp; Gardens</title></head>
      <body>
        <div class="eventdetails">
          <div class="image"></div>
          <div class="box hasImage">
            <h2>{title}</h2>
            <p class="timedatetext">{when}</p>
            <p>{body}</p>
          </div>
        </div>
        <footer>Lamport Hall, Lamport, Northamptonshire, NN6 9HD
          (NN6 9EZ for satnav)</footer>
      </body></html>"""


CONCERT_PAGE = page(
    "Raymond Yui and Kyle Nash-Baker in Concert",
    "6th November, 6.00pm - 9.00pm",
    "Lamport Hall is delighted to be hosting the annual Autumn concert "
    "in aid of the Counties Heritage Foundation.")

MARKET_PAGE = page(
    "Christmas Market",
    "Saturday 5th &amp; Sunday 6th and Saturday 12th &amp; Sunday 13th "
    "December, 10am-4pm")

SHOP_PAGE = page("Christmas Shop &amp; Cafe", "Selected dates throughout December")


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.pages[url]


class TestTheRealDateShapes(unittest.TestCase):
    """Every timedatetext the site carried, and what it means."""

    CORPUS = [
        # One day, with and without the weekday, with and without times.
        ("Monday 26th October, 3:30pm-5pm & 7:30pm-9pm",
         [("2026-10-26", "2026-10-26")]),
        ("Friday 18th September, 6pm-9pm", [("2026-09-18", "2026-09-18")]),
        ("6th November, 6.00pm - 9.00pm", [("2026-11-06", "2026-11-06")]),
        ("Thursday 22nd October, 10:30am-3:30pm", [("2026-10-22", "2026-10-22")]),
        ("Friday 11th September, 10am-4pm", [("2026-09-11", "2026-09-11")]),
        ("Thursday 15th October, 6:30pm-8:30pm", [("2026-10-15", "2026-10-15")]),
        ("Thursday 17th December, 11:30am-2pm", [("2026-12-17", "2026-12-17")]),
        ("Thursday 19th November", [("2026-11-19", "2026-11-19")]),
        ("Saturday 3rd October, 11am-2pm", [("2026-10-03", "2026-10-03")]),

        # Several days sharing a month named once, at the end. Touching
        # days join; a gap starts a new event.
        ("Saturday 5th & Sunday 6th and Saturday 12th & Sunday 13th December, 10am-4pm",
         [("2026-12-05", "2026-12-06"), ("2026-12-12", "2026-12-13")]),
        ("5th, 6th, 8th, 9th, 10th, 12th & 13th December",
         [("2026-12-05", "2026-12-06"), ("2026-12-08", "2026-12-10"),
          ("2026-12-12", "2026-12-13")]),
        ("Saturday 7th & Friday 13th November, 10:30am-1pm",
         [("2026-11-07", "2026-11-07"), ("2026-11-13", "2026-11-13")]),
        ("Saturday 7th & Friday 13th November, 1:30pm-4pm",
         [("2026-11-07", "2026-11-07"), ("2026-11-13", "2026-11-13")]),
        ("Thursday 1st & Thursday 8th October, 12pm-2pm",
         [("2026-10-01", "2026-10-01"), ("2026-10-08", "2026-10-08")]),

        # A month named per day rather than once at the end.
        ("Thursday 22nd October & Thursday 29th October, 11am-12pm",
         [("2026-10-22", "2026-10-22"), ("2026-10-29", "2026-10-29")]),

        # No day stated: real programmes, no readable date.
        ("Selected dates throughout December", []),
        ("Wednesday-Friday May-September, 10am-4pm", []),
        ("Wednesdays-Sundays throughout September, 10am-4pm", []),
    ]

    def test_every_string_the_site_publishes(self):
        for text, expected in self.CORPUS:
            self.assertEqual(date_runs(text, TODAY), expected, text)

    def test_the_corpus_is_the_whole_site(self):
        # 18 pages were on the index the day this was measured; if the
        # corpus shrinks, a shape stopped being covered.
        self.assertEqual(len(self.CORPUS), 18)


class TestReadingDates(unittest.TestCase):

    def test_a_time_is_not_a_day(self):
        # "10am-4pm" carries a 10 and a 4, and neither is a date. Only
        # the ordinal is a day.
        self.assertEqual(date_runs("Friday 11th September, 10am-4pm", TODAY),
                         [("2026-09-11", "2026-09-11")])

    def test_a_day_takes_the_month_named_after_it(self):
        # The month comes once at the end and governs every day before it.
        self.assertEqual(date_runs("5th & 6th December", TODAY),
                         [("2026-12-05", "2026-12-06")])

    def test_a_day_with_no_month_after_it_is_dropped(self):
        # Every one of the 18 puts the month after the days it governs.
        # Reading backwards as well would cover a shape this site does
        # not publish, on the guess that it means the same thing — and a
        # parser written for a shape nobody has seen is what slugdate.py
        # cost. An unread date is recoverable; a wrong one is not.
        self.assertEqual(date_runs("January 5th & 6th", TODAY), [])

    def test_the_year_is_the_next_occurrence(self):
        # March is well past on 5 September, so it is next year's.
        self.assertEqual(date_runs("Tuesday 3rd March", TODAY),
                         [("2027-03-03", "2027-03-03")])

    def test_an_event_that_has_just_started_stays_this_year(self):
        # Four days past, inside the month of grace: a run under way,
        # not one eleven months off.
        self.assertEqual(date_runs("1st September", TODAY),
                         [("2026-09-01", "2026-09-01")])

    def test_a_day_that_is_not_a_date_is_refused(self):
        self.assertEqual(date_runs("31st September", TODAY), [])

    def test_nothing_at_all(self):
        self.assertEqual(date_runs("", TODAY), [])
        self.assertEqual(date_runs("Open daily", TODAY), [])


class TestReadingAnEventPage(unittest.TestCase):

    def test_the_title_and_date_are_read(self):
        events = parse_event(CONCERT_PAGE, CONCERT, TODAY)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"],
                         "Raymond Yui and Kyle Nash-Baker in Concert")
        self.assertEqual(events[0]["start_date"], "2026-11-06")
        self.assertEqual(events[0]["end_date"], "2026-11-06")

    def test_the_venue_is_the_hall_itself(self):
        # A single-venue site does not repeat its address per event, and
        # an event the pipeline cannot place is dropped.
        event = parse_event(CONCERT_PAGE, CONCERT, TODAY)[0]
        self.assertEqual(event["location_name"], "Lamport Hall")
        self.assertEqual(event["location_postcode"], "NN6 9EZ")

    def test_two_weekends_are_two_events_with_distinct_ids(self):
        events = parse_event(MARKET_PAGE, MARKET, TODAY)
        self.assertEqual([(e["start_date"], e["end_date"]) for e in events],
                         [("2026-12-05", "2026-12-06"),
                          ("2026-12-12", "2026-12-13")])
        # Sharing a source_id would have the second overwrite the first.
        self.assertEqual(len({e["source_id"] for e in events}), 2)

    def test_a_page_with_no_readable_date_yields_nothing(self):
        self.assertEqual(parse_event(SHOP_PAGE, SHOP, TODAY), [])

    def test_the_description_is_the_prose_not_the_date(self):
        event = parse_event(CONCERT_PAGE, CONCERT, TODAY)[0]
        self.assertNotIn("6.00pm", event["description"])
        self.assertIn("Counties Heritage Foundation", event["description"])


class TestTheIndex(unittest.TestCase):

    def test_only_event_pages_are_listed_once_each(self):
        self.assertEqual(event_urls(INDEX_PAGE), [CONCERT, MARKET, SHOP])

    def test_the_index_does_not_list_itself(self):
        self.assertNotIn(INDEX, event_urls(INDEX_PAGE))

    def test_the_back_to_top_link_is_not_an_event(self):
        # href="/events/#scrolltop" reads as a slug unless the fragment
        # is dropped first, and did: a nineteenth page that fetched the
        # index again and was then reported as having no date.
        self.assertNotIn(f"{BASE}/events/#scrolltop", event_urls(INDEX_PAGE))

    def test_another_sites_events_path_is_not_ours(self):
        self.assertNotIn("https://www.facebook.com/events/12345/",
                         event_urls(INDEX_PAGE))


class TestTheCrawl(unittest.TestCase):

    def fetcher(self):
        return FakeFetcher({INDEX: INDEX_PAGE, CONCERT: CONCERT_PAGE,
                            MARKET: MARKET_PAGE, SHOP: SHOP_PAGE})

    def test_the_index_is_read_then_each_event(self):
        f = self.fetcher()
        list(LamportHall().scrape(f))
        self.assertEqual(f.fetched, [INDEX, CONCERT, MARKET, SHOP])

    def test_events_reach_the_database_at_the_hall(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('NN69EZ', 52.353, -0.879)")
        ok, message = run_source(db, self.fetcher(), LamportHall())
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("Raymond Yui and Kyle Nash-Baker in Concert",
              "2026-11-06", "2026-11-06"),
             ("Christmas Market", "2026-12-05", "2026-12-06"),
             ("Christmas Market", "2026-12-12", "2026-12-13")])

        # Every event at one venue, created once from its postcode.
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Lamport Hall", "NN6 9EZ")])


if __name__ == "__main__":
    unittest.main()
