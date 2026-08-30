"""Shuttleworth — air shows, house and gardens at Old Warden.

One venue with its own event pages, and nothing machine-readable on
them: no Event JSON-LD, no <time>, no date-classed elements, and no date
in the URL. Its 33 event pages come from the sitemap; the date has to be
read out of the markup, which is only safe because the deploy printed
where each date on the page actually sits.

Two shapes, both taken from real pages:

  * The event's own date is a list item under <ul class="icon-list">:
    "5 -  6 December 2026" on the Christmas market page.
  * A show that runs to a timetable has no such list, and gives its days
    as <h5 class="itinerary-listing--day--title">29 August 2026</h5>.

Every page also carries a carousel of *other* events — the same six on
every page — whose dates sit under <ul class="icon-list text-muted my-3">
inside <li class="swiper-slide">. Those are what make "this page has
date-looking text" useless here, and why the read is anchored to the
element rather than to the first date found.
"""

import logging
import re

from bs4 import BeautifulSoup

from .. import dates, postcode as postcodes
from ..sitemap_source import sitemap_urls

log = logging.getLogger(__name__)

EVENT_RE = re.compile(r"^https://www\.shuttleworth\.org/events/[^/]+/?$")

# The carousel of other events reuses icon-list with these on it.
CAROUSEL_MARKERS = ("text-muted", "swiper-slide")


class Shuttleworth:

    name = "shuttleworth-events"
    sitemaps = ("https://www.shuttleworth.org/sitemap.xml",)
    category = "airfield"
    venue_name = "Shuttleworth"

    def scrape(self, fetcher, max_pages=0):

        urls = []
        for sitemap in self.sitemaps:
            for url, lastmod in sitemap_urls(fetcher, sitemap, with_lastmod=True):
                if EVENT_RE.match(url):
                    urls.append((lastmod, url))
        log.info("%s: %d event page(s) in the sitemap", self.name, len(urls))

        pages = [url for _, url in sorted(urls, reverse=True)]
        if max_pages:
            pages = pages[:max_pages]

        undated = []
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
                undated.append(url.rstrip("/").rsplit("/", 1)[-1])

        if undated:
            # Which pages, not just how many: a date shape we do not read
            # yet looks exactly like a page that has no date.
            log.info("%s: no date found on %d of %d page(s): %s",
                     self.name, len(undated), len(pages), ", ".join(undated[:8]))

    def link_event(self, event):
        return None


def parse_event(body, url):
    """An event dict for one Shuttleworth event page, or None."""

    soup = BeautifulSoup(body, "html.parser")
    start, end = _dates(soup)
    if not start:
        return None

    title = _heading(soup)
    if not title:
        return None

    return {
        "source_id": url.rstrip("/").rsplit("/", 1)[-1],
        "title": title,
        "description": "",
        "url": url,
        "start_date": start,
        "end_date": end,
        # One venue publishing its own events: the address in the page
        # chrome is the venue's, unlike a directory site's footer.
        "location_name": "Shuttleworth",
        "location_postcode": postcodes.find(soup.get_text(" ", strip=True)),
    }


def _dates(soup):
    """(start, end) for the page's own event, or ('', '')."""

    for element in soup.select("ul.icon-list li"):
        if _in_carousel(element):
            continue
        start, end = dates.parse_range(element.get_text(" ", strip=True))
        if start:
            return start, end

    # A show with a timetable lists a heading per day; the event runs from
    # the first to the last.
    days = []
    for element in soup.select(".itinerary-listing--day--title"):
        start, _ = dates.parse_range(element.get_text(" ", strip=True))
        if start:
            days.append(start)
    if days:
        return min(days), max(days)

    return "", ""


def _in_carousel(element):
    """Is this date one of the other events every page advertises?"""
    for parent in [element] + list(element.parents):
        classes = parent.get("class") or [] if hasattr(parent, "get") else []
        if any(marker in classes for marker in CAROUSEL_MARKERS):
            return True
    return False


def _heading(soup):
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return " ".join(heading.get_text(" ", strip=True).split())[:160]
    if soup.title and soup.title.string:
        # "Military Air Show - Shuttleworth" — the site name is not the event.
        return re.split(r"\s+[|–-]\s+", soup.title.string.strip())[0][:160]
    return ""
