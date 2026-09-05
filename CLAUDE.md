# Daysout — Project Context for Claude

## What this project is

A self-hosted days-out planner: a Go web server serves a React map/events
UI entirely from local data (SQLite + a PMTiles map archive), and a
separate Python scraper refreshes the database on a daily systemd timer.
Runs in an LXD container. Design principle: **nothing external at serve
time** — no map providers, no geocoding APIs, no paid services; only the
scraper (and four one-off setup downloads) ever touch the internet.

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
│   │                             historic_houses, shuttleworth,
│   │                             ukcraftfairs, lamporthall, waddesdon
│   └── tests/         fixture-based; python3 -m unittest discover tests
├── setup/             One-off data population (postcodes, places, map tiles)
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
- **Town → coordinates, when there is no postcode at all.** Some listings
  never print an address: "Ludlow Food Festival, Shropshire" is all you
  get, and `ensure_venue` used to drop every such event, so those sources
  contributed nothing however good their dates were. `setup/import_places.py`
  fills a `places` table from Wikidata (CC0 — the same source and licence
  the scraper already uses for destinations), and `db.geocode_place` is the
  fallback `ensure_venue` tries when a postcode is missing *or* unknown. A
  postcode still wins: it is a doorstep and a town is a centroid, which is
  the right order of accuracy for rings measured in tens of kilometres but
  not for anything finer. **Only unambiguous names are imported** — there
  are twenty Middletons, and an event at the wrong one is worse than one
  the map never shows, the same reasoning that makes `dates.to_iso` refuse
  a date rather than approximate it. Names within `SAME_PLACE_KM` of each
  other are folded into one row, since duplicate Wikidata entries for a
  single town are common; genuinely different places sharing a name are
  dropped (~1,900 of ~24,000). Counties are *not* in the table, only
  settlements, so "Staffordshire" places nothing: a county centroid can be
  tens of kilometres from the event, which is the error the drive-time
  ring is measuring in. A venue placed this way says so in the run log,
  because it is less precise than one placed by postcode and that
  difference has to be visible. **The normaliser exists twice** — in the
  importer that writes the key and in `db.normalise_place` that reads it —
  and a disagreement would not fail, it would silently never match, so
  `test_places.py` asserts the two agree. One query per settlement type:
  the endpoint 504s on `wdt:P31/wdt:P279*` and on the flat query for all
  30,000 rows at once (measured 5 Sep 2026).
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
- **Lamport Hall** (`sources/lamporthall.py`) is the second single venue
  with nothing machine-readable — no Event JSON-LD, no `<time>`, no events
  API, no date in the URL — and the only source so far whose dates **state
  no year**. All 18 pages read "6th November" or "Thursday 22nd October",
  so `dates.parse_range` cannot touch them: it requires a 4-digit year,
  precisely because inventing one puts an event twelve months out. The
  year is inferred here, where the page's own purpose justifies it — a
  what's-on page lists what is coming — as the next occurrence, with a
  month of grace so a run already under way is not thrown forward a year.
  Three date shapes, all real: one day; several days sharing a month named
  once at the end ("5th, 6th, 8th … & 13th December"); and several each
  naming its own ("22nd October & 29th October"). A day therefore takes
  the first month named *after* it, the one rule that reads all three —
  and a month written *before* its days is deliberately not read, since
  the site never writes one and covering an unseen shape is what
  `slugdate.py` cost. Times are stripped first or "10am-4pm" contributes a
  10 and a 4, and only a number with an ordinal suffix counts as a day.
  Days are then grouped into runs of touching days and **each run is its
  own event**, the way `ical._merge_runs` joins a fair published a day at
  a time: the Christmas Market's two weekends are two events, not a
  nine-day market, so `source_id` is `<slug>-<start>` — the slug alone
  would have the second overwrite the first on `(source, source_id)`.
  Three pages state no day at all ("Selected dates throughout December")
  and are skipped and named in the log rather than guessed at. The index
  needs its fragments dropped before the path is matched: `/events/#scrolltop`
  is a back-to-top link that otherwise reads as a nineteenth event,
  re-fetches the index and is then reported as undated — junk in the one
  line that says which date shapes went unread. Measured against the live
  site 5 Sep 2026: 18 pages, 15 dated, 22 events, all at NN6 9EZ.
  That postcode is the one the site gives "for satnav"; its postal
  address is NN6 9HD, and this is a tool for driving somewhere.
