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
│   ├── daysout_scraper/sources/  wikidata, english_heritage,
│   │                             historic_houses, shuttleworth,
│   │                             ukcraftfairs, lamporthall, waddesdon,
│   │                             foodfestivals, ngs, iacf, rhs, stonor
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
  not for anything finer. **A shared name is refused unless one place dwarfs the rest** — there are
  twenty Middletons of similar size, and an event at the wrong one is
  worse than one the map never shows, the same reasoning that makes
  `dates.to_iso` refuse a date rather than approximate it. Entries within
  `SAME_PLACE_KM` are folded together as they are collected, since
  duplicate Wikidata entries for a single town are common. Where genuinely
  different places share a name, **population decides**: one of at least
  `MIN_POPULATION` that is `DOMINANCE`× the next answers for the name, and
  anything closer is dropped (~1,870 of ~24,000). Population rather than
  Wikidata's settlement type, because the typing is not consistent enough
  to lean on — Bath is filed a "city of the United Kingdom" and Brighton a
  "market town", and a first version that ranked by type dropped Brighton
  for exactly that reason. **The type list is only for coverage, and
  leaving types out of it is not a neutral omission**: with no Brighton in
  the table, the hamlet of Brighton in Cornwall was the only one of that
  name, looked perfectly unambiguous, and took every Brighton event 230 km
  west. An absent place does not merely fail to match; it lets a smaller
  namesake answer for it. **The import re-runs when its own rules change**, not once per lifetime:
  `--if-stale` hashes `import_places.py` and compares that with a
  fingerprint recorded in `places_meta`, so the deploy runs it every time
  and it refetches only when the rules differ. A "first deploy only" guard
  is what left the Bath-less table in place — the rules here change more
  often than the data does, and a table built by old ones looks perfectly
  healthy from outside. A version recorded over an empty table counts as
  stale, since that is what a half-finished import leaves.
  The population is fetched with `MAX` and
  `GROUP BY`, not a bare `OPTIONAL`: a town with a figure per census comes
  back once per figure, which pushed the village response past the size
  the endpoint returns intact — it arrived truncated mid-JSON and the type
  was lost silently. Counties are *not* in the table, only
  settlements, so "Staffordshire" places nothing: a county centroid can be
  tens of kilometres from the event, which is the error the drive-time
  ring is measuring in. A venue placed this way says so in the run log,
  because it is less precise than one placed by postcode and that
  difference has to be visible.
  **The venue is then named after the town, not after the event.** A
  touring festival runs under one name in a dozen places — Foodies
  Festival plays Bath, Oxford, Edinburgh and Glasgow — and while the venue
  carried the festival's name they were all the same venue: the first
  created won and `find_destination_id_by_name` matched the rest to it, so
  Bath's was reported at St Albans, 170 km and an hour wrong. A source
  that knows only the town must claim only the town, which is why
  `foodfestivals` sends an empty `location_name`; two festivals in one
  town then correctly share its pin.
  **The normaliser exists twice** — in the
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
- **The National Trust source is gone, and the refusal it met is not.**
  It read one events page per property and never contributed a row:
  **measured 30 Aug 2026 on the house server, robots.txt allows those
  pages and the site still answers with a 118,419-byte bot-protection
  challenge carrying no JSON-LD.** It was kept for a while on the grounds
  that it would work unchanged if that ever stopped; it was removed
  instead, because a source that cannot run is upkeep with no return, and
  the version in git is there if the site ever opens up. **NT properties
  are unaffected** — they always came from Wikidata (`wdt:P137
  wd:Q333515`, 369 of them with coordinates) and still do. Two things
  survive the removal deliberately. `fetch.looks_like_a_challenge` moved
  out of that module into `fetch.py`, where it belongs anyway: it
  describes what a *server* returned, `feedhunt` uses it on any site, and
  several sources cite it to say "nobody is turning us away". There was
  also a `refusedHosts` guard keeping nationaltrust.org.uk out of the
  Sources tab's Add form; it was kept when this source went and then
  became unreachable when the form itself did, since a page that cannot
  add a source cannot be pointed at a refusing one. It went with the form.
  We never work around a challenge: no disguised User-Agent, no solving
  it, no rotating identities. The point of detecting one is to stop and
  say so rather than collect hundreds of refusals and report an empty
  site.
