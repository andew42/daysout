"""Sources defined by a row in the database rather than by code.

Each row in the `sources` table names a URL and a kind; this turns one
into something the pipeline can run. Adding a listing site is then an
INSERT, not a release — which is the point, because most event sites are
found by trying them and many turn out not to publish anything usable.

Events arrive with a venue name and often an address, but rarely with
coordinates. Venues are resolved against the local postcode table so an
event brings its destination with it, which is what makes distance
sorting work for sites we have never seen before.
"""

import logging
import re

from .. import discover, ical, jsonld
from ..sitemap_source import sitemap_urls

log = logging.getLogger(__name__)

# Listing pages rarely carry the events themselves; the individual event
# pages do, because sites want Google's event rich results. Crawling a whole
# sitemap for that would be rude and slow, so take the most recently
# modified pages — on an events site those are the current events.
DEFAULT_SITEMAP_PAGES = 50

# "Bolsover Castle, Castle Street, Bolsover, S44 6PR" -> S44 6PR
POSTCODE_RE = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.IGNORECASE)


def find_postcode(*texts):
    for text in texts:
        if not text:
            continue
        match = POSTCODE_RE.search(text)
        if match:
            return f"{match.group(1).upper()} {match.group(2).upper()}"
    return ""


class FeedSource:
    """Runs one row of the sources table."""

    def __init__(self, row):
        # row: (id, name, url, kind, category)
        self.source_id, self.name, self.url, self.kind, self.category = row
        self.sitemap = ""

    # The pipeline treats every source the same way.
    def scrape(self, fetcher, max_pages=0):
        kind = self.kind
        if kind == "auto":
            kind = self._detect(fetcher)
            if not kind:
                log.warning("%s: no machine-readable events at %s", self.name, self.url)
                return

        if kind == "ical":
            yield from self._from_ical(fetcher, max_pages)
        elif kind == "jsonld":
            yield from self._from_jsonld(fetcher)
        elif kind == "sitemap":
            yield from self._from_sitemap(fetcher, max_pages)
        else:
            log.warning("%s: unsupported kind %r", self.name, kind)

    def _detect(self, fetcher):
        report = discover.probe(fetcher, self.url)
        if "ical" in report["formats"]:
            return "ical"
        if "ical-link" in report["formats"]:
            self.url = report["ical_urls"][0]
            log.info("%s: following iCal link %s", self.name, self.url)
            return "ical"
        if "jsonld" in report["formats"]:
            return "jsonld"
        if "sitemap" in report["formats"]:
            self.sitemap = report["sitemap_urls"][0]
            return "sitemap"
        return None

    def _from_sitemap(self, fetcher, max_pages):
        sitemap = self.sitemap or self.url
        limit = max_pages or DEFAULT_SITEMAP_PAGES

        pages = sorted(
            ((lastmod, url) for url, lastmod
             in sitemap_urls(fetcher, sitemap, with_lastmod=True)),
            reverse=True)[:limit]
        log.info("%s: scanning %d most recent page(s) of %s",
                 self.name, len(pages), sitemap)

        found = 0
        for _, url in pages:
            try:
                body = fetcher.get(url)
            except Exception as e:  # noqa: BLE001 — one bad page, keep going
                log.debug("%s: %s failed: %s", self.name, url, e)
                continue
            for obj in jsonld.extract_objects(body):
                parsed = jsonld.parse_event(obj, url)
                if parsed:
                    found += 1
                    yield "event", self._event(
                        parsed, f"{parsed['title']}-{parsed['start_date']}")
        log.info("%s: %d event(s) in those pages", self.name, found)

    def _from_ical(self, fetcher, max_pages):
        text = fetcher.get(self.url)
        for index, event in enumerate(ical.parse(text)):
            if max_pages and index >= max_pages:
                break
            yield "event", self._event(
                event, event.get("uid") or f"{event['title']}-{event['start_date']}")

    def _from_jsonld(self, fetcher):
        body = fetcher.get(self.url)
        for obj in jsonld.extract_objects(body):
            parsed = jsonld.parse_event(obj, self.url)
            if parsed:
                yield "event", self._event(
                    parsed, f"{parsed['title']}-{parsed['start_date']}")

    def _event(self, event, source_id):
        """Normalise into the shape the pipeline stores, carrying the venue."""
        venue = event.get("location_name", "")
        return {
            "source_id": source_id[:200],
            "title": event["title"],
            "description": event.get("description", ""),
            "url": event.get("url", "") or self.url,
            "start_date": event["start_date"],
            "end_date": event.get("end_date", event["start_date"]),
            "category": self.category,
            # The venue as published: a name, plus its postcode — from the
            # structured address where the site provides one, otherwise
            # found in the location or description text.
            "location_name": venue.split(",")[0].strip(),
            "venue_full": venue,
            "venue_postcode": (event.get("location_postcode")
                               or find_postcode(venue, event.get("description", ""))),
        }

    def link_event(self, event):
        return None  # linked by venue name/postcode in the pipeline


def load_enabled(db):
    """FeedSource for every enabled row in the sources table."""
    rows = db.execute(
        "SELECT id, name, url, kind, category FROM sources "
        "WHERE enabled = 1 ORDER BY name").fetchall()
    return [FeedSource(row) for row in rows]