- **Waddesdon** (`sources/waddesdon.py`) is the case where the pages are
  worthless and the API is excellent. A National Trust property but not a
  National Trust *site*: waddesdon.org.uk is the Rothschild Foundation's
  own WordPress, `robots.txt` is `Disallow:` with nothing after it, and
  nothing here works around anything. Its pages carry JSON-LD of type
  WebPage/Organization only — no Event, no dates, 273 KB each — and The
  Events Calendar is not installed, so `wpevents` does not apply. What it
  does publish is its own post type, `rothschild_event`, at
  **`/wp-json/wp/v2/events`**: 46 events with real dates in `meta`. Two
  requests a run instead of 46 page fetches, which matters because
  robots.txt asks `Crawl-delay: 10` and **the Fetcher does not implement
  crawl-delay** — it holds a fixed per-host interval, so a page crawl here
  would be ruder than the site asked for. Three traps. WordPress's own
  `date` is when the entry was *published*, not when the event runs —
  that is `meta.rothschild_event_start_date`. Half the feed is over (22 of
  46, some from 2025, since nothing takes an old event down), so events
  are dropped on `end_date` the way `wpevents` asks only for future ones.
  And the API mixes "2026-10-18T13:08:53" with "2026-08-14T00:00:00+01:00",
  where the offset is the trap: midnight on the 14th British time is 23:00
  on the *13th* UTC, so anything converting these to an instant moves the
  event a day — `dates.to_iso` takes the published calendar date and never
  builds a moment, the same rule `EventsView.formatDate` follows at the
  other end. The `event-locations` taxonomy names places *inside* the
  estate (Wine Cellars, South Front, Aviary Glade) and is deliberately not
  used as the venue: passing one to the pipeline would geocode a second
  destination with no address of its own. `event-categories` *is* used,
  mapped onto the app's own list by term **name**, because the slugs carry
  an import artefact ("food-wine-3338" but plain "exhibitions") and the
  names do not. Where the span is not when you can turn up — "Every Friday
  and Saturday" runs 6-28 November — the site's own summary of when is
  prepended to the description, since two dates alone would send a reader
  on a Tuesday. Long programmes are stored at their true span rather than
  clamped: `isOngoing` already files anything over `OngoingDays` as a
  standing programme and sorts it below the special events. Measured
  5 Sep 2026: 46 published, 22 over, 24 current, all at HP18 0JH.
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
- **An iCal feed needs no parser of ours.** `ical.py` reads RFC 5545 and
  `kind='ical'` runs it, so a site publishing .ics is an INSERT — IACF is
  the case in point, as one row (`iacf`) reading the combined feed its own
  calendar page links as "Add all iacf fairs to my calendar". Three things about the
  format bite. An all-day `DTEND` is **exclusive**, so a fair running the
  2nd to the 3rd is published as ending on the 4th. Long lines are folded
  as CRLF plus **one** inserted space, so unfolding a fold at a word gap
  needs two spaces on the continuation line — a test fixture written with
  one is wrong, not the reader. And a WordPress export writes its post
  text straight into `SUMMARY`/`DESCRIPTION` with HTML entities still in
  it, so `_unescape` decodes those as well as RFC 5545's own escaping.
  Their URLs are query strings (`?feed=...`), so the kind is set
  explicitly: `auto` would probe it as a web page. Shepton Mallet's own
  feed answered with a valid calendar listing **no** fairs — a real
  answer, so `_from_ical` says so rather than leaving the pipeline's
  "unreachable, blocked, or its patterns are wrong" as the only word.
