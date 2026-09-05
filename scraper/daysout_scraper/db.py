"""SQLite access shared with the Go server.

The server opens the same file in WAL mode, so the scraper can write while
the site stays up. All writes are upserts keyed on (source, source_id) so a
re-run updates rows instead of duplicating them.
"""

import logging
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def now():
    # Microsecond precision so purge_stale can compare timestamps within a
    # single run (string comparison stays correct for this fixed format).
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def start_run(db, source):
    cur = db.execute(
        "INSERT INTO scrape_runs (source, started_at) VALUES (?, ?)",
        (source, now()))
    db.commit()
    return cur.lastrowid


def finish_run(db, run_id, ok, message=""):
    db.execute(
        "UPDATE scrape_runs SET finished_at = ?, ok = ?, message = ? WHERE id = ?",
        (now(), 1 if ok else 0, message, run_id))
    db.commit()


def upsert_destination(db, source, dest):
    """dest keys: source_id, name, category, description, url, postcode, lat, lon."""
    ts = now()
    db.execute(
        """INSERT INTO destinations
             (name, category, description, url, postcode, lat, lon,
              source, source_id, first_seen, last_seen)
           VALUES (:name, :category, :description, :url, :postcode, :lat, :lon,
                   :source, :source_id, :ts, :ts)
           ON CONFLICT (source, source_id) DO UPDATE SET
             name = :name, category = :category, description = :description,
             url = :url, postcode = :postcode, lat = :lat, lon = :lon,
             last_seen = :ts""",
        {**dest, "source": source, "ts": ts,
         "description": dest.get("description", ""),
         "url": dest.get("url", ""), "postcode": dest.get("postcode", "")})


MIN_CONTAINMENT_MATCH = 8


