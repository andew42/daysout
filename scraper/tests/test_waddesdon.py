"""Waddesdon: read the event's dates, not the day somebody typed it up.

Every record below is the shape the live API returned on 5 Sep 2026,
including the two date spellings it mixes — a bare "2026-10-18T13:08:53"
and an offset "2026-08-14T00:00:00+01:00" — because the offset is the
one that can move an event a day if it is ever treated as an instant.
"""

import json
import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.waddesdon import Waddesdon, parse_event

from schema import SCHEMA

BASE = "https://waddesdon.org.uk"
EVENTS = f"{BASE}/wp-json/wp/v2/events?per_page=100&page=1"
CATEGORIES = f"{BASE}/wp-json/wp/v2/event-categories?per_page=100"

TODAY = "2026-09-05"

# Term ids as the live taxonomy numbers them, slugs and all.
CATEGORY_TERMS = [
    {"id": 56, "slug": "arts-culture-3339", "name": "Arts &amp; Culture"},
    {"id": 55, "slug": "evening-3340", "name": "Evening"},
    {"id": 61, "slug": "exhibitions", "name": "Exhibitions"},
    {"id": 59, "slug": "families-3335", "name": "Families"},
    {"id": 57, "slug": "food-wine-3338", "name": "Food &amp; Wine"},
    {"id": 58, "slug": "nature-3336", "name": "Nature"},
    {"id": 60, "slug": "tours-talks-3334", "name": "Tours &amp; Talks"},
]


def record(id, title, start, end, categories=(), excerpt="", display="",
           slug="event"):
    return {
        "id": id,
        "link": f"{BASE}/whats-on/{slug}/",
        "status": "publish",
        # The post date: when the entry was published, not when it runs.
        "date": "2026-08-07T12:09:44",
        "title": {"rendered": title},
        "excerpt": {"rendered": f"<p>{excerpt}</p>"},
        "event-categories": list(categories),
        "event-locations": [],
        "meta": {
            "rothschild_event_start_date": start,
            "rothschild_event_end_date": end,
            "rothschild_event_date_range_display": display,
        },
    }


CHILLI = record(
    101, "Chilli Fest", "2026-09-05T00:00:00", "2026-09-06T23:59:00+01:00",
    categories=[59, 57], excerpt="A weekend of chilli.", display="5 - 6 September",
    slug="chilli-fest")

# Midnight on the 14th British time is 23:00 on the 13th UTC.
TOUR = record(
    102, "Contemporary Art &amp; Architecture Tour",
    "2026-10-14T00:00:00+01:00", "2026-10-14T23:59:00+01:00",
    categories=[56], display="14 October", slug="art-architecture-tours")

# A span whose display says the span is not when you can turn up.
GIANTS = record(
    103, "Standing With Giants (Twilight Opening)",
    "2026-11-06T00:00:00+00:00", "2026-11-28T23:59:00+00:00",
    categories=[60], excerpt="An installation after dark.",
    display="Every Friday and Saturday", slug="standing-with-giants-twilight")

# Finished in August; nothing takes an old event down.
OVER = record(
    104, "Standing With Giants Recruitment Day",
    "2026-08-15T16:02:46", "2026-08-15T16:02:48", display="15 August",
    slug="recruitment-day")

# Sub-location on the estate, which must not become a venue of its own.
CELLAR = record(
    105, "Cellar Tour &amp; History of Rothschild Wines",
    "2026-09-12T00:00:00+01:00", "2026-11-27T23:59:00+00:00",
    categories=[57], display="Every Friday until 27 November", slug="cellar-tour")
CELLAR["event-locations"] = [63]

ALL = [CHILLI, TOUR, GIANTS, OVER, CELLAR]


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.pages[url]


def fetcher(records=None):
    return FakeFetcher({
        CATEGORIES: json.dumps(CATEGORY_TERMS),
        EVENTS: json.dumps(ALL if records is None else records),
    })


def categories():
    return {56: "art", 61: "art", 57: "food", 58: "garden"}


