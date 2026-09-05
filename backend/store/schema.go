package store

// Schema is applied on every startup; all statements are idempotent.
const schema = `
CREATE TABLE IF NOT EXISTS destinations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    postcode    TEXT NOT NULL DEFAULT '',
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY,
    destination_id INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    url            TEXT NOT NULL DEFAULT '',
    start_date     TEXT NOT NULL,
    end_date       TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_events_dates ON events (start_date, end_date);

CREATE TABLE IF NOT EXISTS postcodes (
    postcode TEXT PRIMARY KEY,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL
);

-- Place name -> coordinates, for a listing that names a town and no
-- postcode. Filled by setup/import_places.py from Wikidata (CC0).
--
-- Only names that identify ONE settlement are in here: the import drops
-- anything ambiguous (there are twenty Middletons), because a venue put in
-- the wrong county is worse than one the map never shows. So a hit is
-- always safe to use and the lookup needs no tie-breaking.
CREATE TABLE IF NOT EXISTS places (
    name TEXT PRIMARY KEY,
    lat  REAL NOT NULL,
    lon  REAL NOT NULL
);

-- There were sources and removed_sources tables here, holding listing
-- sites as rows so a new one was an INSERT rather than a release, and a
-- record of the ones removed through the UI so a removal did not undo
-- itself. Both are gone, and migrate.go drops them from databases that
-- still have them: the sites differ too much for a generic engine to read,
-- so every source is written in code and the list of them lives there.

CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    message     TEXT NOT NULL DEFAULT ''
);
`
