"""Stonor: the API lists the events and dates none of them.

Its old route, The Events Calendar's /wp-json/tribe/..., 404s now. The
site registers its own `events` post type instead, which gives six events
and their links with no meta and no acf — so the API is the index and each
page carries the Event JSON-LD.

The fixture keeps the two things this site taught the project. Its dates
are day-first and slashed, which is where "02/05/2026" got stored raw and
made five events invisible while the run called them linked. And its
titles arrive escaped, which reaches the reader because the frontend
escapes what it interpolates.
"""

import json
import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.stonor import API, Stonor, event_urls, parse_event

from schema import SCHEMA

BASE = "https://www.stonor.com"
JOUST = f"{BASE}/events/medieval-jousting-september/"
CHRISTMAS = f"{BASE}/events/christmas-at-stonor/"
NO_EVENT = f"{BASE}/events/plan-your-visit/"

LISTING = json.dumps([
    {"id": 1, "link": JOUST, "title": {"rendered": "Medieval Jousting"}},
    {"id": 2, "link": CHRISTMAS, "title": {"rendered": "Christmas"}},
    {"id": 3, "link": NO_EVENT, "title": {"rendered": "Plan your visit"}},
    # Somebody else's link has no business being fetched as ours.
    {"id": 4, "link": "https://example.invalid/events/elsewhere/"},
])


def page(name, start, end):
    data = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": name,
        "description": "A day out at Stonor.",
        "startDate": start,
        "endDate": end,
        "location": {
            "@type": "Place", "name": "Stonor Park",
            "address": {"@type": "PostalAddress", "streetAddress": "Stonor",
                        "addressLocality": "Henley-on-Thames",
                        "postalCode": "RG9 6HF"},
        },
    }
    return (f'<html><head><script type="application/ld+json">'
            f'{json.dumps(data)}</script></head><body>{name}</body></html>')


# Day-first and slashed, exactly as the site publishes it.
JOUST_PAGE = page("Medieval Jousting &#8211; The Ultimate medieval rematch",
                  "19/09/2026", "20/09/2026")
CHRISTMAS_PAGE = page("Christmas at Stonor", "05/12/2026", "24/12/2026")
NO_EVENT_PAGE = ('<html><head><script type="application/ld+json">'
                 '{"@type": "WebPage", "name": "Plan your visit"}'
                 '</script></head><body>Visit</body></html>')


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append((url, api))
        return self.pages[url]


def fetcher():
    return FakeFetcher({API: LISTING, JOUST: JOUST_PAGE,
                        CHRISTMAS: CHRISTMAS_PAGE, NO_EVENT: NO_EVENT_PAGE})


class TestTheIndex(unittest.TestCase):

    def test_the_api_gives_the_pages_to_read(self):
        self.assertEqual(event_urls(json.loads(LISTING)),
                         [JOUST, CHRISTMAS, NO_EVENT])

    def test_a_link_to_another_site_is_not_ours_to_fetch(self):
        self.assertNotIn("https://example.invalid/events/elsewhere/",
                         event_urls(json.loads(LISTING)))


class TestReadingAnEvent(unittest.TestCase):

    def test_a_day_first_date_is_read_in_the_right_order(self):
        # "19/09/2026" is 19 September, not 9 July. Slicing ten
        # characters off it is what made five Stonor events invisible.
        event = parse_event(JOUST_PAGE, JOUST)
        self.assertEqual((event["start_date"], event["end_date"]),
                         ("2026-09-19", "2026-09-20"))

    def test_the_title_is_unescaped(self):
        self.assertEqual(parse_event(JOUST_PAGE, JOUST)["title"],
                         "Medieval Jousting – The Ultimate medieval rematch")

    def test_the_venue_comes_from_the_structured_address(self):
        event = parse_event(JOUST_PAGE, JOUST)
        self.assertEqual(event["location_name"], "Stonor Park")
        self.assertEqual(event["location_postcode"], "RG9 6HF")

    def test_the_slug_is_the_id_so_an_annual_event_keeps_its_row(self):
        self.assertEqual(parse_event(JOUST_PAGE, JOUST)["source_id"],
                         "medieval-jousting-september")

    def test_a_page_with_no_event_is_not_one(self):
        self.assertIsNone(parse_event(NO_EVENT_PAGE, NO_EVENT))


class TestTheRun(unittest.TestCase):

    def test_the_api_is_read_as_an_api_then_each_page_plainly(self):
        f = fetcher()
        list(Stonor().scrape(f))
        self.assertEqual(f.fetched, [(API, True), (JOUST, False),
                                     (CHRISTMAS, False), (NO_EVENT, False)])

    def test_the_events_reach_the_database_at_stonor_park(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('RG96HF', 51.556, -0.949)")
        ok, message = run_source(db, fetcher(), Stonor())
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("Medieval Jousting – The Ultimate medieval rematch",
              "2026-09-19", "2026-09-20"),
             ("Christmas at Stonor", "2026-12-05", "2026-12-24")])
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Stonor Park", "RG9 6HF")])


if __name__ == "__main__":
    unittest.main()
