"""SQLite access shared with the Go server.

The server opens the same file in WAL mode, so the scraper can write while
the site stays up. All writes are upserts keyed on (source, source_id) so a
re-run updates rows instead of duplicating them.
"""

import sqlite3
from datetime import datetime, timezone


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


def upsert_event(db, source, event):
    """event keys: source_id, destination_source_id, title, description, url,
    start_date, end_date (ISO dates). The destination must already be
    upserted by the same source."""
    ts = now()
    row = db.execute(
        "SELECT id FROM destinations WHERE source = ? AND source_id = ?",
        (source, event["destination_source_id"])).fetchone()
    if row is None:
        return False
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


def ensure_venue(db, source, name, postcode, category="venue"):
    """Make sure a destination exists for an event's venue, creating it from
    the venue postcode when we have never seen the place before.

    Events from listing sites name a venue that is usually not already a
    destination. Geocoding it from the local postcode table means an event
    brings its own location, so it can be sorted by distance like any
    other — without which a new source contributes nothing usable.

    Returns the destination source_id to link to, or None.
    """
    if not name:
        return None

    # Already known under this source: touch last_seen, or the stale purge
    # at the end of the run deletes the venue we are about to attach an
    # event to.
    ts = now()
    row = db.execute(
        "SELECT source_id FROM destinations WHERE source = ? AND source_id = ?",
        (source, name)).fetchone()
    if row:
        db.execute(
            "UPDATE destinations SET last_seen = ? WHERE source = ? AND source_id = ?",
            (ts, source, name))
        return row[0]

    coordinates = geocode(db, postcode) if postcode else None
    if not coordinates:
        return None

    db.execute(
        """INSERT INTO destinations
             (name, category, description, url, postcode, lat, lon,
              source, source_id, first_seen, last_seen)
           VALUES (?, ?, '', '', ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source, source_id) DO UPDATE SET last_seen = excluded.last_seen""",
        (name, category, postcode, coordinates[0], coordinates[1],
         source, name, ts, ts))
    return name


def geocode(db, postcode):
    """Postcode to (lat, lon) via the locally imported Code-Point Open table."""
    norm = postcode.upper().replace(" ", "")
    row = db.execute(
        "SELECT lat, lon FROM postcodes WHERE postcode = ?", (norm,)).fetchone()
    return row if row else None