def normalise_name(name):
    """Loose key for matching venue names across sources."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def find_destination_id(db, source, source_id):
    row = db.execute(
        "SELECT id FROM destinations WHERE source = ? AND source_id = ?",
        (source, source_id)).fetchone()
    return row[0] if row else None


def find_destination_id_by_name(db, name):
    """Any destination with this name, whichever source found it.

    An event listing names a venue like "RHS Garden Wisley" with no
    postcode, but we may already hold that place with coordinates from
    another source. Matching by name across the whole table is what lets
    such an event be placed at all.
    """
    key = normalise_name(name)
    if len(key) < 4:  # too short to be a confident match
        return None

    rows = [(destination_id, normalise_name(candidate))
            for destination_id, candidate in
            db.execute("SELECT id, name FROM destinations").fetchall()]

    for destination_id, candidate in rows:
        if candidate == key:
            return destination_id

    # Sites qualify names differently — "RHS Garden Wisley" against a
    # catalogue's "Wisley", "Audley End" against "Audley End House and
    # Gardens". Accept one name containing the other, but only for a name
    # long enough to be distinctive and only when exactly one destination
    # matches, so a common word can't attach an event to the wrong place.
    # Eight characters keeps real names like "Audley End" (audleyend) while
    # excluding words like "Abbey" that many places share.
    if len(key) < MIN_CONTAINMENT_MATCH:
        return None
    matches = {destination_id for destination_id, candidate in rows
               if len(candidate) >= MIN_CONTAINMENT_MATCH
               and (key in candidate or candidate in key)}
    return matches.pop() if len(matches) == 1 else None


def touch_destination(db, destination_id, source):
    """Mark a destination still in use by this run.

    purge_stale removes this source's rows that this run didn't report, so
    every destination an event is attached to has to be touched — however
    it was found. Miss this and the purge deletes the venue out from under
    the event that needs it.
    """
    db.execute(
        "UPDATE destinations SET last_seen = ? WHERE id = ? AND source = ?",
        (now(), destination_id, source))


ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def upsert_event(db, source, event, destination_id):
    """event keys: source_id, title, description, url, start_date, end_date
    (ISO dates), category. destination_id is the place it happens at.

    The ISO check is not belt and braces. Dates are stored as text and
    every query compares them as text, so a date in any other shape is
    not merely odd — it fails `end_date >= today` and the event becomes
    invisible while every count still reports it as linked. Stonor's five
    events sat in the database like that, stored as "02/05/2026", with
    the run reporting 5/5 linked. Refusing the row makes that loud.
    """
    ts = now()
    if destination_id is None:
        return False

    for field in ("start_date", "end_date"):
        value = event.get(field, "")
        if not ISO_DATE_RE.match(str(value)):
            log.warning("%s: refusing %r — %s is %r, not ISO (YYYY-MM-DD)",
                        source, str(event.get("title", ""))[:40], field, value)
            return False
    row = (destination_id,)
    db.execute(
        """INSERT INTO events
             (destination_id, title, description, url, start_date, end_date,
              category, source, source_id, last_seen)
           VALUES (:destination_id, :title, :description, :url, :start_date,
                   :end_date, :category, :source, :source_id, :ts)
           ON CONFLICT (source, source_id) DO UPDATE SET
             destination_id = :destination_id, title = :title,
             description = :description, url = :url, start_date = :start_date,
             end_date = :end_date, category = :category, last_seen = :ts""",
        {**event, "source": source, "ts": ts, "destination_id": row[0],
         "description": event.get("description", ""),
         "category": event.get("category", ""),
         "url": event.get("url", "")})
    return True


def purge_stale(db, source, before):
    """Remove rows a source no longer reports (last_seen older than the run
    start): the place closed or the event page vanished."""
    db.execute("DELETE FROM events WHERE source = ? AND last_seen < ?", (source, before))
    db.execute("DELETE FROM destinations WHERE source = ? AND last_seen < ?", (source, before))


def purge_seed(db):
    """Demo seed rows are only useful until any real source has data."""
    n = db.execute("SELECT COUNT(*) FROM destinations WHERE source != 'seed'").fetchone()[0]
    if n > 0:
        db.execute("DELETE FROM destinations WHERE source = 'seed'")
        db.execute("DELETE FROM events WHERE source = 'seed'")


def purge_unknown_sources(db, known):
    """Remove everything left by a source that no longer exists.

    `purge_stale` only ever removes rows a *running* source stopped
    reporting, so a source that is deleted outright leaves its events and
    venues behind with nothing to refresh or remove them. The house server
    was still serving events from sources retired days earlier —
    national_trust, three per-venue IACF rows, a handful of listing sites
    — and their scrape_runs history was still being reported by /api/status
    as though they were sources.

    Only ever called for a run that read every source: one told to run a
    single source knows nothing about the rest, the same reason a bounded
    run never purges.

    Venues go only when no surviving event still sits at them, since
    another source may have adopted a place this one introduced. Returns
    (sources, events, destinations) removed, for the log.
    """
    placeholders = ",".join("?" * len(known))
    names = [row[0] for row in db.execute(
        f"SELECT DISTINCT source FROM ("
        f"  SELECT source FROM events UNION"
        f"  SELECT source FROM destinations UNION"
        f"  SELECT source FROM scrape_runs)"
        f" WHERE source NOT IN ({placeholders}) AND source != 'seed'",
        tuple(known))]
    if not names:
        return 0, 0, 0

    events = destinations = 0
    for name in names:
        events += db.execute(
            "DELETE FROM events WHERE source = ?", (name,)).rowcount
        destinations += db.execute(
            "DELETE FROM destinations WHERE source = ?"
            " AND id NOT IN (SELECT destination_id FROM events)",
            (name,)).rowcount
        db.execute("DELETE FROM scrape_runs WHERE source = ?", (name,))
    log.info("removed %d source(s) that no longer exist: %s",
             len(names), ", ".join(sorted(names)))
    return len(names), events, destinations


def ensure_venue(db, source, name, postcode, category="venue", url="",
                 places=()):
    """Make sure a destination exists for an event's venue, creating it from
    the venue postcode when we have never seen the place before.

    Events from listing sites name a venue that is usually not already a
    destination. Geocoding it from the local postcode table means an event
    brings its own location, so it can be sorted by distance like any
    other — without which a new source contributes nothing usable.

    The url is the event's own page reduced to its site, because a venue
    outlives the event that introduced it. Without it these destinations
    carry no link at all, which is why their map pins had nothing to click.

    Returns the destination source_id to link to, or None.
    """
    if not name and not places:
        return None

    ts = now()
    if name:
        # Already known under this source: touch last_seen, or the stale
        # purge at the end of the run deletes the venue we are about to
        # attach an event to.
        row = db.execute(
            "SELECT source_id FROM destinations WHERE source = ? AND source_id = ?",
            (source, name)).fetchone()
        if row:
            # Also fill in a link for venues created before we recorded one.
            db.execute(
                "UPDATE destinations SET last_seen = ?,"
                " url = CASE WHEN url = '' THEN ? ELSE url END"
                " WHERE source = ? AND source_id = ?",
                (ts, site_root(url), source, name))
            return row[0]

    coordinates = geocode(db, postcode) if postcode else None
    if not coordinates:
        # No address, but one of these may be a town we know. A listing
        # that writes "Ludlow Food Festival, Shropshire" and never an
        # address was contributing nothing at all before this; a town
        # centroid is the right order of accuracy for rings measured in
        # tens of kilometres.
        #
        # **The venue is then named after the town, not after the event.**
        # A touring festival runs under one name in a dozen places —
        # Foodies Festival plays Bath, Oxford, Edinburgh and Glasgow — and
        # naming the venue for the festival made every one of them the
        # same venue: the first created won, and the rest were linked to
        # it, so Bath's was reported at St Albans. The town is what we
        # actually know here, so it is what the pin is called, and two
        # festivals in one town correctly share it.
        for candidate in ((name,) if name else ()) + tuple(places):
            coordinates = geocode_place(db, candidate)
            if coordinates:
                if candidate != name:
                    log.info("placed %r at %r by town, not postcode",
                             name or "(no venue named)", candidate)
                    name = candidate
                else:
                    log.info("placed %r by town, not postcode", name)
                break
    if not coordinates or not name:
        return None

    # The town may already be a venue here, from another event in it.
    row = db.execute(
        "SELECT source_id FROM destinations WHERE source = ? AND source_id = ?",
        (source, name)).fetchone()
    if row:
        db.execute(
            "UPDATE destinations SET last_seen = ? WHERE source = ? AND source_id = ?",
            (ts, source, name))
        return row[0]

    db.execute(
        """INSERT INTO destinations
             (name, category, description, url, postcode, lat, lon,
              source, source_id, first_seen, last_seen)
           VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source, source_id) DO UPDATE SET
             url = CASE WHEN destinations.url = '' THEN excluded.url
                        ELSE destinations.url END,
             last_seen = excluded.last_seen""",
        (name, category, site_root(url), postcode, coordinates[0],
         coordinates[1], source, name, ts, ts))
    return name


def backfill_venue_url(db, destination_id, url):
    """Give a venue we already hold a link, when it has none.

    ensure_venue runs only when a venue has to be created, so it never
    sees the venues we already hold — which, after the first scrape, is
    all of them. Adding the link there alone changed nothing on the map:
    the pins that lacked a link were exactly the ones that path skips.

    Only ever fills a blank, so a link a source published for itself is
    never replaced by one inferred from an event.
    """
    root = site_root(url)
    if not destination_id or not root:
        return False
    cursor = db.execute(
        "UPDATE destinations SET url = ? WHERE id = ? AND url = ''",
        (root, destination_id))
    return cursor.rowcount > 0


def site_root(url):
    """The site an event page belongs to: "https://host/".

    A venue outlives the event that introduced it, so linking its pin at
    one event's page would rot; the site keeps working.
    """
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}/"


def geocode(db, postcode):
    """Postcode to (lat, lon) via the locally imported Code-Point Open table."""
    norm = postcode.upper().replace(" ", "")
    row = db.execute(
        "SELECT lat, lon FROM postcodes WHERE postcode = ?", (norm,)).fetchone()
    return row if row else None


def normalise_place(name):
    """The key the places table is stored under.

    Must agree with setup/import_places.py's normalise(), or every lookup
    misses. The apostrophe is dropped rather than separated, so
    "Bishop's Stortford" matches the "Bishops Stortford" a listing wrote.
    """
    text = (name or "").lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def geocode_place(db, name):
    """Town name to (lat, lon) via the gazetteer, or None.

    The coarse fallback for a listing that names a town and no address —
    a town centroid rather than a doorstep, which is the right order of
    accuracy for drive-time rings measured in tens of kilometres.

    Only names identifying one settlement are in the table (the import
    drops the twenty Middletons), so a hit here needs no tie-breaking and
    a miss is either an unknown name or a deliberately refused one.
    """
    key = normalise_place(name)
    if not key:
        return None
    row = db.execute(
        "SELECT lat, lon FROM places WHERE name = ?", (key,)).fetchone()
    return row if row else None
