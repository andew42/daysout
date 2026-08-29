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
              source, source_id, last_seen)
           VALUES (:destination_id, :title, :description, :url, :start_date,
                   :end_date, :source, :source_id, :ts)
           ON CONFLICT (source, source_id) DO UPDATE SET
             destination_id = :destination_id, title = :title,
             description = :description, url = :url, start_date = :start_date,
             end_date = :end_date, last_seen = :ts""",
        {**event, "source": source, "ts": ts, "destination_id": row[0],
         "description": event.get("description", ""),
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


def geocode(db, postcode):
    """Postcode to (lat, lon) via the locally imported Code-Point Open table."""
    norm = postcode.upper().replace(" ", "")
    row = db.execute(
        "SELECT lat, lon FROM postcodes WHERE postcode = ?", (norm,)).fetchone()
    return row if row else None
