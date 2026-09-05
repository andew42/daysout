"""The food festival roundup, placed by town because it gives no postcode.

The markup below is the shape the live page carries (5 Sep 2026): an h3
whose link leaves for the festival's own site, and a paragraph opening
with the date in a <strong>. What this source exists to prove is that a
listing with no address in it can still reach the map, so the tests that
matter most are the ones about which town a heading offers and what
happens when none of them is a place we hold.
"""

import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.foodfestivals import (
    URL, FoodFestivals, parse_page, place_candidates)

from schema import SCHEMA


def entry(title, when, prose, href="https://example.invalid/"):
    return (f'<h3><a href="{href}" target="_blank">{title}</a></h3>'
            f"<p><strong>{when}</strong>. {prose}</p>")


PAGE = f"""<html><body>
  <h2>The Ultimate Guide to Food &amp; Drink Festivals in the UK</h2>
  <h4>February</h4>
  {entry("Olney Pancake Race, Buckinghamshire", "Tuesday 17 February 2026",
         "It&#8217;s flipping traditional!", "http://olneypancakerace.org/")}
  {entry("Wakefield Rhubarb Festival", "20 &#8211; 22 February 2026",
         "In the heart of England&#8217;s Rhubarb Triangle.")}
  <h4>September</h4>
  {entry("Foodies Festival, Bath, Somerset", "4 - 6 September 2026",
         "Chefs, music and street food.")}
  {entry("Great British Food Festival, Arley Hall, Cheshire",
         "12 - 13 September 2026", "A country house food festival.")}
  <h4>Undated</h4>
  <h3><a href="https://example.invalid/x">Exmoor Food Fest</a></h3>
  <p>Every year in February a range of restaurants offer good food.</p>
</body></html>"""


class FakeFetcher:
    def __init__(self, body):
        self.body = body
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.body


class TestReadingThePage(unittest.TestCase):

    def test_every_festival_is_seen_dated_or_not(self):
        self.assertEqual(len(parse_page(PAGE)), 5)

    def test_a_date_is_read_with_its_own_year(self):
        # No inference needed here, unlike Lamport Hall: the year is on
        # the page.
        events = {t: e for t, e in parse_page(PAGE) if e}
        olney = events["Olney Pancake Race, Buckinghamshire"]
        self.assertEqual((olney["start_date"], olney["end_date"]),
                         ("2026-02-17", "2026-02-17"))
        rhubarb = events["Wakefield Rhubarb Festival"]
        self.assertEqual((rhubarb["start_date"], rhubarb["end_date"]),
                         ("2026-02-20", "2026-02-22"))

    def test_an_entry_with_no_readable_date_is_not_an_event(self):
        undated = [t for t, e in parse_page(PAGE) if e is None]
        self.assertEqual(undated, ["Exmoor Food Fest"])

    def test_the_link_is_the_festivals_own_site(self):
        events = {t: e for t, e in parse_page(PAGE) if e}
        self.assertEqual(events["Olney Pancake Race, Buckinghamshire"]["url"],
                         "http://olneypancakerace.org/")

    def test_the_date_is_not_repeated_into_the_description(self):
        events = {t: e for t, e in parse_page(PAGE) if e}
        description = events["Wakefield Rhubarb Festival"]["description"]
        self.assertNotIn("2026", description)
        self.assertIn("Rhubarb Triangle", description)

    def test_an_annual_festival_keeps_its_years_apart(self):
        # Same festival, next year, must not overwrite this year's row.
        events = {t: e for t, e in parse_page(PAGE) if e}
        self.assertTrue(
            events["Wakefield Rhubarb Festival"]["source_id"].endswith("2026-02-20"))


