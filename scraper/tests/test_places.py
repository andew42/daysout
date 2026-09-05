"""Placing an event that names a town and no postcode.

The gazetteer is the coarse fallback: a postcode puts a venue on a
doorstep, a town name puts it in the right town, and before this a
listing that never printed an address contributed nothing at all.

Two things here are worth more than the rest. The normaliser exists twice
— once in the importer that writes the table, once in the lookup that
reads it — and a disagreement between them would not fail, it would
simply never match; TestTheKeyIsWrittenAndReadTheSameWay is what stops
that. And an ambiguous name must stay unplaced: twenty Middletons means a
festival at the wrong one, which is worse than a festival the map never
shows.
"""

import importlib.util
import sqlite3
import unittest
from pathlib import Path

from daysout_scraper import db as dbmod

from schema import SCHEMA

SETUP = (Path(__file__).resolve().parents[2] / "setup" / "import_places.py")


def load_importer():
    """The setup script, imported by path — it is not on the package path."""
    spec = importlib.util.spec_from_file_location("import_places", SETUP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheKeyIsWrittenAndReadTheSameWay(unittest.TestCase):
    """The importer writes the key; the scraper looks it up. They must agree."""

    def test_the_two_normalisers_agree(self):
        importer = load_importer()
        for name in ["Ludlow", "Bishop's Stortford", "Bishop’s Stortford",
                     "Stoke-on-Trent", "  Bakewell  ", "Weston-super-Mare",
                     "St Ives", "Newcastle upon Tyne", "", "Ross-on-Wye"]:
            self.assertEqual(importer.normalise(name),
                             dbmod.normalise_place(name), name)

    def test_the_shapes_a_listing_writes(self):
        self.assertEqual(dbmod.normalise_place("Bishop's Stortford"),
                         dbmod.normalise_place("Bishops Stortford"))
        self.assertEqual(dbmod.normalise_place("Stoke-on-Trent"),
                         dbmod.normalise_place("stoke on trent"))


class TestTheLookup(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT INTO places (name, lat, lon)"
                        " VALUES ('ludlow', 52.368, -2.717)")
        self.db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                        " VALUES ('SY81AY', 52.367, -2.719)")
        self.db.commit()

    def test_a_town_is_found(self):
        self.assertEqual(dbmod.geocode_place(self.db, "Ludlow"),
                         (52.368, -2.717))

    def test_the_name_is_matched_however_it_is_written(self):
        self.assertEqual(dbmod.geocode_place(self.db, "  LUDLOW "),
                         (52.368, -2.717))

    def test_a_name_that_is_not_in_the_table_is_not_placed(self):
        # Ambiguous names are never imported, so this is also what a
        # Middleton looks like: unplaced, rather than placed wrongly.
        self.assertIsNone(dbmod.geocode_place(self.db, "Middleton"))
        self.assertIsNone(dbmod.geocode_place(self.db, ""))
        self.assertIsNone(dbmod.geocode_place(self.db, None))


class TestPlacingAVenue(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT INTO places (name, lat, lon)"
                        " VALUES ('ludlow', 52.368, -2.717)")
        self.db.execute("INSERT INTO postcodes (postcode, lat, lon)"
                        " VALUES ('SY81AY', 52.300, -2.700)")
        self.db.commit()

    def coords(self, name):
        return self.db.execute(
            "SELECT lat, lon FROM destinations WHERE name = ?", (name,)).fetchone()

    def test_a_venue_with_no_postcode_is_placed_by_its_town(self):
        got = dbmod.ensure_venue(self.db, "food-festivals", "Ludlow", "")
        self.assertEqual(got, "Ludlow")
        self.assertEqual(self.coords("Ludlow"), (52.368, -2.717))

    def test_a_postcode_still_wins_when_there_is_one(self):
        # The gazetteer is the fallback, not the answer: a postcode is a
        # doorstep and a town is a centroid.
        dbmod.ensure_venue(self.db, "food-festivals", "Ludlow", "SY8 1AY")
        self.assertEqual(self.coords("Ludlow"), (52.300, -2.700))

    def test_a_venue_that_is_neither_is_still_dropped(self):
        self.assertIsNone(
            dbmod.ensure_venue(self.db, "food-festivals", "Arley Hall", ""))
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 0)

    def test_an_unknown_postcode_falls_through_to_the_town(self):
        # A postcode the Code-Point import does not hold should not cost
        # the event its place when the name is one we know.
        dbmod.ensure_venue(self.db, "food-festivals", "Ludlow", "ZZ99 9ZZ")
        self.assertEqual(self.coords("Ludlow"), (52.368, -2.717))


