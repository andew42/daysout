"""Destinations from Wikidata.

Wikidata publishes UK visitor attractions as CC0 open data with an
endpoint built for programmatic queries, so this is a better source of
*destinations* than crawling each organisation's website: one request per
category instead of thousands of page fetches, stable identifiers, and
coordinates that are already structured.

It gives us places, not events — event listings still have to come from
the organisations' own sites.

Each query is logged with its row count, so a query that silently returns
nothing (a wrong entity id, a Wikidata schema change) is visible in the
scrape log rather than looking like an empty category.
"""

import json
import logging
import re
from urllib.parse import urlencode

log = logging.getLogger(__name__)

ENDPOINT = "https://query.wikidata.org/sparql"

# Entity ids used below:
#   Q145      United Kingdom          Q333515  National Trust
#   Q936287   English Heritage        Q1107656 garden
#   Q167346   botanical garden        Q33506   museum
BASE = """
SELECT ?item ?itemLabel ?itemDescription ?coord ?postcode ?website WHERE {
  %s
  OPTIONAL { ?item wdt:P281 ?postcode }
  OPTIONAL { ?item wdt:P856 ?website }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
LIMIT %d
"""

# (query name, fixed category or None to derive from the label, WHERE body)
QUERIES = [
    ("national-trust", None,
     "?item wdt:P137 wd:Q333515 ; wdt:P625 ?coord ."),
    ("english-heritage", None,
     "?item wdt:P137 wd:Q936287 ; wdt:P625 ?coord ."),
    ("gardens", "garden",
     "VALUES ?type { wd:Q1107656 wd:Q167346 }\n"
     "  ?item wdt:P31 ?type ; wdt:P17 wd:Q145 ; wdt:P625 ?coord ."),
    ("museums", None,
     "?item wdt:P31 wd:Q33506 ; wdt:P17 wd:Q145 ; wdt:P625 ?coord ."),
]

GARDEN_WORDS = re.compile(r"\bgardens?\b|\barboretum\b", re.IGNORECASE)
AVIATION_WORDS = re.compile(
    r"\baviation\b|\baircraft\b|\bairfield\b|\bair museum\b|\baerodrome\b|"
    r"\bflight\b|\bflying\b|\bRAF\b|\bair force\b", re.IGNORECASE)

# Wikidata point coordinates look like "Point(-2.3187 51.1054)" — longitude
# first, which is the opposite order to everything else here.
POINT_RE = re.compile(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")


class Wikidata:

    name = "wikidata"

    def category(self, name, description, query_name):
        text = f"{name} {description}"
        if query_name == "gardens" or GARDEN_WORDS.search(text):
            return "garden"
        if AVIATION_WORDS.search(text):
            return "airfield"
        return "historic-house"

    def scrape(self, fetcher, max_pages=0):
        # max_pages caps rows per query for quick verification runs.
        limit = max_pages if max_pages else 1000

        for query_name, fixed_category, where in QUERIES:
            url = ENDPOINT + "?" + urlencode(
                {"format": "json", "query": BASE % (where, limit)})
            try:
                # api=True: WDQS is a published query endpoint meant for
                # programmatic use, and its robots.txt disallows /sparql so
                # crawlers don't walk infinitely many generated query URLs.
                payload = json.loads(fetcher.get(url, api=True))
            except Exception as e:  # noqa: BLE001 — one bad query mustn't end the run
                log.warning("wikidata query %s failed: %s", query_name, e)
                continue

            rows = payload.get("results", {}).get("bindings", [])
            log.info("wikidata query %s: %d rows", query_name, len(rows))

            for row in rows:
                place = self._parse(row, query_name, fixed_category)
                if place:
                    yield "place", place

    def _parse(self, row, query_name, fixed_category):
        def value(key):
            return row.get(key, {}).get("value", "")

        name = value("itemLabel")
        item = value("item")
        point = POINT_RE.match(value("coord"))
        if not name or not item or not point:
            return None
        # A label that is still a Q-id means the item has no English label.
        if re.fullmatch(r"Q\d+", name):
            return None

        description = value("itemDescription")
        # For the museums query keep only aviation-related ones; general
        # museums are a different kind of day out and would swamp the map.
        if query_name == "museums" and not AVIATION_WORDS.search(f"{name} {description}"):
            return None

        return {
            "source_id": item.rsplit("/", 1)[-1],
            "name": name,
            "description": description,
            "url": value("website") or item,
            "postcode": value("postcode"),
            "lon": float(point.group(1)),
            "lat": float(point.group(2)),
            "category": fixed_category or self.category(name, description, query_name),
        }

    def link_event(self, event):
        return None  # Wikidata supplies destinations only
