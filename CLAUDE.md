# Daysout — Project Context for Claude

## What this project is

A self-hosted days-out planner: a Go web server serves a React map/events
UI entirely from local data (SQLite + a PMTiles map archive), and a
separate Python scraper refreshes the database on a daily systemd timer.
Runs in an LXD container. Design principle: **nothing external at serve
time** — no map providers, no geocoding APIs, no paid services; only the
scraper (and three one-off setup downloads) ever touch the internet.

## Repository layout

```
daysout/
├── backend/           Go server (module github.com/andew42/daysout)
│   ├── main.go        Entry point; env DAYSOUT / DAYSOUT_DATA / DAYSOUT_PORT
│   ├── store/         SQLite (modernc.org/sqlite, pure Go), schema, queries,
│   │                  haversine drive-time maths, demo seed data
│   └── servers/       HTTP handlers (/api/*, /tiles/*, SPA fallback)
├── frontend/          React 19 + Vite 8; MapLibre GL + pmtiles + @protomaps/basemaps
│   └── src/           .jsx files: MapView, EventsView, SettingsView, api, settings
├── scraper/           Python 3.11+ package (requests + beautifulsoup4)
│   ├── daysout_scraper/          pipeline, polite fetcher, JSON-LD engine
│   ├── daysout_scraper/sources/  national_trust, english_heritage (+ stubs)
│   └── tests/         fixture-based; python3 -m unittest discover tests
├── setup/             One-off data population (postcodes, map tiles)
├── packaging/         systemd units + timer + install.sh
└── .github/workflows/build.yml   CI → rolling `latest` release
```

## Key decisions

- **Postcode → coordinates**: OS Code-Point Open imported into the
  `postcodes` table by `setup/import_postcodes.py`, which implements the
  OSGB36→WGS84 conversion from the OS guide (self-test: `--self-test`).
  Geocoding falls back to outward-district centroid ("SN13" works).
- **Offline map**: `uk.pmtiles` (Protomaps GB extract) served by the Go
  server as plain range requests; MapLibre GL renders it client-side.
  Fonts/sprites served locally from `data/basemap/`. Attribution "© 
  OpenStreetMap contributors" is required and shown on the map.
- **Drive time** = haversine km × 1.3 ÷ 60 km/h (constants in
  `backend/store/distance.go`). One hour ≈ 46 km crow-flies.
- **Schema**: `destinations` ↔ `events` (FK), upsert key `(source,
  source_id)`, `last_seen` ages out rows a source stops reporting. The
  schema lives in `backend/store/schema.go`; `scraper/tests/test_scraper.py`
  carries a mirror copy — keep them in sync.
- **Seed data**: a fresh database gets ~13 demo destinations
  (source='seed'); the scraper purges them once any real source has data.
- **Scraper strategy**: destinations come from Wikidata's SPARQL endpoint
  (CC0 open data, one request per category — `sources/wikidata.py`);
  organisation sites are crawled via sitemap + schema.org JSON-LD (generic
  engine in `sitemap_source.py`/`jsonld.py`) for their own properties and
  events. Politeness: robots.txt, 1 req/s/host, honest UA, 20h on-disk
  cache. Each source run is logged to `scrape_runs`.
- **National Trust: events only, and it stops when told no.** Each
  property publishes an events page
  (`/visit/<region>/<property>/events`), which robots.txt permits and
  which the old patterns missed entirely — they matched only
  `<property>/events/<slug>`. Both shapes are now read. Property pages are
  deliberately *not* crawled: Wikidata already supplies the properties, and
  the engine visits places before events, so crawling them would spend the
  run's first requests on the pages most likely to be challenged before
  reaching any event. `looks_like_a_challenge()` detects a bot-protection
  interstitial and sets `blocked`. A canary request runs before the
  sitemap so a refusal costs one request, and `failure_note` makes the run
  say it was refused rather than "no places found", which cannot tell a
  refusal apart from stale URL patterns. **Measured 30 Aug 2026 on the
  house server: robots.txt allows the events pages and the site still
  returns a 118,419-byte challenge with no JSON-LD.** So this source
  currently contributes nothing, by the site's choice, and is kept because
  it will work unchanged if that ever stops. We still never work around a
  challenge — no disguised User-Agent, no
  solving it, no rotating identities; the point of detecting it is to stop
  and say so rather than collect hundreds of refusals and report an empty
  site. NT event ids are `<property>-<title>-<start date>` so an event
  found on both the listing and its own page is one row.
- **Bounded runs never purge**: `--max-pages` runs (verification deploys)
  set `partial` and skip `purge_stale`, because a run that only looked at
  part of a source knows nothing about the rest.
- **Diagnosing a source**: `python3 -m daysout_scraper.inspect --source X
  --kind place|event` prints what the parser actually sees on real pages
  (code sources only). For any URL, including a `sources`-table row,
  `python3 -m daysout_scraper.discover --url U [--browser]` reports the
  formats it publishes and then `domscan.py`'s DOM evidence: byte count,
  `<time>` and date-classed elements, date-looking text, event-looking
  links, embedded JSON blobs — un-rendered and rendered side by side, with
  a verdict on whether a hand-written parser could read it. That
  comparison is the point: "rendering changed nothing" has to be a byte
  count in the log, not an assumption. The dev sandbox can't reach these
  sites — the deploy workflow runs it on the house server and the output
  lands in the run log.
