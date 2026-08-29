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
- **Scraper strategy**: sitemap crawl + schema.org JSON-LD parsing
  (generic engine in `sitemap_source.py`/`jsonld.py`), not per-site HTML
  scraping or private APIs. Politeness: robots.txt, 1 req/s/host, honest
  UA, 20h on-disk cache. Each source run is logged to `scrape_runs`.
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
