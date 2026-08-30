"""Shuttleworth: read the event's own date, not the six on every page.

Its pages carry no Event JSON-LD, no <time> and no date-classed
elements, and 0% of its URLs carry a date — so "the page has
date-looking text" was all the earlier attempt had, and every page has
seven such phrases. The markup below is the shape the deploy printed:
the event's own date under ul.icon-list, the carousel of other events
under ul.icon-list.text-muted inside li.swiper-slide, and a timetabled
show that gives its days as itinerary headings instead.
"""

import sqlite3
import unittest

from daysout_scraper import dates
from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.shuttleworth import Shuttleworth, parse_event

from schema import SCHEMA

BASE = "https://www.shuttleworth.org"
SITEMAP_URL = f"{BASE}/sitemap.xml"
MARKET = f"{BASE}/events/christmas-market-at-shuttleworth-house"
AIRSHOW = f"{BASE}/events/military-air-show-2026"

SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{AIRSHOW}</loc><lastmod>2026-08-28</lastmod></url>
  <url><loc>{MARKET}</loc><lastmod>2026-08-27</lastmod></url>
  <url><loc>{BASE}/visit/help-faqs/opening-times</loc><lastmod>2026-08-20</lastmod></url>
</urlset>"""

# The same six events are advertised at the foot of every event page.
CAROUSEL = """
<ul class="swiper-wrapper">
  <li class="swiper-slide">
    <a href="/events/comedy-night-at-shuttleworth-house-september">Comedy Night</a>
    <ul class="icon-list text-muted my-3"><li>4 September 2026</li></ul>
  </li>
  <li class="swiper-slide">
    <a href="/events/wedding-show-at-shuttleworth">Wedding Show</a>
    <ul class="icon-list text-muted my-3"><li>6 September 2026</li></ul>
  </li>
  <li class="swiper-slide">
    <a href="/events/flying-proms">Flying Proms</a>
    <ul class="icon-list text-muted my-3"><li>18 - 20 September 2026</li></ul>
  </li>
</ul>"""

FOOTER = ('<footer>Shuttleworth, Old Warden Park, Biggleswade, '
          'Bedfordshire SG18 9DT</footer>')

MARKET_PAGE = f"""<html><head><title>Christmas Market - Shuttleworth</title></head>
  <body>
    <h1>Christmas Market at Shuttleworth House</h1>
    <ul class="icon-list"><li>5 -  6 December 2026</li></ul>
    {CAROUSEL}{FOOTER}
  </body></html>"""

# A timetabled show: no icon-list date, days given as itinerary headings.
AIRSHOW_PAGE = f"""<html><head><title>Military Air Show - Shuttleworth</title></head>
  <body>
    <h1>Military Air Show 2026</h1>
    <button class="nav-link heading-font px-2 active">Sat 29 August 2026</button>
    <h5 class="itinerary-listing--day--title">29 August 2026</h5>
    <h5 class="itinerary-listing--day--title">30 August 2026</h5>
    {CAROUSEL}{FOOTER}
  </body></html>"""

UNDATED_PAGE = f"""<html><body><h1>Something Or Other</h1>
  {CAROUSEL}{FOOTER}</body></html>"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.pages[url]


class TestReadingAnEventPage(unittest.TestCase):

    def test_the_events_own_date_is_read(self):
        event = parse_event(MARKET_PAGE, MARKET)
        self.assertEqual(event["start_date"], "2026-12-05")
        self.assertEqual(event["end_date"], "2026-12-06")
        self.assertEqual(event["title"], "Christmas Market at Shuttleworth House")

    def test_the_carousel_of_other_events_is_not_mistaken_for_it(self):
        # 4 September is the first date in the markup order on some pages
        # and belongs to a different event entirely.
        event = parse_event(MARKET_PAGE, MARKET)
        self.assertNotEqual(event["start_date"], "2026-09-04")

    def test_a_timetabled_show_runs_from_its_first_day_to_its_last(self):
        event = parse_event(AIRSHOW_PAGE, AIRSHOW)
        self.assertEqual(event["start_date"], "2026-08-29")
        self.assertEqual(event["end_date"], "2026-08-30")

    def test_the_venue_postcode_comes_off_the_page(self):
        # One venue publishing its own events, so the address in the page
        # chrome is the venue's — the opposite of a directory site.
        self.assertEqual(parse_event(MARKET_PAGE, MARKET)["location_postcode"],
                         "SG18 9DT")

    def test_a_page_with_no_date_of_its_own_is_skipped(self):
        # Not given the carousel's first date, which is what "take the
        # first date on the page" would have done.
        self.assertIsNone(parse_event(UNDATED_PAGE, MARKET))


class TestTheCrawl(unittest.TestCase):

    def fetcher(self):
        return FakeFetcher({SITEMAP_URL: SITEMAP,
                            MARKET: MARKET_PAGE, AIRSHOW: AIRSHOW_PAGE})

    def test_only_event_pages_are_fetched(self):
        f = self.fetcher()
        list(Shuttleworth().scrape(f))
        self.assertEqual(f.fetched, [SITEMAP_URL, AIRSHOW, MARKET])

    def test_events_reach_the_database_with_a_venue(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('SG189DT', 52.083, -0.319)")
        ok, message = run_source(db, self.fetcher(), Shuttleworth())
        self.assertTrue(ok, message)
        rows = db.execute(
            "SELECT title, start_date, end_date FROM events ORDER BY start_date"
        ).fetchall()
        self.assertEqual(rows, [
            ("Military Air Show 2026", "2026-08-29", "2026-08-30"),
            ("Christmas Market at Shuttleworth House", "2026-12-05", "2026-12-06"),
        ])
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Shuttleworth", "SG18 9DT")])


class TestDateRanges(unittest.TestCase):
    """Every shape seen in the deploy's own output."""

    def test_the_real_shapes(self):
        for text, expected in [
            ("5 -  6 December 2026", ("2026-12-05", "2026-12-06")),
            ("18 - 20 September 2026", ("2026-09-18", "2026-09-20")),
            ("4 September 2026", ("2026-09-04", "2026-09-04")),
            ("Sat 29 August 2026", ("2026-08-29", "2026-08-29")),
            ("29 August - 1 September 2026", ("2026-08-29", "2026-09-01")),
            ("31 October 2026", ("2026-10-31", "2026-10-31")),
        ]:
            self.assertEqual(dates.parse_range(text), expected, text)

    def test_a_range_that_runs_into_the_next_year(self):
        self.assertEqual(dates.parse_range("29 December - 2 January 2026"),
                         ("2026-12-29", "2027-01-02"))
