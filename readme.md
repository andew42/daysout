# Daysout

A self-hosted "what's on near me" site. Open it on a Saturday morning and
see destinations (historic houses, gardens, airfields) and special events
within an hour's drive of your postcode — served entirely from a local
SQLite database with an offline map. No external data providers, no API
keys, no subscriptions.

- **Map view** — pan/zoom map centred on your postcode with destination
  markers, filtered by category and maximum drive time.
- **Events view** — special events over the next few days, ordered by
  distance from home.
- **Settings** — home postcode, categories, drive-time limit (kept in the
  browser).

A separate Python scraper runs on a daily systemd timer and is the only
process that touches the internet: it crawls destination websites
(National Trust and English Heritage so far) via their sitemaps, parses
the schema.org JSON-LD their pages embed, and upserts destinations and
events into the shared database.

## How it works

```
Browser ── React + MapLibre GL (frontend/)
   │  HTTP (LAN)
Go server (backend/) ── /api/* JSON, /tiles/* range requests, static files
   │
   ├─ daysout.db    SQLite (WAL): destinations, events, postcodes
   └─ uk.pmtiles    offline map tile archive (single file)
   ▲
Python scraper (scraper/) ── daily systemd timer, upserts via WAL
```

Offline data comes from three one-off downloads (see `setup/README.md`):
OS Code-Point Open for postcode→coordinates, a Protomaps PMTiles extract
of Great Britain for the map, and the basemap fonts/sprites. Drive time
is estimated as great-circle distance × 1.3 road-wiggle at 60 km/h
average — roughly ±15 minutes, fine for a Saturday-morning glance.

## Install (LXD container or any systemd Linux)

```bash
curl -fsSL https://github.com/andew42/daysout/releases/latest/download/install.sh | sudo bash
```

Then populate the data directory once (postcodes + map tiles) — the
installer prints the two commands, which are documented in
`setup/README.md`. Kick off a first scrape with
`systemctl start daysout-scrape` or wait for the 05:30 timer.

## Development

```bash
# Backend dev server (creates ./data/daysout.db with demo seed data)
cd backend && go run .

# Frontend dev server (proxies /api, /tiles, /basemap to localhost:8080)
cd frontend && npm install && npm start

# Scraper tests (no network needed)
cd scraper && python3 -m unittest discover tests

# Scraper verification run against the live sites (limit pages first!)
cd scraper && python3 -m daysout_scraper --db ../backend/data/daysout.db --max-pages 20
```

The backend is Go with a single dependency (`modernc.org/sqlite`, pure Go
so no cgo when cross-compiling). The frontend is React 19 + Vite; MapLibre
GL renders the offline vector tiles via the `pmtiles` protocol. CI builds
everything on every push to `master` and republishes the rolling `latest`
release the installer pulls from.

For hands-off testing on the real house server, a self-hosted runner in
the LXD container lets the **Deploy to house server** workflow install
and smoke-test every build in place — setup in
`docs/self-hosted-runner.md`.

## Data licensing

- Map tiles: © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors (ODbL), built by [Protomaps](https://protomaps.com/).
- Postcodes: Contains OS data © Crown copyright and database right;
  contains Royal Mail data © Royal Mail copyright and database right
  (Code-Point Open, Open Government Licence).
- Scraped destination/event details remain © their respective sites; the
  scraper is polite (robots.txt, 1 request/second, honest User-Agent,
  on-disk cache) and intended for personal use.
