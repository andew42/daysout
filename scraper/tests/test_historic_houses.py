"""Historic Houses: turn a house page into a place that can be found.

The sitemap shape is known — one entry per house, exactly as the site
publishes it. What a house page carries is not, so the postcode is read
from three places in turn and each is covered here, including the one that
would be actively harmful: a postcode taken from the footer would give
every house in the country the charity's own location.
"""

import sqlite3
import unittest

from daysout_scraper import db as dbmod
from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.historic_houses import HistoricHouses, parse_house

from schema import SCHEMA

BASE = "https://www.historichouses.org"
SITEMAP_URL = f"{BASE}/house-sitemap.xml"
DITCHLEY = f"{BASE}/house/ditchley-park/"
MICKLEFIELD = f"{BASE}/house/micklefield-hall"

# The shape the sitemap actually returns, lastmod and all.
SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{DITCHLEY}</loc><lastmod>2025-06-20T09:20:00+00:00</lastmod></url>
  <url><loc>{MICKLEFIELD}</loc><lastmod>2025-06-19T09:20:00+00:00</lastmod></url>
  <url><loc>{BASE}/whats-on/</loc><lastmod>2025-06-21T09:20:00+00:00</lastmod></url>
</urlset>"""

# A footer postcode on every page: the charity's, never the house's.
FOOTER = ('<footer><p>Historic Houses, 2 Chester Street, London SW1X 7BB</p>'
          '</footer>')


def page(body, head=""):
    return f"<html><head>{head}</head><body>{body}{FOOTER}</body></html>"


JSONLD_PAGE = page(
    "<h1>Ditchley Park</h1>",
    head='<script type="application/ld+json">'
         '{"@context": "https://schema.org", "@type": "TouristAttraction",'
         ' "name": "Ditchley Park", "description": "A Palladian house.",'
         ' "address": {"@type": "PostalAddress", "postalCode": "OX7 4AT"}}'
         '</script>')

ADDRESS_ELEMENT_PAGE = page(
    "<h1>Micklefield Hall</h1>"
    "<address>Micklefield Hall, Sarratt, Rickmansworth, WD3 4JX</address>")

ADDRESS_CLASS_PAGE = page(
    '<h1>Micklefield Hall</h1>'
    '<div class="house-location"><span>Sarratt, Rickmansworth WD3 4JX</span></div>')

PROSE_ONLY_PAGE = page(
    "<h1>Micklefield Hall</h1>"
    "<main><p>Visit us at Sarratt, Rickmansworth, WD3 4JX.</p></main>")

NO_POSTCODE_PAGE = page("<h1>Micklefield Hall</h1><p>Open by appointment.</p>")


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def get(self, url, api=False, render=False, fresh=False):
        self.fetched.append(url)
        return self.pages[url]


class TestReadingAHousePage(unittest.TestCase):

    def test_structured_data_is_preferred(self):
        place = parse_house(JSONLD_PAGE, DITCHLEY)
        self.assertEqual(place["name"], "Ditchley Park")
        self.assertEqual(place["postcode"], "OX7 4AT")
        self.assertEqual(place["source_id"], "ditchley-park")
        self.assertEqual(place["category"], "historic-house")

    def test_an_address_element_is_read(self):
        place = parse_house(ADDRESS_ELEMENT_PAGE, MICKLEFIELD)
        self.assertEqual(place["postcode"], "WD3 4JX")
        self.assertEqual(place["name"], "Micklefield Hall")

    def test_an_address_block_is_read(self):
        self.assertEqual(
            parse_house(ADDRESS_CLASS_PAGE, MICKLEFIELD)["postcode"], "WD3 4JX")

    def test_prose_is_read_as_a_last_resort(self):
        self.assertEqual(
            parse_house(PROSE_ONLY_PAGE, MICKLEFIELD)["postcode"], "WD3 4JX")

    def test_the_footers_postcode_is_never_the_houses(self):
        # Every page carries it, so accepting it would put every house in
        # the country at the charity's London office.
        self.assertIsNone(parse_house(NO_POSTCODE_PAGE, MICKLEFIELD))

    def test_a_house_with_no_postcode_is_skipped_not_placed_at_zero(self):
        self.assertIsNone(parse_house(NO_POSTCODE_PAGE, MICKLEFIELD))


class TestTheCrawl(unittest.TestCase):

    def fetcher(self):
        return FakeFetcher({
            SITEMAP_URL: SITEMAP,
            DITCHLEY: JSONLD_PAGE,
            MICKLEFIELD: ADDRESS_ELEMENT_PAGE,
        })

    def test_only_house_pages_are_fetched(self):
        f = self.fetcher()
        list(HistoricHouses().scrape(f))
        self.assertEqual(f.fetched, [SITEMAP_URL, DITCHLEY, MICKLEFIELD])

    def test_both_houses_become_places(self):
        places = [item for kind, item in HistoricHouses().scrape(self.fetcher())
                  if kind == "place"]
        self.assertEqual([p["name"] for p in places],
                         ["Ditchley Park", "Micklefield Hall"])


class TestPlacesReachTheDatabase(unittest.TestCase):
    """A place with a postcode but no coordinates used to be impossible.

    Every source so far published coordinates, so the pipeline assumed
    them; this one publishes an address instead, which is the whole reason
    the postcode is worth digging out.
    """

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.db.execute(
            "INSERT INTO postcodes (postcode, lat, lon) VALUES ('OX74AT', 51.86, -1.42)")
        self.db.execute(
            "INSERT INTO postcodes (postcode, lat, lon) VALUES ('WD34JX', 51.69, -0.49)")

    def test_a_postcode_only_place_is_geocoded_and_stored(self):
        ok, message = run_source(self.db, FakeFetcher({
            SITEMAP_URL: SITEMAP,
            DITCHLEY: JSONLD_PAGE,
            MICKLEFIELD: ADDRESS_ELEMENT_PAGE,
        }), HistoricHouses())
        self.assertTrue(ok, message)
        rows = self.db.execute(
            "SELECT name, postcode, lat, lon FROM destinations"
            " WHERE source = 'historic-houses' ORDER BY name").fetchall()
        self.assertEqual(rows, [
            ("Ditchley Park", "OX7 4AT", 51.86, -1.42),
            ("Micklefield Hall", "WD3 4JX", 51.69, -0.49),
        ])

    def test_a_place_whose_postcode_is_unknown_is_skipped_not_placed_at_zero(self):
        # Code-Point Open has no row for it: better absent than at 0,0 in
        # the Gulf of Guinea, which would show as the nearest place there is.
        self.db.execute("DELETE FROM postcodes WHERE postcode = 'WD34JX'")
        ok, _ = run_source(self.db, FakeFetcher({
            SITEMAP_URL: SITEMAP,
            DITCHLEY: JSONLD_PAGE,
            MICKLEFIELD: ADDRESS_ELEMENT_PAGE,
        }), HistoricHouses())
        self.assertTrue(ok)
        names = [r[0] for r in self.db.execute(
            "SELECT name FROM destinations WHERE source = 'historic-houses'")]
        self.assertEqual(names, ["Ditchley Park"])
