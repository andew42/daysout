"""Stonor Park — one Oxfordshire house, read from its own event pages.

This was a `sources` row of kind `wpevents` and worked for a while: the
site ran The Events Calendar and answered
`/wp-json/tribe/events/v1/events`. Measured 5 Sep 2026, that route 404s —
the plugin has gone. The site is still WordPress and now registers its own
`events` post type, so `/wp-json/wp/v2/events` lists them, but with no
`meta` and no `acf`: the API gives the six events and their links, and not
a single date.

The dates are on the pages, as Event JSON-LD with a full address. So the
API is the index and each page is the detail — the same division UK Craft
Fairs and RHS have, arrived at from the opposite direction, because here
it is the *API* that is thin rather than the listing page.

**The date is day-first and slashed.** `"startDate": "19/09/2026"`, and
this site is where that lesson was learned: its old API answered
"02/05/2026 10:00:00", whose first ten characters are the right length and
the wrong order, so all five events sat in the database stored as
"02/05/2026" — sorting before every real date and failing `end_date >=
today`, while the run reported them linked. Nothing here slices a date;
`jsonld.parse_event` goes through `dates.to_iso`, which reads day-first.

Its titles come escaped ("Medieval Jousting &#8211; The Ultimate...") and
`jsonld._text` unescapes them, because the frontend escapes what it
interpolates and an entity left in the database is one the reader sees.
"""

import json
import logging

from .. import jsonld

log = logging.getLogger(__name__)

BASE = "https://www.stonor.com"
API = f"{BASE}/wp-json/wp/v2/events?per_page=100"
SITE = f"{BASE}/whats-on/"


class Stonor:

    name = "stonor-whats-on"
    category = "historic-house"
    site_url = SITE

    def scrape(self, fetcher, max_pages=0):

        try:
            body = fetcher.get(API, api=True)
        except Exception as e:  # noqa: BLE001 — the run, not one event
            log.warning("%s: %s failed: %s", self.name, API, e)
            return

        pages = event_urls(json.loads(body))
        log.info("%s: %d event(s) listed by the API", self.name, len(pages))
        if max_pages:
            pages = pages[:max_pages]

        undated = []
        for url in pages:
            try:
                page = fetcher.get(url)
            except Exception as e:  # noqa: BLE001 — one page, not the run
                log.warning("fetch %s failed: %s", url, e)
                continue
            event = parse_event(page, url)
            if event:
                event["category"] = self.category
                yield "event", event
            else:
                undated.append(url.rstrip("/").rsplit("/", 1)[-1])

        if undated:
            # Which pages: an event whose JSON-LD has gone looks exactly
            # like one this parser has stopped understanding.
            log.info("%s: no Event data on %d of %d page(s): %s", self.name,
                     len(undated), len(pages), ", ".join(undated[:8]))

    def link_event(self, event):
        return None


def event_urls(records):
    """The event page URLs the API lists, in the order it gives them."""

    urls = []
    for record in records:
        url = str(record.get("link") or "").strip()
        if url.startswith(BASE) and url not in urls:
            urls.append(url)
    return urls


def parse_event(body, url):
    """The event one page describes, or None if it publishes no Event."""

    for obj in jsonld.extract_objects(body):
        event = jsonld.parse_event(obj, url)
        if event:
            # source_id from the page rather than the title: an annual
            # event keeps its slug and changes its dates.
            event["source_id"] = url.rstrip("/").rsplit("/", 1)[-1]
            return event
    return None