- **Bounded runs never purge**: `--max-pages` runs (verification deploys)
  set `partial` and skip `purge_stale`, because a run that only looked at
  part of a source knows nothing about the rest.
- **Diagnosing a source**: `python3 -m daysout_scraper.inspect --source X
  --kind place|event` prints what the parser actually sees on real pages
  (code sources only). For any URL at all — which is where reading a new
  site starts —
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
  This is a rule about how sources are written, not a setting to get
  wrong: nothing can be pointed at a site from the UI any more, so the
  only way a renderer meets a challenge is somebody writing a source that
  does it on purpose. `looks_like_a_challenge` is there to notice and
  stop.
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
  cannot geocode rather than storing it at 0,0. It began as a seeded row
  and was the first candidate to earn a parser of its own.
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
- **Food festivals** (`sources/foodfestivals.py`) is the source the
  gazetteer was built for, and the one that shows what "wrong kind" costs.
  It was seeded `kind='browser'` on the guess that a blog's roundups "may
  render dates", and that was wrong twice over: the page is a
  `BlogPosting` with no Event JSON-LD for a structured-data kind to find,
  and its dates were in the served HTML all along, so rendering was never
  the missing piece. One plain request gets all of it. **Check what a page
  is actually missing before deciding how to read it.** The markup is an
  `<h4>` per month and an `<h3>` per festival whose link leaves for the
  festival's own site, with the date opening the `<p>` after it — and
  those dates carry their year, so `parse_range` reads 124 of 134 as they
  stand, no inference of the Lamport Hall kind. What stopped it working
  was that there is **not one postcode on the page**, and all 134 links
  are third-party, so the UK Craft Fairs answer (listing as index, item's
  own page for the address) would mean crawling 134 unrelated domains.
  Place names are therefore offered to the pipeline as *candidates* in
  order rather than resolved in the source, which cannot see the database:
  "Foodies Festival, Bath, Somerset" hides its town in the middle and
  "Ludlow Food Festival, Shropshire" hides it in the festival's own name,
  and only the gazetteer can tell a town from a county — which it does by
  holding no counties at all. `ensure_venue` takes the first candidate it
  holds. The event's title stays the venue label, as RHS shows are
  labelled: what we know is the festival and roughly where, not the field
  it is in. Measured 5 Sep 2026 against the live page with the real
  gazetteer: 124 dated, **80 linked at 68 venues**, up from nothing, and
  six spot-checks land within 1.4 km of the right town. The rest name a
  country house or only a county and are dropped and named in the log.
