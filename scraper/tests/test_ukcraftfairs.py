"""UK Craft Fairs: the calendar is an index, the fair's own page the source.

The markup below is verbatim from what the house server rendered on
31 Aug 2026. Two things about it drive the parser and so are pinned here:

  * A day page is a *single day's* view, and the date on a row is the
    fair's START with "(N day event)" giving its length — which is why a
    page headed the 31st carries fairs dated the 29th.
  * .panel-list matches both the outer <a> and the panel inside it, so a
    naive select finds every fair twice.

Neither page carries a postcode on the listing, and without one the
pipeline drops the event, so the fair's own page is fetched for it.
"""

import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.ukcraftfairs import (
    UKCraftFairs, day_url, parse_listing)

from datetime import date

from schema import SCHEMA

BASE = "https://www.ukcraftfairs.com"
LOWTHER = f"{BASE}/craft-events/26533/lowther-gardens-food-and-drink-festival"
HAWES = f"{BASE}/craft-events/26465/august-bank-holiday-craft-fair-in-hawes-wensleydale"
NOWHERE = f"{BASE}/craft-events/26999/a-fair-with-no-address"

# Verbatim from the render, including the class lists.
LOWTHER_ROW = """
<a class="grid-item panel-list" href="/craft-events/26533/lowther-gardens-food-and-drink-festival"><div class="panel panel-default panel-list CyberspaceReposeGray"><div class="panel-body panel-list-heading CyberspaceReposeGray text-center"><h2 class="h4">Lowther Gardens Food and Drink Festival</h2></div><div class="panel-body panel-list-bottom ReposeGrayCyberspace text-center"><span class="circleA circleColoursFair"><span class="circleText">Craft Fair</span></span><p><strong>Lowther Gardens</strong>, Lytham St Annes, Lancashire</p><p>Saturday, <strong>29 August 2026</strong> (3 day event)</p></div></div></a>
"""

HAWES_ROW = """
<a class="grid-item panel-list" href="/craft-events/26465/august-bank-holiday-craft-fair-in-hawes-wensleydale"><div class="panel panel-default panel-list CyberspaceReposeGray"><div class="panel-body panel-list-heading CyberspaceReposeGray text-center"><h2 class="h4">August Bank Holiday Craft Fair in Hawes Wensleydale</h2></div><div class="panel-body panel-list-bottom ReposeGrayCyberspace text-center"><img alt="August Bank Holiday Craft Fair in Hawes Wensleydale" class="panel-list-img panel-list-img-fairs" loading="lazy" src="/images/uploaded/craft-fair-26465-thumb.jpg" title="August Bank Holiday Craft Fair in Hawes Wensleydale"/><p><strong>The Market House</strong>, Hawes, Wensleydale, North Yorkshire</p><p>Thursday, <strong>27 August 2026</strong> (1 day event)</p></div></div></a>
"""

NOWHERE_ROW = """
<a class="grid-item panel-list" href="/craft-events/26999/a-fair-with-no-address"><div class="panel panel-default panel-list"><div class="panel-body panel-list-heading text-center"><h2 class="h4">A Fair With No Address</h2></div><div class="panel-body panel-list-bottom text-center"><p><strong>Somewhere Hall</strong>, Elsewhere</p><p>Sunday, <strong>30 August 2026</strong> (1 day event)</p></div></div></a>
"""

# The day page's own navigation, which points at /calendar and must not be
# mistaken for a fair.
NAV = ('<h1 class="page-header modal-title h6 text-center">Monday, 31 August 2026</h1>'
       '<a href="/calendar/31-august-2026">&lt;</a>'
       '<a href="/calendar/1-september-2026">&gt;</a>'
       '<a href="/calendar/today">Today</a>')

DAY_PAGE = f"<html><body>{NAV}{LOWTHER_ROW}{HAWES_ROW}{NOWHERE_ROW}</body></html>"

# Its JSON-LD has no endDate and no postalCode; the postcode is in the
# prose beside the map, exactly as the deploy printed it. Note the
# startDate: this site does not zero-pad, so "2026-8-29T10:00:00" is what
# arrives, and its first ten characters are "2026-8-29T" — not a date.
LOWTHER_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event",
 "name":"Lowther Gardens Food and Drink Festival",
 "startDate":"2026-8-29T10:00:00",
 "location":{"@type":"Place","name":"Lowther Gardens"}}
</script></head><body>
<p>Lowther Gardens West Beach, Lytham St Annes , Lancashire , FY8 5QQ</p>
</body></html>"""

# This one publishes the lot, including a structured postcode.
HAWES_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event",
 "name":"August Bank Holiday Craft Fair in Hawes Wensleydale",
 "startDate":"2026-8-27T10:00:00","endDate":"2026-8-27T16:00:00",
 "location":{"@type":"Place","name":"The Market House",
   "address":{"@type":"PostalAddress","postalCode":"DL8 3QR"}}}
</script></head><body></body></html>"""

NOWHERE_PAGE = "<html><body><p>Somewhere Hall, Elsewhere. Details to follow.</p></body></html>"


class FakeFetcher:
    """Answers any calendar day with the same listing, as a quiet site would."""

    def __init__(self, pages=None):
        self.pages = pages if pages is not None else {
            LOWTHER: LOWTHER_PAGE, HAWES: HAWES_PAGE, NOWHERE: NOWHERE_PAGE}
        self.fetched = []
        self.rendered = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        if render:
            self.rendered.append(url)
        if "/calendar/" in url:
            return DAY_PAGE
        if url in self.pages:
            return self.pages[url]
        raise RuntimeError(f"unexpected fetch {url}")


