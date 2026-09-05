"""RHS flower shows.

A handful of large annual shows — Chelsea, Tatton Park, Malvern,
Badminton, Sandringham — rather than a long listing, and each one has a
page carrying clean Event JSON-LD: name, startDate, endDate and a full
PostalAddress. That is everything an event needs, from one fetch per
show.

The shape matters, because it is the opposite way round from what the old
`sources`-table row assumed. Measured 5 Sep 2026: **the listing page
`/shows-events` publishes no JSON-LD at all**, and neither does the site
root the row pointed at. Only the individual show pages do. A row aimed at
the site with kind `auto` therefore found nothing where it looked; the
listing is an index and the detail is on the pages it links, which is the
same division UK Craft Fairs has.

Five of the ten links on that page are shows. The others — an event
search, an "exhibit at a show" guide, and shows with no dates published
yet — carry no Event JSON-LD, and are skipped by that fact rather than by
a list of names that would rot the moment RHS renames one.

**A postcode field can contain prose.** Sandringham publishes
`postalCode` as "PE31 6AT (please don't follow sat nav directions on
approach, please follow the event signs)" — a real instruction to
visitors, wrapped inside a field meant to hold six characters. Storing
that whole string would fail to geocode and lose the show, so the
postcode is dug out of it with `postcode.find`. Anywhere a publisher can
type free text, assume somebody has.
"""

import json
import logging
import re

from bs4 import BeautifulSoup

from .. import dates, postcode as postcodes
from ..text import plain

log = logging.getLogger(__name__)

BASE = "https://www.rhs.org.uk"
INDEX = f"{BASE}/shows-events"

# /shows-events/<slug> and nothing deeper.
SHOW_RE = re.compile(r"^/shows-events/([a-z0-9\-]+)/?$")


class RHS:

    name = "rhs-events"
    category = "garden"

    def scrape(self, fetcher, max_pages=0):

        try:
            index = fetcher.get(INDEX)
        except Exception as e:  # noqa: BLE001 — the run, not one show
            log.warning("%s: %s failed: %s", self.name, INDEX, e)
            return

        pages = show_urls(index)
        log.info("%s: %d page(s) linked from the listing", self.name, len(pages))
        if max_pages:
            pages = pages[:max_pages]

        no_event = []
        for url in pages:
            try:
                body = fetcher.get(url)
            except Exception as e:  # noqa: BLE001 — one page, not the run
                log.warning("fetch %s failed: %s", url, e)
                continue
            event = parse_event(body, url)
            if event:
                event["category"] = self.category
                yield "event", event
            else:
                no_event.append(url.rstrip("/").rsplit("/", 1)[-1])

        if no_event:
            # Which pages: a show whose dates are not announced yet looks
            # exactly like a page shape we have stopped reading.
            log.info("%s: no Event data on %d of %d page(s): %s", self.name,
                     len(no_event), len(pages), ", ".join(no_event[:8]))

    def link_event(self, event):
        return None


def show_urls(body):
    """The /shows-events/<slug> pages linked from the listing."""

    soup = BeautifulSoup(body, "html.parser")
    urls = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        path = href[len(BASE):] if href.startswith(BASE) else href
        if not SHOW_RE.match(path):
            continue
        url = f"{BASE}{path.rstrip('/')}"
        if url not in urls:
            urls.append(url)
    return urls


def parse_event(body, url):
    """The show one page describes, or None if it publishes no Event."""

    data = event_data(body)
    if not data:
        return None

    start = dates.to_iso(data.get("startDate"))
    title = plain(data.get("name"))
    if not start or not title:
        return None

    location = data.get("location") or {}
    address = location.get("address") or {}
    return {
        "source_id": url.rstrip("/").rsplit("/", 1)[-1],
        "title": title[:160],
        "description": plain(data.get("description"))[:400],
        "url": data.get("url") or url,
        "start_date": start,
        "end_date": dates.to_iso(data.get("endDate")) or start,
        "location_name": plain(location.get("name")) or title,
        # Not the raw field: RHS puts visitor instructions inside it.
        "location_postcode": postcodes.find(
            str(address.get("postalCode") or ""),
            " ".join(str(part) for part in address.values())),
    }


def event_data(body):
    """The Event object in a page's JSON-LD, or None."""

    soup = BeautifulSoup(body, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            parsed = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for item in (parsed if isinstance(parsed, list) else [parsed]):
            if isinstance(item, dict) and item.get("@type") == "Event":
                return item
    return None
