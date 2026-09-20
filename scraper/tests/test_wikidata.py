"""Wikidata source tests against a captured SPARQL response shape."""

import json
import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.wikidata import Wikidata
from test_scraper import SCHEMA


def binding(item, label, coord, description="", postcode=None, website=None):
    row = {
        "item": {"value": f"http://www.wikidata.org/entity/{item}"},
        "itemLabel": {"value": label},
        "itemDescription": {"value": description},
        "coord": {"value": coord},
    }
    if postcode:
        row["postcode"] = {"value": postcode}
    if website:
        row["website"] = {"value": website}
    return row


RESPONSES = {
    "national-trust": [
        binding("Q1633692", "Stourhead", "Point(-2.3187 51.1054)",
                "landscape garden in Wiltshire", "BA12 6QF",
                "https://www.nationaltrust.org.uk/stourhead"),
        binding("Q1799374", "Lacock Abbey", "Point(-2.1180 51.4147)",
                "country house in Wiltshire", "SN15 2LG"),
    ],
    "english-heritage": [
        binding("Q188426", "Stonehenge", "Point(-1.8262 51.1789)",
                "prehistoric monument"),
    ],
    "gardens": [
        binding("Q1319441", "RHS Garden Wisley", "Point(-0.4740 51.3120)"),
    ],
    "museums": [
        binding("Q1130791", "Imperial War Museum Duxford", "Point(0.1312 52.0943)",
                "aviation museum in Cambridgeshire"),
        binding("Q6373", "Some Local History Museum", "Point(-1.0 52.0)",
                "local museum"),
        binding("Q999999", "Q999999", "Point(-1.0 52.0)", "item with no label"),
    ],
}


class FakeFetcher:
    """Answers SPARQL URLs by matching the query text to a fixture set."""

    def __init__(self, responses=RESPONSES):
        self.responses = responses
        self.requests = []

    def get(self, url, api=False):
        # The real source calls a published query endpoint, so it passes
        # api=True; assert that rather than quietly accepting either.
        assert api, "the Wikidata SPARQL endpoint should be fetched as an API"
        self.requests.append(url)
        for key, marker in (("national-trust", "Q333515"),
                            ("english-heritage", "Q936287"),
                            ("gardens", "Q1107656"),
                            ("museums", "Q33506")):
            if marker in url:
                return json.dumps({"results": {"bindings": self.responses.get(key, [])}})
        raise AssertionError(f"unexpected query URL: {url}")


class WikidataTest(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def test_parses_places_with_coordinates(self):
        ok, message = run_source(self.db, FakeFetcher(), Wikidata())
        self.assertTrue(ok, message)

        rows = dict(self.db.execute(
            "SELECT name, category FROM destinations").fetchall())
        # Point() is longitude-first; Stourhead must land in Wiltshire.
        lat, lon = self.db.execute(
            "SELECT lat, lon FROM destinations WHERE name = 'Stourhead'").fetchone()
        self.assertAlmostEqual(lat, 51.1054)
        self.assertAlmostEqual(lon, -2.3187)

        self.assertEqual(rows["Stourhead"], "garden")          # from description
        self.assertEqual(rows["Lacock Abbey"], "historic-house")
        self.assertEqual(rows["RHS Garden Wisley"], "garden")  # fixed category
        self.assertEqual(rows["Imperial War Museum Duxford"], "airfield")

    def test_filters_non_aviation_museums_and_unlabelled_items(self):
        run_source(self.db, FakeFetcher(), Wikidata())
        names = [r[0] for r in self.db.execute("SELECT name FROM destinations")]
        self.assertNotIn("Some Local History Museum", names)
        self.assertNotIn("Q999999", names)

    def test_postcode_and_website_optional(self):
        run_source(self.db, FakeFetcher(), Wikidata())
        postcode, url = self.db.execute(
            "SELECT postcode, url FROM destinations WHERE name = 'Stourhead'").fetchone()
        self.assertEqual(postcode, "BA12 6QF")
        self.assertEqual(url, "https://www.nationaltrust.org.uk/stourhead")
        # No website in the fixture: falls back to the Wikidata item URL.
        stonehenge_url = self.db.execute(
            "SELECT url FROM destinations WHERE name = 'Stonehenge'").fetchone()[0]
        self.assertIn("wikidata.org", stonehenge_url)

    def test_failed_query_does_not_end_the_run(self):
        class OneBadQuery(FakeFetcher):
            def get(self, url, api=False):
                if "Q333515" in url:
                    raise OSError("timeout")
                return super().get(url, api=api)

        ok, _ = run_source(self.db, OneBadQuery(), Wikidata())
        self.assertTrue(ok)
        names = [r[0] for r in self.db.execute("SELECT name FROM destinations")]
        self.assertIn("Stonehenge", names)      # other queries still ran
        self.assertNotIn("Stourhead", names)

    def test_partial_run_purges_nothing(self):
        run_source(self.db, FakeFetcher(), Wikidata())
        before = self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0]

        # A bounded run that returns only one row must not delete the rest.
        thin = {"national-trust": RESPONSES["national-trust"][:1],
                "english-heritage": [], "gardens": [], "museums": []}
        ok, message = run_source(self.db, FakeFetcher(thin), Wikidata(), max_pages=1)
        self.assertTrue(ok)
        self.assertIn("nothing purged", message)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], before)


if __name__ == "__main__":
    unittest.main()