- **One IACF row, not one per venue.** Measured 1 Sep 2026: the site has
  no events API (every `wp-json` event route 404s), its calendar page
  carries no Event JSON-LD and its sitemap no event URLs — but that page
  links `?feed=iacf-all-events-ical`, offered for exactly this. IACF runs
  more than the three venues first seeded: Newark, Ardingly, Shepton
  Mallet, Builth Wells, Norfolk, Runway and Newbury. The per-venue rows
  are `RETIRED`, not `SUPERSEDED` — no code source takes those names, and
  their events must go with them, since nothing refreshes an event whose
  row is gone and the same fairs would sit in the list twice.
  A row spanning seven showgrounds **cannot carry a fallback venue**: a
  single `venue_postcode` would put a Welsh fair at a Nottinghamshire
  postcode, so `venue_name`/`venue_postcode` are left blank and an event
  whose LOCATION omits the postcode is dropped and named in the log.
- **A multi-day fair may be published as one event per day.** IACF's
  feeds carry "…Fair: 10-11 December" twice, dated the 10th and the 11th,
  and stored as they arrive that shows every fair twice on the events
  list with each copy claiming a single day its own title contradicts.
  `ical._merge_runs` joins a run back together: same title, same
  location, and only where the days actually touch, so a monthly fair of
  the same name stays several events. It sorts before merging rather
  than trusting the feed's order — Newark lists December before October.
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
- **Stored ISO, shown dd/mm/yyyy.** `EventsView.formatDate` slices the
  stored `YYYY-MM-DD` string rather than going through a `Date`: these
  are plain dates with no time, and parsing one into a `Date` makes it a
  moment, which is why the old version pinned it to midday to stop a
  timezone shift showing the 1st as the 31st. Slicing text cannot drift.
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
- **JSON-LD text has to be unescaped, page markup does not.** Script
  content is raw text in HTML5, so the parser decodes entities in a
  page's markup and leaves them untouched inside
  `<script type="application/ld+json">`. A site whose templating escapes
  the block anyway hands us "Members&#39; Event" — and because the
  frontend escapes what it interpolates, quite correctly, an entity left
  in the database is one the reader actually sees. `jsonld._text` is the
  one place every JSON-LD string comes through, so it unescapes there,
  once: English Heritage escapes singly. The same trap arrives by two
  other routes and is closed at each: `ical._unescape` decodes entities a
  WordPress .ics export leaves in `SUMMARY`/`DESCRIPTION`, and
  `feeds._plain` unescapes *twice* because the WordPress REST API
  double-encodes. Anywhere text arrives from somebody else's template,
  assume it is escaped once too often.
  Existing rows heal themselves: `upsert_destination` updates the name on
  conflict, and a venue created by `ensure_venue` keys on its name, so the
  corrected one is a new row and the stale purge takes the old.
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
- **Concurrency**: server and scraper share the DB via WAL mode. Two
  *scrapers* cannot share it, though: `pipeline.run_source` holds a write
  transaction for the whole of a source's crawl — `upsert_destination`
  runs inside the loop and the commit comes after the generator is
  exhausted — so a source with a few hundred pages holds the lock for
  minutes, and a second scraper dies on "database is locked" after
  `db.connect`'s 30 seconds. The timer fires at 05:30 and a deploy landed
  at 05:42 while it was still going: the deploy's scrape died in
  `seed_sources.ensure` before reading a single source, and because the
  Scrape step is `continue-on-error` the deploy went green with the
  previous day's rows still in the database. `runlock.acquire` now takes
  an exclusive lock and waits, which is what the Update button needs —
  pressed during the nightly run it should do the work a moment later
  rather than refuse. **The dev sandbox does not honour flock between
  processes** (nor lockf): two processes both take the same exclusive
  lock and neither waits, while within one process it behaves. So the
  unit tests cannot prove the case that matters and a deploy step checks
  it on the house server.

## Gotchas

- **The development environment usually cannot reach a scraped site**
  (egress proxy: `CONNECT tunnel failed, 403`). Most facts about a real
  page in this file came from the deploy workflow's log, and a parser
  written without that evidence is a guess — `slugdate.py` is what that
  costs. When a new site needs reading, add a step to `deploy.yml` that
  prints what its pages carry, push, and write the parser against the
  output. **Check before assuming, in either direction**: on 5 Sep 2026 a
  sandbox did have egress, and `sources/lamporthall.py` was written and
  run against the live site from it — one `curl` settled that in a
  second. The rule that matters is not "the sandbox is offline", it is
  that a parser must be written against a page somebody actually read.
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
python3 setup/import_places.py --self-test         # gazetteer rules
```