class TestATouringFestivalIsNotOneVenue(unittest.TestCase):
    """The bug this pair of rules exists to prevent.

    "Foodies Festival" plays Bath, Oxford, Edinburgh and Glasgow. Naming
    the venue after the festival made all four the same venue: the first
    created won and the rest were matched to it by name, so the Bath one
    was reported at St Albans, 170 km away and an hour wrong. The venue is
    named after the town it resolved to, which is the thing actually
    known.
    """

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        for name, lat, lon in [("bath", 51.381, -2.360),
                               ("oxford", 51.752, -1.258),
                               ("st albans", 51.755, -0.336)]:
            self.db.execute("INSERT INTO places VALUES (?,?,?)", (name, lat, lon))
        self.db.commit()

    def place(self, *candidates):
        return dbmod.ensure_venue(self.db, "food-festivals", "", "",
                                  places=candidates)

    def test_each_stop_gets_its_own_venue(self):
        first = self.place("St Albans")
        second = self.place("Somerset", "Bath")
        third = self.place("Oxford")
        self.assertEqual([first, second, third], ["St Albans", "Bath", "Oxford"])
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 3)

    def test_the_venue_is_named_after_the_town(self):
        self.place("Somerset", "Bath")
        self.assertEqual(
            self.db.execute("SELECT name, lat, lon FROM destinations").fetchone(),
            ("Bath", 51.381, -2.360))

    def test_two_events_in_one_town_share_it(self):
        self.assertEqual(self.place("Bath"), self.place("Bath"))
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1)

    def test_a_county_is_never_the_answer(self):
        # "Somerset" is offered first and is not a settlement, so it must
        # fall through to the town rather than placing anything.
        self.assertEqual(self.place("Somerset", "Bath"), "Bath")

    def test_nothing_known_places_nothing(self):
        self.assertIsNone(self.place("Somerset", "Nowhere At All"))
        self.assertIsNone(self.place())


class TestTheImporter(unittest.TestCase):

    def setUp(self):
        self.importer = load_importer()

    def test_duplicate_entries_for_one_town_are_one_place(self):
        # Wikidata carries the same town twice often enough; two points a
        # few hundred metres apart are one place recorded twice, folded
        # together as the rows are collected.
        collected = self.importer.collect([
            {"iLabel": {"value": "Ludlow"},
             "coord": {"value": "Point(-2.717 52.368)"},
             "population": {"value": "10500"}},
            {"iLabel": {"value": "Ludlow"},
             "coord": {"value": "Point(-2.718 52.369)"},
             "population": {"value": "1801"}},
        ], {})
        rows, dropped = self.importer.build(collected)
        self.assertEqual(len(rows), 1)
        self.assertEqual(dropped, 0)

    def test_two_places_sharing_a_name_are_dropped(self):
        # (population, lat, lon). Two villages of similar size: nobody
        # could say which was meant, so neither is stored.
        rows, dropped = self.importer.build(
            {"middleton": [(900, 53.55, -2.19), (850, 54.60, -1.50)]})
        self.assertEqual(rows, [])
        self.assertEqual(dropped, 1)

    def test_a_city_answers_for_its_smaller_namesake(self):
        # Brighton in Sussex against the hamlet in Cornwall. Without this
        # the hamlet was the only Brighton in the table and took every
        # Brighton event 230 km west.
        rows, dropped = self.importer.build(
            {"brighton": [(134293, 50.82, -0.14), (0, 50.35, -4.95)]})
        self.assertEqual(rows, [("brighton", 50.82, -0.14)])
        self.assertEqual(dropped, 0)

    def test_a_place_too_small_to_be_the_one_meant_wins_nothing(self):
        rows, dropped = self.importer.build(
            {"nowhere": [(3000, 51.5, -0.1), (10, 53.5, -2.2)]})
        self.assertEqual(rows, [])
        self.assertEqual(dropped, 1)

    def test_an_unresolved_label_is_not_a_place(self):
        # The label service answers with the entity id when it has no
        # English label, and "Q12345" is not a town.
        collected = self.importer.collect(
            [{"iLabel": {"value": "Q12345"},
              "coord": {"value": "Point(-1.0 52.0)"}}], {})
        self.assertEqual(collected, {})


if __name__ == "__main__":
    unittest.main()