class TestWhichTownIsOffered(unittest.TestCase):
    """The source cannot see the gazetteer, so it offers candidates in order."""

    def test_the_town_may_be_in_the_middle(self):
        # "Foodies Festival, Bath, Somerset" — Bath is the town and
        # Somerset the county, and only the gazetteer can tell them
        # apart, so both are offered with the nearer one first.
        self.assertEqual(place_candidates("Foodies Festival, Bath, Somerset")[:2],
                         ["Somerset", "Bath"])

    def test_the_town_may_only_be_in_the_festivals_name(self):
        # "Ludlow Food Festival, Shropshire" names its county and hides
        # its town in its own name.
        candidates = place_candidates("Ludlow Food Festival, Shropshire")
        self.assertIn("Ludlow", candidates)
        self.assertLess(candidates.index("Shropshire"), candidates.index("Ludlow"))

    def test_a_colon_separates_a_place_too(self):
        self.assertIn("Crawley", place_candidates("Taste of the Caribbean: Crawley"))

    def test_prose_is_not_offered_as_a_place(self):
        candidates = place_candidates(
            "Steyning Food Festival, various locations in the village")
        self.assertNotIn("various locations in the village", candidates)
        self.assertIn("Steyning", candidates)

    def test_a_longer_name_is_tried_before_its_first_word(self):
        candidates = place_candidates("Bishops Stortford Food Festival")
        self.assertLess(candidates.index("Bishops Stortford"),
                        candidates.index("Bishops"))

    def test_a_title_with_nothing_to_offer(self):
        self.assertEqual(place_candidates(""), [])


class TestPlacingThem(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        for name, lat, lon in [("olney", 52.153, -0.700),
                               ("wakefield", 53.682, -1.498),
                               ("bath", 51.380, -2.360)]:
            self.db.execute("INSERT INTO places (name, lat, lon) VALUES (?,?,?)",
                            (name, lat, lon))
        self.db.commit()

    def test_events_reach_the_map_through_the_gazetteer(self):
        ok, message = run_source(self.db, FakeFetcher(PAGE), FoodFestivals())
        self.assertTrue(ok, message)
        placed = self.db.execute(
            "SELECT e.title, d.lat, d.lon FROM events e"
            " JOIN destinations d ON d.id = e.destination_id"
            " ORDER BY e.start_date").fetchall()
        self.assertEqual([p[0] for p in placed],
                         ["Olney Pancake Race, Buckinghamshire",
                          "Wakefield Rhubarb Festival",
                          "Foodies Festival, Bath, Somerset"])
        # Bath, not Somerset: a county is never in the gazetteer, so the
        # town is what the lookup finds.
        self.assertEqual(placed[2][1:], (51.380, -2.360))

    def test_a_festival_at_a_place_we_do_not_hold_is_left_off(self):
        # "Great British Food Festival, Arley Hall, Cheshire" — a country
        # house, not a settlement. Dropped rather than guessed at.
        run_source(self.db, FakeFetcher(PAGE), FoodFestivals())
        titles = [r[0] for r in self.db.execute("SELECT title FROM events")]
        self.assertNotIn("Great British Food Festival, Arley Hall, Cheshire",
                         titles)

    def test_a_touring_festival_does_not_collapse_into_one_venue(self):
        # The bug a reader found: Foodies Festival plays Bath, Wakefield
        # and half a dozen other towns under one name. While the venue was
        # named after the festival, the first one created won and the rest
        # were matched to it by name — so Bath's was reported at St Albans,
        # 170 km away. The venue is the town now, so each stop is its own.
        touring = f"""<html><body>
          {entry("Foodies Festival, Bath, Somerset", "5 September 2026", "Chefs.")}
          {entry("Foodies Festival, Wakefield", "12 September 2026", "More chefs.")}
        </body></html>"""
        ok, message = run_source(self.db, FakeFetcher(touring), FoodFestivals())
        self.assertTrue(ok, message)

        self.assertEqual(
            self.db.execute(
                "SELECT e.title, d.name, d.lat FROM events e"
                " JOIN destinations d ON d.id = e.destination_id"
                " ORDER BY e.start_date").fetchall(),
            [("Foodies Festival, Bath, Somerset", "Bath", 51.380),
             ("Foodies Festival, Wakefield", "Wakefield", 53.682)])

    def test_the_page_is_fetched_once_and_plainly(self):
        # A blog post, not a rendered listing: the dates are in the
        # served HTML and one request gets all of them.
        fetcher = FakeFetcher(PAGE)
        list(FoodFestivals().scrape(fetcher))
        self.assertEqual(fetcher.fetched, [URL])


if __name__ == "__main__":
    unittest.main()
