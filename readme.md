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
process that touches the internet. Destinations come from Wikidata's
SPARQL endpoint (CC0 open data, one request per category — National Trust
and English Heritage properties, gardens, aviation museums); English
Heritage's own site is crawled via its sitemap for schema.org JSON-LD.
Both feed the same destinations and events tables.

There was a National Trust events source and it has been removed. Each
property publishes an events page (`/visit/<region>/<property>/events`)
and the scraper knew how to read them, but it never could: measured on
real hardware, robots.txt allows those pages and the site still answers
with a 118 KB Radware bot-protection challenge carrying no data. Working
around a challenge (a disguised User-Agent, solving it, rotating
identities) would circumvent an access control the owner put there on
purpose, and is not something this scraper does — so the source probed one
page, recorded that it was refused, and stopped. It was kept for a while
in case the site opened up, then deleted: code that cannot run is upkeep
with no return, and git remembers it.

A hunt for a route they do sanction (`python3 -m daysout_scraper.feedhunt
--url <site>`, 30 Aug 2026) came back empty: robots.txt declares no
sitemap of its own, none of nine conventional feed paths holds a calendar
or RSS file (`/events.ics` serves an ordinary HTML page; the rest answer
with the same challenge), and — the route with the best odds — the
sitemap's event URLs carry **no dates at all**, so a URL list alone gives
titles with nothing to put them on a calendar with. English Heritage's
slugs do carry dates, which is why it was worth checking. Getting NT
events would therefore need either a feed from them or a page fetched by a
person in their own browser.

**National Trust properties are unaffected.** They reach the map from
Wikidata, as they always have.

### Which event sources actually work

Every source has a parser written for it. Sources used to be rows in a
table, added from the **Sources** tab and read by a generic engine that
picked an extractor by kind — which meant trying a new listing site was an
INSERT rather than a release. That is gone: these sites publish in too
many different shapes for one engine to read, so a new source starts with
`python3 -m daysout_scraper.discover --url <site>` to see what the site
actually offers, and ends with a parser written against it.

The Sources tab is now a report. Each source shows how many events and
places it is actually contributing, so one that yields nothing is visibly
different from one that works — click the count to see the events
themselves; **Update** runs a full
crawl of that one site and shows what came back — the events it read, or the reason there were
none. A test samples the site rather than crawling it, so it can add
events but never remove any. Sites not tested by hand are picked up by
the next daily scrape.
Twelve candidates were tried against the real sites (August 2026), and the
result is worth knowing before adding more:

| Source | Result |
|--------|--------|
| English Heritage | **Works** — 392 properties, ~119 events, Event JSON-LD per page |
| National Trust | Source removed. robots.txt permits `/visit/**`; the site answers with a 118 KB bot-protection challenge. Its properties still come from Wikidata — see above |
| RHS | **Works** — five flower shows, each with Event JSON-LD on its own page. The listing page has none, which is why a source aimed at the site root found nothing |
| NGS open gardens | **Works** — 214 gardens, 461 open days, from the find-a-garden JSON API. The "open this week" page is a hub of regional links, which is why rendering it found nothing |
| IACF antiques fairs | **Works** — 28 fairs across seven showgrounds, from the combined iCal feed its calendar page offers |
| Historic Houses | **Works** — 579 houses from its own sitemap; places only, no events |
| Invitation to View, Creative Crafts, The Festival Calendar (art/food/music) | Dropped. Sitemap only, no Event JSON-LD, and nothing after rendering either |
| Brighton Open Houses | Dropped — an open-houses trail publishes its dates in prose on a festival page, not per house |
| Food festival blog | **Works** — 80 festivals. BlogPosting JSON-LD and no postcode anywhere, so the dates come from its markup and the towns from the place-name gazetteer |
| UK Craft Fairs | **Works** — its calendar is the index and each fair's own page carries the JSON-LD. No structured data on the listing; malformed HTTP headers, so it can only be rendered |

Some sites build their listings in the browser, so a source may render the
page in headless Chromium before reading it — which is what a visitor's
browser does, and nothing more. UK Craft Fairs is the one that needs it.
Rendering is deliberately never used to get past a refusal: where a site
answers with a bot-protection challenge, rendering past it would be
evading an access control rather than reading a page, so
`looks_like_a_challenge` notices one and the source stops.

Browser automation is optional. Without Playwright installed those sources
are skipped with a warning and everything else runs as before:

```bash
pip install playwright && python3 -m playwright install chromium
# or point DAYSOUT_CHROMIUM at a Chromium already on the machine
```

The best outcome for a new site is that it needs no scraping at all: a
large share of UK venues and festivals run WordPress with The Events
Calendar, which publishes a documented REST API of dated, located events.
`feedhunt` looks for one, and source kind `wpevents` reads it.

Whether a site is worth a hand-written DOM parser is decided by evidence,
not by guessing: `discover --url <page> --browser` prints the served page
and the rendered page side by side — dates, date-carrying elements, event
links — and says which of the two failure modes applies (the listing is
there but unstructured, or it never reaches the page at all).

Sites that yielded nothing even rendered were dropped rather than left in
a table reporting the same failure nightly. The common thread is that they
build their listings client-side or behind a search form, so the dates a
visitor sees never reach the HTML — and where that is true, the answer is
usually not a heavier tool but a different address: the data is often in
an API the site's own front end calls, as it was for Waddesdon and NGS.

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
is estimated as great-circle distance × 1.2 road-wiggle at 60 km/h
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
