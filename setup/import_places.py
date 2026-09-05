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
    python3 import_places.py --db PATH --if-stale
    python3 import_places.py --self-test

`--if-stale` imports only when the table was built by different rules from
these, so a deploy can run it every time without refetching. The rules
change more often than the data does, and a table built by the old ones
looks perfectly healthy from outside — the version that lacked Bath gave
no sign beyond events quietly failing to be placed.

**Only unambiguous names are stored.** There are twenty Middletons and
seventeen Newtons in the UK, and a festival at the wrong one is worse than
a festival the map never shows — the same reasoning that makes the scraper
refuse a date it cannot read rather than approximate it. Duplicate
Wikidata entries for one town are folded together by SAME_PLACE_KM;
genuinely different places of equal standing are dropped.

**Where one of them dwarfs the rest, it wins.** Brighton is a city of
134,293 on the south coast and a hamlet in Cornwall; a listing saying
"Brighton" means the first, and dropping the name because a hamlet shares
it loses the one everybody meant. Population decides that, not Wikidata's
settlement type — the typing is not consistent enough to lean on, as Bath
is filed a "city of the United Kingdom" and Brighton a "market town".

One query per settlement type rather than one for all of them: the
endpoint times out on `wdt:P31/wdt:P279*` over settlements, and returns a
504 even for the flat query when the label service is asked for 30,000
rows at once. Measured 5 Sep 2026.
"""

import argparse
import hashlib
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

# Q145 United Kingdom. One query per type, because the endpoint will not
# answer a single query for all of them.
#
# The four types after Q515 are not decoration, and leaving them out was a
# real bug. Wikidata files Bath as a "city of the United Kingdom" and
# Brighton as a "market town", so a list of city/town/village/hamlet
# missed both — and missing them was worse than it sounds. With no
# Brighton in the table the hamlet of Brighton in Cornwall was the only
# one of that name, looked perfectly unambiguous, and took every Brighton
# event 230 km west. **An absent place does not merely fail to match; it
# lets a smaller namesake answer for it.**
SETTLEMENT_TYPES = [
    ("city", "Q515"),
    ("city of the UK", "Q110390579"),
    ("big city", "Q1549591"),
    ("county town", "Q1357964"),
    ("market town", "Q18511725"),
    ("town", "Q3957"),
    ("village", "Q532"),
    ("hamlet", "Q5084"),
]

# MAX and GROUP BY, not a bare OPTIONAL: a place with populations recorded
# for several census years comes back once per figure, which doubled the
# village response past the size the endpoint will return intact — it
# arrived truncated mid-JSON and the whole type was lost.
QUERY = """
SELECT ?iLabel ?coord (MAX(?pop) AS ?population) WHERE {
  ?i wdt:P31 wd:%s ; wdt:P17 wd:Q145 ; wdt:P625 ?coord .
  OPTIONAL { ?i wdt:P1082 ?pop }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
GROUP BY ?iLabel ?coord
"""

# Wikidata writes coordinates longitude first.
POINT_RE = re.compile(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")

# A label the label service could not resolve comes back as the entity id.
QID_RE = re.compile(r"^Q\d+$")

# Two points this close are taken to be duplicate entries for one place
# rather than two places sharing a name. A large town is a couple of
# kilometres across, so this is generous without spanning counties.
SAME_PLACE_KM = 10.0

# What it takes for one place to answer for a shared name: it must be a
# real town in its own right, and it must dwarf the others. Brighton is
# 134,293 people against a Cornish hamlet too small to have a figure at
# all, which is not a close call; two villages of nine hundred each are,
# and stay ambiguous.
MIN_POPULATION = 20_000
DOMINANCE = 10

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
    """Add (name -> list of (population, lat, lon)) from one query's rows.

    A place with several recorded populations arrives as several rows at
    the same point; the largest is kept, so a figure from 1801 does not
    stand in for the current one.
    """
    for row in bindings:
        label = row.get("iLabel", {}).get("value", "")
        if not label or QID_RE.match(label):
            continue
        match = POINT_RE.match(row.get("coord", {}).get("value", ""))
        if not match:
            continue
        lon, lat = float(match.group(1)), float(match.group(2))
        try:
            population = int(float(row.get("population", {}).get("value", 0)))
        except (TypeError, ValueError):
            population = 0
        key = normalise(label)
        if not key:
            continue

        for index, (known, plat, plon) in enumerate(into.setdefault(key, [])):
            if haversine_km(lat, lon, plat, plon) <= SAME_PLACE_KM:
                if population > known:
                    into[key][index] = (population, plat, plon)
                break
        else:
            into[key].append((population, lat, lon))
    return into


def unambiguous(places):
    """One (lat, lon) for a name, or None when the name names two places.

    `collect` has already folded duplicate entries for a single place
    together, so anything left here is genuinely more than one place.

    **The one people mean wins, when it is not a close call.** Brighton is
    a city of 134,293 on the south coast and a hamlet in Cornwall; a
    listing that says "Brighton" means the first, and refusing to place it
    because a hamlet shares the name loses the one everybody meant. The
    test is population rather than Wikidata's settlement type, because the
    typing is not consistent enough to lean on — Bath is filed as a "city
    of the United Kingdom" and Brighton as a "market town".

    **Anything closer stays ambiguous.** Two villages of nine hundred
    apiece, or a town only twice the size of its namesake, are dropped:
    an event at the wrong one is worse than an event the map never shows,
    which is the same reasoning that makes `dates.to_iso` refuse a date
    rather than approximate it.
    """
    if not places:
        return None
    if len(places) == 1:
        return places[0][1], places[0][2]

    biggest = max(places, key=lambda place: place[0])
    rest = max(place[0] for place in places if place is not biggest)
    if biggest[0] >= MIN_POPULATION and biggest[0] >= DOMINANCE * max(rest, 1):
        return biggest[1], biggest[2]
    return None


def build(places):
    """(rows, dropped) — the table to write, and how many names were ambiguous."""
    rows, dropped = [], 0
    for name, found in places.items():
        point = unambiguous(found)
        if point is None:
            dropped += 1
            continue
        rows.append((name, point[0], point[1]))
    return sorted(rows), dropped


def rules_version():
    """A fingerprint of this file, identifying the rules that built a table.

    The rules change more often than the data does — the settlement types
    to fetch, what counts as ambiguous, how the key is normalised — and a
    table built by the old ones looks perfectly healthy from outside. It
    was: the gazetteer had no Bath in it, and the only sign was events
    quietly failing to be placed.

    Hashing the file rather than a version constant somebody has to
    remember to bump. A comment-only edit then costs one needless import,
    which is a minute; a forgotten bump costs a wrong map until the next
    person notices.
    """
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def stored_version(db_path):
    """The rules that built the table in this database, or '' if none."""
    if not Path(db_path).exists():
        return ""
    db = sqlite3.connect(db_path)
    try:
        row = db.execute(
            "SELECT value FROM places_meta WHERE key = 'rules_version'").fetchone()
        count = db.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    except sqlite3.OperationalError:  # neither table exists yet
        return ""
    finally:
        db.close()
    # An empty table is not up to date whatever it claims.
    return row[0] if row and count else ""


def write(db_path, rows):
    db = sqlite3.connect(db_path)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS places ("
                   "name TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS places_meta ("
                   "key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        # Replace wholesale: the gazetteer is reference data, and a name
        # Wikidata has stopped calling a settlement should stop being one
        # here too.
        db.execute("DELETE FROM places")
        db.executemany("INSERT OR REPLACE INTO places (name, lat, lon)"
                       " VALUES (?, ?, ?)", rows)
        # Written last and in the same transaction as the rows: a version
        # recorded against a half-written table would make the next run
        # skip a gazetteer that is not there.
        db.execute("INSERT OR REPLACE INTO places_meta (key, value)"
                   " VALUES ('rules_version', ?)", (rules_version(),))
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

    # (population, lat, lon).
    assert unambiguous([(1000, 51.5, -0.1)]) == (51.5, -0.1)

    # Brighton, 134,293, against a Cornish hamlet with no figure at all.
    assert unambiguous([(134293, 50.82, -0.14), (0, 50.35, -4.95)]) == (50.82, -0.14)

    # Two villages of nine hundred: nobody could say which, so neither.
    assert unambiguous([(900, 51.5, -0.1), (850, 53.5, -2.2)]) is None
    # Big, but not big enough to speak for the other: 30k against 9k.
    assert unambiguous([(30000, 51.5, -0.1), (9000, 53.5, -2.2)]) is None
    # Dominant but too small to be the one anybody means.
    assert unambiguous([(3000, 51.5, -0.1), (10, 53.5, -2.2)]) is None

    # A place recorded twice, once with a stale population: one place,
    # and the larger figure is the one kept.
    collected = collect([
        {"iLabel": {"value": "Ludlow"}, "coord": {"value": "Point(-2.7166 52.3681)"},
         "population": {"value": "10500"}},
        {"iLabel": {"value": "Ludlow"}, "coord": {"value": "Point(-2.7168 52.3683)"},
         "population": {"value": "1801"}},
        {"iLabel": {"value": "Q12345"}, "coord": {"value": "Point(-1.0 52.0)"}},
        {"iLabel": {"value": "No Coords"}, "coord": {"value": "elsewhere"}},
    ], {})
    assert list(collected) == ["ludlow"], collected
    assert collected["ludlow"] == [(10500, 52.3681, -2.7166)], collected

    rows, dropped = build({
        "ludlow": [(10500, 52.368, -2.717)],
        "middleton": [(900, 53.55, -2.19), (850, 54.6, -1.5)],
        "brighton": [(134293, 50.82, -0.14), (0, 50.35, -4.95)],
    })
    assert rows == [("brighton", 50.82, -0.14), ("ludlow", 52.368, -2.717)], rows
    assert dropped == 1

    # --if-stale: an import is skipped only when the same rules built the
    # table and the table is not empty.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "t.db")
        assert stored_version(path) == "", "a database that does not exist"

        write(path, [("ludlow", 52.368, -2.717)])
        assert stored_version(path) == rules_version(), "just written"

        db = sqlite3.connect(path)
        db.execute("UPDATE places_meta SET value = 'older-rules'")
        db.commit()
        db.close()
        assert stored_version(path) != rules_version(), "built by other rules"

        db = sqlite3.connect(path)
        db.execute("UPDATE places_meta SET value = ?", (rules_version(),))
        db.execute("DELETE FROM places")
        db.commit()
        db.close()
        # The right rules over an empty table is not up to date: that is
        # what a half-finished import leaves behind.
        assert stored_version(path) == "", "empty table"

    print("self-test passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(Path("data") / "daysout.db"),
                        help="database to fill (default: data/daysout.db)")
    parser.add_argument("--self-test", action="store_true",
                        help="check the rules and exit, no network")
    parser.add_argument("--if-stale", action="store_true",
                        help="import only when the table was built by "
                             "different rules from these, so a deploy can "
                             "run this every time without refetching")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.if_stale and stored_version(args.db) == rules_version():
        print(f"{args.db} already holds a gazetteer built by these rules "
              f"({rules_version()}); nothing to do")
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
