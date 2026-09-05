"""NGS open gardens: a day you can turn up, not a season you can ring in.

The feed mixes both in one list. Records below are the shapes the live
API returns (5 Sep 2026): a same-day opening with times, a
by-arrangement window covering most of a year, a cancelled day, and one
already past. Telling the first from the rest is the whole job, and the
rule is what the dates say rather than what the undocumented
garden_opening_type_id says.
"""

import json
import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.ngs import NGS, open_days, parse_place

from schema import SCHEMA

TODAY = "2026-09-05"


def opening(start, end=None, type_id=1, canceled=0):
    return {"garden_opening_type_id": type_id,
            "start_date": f"{start} 11:00:00",
            "end_date": f"{end or start} 18:00:00",
            "canceled": canceled}


def garden(id, name, openings, lat=51.06, lng=0.61, postcode="TN17 4JB"):
    return {
        "id": id,
        "name": name,
        "town": "Cranbrook",
        "county": "Kent",
        "postcode": postcode,
        "description": "A fine garden with yew hedges and mixed borders.",
        "garden_type_id": 3,
        "tags": ["teas", "dogs"],
        "openings": openings,
        "position": {"lat": lat, "lng": lng},
    }


HOLE_PARK = garden(180, "Hole Park", [
    opening("2026-10-04"),                      # a day, still to come
    opening("2026-05-13"),                      # a day, already gone
    opening("2026-01-01", "2026-12-31", 4),     # by arrangement, all year
    opening("2026-11-02", canceled=1),          # called off
])

# Two gardens really can share a name, which is why events link by id.
OLD_VICARAGE_A = garden(300, "The Old Vicarage", [opening("2026-09-20")],
                        lat=53.10, lng=-1.55, postcode="DE4 4NH")
OLD_VICARAGE_B = garden(301, "The Old Vicarage", [opening("2026-09-27")],
                        lat=52.60, lng=1.30, postcode="NR12 8TP")

# Nothing to come: not published at all, since an NGS garden with no open
# day is somebody's private garden.
SHUT = garden(400, "Firby Hall", [opening("2026-01-01", "2026-12-31", 4),
                                  opening("2026-06-07")])

FEED = {"total": 4, "stats": {},
        "results": [HOLE_PARK, OLD_VICARAGE_A, OLD_VICARAGE_B, SHUT]}


class FakeFetcher:
    def __init__(self, body):
        self.body = body
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append((url, api))
        return self.body


class TestWhichOpeningsCount(unittest.TestCase):

    def test_only_a_future_uncancelled_day_is_an_open_day(self):
        self.assertEqual(open_days(HOLE_PARK, TODAY), ["2026-10-04"])

    def test_a_window_is_not_a_day(self):
        # 1 January to 31 December is "ring the owner", not "turn up".
        # Read from the dates, so a sixth opening type needs no change.
        window = garden(1, "G", [opening("2026-03-01", "2026-09-30", 3)])
        self.assertEqual(open_days(window, TODAY), [])

    def test_a_day_that_starts_today_still_counts(self):
        today = garden(1, "G", [opening(TODAY)])
        self.assertEqual(open_days(today, TODAY), [TODAY])

    def test_days_come_back_sorted_and_deduplicated(self):
        many = garden(1, "G", [opening("2026-11-02"), opening("2026-09-20"),
                               opening("2026-09-20")])
        self.assertEqual(open_days(many, TODAY), ["2026-09-20", "2026-11-02"])

    def test_a_garden_with_nothing_to_come_has_no_days(self):
        self.assertEqual(open_days(SHUT, TODAY), [])


class TestTheGardenAsAPlace(unittest.TestCase):

    def test_it_carries_its_own_coordinates(self):
        # The feed knows where the garden is, so the pipeline never
        # geocodes it — a garden down a lane is where the feed says, not
        # at its postcode's centroid.
        place = parse_place(HOLE_PARK)
        self.assertEqual((place["lat"], place["lon"]), (51.06, 0.61))
        self.assertEqual(place["postcode"], "TN17 4JB")
        self.assertEqual(place["category"], "garden")

    def test_the_link_is_the_gardens_own_page(self):
        self.assertEqual(parse_place(HOLE_PARK)["url"],
                         "https://findagarden.ngs.org.uk/garden/180/hole-park")

    def test_a_garden_with_no_coordinates_is_not_a_place(self):
        nowhere = garden(1, "G", [opening("2026-10-01")])
        nowhere["position"] = {}
        self.assertIsNone(parse_place(nowhere))


class TestTheRun(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def run_it(self):
        return run_source(self.db, FakeFetcher(json.dumps(FEED)), NGS(TODAY))

    def test_the_api_is_read_once_as_an_api(self):
        fetcher = FakeFetcher(json.dumps(FEED))
        list(NGS(TODAY).scrape(fetcher))
        self.assertEqual(
            fetcher.fetched,
            [("https://api.findagarden.ngs.org.uk/api/gardens", True)])

    def test_only_gardens_with_a_future_day_are_published(self):
        ok, message = self.run_it()
        self.assertTrue(ok, message)
        names = [r[0] for r in self.db.execute(
            "SELECT name FROM destinations ORDER BY name")]
        self.assertEqual(names, ["Hole Park", "The Old Vicarage",
                                 "The Old Vicarage"])
        self.assertNotIn("Firby Hall", names)

    def test_every_open_day_reaches_its_garden(self):
        self.run_it()
        rows = self.db.execute(
            "SELECT e.start_date, e.title, d.postcode FROM events e"
            " JOIN destinations d ON d.id = e.destination_id"
            " ORDER BY e.start_date").fetchall()
        self.assertEqual(rows, [
            ("2026-09-20", "The Old Vicarage open day", "DE4 4NH"),
            ("2026-09-27", "The Old Vicarage open day", "NR12 8TP"),
            ("2026-10-04", "Hole Park open day", "TN17 4JB"),
        ])

    def test_two_gardens_sharing_a_name_keep_their_own_days(self):
        # Linking by name would put both days at whichever garden was
        # matched first, two hundred miles from one of them.
        self.run_it()
        pairs = self.db.execute(
            "SELECT d.postcode, e.start_date FROM events e"
            " JOIN destinations d ON d.id = e.destination_id"
            " WHERE d.name = 'The Old Vicarage' ORDER BY e.start_date").fetchall()
        self.assertEqual(pairs, [("DE4 4NH", "2026-09-20"),
                                 ("NR12 8TP", "2026-09-27")])

    def test_a_cancelled_or_past_day_is_not_an_event(self):
        self.run_it()
        dates = {r[0] for r in self.db.execute("SELECT start_date FROM events")}
        self.assertNotIn("2026-11-02", dates)   # cancelled
        self.assertNotIn("2026-05-13", dates)   # past

    def test_the_title_says_what_the_event_is(self):
        # "Hole Park" at venue "Hole Park" tells a reader nothing.
        self.run_it()
        self.assertEqual(
            self.db.execute("SELECT title FROM events WHERE start_date ="
                            " '2026-10-04'").fetchone()[0],
            "Hole Park open day")


if __name__ == "__main__":
    unittest.main()