- **NGS open gardens** (`sources/ngs.py`) is the best-shaped data here and
  the clearest case of a diagnostic being right while its conclusion was
  wrong. Two rows were seeded at ngs.org.uk pages and switched to
  `kind='browser'` because rendering `/gardens-open-this-coming-week/`
  added 130 KB of Cookiebot tables and no gardens. All true — but measured
  5 Sep 2026, **that page is not a listing**: it is a hub of regional
  links ("East of England — Click here"), so there were never gardens on
  it to render, and rendering the wrong page harder was never going to
  help. **Ask what a page is before asking why it will not parse.**
  Following those links leaves ngs.org.uk for a separate app at
  findagarden.ngs.org.uk, whose Vue bundle names its own JSON API —
  `https://api.findagarden.ngs.org.uk/api`, with `/gardens`,
  `/gardens/filters`, `/geocode`. One request returns every listed garden
  with name, **postcode**, description, tags, **real coordinates** and its
  dated openings: no rendering, no geocoding, nothing parsed out of prose.
  ngs.org.uk's robots.txt disallows its own faceted-search query strings,
  the usual crawler trap; findagarden serves no robots.txt, and this reads
  one endpoint once rather than crawling facets.
  **An opening is a day or it is a window, and only one is an event.** The
  feed mixes both, separated by an undocumented `garden_opening_type_id`,
  so the rule is what the dates say instead: across all 2,342 records,
  types 1/2/5 are **100% same-day** (1,889 of them) while 3/4 run a median
  182 days and up to 364 — "by arrangement", a season in which you may ring
  the owner, not a day anyone can turn up. Same start and end means an
  event; longer does not. That needs no knowledge of the enum and survives
  a sixth type appearing. Cancelled openings are flagged and kept by the
  feed, so they are skipped explicitly, as are past ones — and a garden
  with no future day is not published as a place at all, since an NGS
  garden is somebody's private garden and a pin for one that never opens
  is a pin for somewhere you cannot go. Events link to their garden **by
  the feed's id** through `link_event`, not by name: two gardens really
  are called The Old Vicarage, and name-matching would put one's open day
  two hundred miles away. Measured 5 Sep 2026: 624 gardens listed, **214
  with a future open day, 461 openings, 461/461 linked**, every one with a
  postcode and inside the UK. Both seeded NGS rows are gone with the table
  that held them.
- **Stonor** (`sources/stonor.py`) is where the day-first date lesson came
  from, and it now needs reading a third way. It was a `wpevents` row while
  the site ran The Events Calendar; measured 5 Sep 2026 that route 404s and
  the plugin has gone. The site registers its own `events` post type, so
  `/wp-json/wp/v2/events` lists six events and their links — with **no
  `meta` and no `acf`**, so the API gives the index and not one date. The
  dates are on the pages as Event JSON-LD with a full address, so the API
  is the index and each page the detail: the UK Craft Fairs division
  arrived at from the opposite end, because here it is the API that is
  thin rather than the listing. `startDate` is `"19/09/2026"` — day-first
  and slashed, the shape that once put five Stonor events in the database
  as "02/05/2026", sorting before every real date and failing
  `end_date >= today` while the run reported them linked. Nothing slices a
  date: `jsonld.parse_event` goes through `dates.to_iso`. Measured live:
  6/6 events at Stonor Park, RG9 6HF.
- **A source that is deleted leaves its rows behind**, and `purge_stale`
  will not take them: that only removes what a *running* source stopped
  reporting. The house server was still serving events from sources
  retired days earlier — national_trust, three per-venue IACF rows, the
  festival-calendar candidates — and still listing their `scrape_runs` in
  `/api/status` as though they were sources.
  `db.purge_unknown_sources` removes anything whose source is not in
  `sources.IMPLEMENTED`, called from `__main__` **only after a run that
  read every source**: one told to run a single source knows nothing about
  the rest, the same reason a bounded run never purges. It lives in the
  scraper rather than the server because that is where the list of sources
  actually is — putting it in Go would mean deleting rows on the strength
  of `CodeSources`, a second list that can drift. Two things it must not
  touch: the demo `seed` rows, which have their own purge that waits for a
  real source to have data, and a venue a surviving source still has
  events at, since destinations cascade to their events.
