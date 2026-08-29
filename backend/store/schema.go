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

-- Where events come from. Kept in the database rather than in code so a new
-- listing site is a row, not a release: the scraper reads this table and
-- picks an extractor by kind.
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    url         TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'auto',  -- auto|ical|jsonld|sitemap
    category    TEXT NOT NULL DEFAULT '',      -- default category for its events
    enabled     INTEGER NOT NULL DEFAULT 1,
    notes       TEXT NOT NULL DEFAULT '',
    added       TEXT NOT NULL,
    last_status TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    message     TEXT NOT NULL DEFAULT ''
);
`
