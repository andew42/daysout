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

import html
import json
import logging
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import dates, discover, domscan, ical, jsonld, postcode, slugdate
from ..sitemap_source import sitemap_urls

log = logging.getLogger(__name__)

# Listing pages rarely carry the events themselves; the individual event
# pages do, because sites want Google's event rich results. Crawling a whole
# sitemap for that would be rude and slow, so take the most recently
# modified pages — on an events site those are the current events.
DEFAULT_SITEMAP_PAGES = 50

# The Events Calendar, the WordPress plugin a large share of UK venues and
# festivals run, publishes a documented REST API. Dated, located,
# structured JSON — better than anything reading a listing could give us,
# and it needs no rendering and no guessing at markup.
EVENTS_API_PATHS = ("wp-json/tribe/events/v1/events",)
EVENTS_API_PAGE_SIZE = 50

# A planner needs the coming months, not a site's whole history.
MAX_API_PAGES = 6

# The newest pages on a site are often blog posts and news, not events, so
# prefer paths that look like an event before falling back on recency.
# Shared with the DOM diagnostic, which asks the same question of a page's
# own links.
EVENT_URL_HINT_RE = domscan.EVENT_URL_HINT_RE

# "Bolsover Castle, Castle Street, Bolsover, S44 6PR" -> S44 6PR.
# Shared with the pipeline, which digs for a postcode the same way for
# sources written in code.
find_postcode = postcode.find


def _plain(value):
    """WordPress gives a string or {'rendered': '<p>…</p>'}; want the text.

    Entities are decoded twice over because the API double-encodes them:
    "Knights&amp;#39; Tournament" survives one pass as "Knights&#39;
    Tournament", which is what reached the page and the map pins.
    """
    if isinstance(value, dict):
        value = value.get("rendered", "")
    text = str(value or "")
    text = " ".join(BeautifulSoup(text, "html.parser").get_text(" ").split())
    return " ".join(html.unescape(text).split())