class TestTheDayURL(unittest.TestCase):

    def test_it_is_the_shape_the_page_links_to(self):
        # The site's own > link on 31 August 2026.
        self.assertEqual(day_url(date(2026, 9, 1)),
                         f"{BASE}/calendar/1-september-2026")

    def test_no_zero_padding(self):
        self.assertEqual(day_url(date(2026, 8, 5)),
                         f"{BASE}/calendar/5-august-2026")


class TestReadingADayPage(unittest.TestCase):

    def test_each_fair_is_found_once(self):
        # .panel-list matches the anchor and the panel inside it, so the
        # obvious selector reports every fair twice.
        rows = parse_listing(DAY_PAGE)
        self.assertEqual([row["source_id"] for row in rows],
                         ["26533", "26465", "26999"])

    def test_the_title_comes_from_the_heading_not_the_image(self):
        # One row has no <img> at all, only a "Craft Fair" badge.
        rows = {row["source_id"]: row for row in parse_listing(DAY_PAGE)}
        self.assertEqual(rows["26533"]["title"],
                         "Lowther Gardens Food and Drink Festival")

    def test_a_multi_day_fair_runs_from_its_start(self):
        # "29 August 2026 (3 day event)" on a page headed the 31st.
        rows = {row["source_id"]: row for row in parse_listing(DAY_PAGE)}
        self.assertEqual(rows["26533"]["start_date"], "2026-08-29")
        self.assertEqual(rows["26533"]["end_date"], "2026-08-31")

    def test_a_one_day_fair_starts_and_ends_the_same_day(self):
        rows = {row["source_id"]: row for row in parse_listing(DAY_PAGE)}
        self.assertEqual(rows["26465"]["start_date"], "2026-08-27")
        self.assertEqual(rows["26465"]["end_date"], "2026-08-27")

    def test_the_venue_is_the_bold_text_that_is_not_a_date(self):
        rows = {row["source_id"]: row for row in parse_listing(DAY_PAGE)}
        self.assertEqual(rows["26533"]["venue_name"], "Lowther Gardens")
        self.assertEqual(rows["26465"]["venue_name"], "The Market House")

    def test_navigation_links_are_not_fairs(self):
        self.assertNotIn("/calendar/", str([r["url"] for r in parse_listing(DAY_PAGE)]))


class TestReadingAFairsOwnPage(unittest.TestCase):

    def events(self):
        return {event["source_id"]: event
                for _, event in UKCraftFairs().scrape(FakeFetcher())}

    def test_a_fair_is_read_once_however_many_days_it_appears_on(self):
        # Every day page lists the same fairs; a three-day fair is one row.
        events = self.events()
        self.assertEqual(sorted(events), ["26465", "26533"])

    def test_the_postcode_is_taken_from_the_page_when_the_jsonld_lacks_one(self):
        self.assertEqual(self.events()["26533"]["location_postcode"], "FY8 5QQ")

    def test_a_structured_postcode_is_used_when_there_is_one(self):
        self.assertEqual(self.events()["26465"]["location_postcode"], "DL8 3QR")

    def test_the_listing_supplies_an_end_date_the_jsonld_omits(self):
        # Its JSON-LD gives only startDate, which would make a three-day
        # fair look like a one-day one.
        self.assertEqual(self.events()["26533"]["end_date"], "2026-08-31")

    def test_an_unpadded_jsonld_date_is_read_not_sliced(self):
        # The site publishes "2026-8-29T10:00:00". Slicing ten characters
        # off that gives "2026-8-29T", which upsert_event refuses — all 26
        # fairs were read correctly and thrown away on the first live run.
        self.assertEqual(self.events()["26533"]["start_date"], "2026-08-29")
        self.assertEqual(self.events()["26465"]["start_date"], "2026-08-27")

    def test_a_fair_with_no_postcode_anywhere_is_dropped(self):
        # The pipeline could not place it, so it is not offered.
        self.assertNotIn("26999", self.events())

    def test_every_page_is_rendered_because_plain_fetching_cannot_work(self):
        fetcher = FakeFetcher()
        list(UKCraftFairs().scrape(fetcher))
        self.assertEqual(fetcher.fetched, fetcher.rendered)

    def test_the_run_is_bounded_by_max_pages(self):
        fetcher = FakeFetcher()
        list(UKCraftFairs().scrape(fetcher, max_pages=1))
        self.assertEqual(len([u for u in fetcher.fetched if "/calendar/" in u]), 1)


class TestTheEventsReachTheDatabase(unittest.TestCase):

    def test_fairs_land_with_a_venue_of_their_own(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        for postcode, lat, lon in (("FY85QQ", 53.736, -2.998),
                                   ("DL83QR", 54.306, -2.196)):
            db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                       " VALUES (?, ?, ?)", (postcode, lat, lon))

        ok, message = run_source(db, FakeFetcher(), UKCraftFairs())
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("August Bank Holiday Craft Fair in Hawes Wensleydale",
              "2026-08-27", "2026-08-27"),
             ("Lowther Gardens Food and Drink Festival",
              "2026-08-29", "2026-08-31")])

        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations"
                       " ORDER BY name").fetchall(),
            [("Lowther Gardens", "FY8 5QQ"), ("The Market House", "DL8 3QR")])


if __name__ == "__main__":
    unittest.main()