- **Browser scanner** (`browser.py`, source kind `browser`): renders a page
  in headless Chromium before reading it, for sites that assemble their
  listing client-side so the dates never reach the served HTML. Playwright
  is an *optional* dependency — absent, browser sources are skipped with a
  warning and the rest of the run is unaffected. `find_chromium()` reuses a
  Chromium already on the machine (`DAYSOUT_CHROMIUM`, /usr/bin/chromium, or
  a Playwright browsers dir whose build number no longer matches the client)
  before falling back to Playwright's own. Rendering goes through the same
  Fetcher, so robots.txt, the rate limit and the cache all still apply;
  rendered pages cache under a separate key.
- **Rendering is not for getting past a refusal.** A site that answers with
  a bot-protection challenge is saying no, and a browser that defeats the
  challenge would be evading an access control rather than reading a page.
  National Trust must never be given kind='browser'; `refusedHosts` in
  `backend/store/sources.go` keeps it out of the Sources tab, and the code
  source stops rather than pushes on.
- **Sources live in the database**, not only in code: the `sources` table
  holds (name, url, kind, category, enabled). `sources/feeds.py` turns a
  row into a runnable source, so adding a listing site is an INSERT — which
  is what lets the **Sources tab** (`frontend/src/SourcesView.jsx`,
  `/api/sources`, `backend/store/sources.go`) add one from the browser.
  Adding a source only writes the row. **Test now**
  (`POST /api/sources/test`, `backend/servers/scrapetest.go`) is the one
  place the server reaches the internet, and it does it the only way
  anything here does — by running `python3 -m daysout_scraper --sources
  <name> --max-pages 10`, then reporting the scrape_runs verdict and the
  scraper's own log. Bounded, so the pipeline marks it a partial run and
  never purges: a test can add rows, never remove any. Guards: the name
  must match `safeSourceName` *and* exist in the table (a name starting
  with `-` would be read as a flag), one test at a time behind a mutex so
  a double-click can't send two crawls at one site, and a 3-minute
  timeout. `scraperLogLines` strips Python tracebacks — forty frames buried
  the one line worth reading — leaving the LEVEL-prefixed log. Rows added there are marked in `notes` with
  `store.UIAddedNote`, because only those are safe to delete — the scraper
  re-inserts any seeded candidate missing from the table, so seeded rows
  can only be disabled. `refusedHosts` in `sources.go` keeps National
  Trust out of the form entirely rather than leaving a trap behind the Add
  button.
  `kind` is ical | jsonld | sitemap | auto; auto probes the URL via
  `discover.py` and picks. `python3 -m daysout_scraper.discover` probes
  every row and records what it found in `sources.last_status` — run from
  the deploy workflow, since the sandbox can't reach the sites.
- **Events bring their venues**: a listing site names a venue we've never
  heard of, so `db.ensure_venue` geocodes its postcode against the local
  postcode table and creates the destination. Without that a new source
  contributes nothing sortable by distance. Structured
  `location.address.postalCode` is preferred over regexing prose.
- **`ensure_venue` must touch last_seen on an existing venue**, or the
  end-of-run stale purge deletes the venue the event needs.
- **`pipeline._venue` is the one place that decides where an event happens.**
  Sources disagree on shape and the disagreement silently lost events: a
  feed row gives `venue_postcode` and a trimmed name, a code source gives
  the raw JSON-LD (`location_postcode`, and a `location_name` that is the
  whole address line). It reads both, takes the first comma-separated part
  as the name, digs the postcode out of the address prose as a last
  resort, and — when a site publishes a postcode but no venue name at all,
  as RHS does for every flower show — labels the venue with the event's
  own title so the show still lands at the right postcode. The title is
  only ever used to *create* a venue, never to claim an event belongs to a
  place we already hold.
- **The scraper tests read the schema from `backend/store/schema.go`**
  (`tests/schema.py`) rather than keeping a copy — the copy drifted once
  and broke tests for unrelated reasons. `schema.go` is the current shape;
  `migrate.go` upgrades databases created before a column existed.
- **Concurrency**: server and scraper share the DB via WAL mode.

## Gotchas

- The development environment this repo was built in could NOT reach the
  scraped sites (egress proxy), so the NT/EH URL patterns in
  `scraper/daysout_scraper/sources/` are designed but unverified — first
  run on real hardware should use `--max-pages 20` and check results.
- `RequireConfigured` in `App.jsx` must stay a render-time component:
  computing "is a postcode configured" in App's body is stale after
  navigation (App doesn't re-render on route changes).
- SPA hard-refresh needs the index.html fallback in
  `backend/servers/spa.go`; plain `http.FileServer` 404s on /events.
- Vite 8 (Rolldown) won't parse JSX in `.js` files — keep `.jsx`.
- `python3 -m daysout_scraper` must run with `scraper/` as the working
  directory (or the package on PYTHONPATH); the systemd unit sets it.

## Build/test commands

```bash
cd backend && go vet ./... && go test ./...        # backend
cd frontend && npm run build                       # frontend
cd scraper && python3 -m unittest discover tests   # scraper
python3 setup/import_postcodes.py --self-test      # coordinate maths
```