class FeedSource:
    """Runs one row of the sources table."""

    def __init__(self, row):
        # row: (id, name, url, kind, category, venue_name, venue_postcode)
        (self.source_id, self.name, self.url, self.kind, self.category,
         self.venue_name, self.venue_postcode) = (tuple(row) + ("", ""))[:7]
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
        elif kind == "browser":
            yield from self._from_browser(fetcher)
        elif kind == "wpevents":
            yield from self._from_events_api(fetcher)
        else:
            log.warning("%s: unsupported kind %r", self.name, kind)

    def _detect(self, fetcher):
        # A documented API beats every kind of scraping, so ask first.
        if self._events_api_url(fetcher):
            log.info("%s: found a WordPress events API", self.name)
            return "wpevents"

        # The URL may itself be a sitemap — someone pasting
        # ".../sitemap.xml" means "crawl this", and probing it as a web
        # page finds nothing, which looked like the site publishing
        # nothing at all.
        if self._is_a_sitemap(fetcher, self.url):
            self.sitemap = self.url
            log.info("%s: the URL is a sitemap; crawling it", self.name)
            return "sitemap"

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

    def _is_a_sitemap(self, fetcher, url):
        try:
            head = fetcher.get(url).lstrip()[:400].lower()
        except Exception:  # noqa: BLE001 — unreachable is not "a sitemap"
            return False
        return "<urlset" in head or "<sitemapindex" in head

    def _from_sitemap(self, fetcher, max_pages):
        sitemap = self.sitemap or self.url
        limit = max_pages or DEFAULT_SITEMAP_PAGES

        all_pages = [(lastmod, url) for url, lastmod
                     in sitemap_urls(fetcher, sitemap, with_lastmod=True)]
        event_like = [p for p in all_pages if EVENT_URL_HINT_RE.search(p[1])]
        chosen, why = (event_like, "event-looking") if event_like else (all_pages, "recent")

        pages = sorted(chosen, reverse=True)[:limit]
        log.info("%s: scanning %d %s page(s) of %d in %s",
                 self.name, len(pages), why, len(all_pages), sitemap)

        found = dated = 0
        for _, url in pages:
            try:
                body = fetcher.get(url)
            except Exception as e:  # noqa: BLE001 — one bad page, keep going
                log.debug("%s: %s failed: %s", self.name, url, e)
                continue

            structured = False
            for obj in jsonld.extract_objects(body):
                parsed = jsonld.parse_event(obj, url)
                if parsed:
                    structured = True
                    found += 1
                    usable = self._event(
                        parsed, f"{parsed['title']}-{parsed['start_date']}")
                    if usable:
                        yield "event", usable
            if structured:
                continue

            # No structured data, but the site may have put the date in
            # the address — which is the most reliable thing about a page
            # that publishes nothing else.
            event = self._event_from_url(url, body)
            if event:
                dated += 1
                yield "event", event

        log.info("%s: %d event(s) from structured data and %d from dated URLs "
                 "in those pages", self.name, found, dated)

    def _event_from_url(self, url, body):
        """An event whose dates come from its URL, or None."""

        from_slug = slugdate.parse(url)
        if not from_slug:
            return None
        start, end = from_slug
        return self._event({
            "title": _page_title(body) or slugdate.title_from(url),
            "description": "",
            "url": url,
            "start_date": start,
            "end_date": end,
            "location_name": "",
            "location_postcode": postcode.find(body[:20000]),
        }, f"{start}-{slugdate.title_from(url)}")

    def _from_ical(self, fetcher, max_pages):
        text = fetcher.get(self.url)
        for index, event in enumerate(ical.parse(text)):
            if max_pages and index >= max_pages:
                break
            usable = self._event(
                event, event.get("uid") or f"{event['title']}-{event['start_date']}")
            if usable:
                yield "event", usable

    def _from_jsonld(self, fetcher, render=False):
        body = fetcher.get(self.url, render=render)
        found = 0
        for obj in jsonld.extract_objects(body):
            parsed = jsonld.parse_event(obj, self.url)
            if parsed:
                found += 1
                usable = self._event(
                    parsed, f"{parsed['title']}-{parsed['start_date']}")
                if usable:
                    yield "event", usable
        if render:
            log.info("%s: %d event(s) in the rendered page (%d bytes)",
                     self.name, found, len(body))

    def _from_browser(self, fetcher):
        """For a site that builds its listing client-side: render, then read.

        Only structured data is taken from the rendered page — the same
        Event JSON-LD every other source is read through. A site that
        renders its listing but still publishes no structured data needs a
        hand-written DOM parser, and the diagnostic
        (inspect --browser) is what decides whether that is worth writing.
        """
        yield from self._from_jsonld(fetcher, render=True)

    def _events_api_url(self, fetcher):
        """The site's events API endpoint, or '' if it has none."""

        base = self.url if self.url.endswith("/") else self.url + "/"
        for path in EVENTS_API_PATHS:
            url = urljoin(base, path)
            try:
                payload = json.loads(fetcher.get(url))
            except Exception:  # noqa: BLE001 — no API here, try the next
                continue
            if isinstance(payload, dict) and isinstance(payload.get("events"), list):
                return url
        return ""

    def _from_events_api(self, fetcher):
        """Read events from The Events Calendar's REST API.

        Paged through `next_rest_url`, which the plugin supplies, rather
        than by guessing page numbers. Only events from today onwards are
        asked for: the archive is large and of no use to a planner.
        """

        url = self._events_api_url(fetcher)
        if not url:
            log.warning("%s: no events API at %s", self.name, self.url)
            return

        separator = "&" if "?" in url else "?"
        url = (f"{url}{separator}per_page={EVENTS_API_PAGE_SIZE}"
               f"&start_date={date.today().isoformat()}")

        found = 0
        for _ in range(MAX_API_PAGES):
            try:
                payload = json.loads(fetcher.get(url))
            except Exception as e:  # noqa: BLE001 — one bad page, keep what we have
                log.warning("%s: %s failed: %s", self.name, url, e)
                return
            for event in payload.get("events", []):
                parsed = self._api_event(event)
                if parsed:
                    found += 1
                    yield "event", parsed
            url = payload.get("next_rest_url")
            if not url:
                break
        log.info("%s: %d event(s) from the events API", self.name, found)

    def _api_event(self, event):
        """One API record in the shape the pipeline stores, or None."""

        title = _plain(event.get("title"))
        # Not [:10]: "02/05/2026 10:00:00" is ten characters of the right
        # length and the wrong order, and passed straight through.
        start = dates.to_iso(event.get("start_date"))
        if not title or not start:
            return None
        venue = event.get("venue") or {}
        location = _plain(venue.get("venue"))
        return self._event(
            {
                "title": title,
                "description": _plain(event.get("description"))[:400],
                "url": event.get("url") or self.url,
                "start_date": start,
                "end_date": dates.to_iso(event.get("end_date")) or start,
                "location_name": location,
                "location_postcode": _plain(venue.get("zip")).upper(),
            },
            str(event.get("id") or f"{title}-{start}"))

    def _event(self, event, source_id):
        """Normalise into the shape the pipeline stores, carrying the venue.

        Returns None when the dates are not dates. Every route in — API,
        iCal, JSON-LD, sitemap — passes through here, so this is the one
        place that can promise the store gets ISO.
        """
        start = dates.to_iso(event.get("start_date"))
        if not start:
            log.warning("%s: unusable start date %r for %r", self.name,
                        event.get("start_date"), event.get("title", "")[:40])
            return None
        end = dates.to_iso(event.get("end_date")) or start

        venue = event.get("location_name", "")
        return {
            "source_id": source_id[:200],
            "title": event["title"],
            "description": event.get("description", ""),
            "url": event.get("url", "") or self.url,
            "start_date": start,
            "end_date": end,
            "category": self.category,
            # The venue as published: a name, plus its postcode — from the
            # structured address where the site provides one, otherwise
            # found in the location or description text.
            # A site that is one venue rarely repeats its address on every
            # event page, so fall back to the venue recorded against the
            # source. Without somewhere to put them those events are
            # dropped, which is most of what an attraction's own site
            # publishes.
            "location_name": venue.split(",")[0].strip() or self.venue_name,
            "venue_full": venue or self.venue_name,
            "venue_postcode": (event.get("location_postcode")
                               or find_postcode(venue, event.get("description", ""))
                               or self.venue_postcode),
        }

    def link_event(self, event):
        return None  # linked by venue name/postcode in the pipeline


def load_enabled(db):
    """FeedSource for every enabled row in the sources table."""
    rows = db.execute(
        "SELECT id, name, url, kind, category, venue_name, venue_postcode "
        "FROM sources WHERE enabled = 1 ORDER BY name").fetchall()
    return [FeedSource(row) for row in rows]


def _page_title(body):
    """The page's own heading, which beats a slug when there is one."""
    soup = BeautifulSoup(body, "html.parser")
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return " ".join(heading.get_text(" ", strip=True).split())[:160]
    if soup.title and soup.title.string:
        # "Evening Airshow | Shuttleworth" — the site name is not the event.
        text = soup.title.string.strip()
        return re.split(r"\s+[|\u2013-]\s+", text)[0][:160]
    return ""
