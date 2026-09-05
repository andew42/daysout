#!/usr/bin/env python3
"""Import a UK place-name gazetteer into the daysout database.

Fills the `places` table so an event that names a town and no postcode can
still be put on the map. Postcodes remain the precise route; this is the
fallback for listing sites that write "Ludlow Food Festival, Shropshire"
and never an address.

The data is Wikidata (CC0), queried through its SPARQL endpoint — the same
source and the same licence the scraper already uses for destinations, so
this adds no new dependency and nothing to agree to. Stdlib only.

    python3 import_places.py [--db PATH]
    python3 import_places.py --self-test

**Only unambiguous names are stored.** There are twenty Middletons and
seventeen Newtons in the UK, and a festival at the wrong one is worse than
a festival the map never shows — the same reasoning that makes the scraper
refuse a date it cannot read rather than approximate it. A name is kept
only when every settlement carrying it sits within SAME_PLACE_KM of the
others, which folds duplicate Wikidata entries for one town into a single
row while still rejecting genuinely different places.

One query per settlement type rather than one for all of them: the
endpoint times out on `wdt:P31/wdt:P279*` over settlements, and returns a
504 even for the flat query when the label service is asked for 30,000
rows at once. Measured 5 Sep 2026.
"""

import argparse
import json
import math
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"

# Wikidata asks for a User-Agent that identifies the client.
USER_AGENT = "daysout-setup/1.0 (place-name gazetteer import)"

# Q145 United Kingdom. The settlement types, queried one at a time:
#   Q3957 town   Q532 village   Q515 city   Q5084 hamlet
SETTLEMENT_TYPES = [
    ("town", "Q3957"),
    ("village", "Q532"),
    ("city", "Q515"),
    ("hamlet", "Q5084"),
]

QUERY = """
SELECT ?iLabel ?coord WHERE {
  ?i wdt:P31 wd:%s ; wdt:P17 wd:Q145 ; wdt:P625 ?coord .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
"""

# Wikidata writes coordinates longitude first.
POINT_RE = re.compile(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")

# A label the label service could not resolve comes back as the entity id.
QID_RE = re.compile(r"^Q\d+$")

# Two points this close are taken to be duplicate entries for one place
# rather than two places sharing a name. A large town is a couple of
# kilometres across, so this is generous without spanning counties.
SAME_PLACE_KM = 10.0

TIMEOUT_SECONDS = 300


def normalise(name):
    """The key a lookup uses: lowercase, letters digits and single spaces.

    An apostrophe is dropped rather than turned into a separator, or
    "Bishop's Stortford" becomes "bishop s stortford" and never meets the
    "Bishops Stortford" a listing wrote without one. Both shapes of
    apostrophe: a web page is as likely to carry the curly one.
    """
    text = (name or "").lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * radius * math.asin(math.sqrt(a))


def fetch(query):
    """Run one SPARQL query, returning its bindings."""
    url = ENDPOINT + "?" + urllib.parse.urlencode(
        {"query": query, "format": "json"})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)["results"]["bindings"]


def collect(bindings, into):
    """Add (name -> list of points) from one query's rows."""
    for row in bindings:
        label = row.get("iLabel", {}).get("value", "")
        if not label or QID_RE.match(label):
            continue
        match = POINT_RE.match(row.get("coord", {}).get("value", ""))
        if not match:
            continue
        lon, lat = float(match.group(1)), float(match.group(2))
        key = normalise(label)
        if key:
            into.setdefault(key, []).append((lat, lon))
    return into


def unambiguous(points):
    """One (lat, lon) for a name, or None when the name names two places.

    Duplicate Wikidata entries for the same town are common and harmless,
    so closeness decides this rather than the number of rows.
    """
    if not points:
        return None
    first = points[0]
    for point in points[1:]:
        if haversine_km(first[0], first[1], point[0], point[1]) > SAME_PLACE_KM:
            return None
    return first


def build(places):
    """(rows, dropped) — the table to write, and how many names were ambiguous."""
    rows, dropped = [], 0
    for name, points in places.items():
        point = unambiguous(points)
        if point is None:
            dropped += 1
            continue
        rows.append((name, point[0], point[1]))
    return sorted(rows), dropped


def write(db_path, rows):
    db = sqlite3.connect(db_path)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS places ("
                   "name TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL)")
        # Replace wholesale: the gazetteer is reference data, and a name
        # Wikidata has stopped calling a settlement should stop being one
        # here too.
        db.execute("DELETE FROM places")
        db.executemany("INSERT OR REPLACE INTO places (name, lat, lon)"
                       " VALUES (?, ?, ?)", rows)
        db.commit()
    finally:
        db.close()


def self_test():
    """The rules that decide what gets stored, without touching the network."""

    assert normalise("Bishop's Stortford") == "bishops stortford"
    assert normalise("  Stoke-on-Trent ") == "stoke on trent"
    assert normalise("") == ""

    # London to Manchester is about 260 km; two points 1 km apart are one
    # place recorded twice.
    assert 250 < haversine_km(51.507, -0.128, 53.480, -2.242) < 270
    assert haversine_km(51.500, -0.100, 51.505, -0.100) < 1.0

    assert unambiguous([(51.5, -0.1)]) == (51.5, -0.1)
    assert unambiguous([(51.500, -0.100), (51.505, -0.100)]) == (51.5, -0.1)
    assert unambiguous([(51.5, -0.1), (53.5, -2.2)]) is None

    collected = collect([
        {"iLabel": {"value": "Ludlow"}, "coord": {"value": "Point(-2.7166 52.3681)"}},
        {"iLabel": {"value": "Q12345"}, "coord": {"value": "Point(-1.0 52.0)"}},
        {"iLabel": {"value": "No Coords"}, "coord": {"value": "elsewhere"}},
    ], {})
    assert list(collected) == ["ludlow"], collected

    rows, dropped = build({
        "ludlow": [(52.368, -2.717)],
        "middleton": [(53.55, -2.19), (54.6, -1.5)],
    })
    assert rows == [("ludlow", 52.368, -2.717)], rows
    assert dropped == 1

    print("self-test passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(Path("data") / "daysout.db"),
                        help="database to fill (default: data/daysout.db)")
    parser.add_argument("--self-test", action="store_true",
                        help="check the rules and exit, no network")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    places = {}
    for label, qid in SETTLEMENT_TYPES:
        try:
            bindings = fetch(QUERY % qid)
        except Exception as e:  # noqa: BLE001 — say which type, keep the rest
            print(f"{label}: query failed: {e}", file=sys.stderr)
            continue
        before = len(places)
        collect(bindings, places)
        print(f"{label}: {len(bindings)} row(s), {len(places) - before} new name(s)")

    if not places:
        print("no places fetched; leaving the table alone", file=sys.stderr)
        return 1

    rows, dropped = build(places)
    write(args.db, rows)
    print(f"\n{len(rows)} place(s) written to {args.db}; "
          f"{dropped} name(s) dropped as ambiguous")
    return 0


if __name__ == "__main__":
    sys.exit(main())