class TestReadingARecord(unittest.TestCase):

    def test_the_event_dates_come_from_meta_not_the_post_date(self):
        # The post was published on 7 August; the event is in September.
        event = parse_event(CHILLI, categories(), "historic-house")
        self.assertEqual(event["start_date"], "2026-09-05")
        self.assertEqual(event["end_date"], "2026-09-06")

    def test_an_offset_does_not_move_the_event_a_day_earlier(self):
        # 2026-10-14T00:00:00+01:00 is 23:00 on the 13th UTC. The
        # published calendar date is the answer, not the instant.
        self.assertEqual(parse_event(TOUR, categories(), "historic-house")["start_date"],
                         "2026-10-14")

    def test_wordpress_entities_are_decoded(self):
        self.assertEqual(parse_event(TOUR, categories(), "historic-house")["title"],
                         "Contemporary Art & Architecture Tour")

    def test_the_venue_is_the_manor_not_a_room_inside_it(self):
        # event-locations says "Wine Cellars"; geocoding that would drop
        # a second pin with no address of its own.
        event = parse_event(CELLAR, categories(), "historic-house")
        self.assertEqual(event["location_name"], "Waddesdon Manor")
        self.assertEqual(event["location_postcode"], "HP18 0JH")

    def test_the_id_is_the_source_id(self):
        self.assertEqual(parse_event(CHILLI, categories(), "historic-house")["source_id"],
                         "101")

    def test_a_record_with_no_start_date_is_refused(self):
        self.assertIsNone(
            parse_event(record(9, "Undated", "", ""), categories(), "historic-house"))

    def test_an_event_with_no_end_date_lasts_one_day(self):
        event = parse_event(record(9, "One Day", "2026-10-01T00:00:00", ""),
                            categories(), "historic-house")
        self.assertEqual((event["start_date"], event["end_date"]),
                         ("2026-10-01", "2026-10-01"))


class TestCategories(unittest.TestCase):

    def test_the_events_own_category_beats_the_houses(self):
        # Families and Food & Wine both; a chilli fest is food.
        self.assertEqual(
            parse_event(CHILLI, categories(), "historic-house")["category"], "food")

    def test_an_unmapped_category_falls_back_to_the_venue(self):
        # Tours & Talks is not one of the app's categories.
        self.assertEqual(
            parse_event(GIANTS, categories(), "historic-house")["category"],
            "historic-house")

    def test_the_terms_are_matched_by_name_not_slug(self):
        # Read end to end through the real taxonomy JSON, whose slugs
        # carry an import artefact ("food-wine-3338") that the names do
        # not: keying the map on the slug would file this as the house.
        found = [e for _, e in Waddesdon(TODAY).scrape(fetcher())
                 if e["title"] == "Chilli Fest"]
        self.assertEqual(found[0]["category"], "food")


class TestDescriptions(unittest.TestCase):

    def test_a_recurrence_is_said_out_loud(self):
        # Stored as 6-28 November; a reader given only that turns up on
        # a Tuesday.
        event = parse_event(GIANTS, categories(), "historic-house")
        self.assertTrue(event["description"].startswith("Every Friday and Saturday."))

    def test_a_plain_date_range_is_not_repeated_into_the_description(self):
        event = parse_event(CHILLI, categories(), "historic-house")
        self.assertEqual(event["description"], "A weekend of chilli.")


class TestTheCrawl(unittest.TestCase):

    def test_an_event_that_is_over_is_not_reported(self):
        events = [e for _, e in Waddesdon(TODAY).scrape(fetcher())]
        self.assertNotIn("Standing With Giants Recruitment Day",
                         [e["title"] for e in events])
        self.assertEqual(len(events), 4)

    def test_an_event_running_today_is_still_on(self):
        # Ends today: still worth showing, and the store's own filter
        # agrees (end_date >= today).
        events = [e for _, e in Waddesdon("2026-09-06").scrape(fetcher())]
        self.assertIn("Chilli Fest", [e["title"] for e in events])

    def test_the_categories_are_read_once_before_the_events(self):
        f = fetcher()
        list(Waddesdon(TODAY).scrape(f))
        self.assertEqual(f.fetched, [CATEGORIES, EVENTS])

    def test_a_short_page_is_the_last_one(self):
        # Five records against a hundred a page: no second page is asked
        # for, so running off the end never has to be handled.
        f = fetcher()
        list(Waddesdon(TODAY).scrape(f))
        self.assertNotIn(f"{BASE}/wp-json/wp/v2/events?per_page=100&page=2",
                         f.fetched)

    def test_events_lost_to_a_missing_taxonomy_still_arrive(self):
        # A category is a nicety; the events are the point.
        f = FakeFetcher({EVENTS: json.dumps(ALL)})
        events = [e for _, e in Waddesdon(TODAY).scrape(f)]
        self.assertEqual(len(events), 4)
        self.assertEqual({e["category"] for e in events}, {"historic-house"})

    def test_events_reach_the_database_at_the_manor(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                   " VALUES ('HP180JH', 51.840, -0.947)")
        ok, message = run_source(db, fetcher(), Waddesdon(TODAY))
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("Chilli Fest", "2026-09-05", "2026-09-06"),
             ("Cellar Tour & History of Rothschild Wines",
              "2026-09-12", "2026-11-27"),
             ("Contemporary Art & Architecture Tour", "2026-10-14", "2026-10-14"),
             ("Standing With Giants (Twilight Opening)",
              "2026-11-06", "2026-11-28")])

        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchall(),
            [("Waddesdon Manor", "HP18 0JH")])


if __name__ == "__main__":
    unittest.main()
