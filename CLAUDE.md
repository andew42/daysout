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
│   └── src/           .jsx files: MapView, EventsView, SettingsView,
│                       SourcesView, api, settings, links
├── scraper/           Python 3.11+ package (requests + beautifulsoup4)
│   ├── daysout_scraper/          pipeline, polite fetcher, JSON-LD engine
│   ├── daysout_scraper/sources/  national_trust, english_heritage,
│   │                             historic_houses, shuttleworth (+ stubs)
│   └── tests/         fixture-based; python3 -m unittest discover tests
├── setup/             One-off data population (postcodes, map tiles)
├── packaging/         systemd units + timer + install.sh
└── .github/workflows/
    ├── build.yml   CI → rolling `latest` release
    └── deploy.yml  self-hosted runner: install, scrape, and every
                    diagnostic that needs to reach the real sites
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
- **Drive time** = haversine km × 1.2 ÷ 60 km/h (constants in
  `backend/store/distance.go`). One hour ≈ 50 km crow-flies. The map
  draws its ring in the browser from its own copy of those two constants,
  so `MapView.jsx` names them and a Go test asserts the pair agree.
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
- **Dates are ISO or they are nothing** (`scraper/daysout_scraper/dates.py`).
  They are stored as text and every query compares them as text, so a date
  in another shape does not look odd — it fails `end_date >= today` and the
  event is invisible while the run still reports it linked. Stonor's events
  API answers "02/05/2026 10:00:00", whose first ten characters are the
  right length and the wrong order, and all five of its events sat in the
  database unseen. `dates.to_iso` normalises on every route in, and
  `db.upsert_event` refuses anything that is not `YYYY-MM-DD` rather than
  storing it quietly. That guard earned its keep on UK Craft Fairs, whose
  JSON-LD is *not* zero-padded — `startDate` is "2026-9-6T10:00:00", and
  its first ten characters are "2026-9-6T1". `jsonld._date` used to take
  that slice, so all 26 fairs of the first live run were read perfectly
  and refused at the door. It parses through `dates.to_iso` now, and
  `to_iso` accepts an unpadded year-first date; slicing ten characters
  off a date assumes a publisher pads, and two sites here do not.