- **Every source is written in code, and that is the second answer to this
  question.** Sources used to live in a `sources` table — (name, url, kind,
  category, enabled) — which `sources/feeds.py` turned into a runnable
  source by picking an extractor from the kind (`auto`, `wpevents`,
  `ical`, `jsonld`, `sitemap`, `browser`). Adding a listing site was an
  INSERT, and the Sources tab could do it from the browser. The idea was
  sound and the results were not: **these sites differ so much that
  reading one takes a parser written against it**, after somebody has
  looked at what it actually publishes, and rows added without that
  investigation reported an empty site for ever. Of the seeded candidates
  only two ever produced anything, and both are now code sources
  (`sources/iacf.py`, `sources/rhs.py`); the other five never did. So the
  table is gone, `feeds.py` and `seed_sources.py` with it, along with
  `slugdate.py`, which nothing but the generic engine used. `migrate.go`
  drops `sources` and `removed_sources` from databases that still hold
  them, rather than leaving a schema that describes a feature nothing
  implements.
  The **Sources tab** (`frontend/src/SourcesView.jsx`, `GET /api/sources`,
  `backend/store/sources.go`) is now a report: it lists what the scraper
  has code for, with **what each source is contributing** — events and
  places, ordered by what they produced, so what works is at the top —
  plus the scraper's own message from its last run. The pill is still a
  button and still opens the rows themselves
  (`GET /api/sources/contribution`), because a count says a source is
  working and only the rows say whether what it produced is any good: a
  source can report five events and have read five meaningless ones.
  Capped at 200 rows a side, with the true totals shown. **Update** is the
  only thing the page can now ask for.
  `store.CodeSources` is the list the page renders, and a test keeps it in
  step with the scraper's `IMPLEMENTED`: a name missing from it is a
  source that has quietly stopped being listed, and nobody would notice
  until they wondered where its events came from.
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
  has gone; ten-minute timeout. Guards: the name must match
  `safeSourceName` *and* be one the scraper actually has (a name starting
  with `-` would be read as a flag), one update at a time behind a mutex
  so a double-click cannot send two crawls at one site. `scraperLogLines`
  strips Python tracebacks — forty frames buried the one line worth
  reading — leaving the LEVEL-prefixed log.
- **An iCal feed needs no parser of ours.** `ical.py` reads RFC 5545, so a
  site publishing .ics needs only a source that fetches it — IACF is the
  case in point (`sources/iacf.py`), reading the combined feed its own
  calendar page links as "Add all iacf fairs to my calendar". Three things about the
  format bite. An all-day `DTEND` is **exclusive**, so a fair running the
  2nd to the 3rd is published as ending on the 4th. Long lines are folded
  as CRLF plus **one** inserted space, so unfolding a fold at a word gap
  needs two spaces on the continuation line — a test fixture written with
  one is wrong, not the reader. And a WordPress export writes its post
  text straight into `SUMMARY`/`DESCRIPTION` with HTML entities still in
  it, so `_unescape` decodes those as well as RFC 5545's own escaping.
  The feed's URL is a query string (`?feed=...`), right to fetch and no use
  to click, so `IACF.site_url` points a reader at the calendar page
  instead. Shepton Mallet's own feed once answered with a valid calendar
  listing **no** fairs — a real answer, so the source says so rather than
  leaving the pipeline's "unreachable, blocked, or its patterns are wrong"
  as the only word.
- **One IACF source, not one per venue.** Measured 1 Sep 2026: the site has
  no events API (every `wp-json` event route 404s), its calendar page
  carries no Event JSON-LD and its sitemap no event URLs — but that page
  links `?feed=iacf-all-events-ical`, offered for exactly this. IACF runs
  more than the three venues first seeded: Newark, Ardingly, Shepton
  Mallet, Builth Wells, Norfolk, Runway and Newbury. The per-venue rows
  it replaced are gone with the table that held them, and their events
  with them: nothing refreshes an event whose source no longer exists,
  and the same fairs would otherwise sit in the list twice.
  A source spanning seven showgrounds **cannot carry a fallback venue**: a
  single postcode would put a Welsh fair at a Nottinghamshire one, so
  every event must bring its own address in LOCATION. One that does not is
  still yielded and named in the log rather than dropped in the source —
  the pipeline can place it at a venue another fair in the same feed
  created, which is how the Newark winter market lands.
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
  Worth knowing how that ended, because the measurement was right and the
  conclusion drawn from it was not: there were no gardens in the rendering
  because there were none on the page. It is a hub of regional links, not
  a listing. "Rendering adds nothing" answers *how* a page is built and
  says nothing about whether it is the right page — so when a scan comes
  back empty, read what the page actually is before reaching for a
  heavier tool. See `sources/ngs.py`.
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
  its first write before reading a single source, and because the
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
