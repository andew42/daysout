"""RHS shows: the detail is on the show's page, never on the listing.

Measured 5 Sep 2026, and it is the opposite way round from what the old
`sources` row assumed: `/shows-events` publishes no JSON-LD at all, while
each show's own page carries a clean Event object with dates and a full
address. A row pointed at the site root therefore looked where there was
nothing to find.

The fixture below keeps the two things that bite. Half the links on the
listing are not shows — an event search, a guide, a show with no dates
announced — and carry no Event data. And Sandringham publishes its
postcode as "PE31 6AT (please don't follow sat nav directions on
approach, please follow the event signs)": a real instruction to visitors,
inside a field meant to hold six characters.
"""

import json
import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.rhs import RHS, parse_event, show_urls

from schema import SCHEMA

BASE = "https://www.rhs.org.uk"
INDEX = f"{BASE}/shows-events"
CHELSEA = f"{BASE}/shows-events/rhs-chelsea-flower-show"
SANDRINGHAM = f"{BASE}/shows-events/rhs-sandringham-flower-show"
SEARCH = f"{BASE}/shows-events/event-search"

INDEX_PAGE = """<html><body>
  <a href="/shows-events/rhs-chelsea-flower-show">Chelsea</a>
  <a href="/shows-events/rhs-sandringham-flower-show">Sandringham</a>
  <a href="/shows-events/event-search">Search all events</a>
  <a href="/shows-events/rhs-chelsea-flower-show">Chelsea, pictured</a>
  <a href="/gardens/wisley">RHS Wisley</a>
  <a href="https://example.invalid/shows-events/elsewhere">Another site</a>
</body></html>"""


def show_page(name, start, end, postcode, street="London Gate"):
    data = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": name,
        "description": "The world&#39;s greatest flower show.",
        "url": f"{BASE}/shows-events/x",
        "startDate": start,
        "endDate": end,
        "location": {
            "@type": "Place",
            "name": name.replace(" Flower Show", " showground"),
            "address": {"@type": "PostalAddress", "streetAddress": street,
                        "addressLocality": "London", "postalCode": postcode},
        },
    }
    return (f'<html><head><script type="application/ld+json">'
            f'{json.dumps(data)}</script></head><body>{name}</body></html>')


CHELSEA_PAGE = show_page("RHS Chelsea Flower Show",
                         "2027-05-18T07:00:00.000Z", "2027-05-22T19:00:00.000Z",
                         "SW3 4SR")

# The postcode field with a sentence of visitor advice inside it.
SANDRINGHAM_PAGE = show_page(
    "RHS Sandringham Flower Show", "2026-07-22T07:00:00.000Z",
    "2026-07-26T19:00:00.000Z",
    "PE31 6AT (please don't follow sat nav directions on approach, "
    "please follow the event signs)")

# A listing-shaped page: an Organization, no Event.
SEARCH_PAGE = ('<html><head><script type="application/ld+json">'
               '{"@type": "Organization", "name": "RHS"}</script></head>'
               '<body>Search</body></html>')


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.pages[url]


def fetcher():
    return FakeFetcher({INDEX: INDEX_PAGE, CHELSEA: CHELSEA_PAGE,
                        SANDRINGHAM: SANDRINGHAM_PAGE, SEARCH: SEARCH_PAGE})


class TestTheListing(unittest.TestCase):

    def test_show_pages_are_found_once_each(self):
        self.assertEqual(show_urls(INDEX_PAGE), [CHELSEA, SANDRINGHAM, SEARCH])

    def test_other_sections_and_other_sites_are_left_alone(self):
        urls = show_urls(INDEX_PAGE)
        self.assertNotIn(f"{BASE}/gardens/wisley", urls)
        self.assertNotIn("https://example.invalid/shows-events/elsewhere", urls)


class TestReadingAShow(unittest.TestCase):

    def test_the_dates_come_off_the_json_ld(self):
        event = parse_event(CHELSEA_PAGE, CHELSEA)
        self.assertEqual((event["start_date"], event["end_date"]),
                         ("2027-05-18", "2027-05-22"))
        self.assertEqual(event["title"], "RHS Chelsea Flower Show")

    def test_a_postcode_buried_in_prose_is_still_a_postcode(self):
        # Storing the whole string would fail to geocode and lose the show.
        event = parse_event(SANDRINGHAM_PAGE, SANDRINGHAM)
        self.assertEqual(event["location_postcode"], "PE31 6AT")

    def test_entities_in_the_json_ld_are_decoded(self):
        # An entity stored here is one the reader sees, since the frontend
        # escapes what it interpolates.
        self.assertIn("world's", parse_event(CHELSEA_PAGE, CHELSEA)["description"])

    def test_a_page_with_no_event_is_not_one(self):
        self.assertIsNone(parse_event(SEARCH_PAGE, SEARCH))

    def test_a_page_with_no_json_ld_at_all(self):
        self.assertIsNone(parse_event("<html><body>nothing</body></html>", SEARCH))


class TestTheRun(unittest.TestCase):

    def test_the_listing_is_read_then_each_linked_page(self):
        f = fetcher()
        list(RHS().scrape(f))
        self.assertEqual(f.fetched, [INDEX, CHELSEA, SANDRINGHAM, SEARCH])

    def test_only_the_shows_become_events(self):
        events = [e for _, e in RHS().scrape(fetcher())]
        self.assertEqual([e["title"] for e in events],
                         ["RHS Chelsea Flower Show", "RHS Sandringham Flower Show"])

    def test_the_shows_reach_the_database_at_their_own_venues(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        for pc, lat, lon in [("SW34SR", 51.487, -0.159),
                             ("PE316AT", 52.828, 0.515)]:
            db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                       " VALUES (?, ?, ?)", (pc, lat, lon))
        ok, message = run_source(db, fetcher(), RHS())
        self.assertTrue(ok, message)

        self.assertEqual(
            db.execute("SELECT title, start_date, end_date FROM events"
                       " ORDER BY start_date").fetchall(),
            [("RHS Sandringham Flower Show", "2026-07-22", "2026-07-26"),
             ("RHS Chelsea Flower Show", "2027-05-18", "2027-05-22")])
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