- **Historic Houses** (`sources/historic_houses.py`) covers the privately
  owned houses the two big charities leave out. Its `house-sitemap.xml` is
  one entry per house and carries no events, so it contributes places only,
  and a house page publishes an address rather than coordinates — hence
  `pipeline` geocoding a place from its postcode, and dropping one it
  cannot geocode rather than storing it at 0,0. A code source and a
  `sources` row must never share a name (both lists run in one pass and
  the loser overwrites the winner's result): `SUPERSEDED` in
  `seed_sources.py` deletes the row, deliberately *not* via `RETIRED`,
  whose `removed_sources` entry would also hide the code source from the
  Sources tab.
- **Shuttleworth** (`sources/shuttleworth.py`) is one venue whose event
  pages carry nothing machine-readable — no Event JSON-LD, no `<time>`, no
  date-classed elements, no date in the URL. The date is read from the
  markup, anchored to the element rather than to the first date on the
  page: every page also advertises the same six *other* events, so "the
  page has date-looking text" (seven phrases per page) is worthless here.
  `domscan.date_context` is what found the anchor, and is the tool to
  reach for on the next site like it.
- **A code source and a `sources` row must never share a name**: both lists
  run in one pass and the loser overwrites the winner's result.
  `CodeSources` in `backend/store/sources.go` names the code sources so a
  name with no row is listed only if one claims it — otherwise it is
  leftover `scrape_runs` history posing as an unremovable built-in. A test
  reads the scraper's registry to keep the two lists in step.
- **Sources live in the database**, not only in code: the `sources` table
  holds (name, url, kind, category, enabled). `sources/feeds.py` turns a
  row into a runnable source, so adding a listing site is an INSERT — which
  is what lets the **Sources tab** (`frontend/src/SourcesView.jsx`,
  `/api/sources`, `backend/store/sources.go`) add one from the browser.
  The listing shows **what each source is contributing** — events and
  places, ordered by events, so what works is at the top — plus the
  scraper's own message from its last run. The pill is a button: it opens
  the rows themselves (`GET /api/sources/contribution`), because a count
  says a source is working and only the rows say whether what it produced
  is any good — a source can report five events and have read five
  meaningless ones. Capped at 200 rows a side, with the true totals shown. A verdict like "publishes:
  sitemap" and a count of zero mean the same thing in the end, and only
  one of them says so. It also lists the sources written in code
  (`builtIn`), found by taking the union of the table with whatever has
  run or produced rows: the sources written in code are not in the table
  and are the ones that work, so a page listing only the table was a list
  of failures. Built-in rows offer Update and nothing else — there is no
  row to remove.
- **Remove is the only way to stop a source**, behind a confirmation
  dialog because it is not undoable. Three things have to happen together
  or it does not stick: the row goes, the name is recorded in
  `removed_sources` (`seed_sources.ensure()` re-inserts any candidate
  missing from the table, so an unrecorded removal undoes itself), and the
  listing excludes removed names — a source keeps its `scrape_runs`
  history, which brought it back through the union looking `builtIn` and
  therefore unremovable. Its events go too: nothing refreshes them once
  the source is gone. Its venues go only if no other source's events sit
  there, since destinations cascade to their events. Enable/disable was
  dropped from the UI; the `enabled` column stays, since the scraper uses it.
- **`seed_sources.RETIRED` drops a candidate for good**, deleting the row
  and its rows from any database that still holds it. Removing a name from
  `CANDIDATES` alone does nothing to an existing database, because
  `ensure()` only ever inserts.
- **A source may carry its own venue** (`venue_name`, `venue_postcode`).
  An attraction's own website rarely repeats its address on every event
  page, so without it those events have nowhere to go and are dropped —
  which is most of what a single-venue site publishes.
- **UK Craft Fairs cannot be fetched, only rendered** — and that is a
  broken server, not a refusal. Measured on the house server 31 Aug 2026:
  every plain request to `www.ukcraftfairs.com` times out, because the
  response's header block contains `Strict Transport Security:` — spaces
  where the hyphens belong — which is not a legal header name, so
  http.client never finds the blank line separating headers from body and
  the read hangs until the timeout, though `Content-Length: 14756` is sat
  right there in the same block. That took out robots.txt, both sitemap
  paths, all four wp-json routes and all nine conventional feed paths, so
  the site has no feed, no API and no crawlable sitemap *as far as we can
  ever tell*. Chromium is lenient about the bad header and renders the
  page in full (40,061 bytes), and `looks_like_a_challenge` is false —
  nobody is turning us away. The *calendar* carries no Event JSON-LD,
  which is exactly why `kind='browser'` yielded nothing: that kind reads
  structured data and that page has none. But each fair's own page does,
  so `sources/ukcraftfairs.py` uses the calendar as the index the site
  otherwise lacks and the fair's page for the details.
- **UK Craft Fairs' calendar is a single-day view.** `/calendar` is headed
  "Monday, 31 August 2026" and lists the fairs running *that day*; other
  days are addressed as its own `<` and `>` links do,
  `/calendar/1-september-2026`. Each fair is an `<a class="grid-item
  panel-list">` whose body holds `<p><strong>Venue</strong>, Town,
  County</p>` and `<p>Saturday, <strong>29 August 2026</strong> (3 day
  event)</p>` — the date is the fair's **start** and the bracket its
  length, which is why a page headed the 31st shows fairs dated the 27th
  and 29th: they are multi-day fairs still running. `.panel-list` matches
  both the anchor and the panel inside it, so the obvious selector finds
  every fair twice; the parser keys on the anchor that wraps a
  `.panel-list-bottom`, which is also what tells a fair's card from the
  navigation links.
- **A UK Craft Fairs day page carries no postcode**, only a town and a
  county, and the pipeline drops an event it cannot geocode — so the
  listing alone would read fairs all day and contribute nothing. The
  fair's own page (`/craft-events/<id>/<slug>`) is fetched for it, and
  carries both Event JSON-LD and an address. Its JSON-LD is preferred but
  is not always complete: one fair gave `startDate` and no `endDate`,
  which would turn a three-day fair into a one-day one, so the listing's
  length wins when it is longer, and `postcode.find` over the page text
  is the fallback when the JSON-LD has no `postalCode`.
- **`slugdate.py` reads dates out of a URL** — "evening-airshow-15-september-2026".
  It was written for Shuttleworth and does **not** apply there: measured
  30 Aug 2026, that sitemap holds 374 URLs and **none** carries a date, so
  the assumption behind it was simply wrong. It still covers the English
  Heritage shape. Before writing another parser for a site, run
  `feedhunt --url <site> --scan-newest`, which reports the URL shapes and
  then what the newest event page actually contains — `_detect` recognising a
  sitemap URL is the part of that work that did help: someone pasting
  ".../sitemap.xml" means "crawl this", and probing it as a web page found
  nothing, which read as the site publishing nothing at all.
- Adding a source only writes the row. **Update**
  (`POST /api/sources/update`, `backend/servers/sourceupdate.go`) is the
  one place the server reaches the internet, and it does it the only way
  anything here does — by running `python3 -m daysout_scraper --sources
  <name>`, then reporting the scrape_runs verdict and the scraper's own
  log. A full crawl, because the point of pressing Update is to have this
  source's events be right, which means letting the pipeline purge what
  has gone; ten-minute timeout. Guards: the name
  must match `safeSourceName` *and* exist in the table (a name starting
  with `-` would be read as a flag), one test at a time behind a mutex so
  a double-click can't send two crawls at one site. `scraperLogLines` strips Python tracebacks — forty frames buried
  the one line worth reading — leaving the LEVEL-prefixed log. Rows added there are marked in `notes` with
  `store.UIAddedNote`, because only those are safe to delete — the scraper
  re-inserts any seeded candidate missing from the table, so seeded rows
  can only be disabled. `refusedHosts` in `sources.go` keeps National
  Trust out of the form entirely rather than leaving a trap behind the Add
  button.
  `kind` is wpevents | ical | jsonld | sitemap | browser | auto; auto
  probes the URL via `discover.py` and picks, trying `wpevents` first
  because a documented API beats every kind of scraping.
- **`wpevents` reads The Events Calendar's REST API**
  (`/wp-json/tribe/events/v1/events`), the WordPress plugin a large share
  of UK venues and festivals run. It gives a title, real dates and a venue
  with a postcode, needs no rendering, and does not break when a site
  restyles. Paging follows the API's own `next_rest_url` rather than
  guessing page numbers, and only events from today on are asked for.
  `feedhunt` probes for it on any site.
- **`domscan.deep_scan` answers "why are there no dates?"** — the three
  explanations worth telling apart are a listing inside an iframe
  (invisible to `page.content()`), one behind a search form, and one that
  never arrives. `discover --url --browser --deep` prints iframes, forms
  and repeated row-shaped blocks. That diagnostic answered the NGS case:
  the 130 KB rendering added was **Cookiebot's own cookie tables** — 94,
  75, 75, 74 repeated `CybotCookiebot*` blocks — and no gardens at all.
- **The renderer answers cookie banners and scrolls.** A consent manager
  holds back the scripts that draw a listing until a choice is made, and a
  banner governs cookies rather than access, so answering one is what
  every visitor does; `CONSENT_SELECTORS` tries *decline* before accept.
  Scrolling follows, for listings that arrive as you go. Both are covered
  by `tests/test_consent.py`, which drives a real browser.
- **`fetcher.get(fresh=True)` skips reading the cache.** The first
  deploy of the scrolling change proved nothing: the render came from the
  20-hour cache and the byte counts came back identical, which looked like
  evidence and was not. Diagnostics that test the renderer must pass
  `--fresh`. `python3 -m daysout_scraper.discover` probes
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
- **A filtered-out event must say so.** `Store.Events` returns an
  `EventsResult`: the events to show plus counts of what was dropped and
  why (too far, wrong category, beyond the horizon, plus the nearest
  excluded venue), and `EventsView` prints it. Silent filtering is
  indistinguishable from a broken query — a source reported five events on
  the Sources tab and showed none here, with nothing to explain the
  difference. An event's own category counts as well as its venue's: a
  craft fair at a historic house is both.
- **Settings apply as they change.** They were written to localStorage
  only on form submit, so moving the drive-time slider and navigating by
  the nav left the app querying the old limit while the page showed the
  new one — a setting that looks applied and is not reads exactly like a
  broken filter. The postcode still waits for the button, because it is
  only worth keeping once it geocodes.
- **`index.html` is revalidated, hashed assets are not**
  (`servers/spa.go`). With no cache headers at all, a browser's heuristic
  could keep serving a deployed-over page — which points at the previous
  build's hashed bundle, so a deploy lands and nothing changes.
- **Scraped text is untrusted.** Names, descriptions and URLs come from
  other people's pages: the map popup escapes what it interpolates, and
  every link goes through `webURL` (`links.jsx`), which passes only
  absolute http(s) — `javascript:` and `data:` come back empty.
- **A venue's link is the site, not the event page**, since a venue
  outlives the event that introduced it. `backfill_venue_url` fills a
  blank on every linked event, not just when creating the venue:
  `ensure_venue` only runs for venues we do *not* already hold, which
  after the first scrape is none of them, so putting the fix there alone
  changed nothing on the map.
- **The Build workflow is serialised** (`concurrency`, cancel-in-progress).
  The rolling release is one mutable tag, deleted and recreated per run,
  so two pushes a minute apart raced and the loser failed with a 403 that
  reads like a permissions problem.
- **Concurrency**: server and scraper share the DB via WAL mode.

## Gotchas

- **The development environment cannot reach any scraped site** (egress
  proxy: `CONNECT tunnel failed, 403`). Every fact about a real page in
  this file came from the deploy workflow's log, and a parser written here
  without that evidence is a guess — `slugdate.py` is what that costs.
  When a new site needs reading, add a step to `deploy.yml` that prints
  what its pages carry, push, and write the parser against the output.
  Patterns since verified on the house server (30-31 Aug 2026): English
  Heritage 392 places / 116 events, Historic Houses 579 places, National
  Trust challenged, Stonor 5 events, Shuttleworth 24 events, UK Craft
  Fairs 26 events at 23 venues.
  A diagnostic that needs a plain fetch to succeed first is one that
  cannot report on a site whose plain fetch never will: `inspect_dom`
  scans the served page before the rendered one and returns on the
  failure, so the whole UK Craft Fairs render went unreported for a
  deploy. Where the point is the rendered page, render it directly.
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
