"""Generic sitemap + JSON-LD source.

A source names its sitemap(s) and classifies URLs as place pages or event
pages; the engine crawls politely, parses the JSON-LD, and links events to
the place whose page they sit under (or whose name matches their location).
"""

import logging
import xml.etree.ElementTree as ElementTree

from . import jsonld

log = logging.getLogger(__name__)

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def sitemap_urls(fetcher, sitemap_url, depth=0):
    """All page URLs in a sitemap, following nested sitemap indexes."""
    if depth > 2:
        return
    try:
        root = ElementTree.fromstring(fetcher.get(sitemap_url))
    except Exception as e:  # noqa: BLE001 — one bad sitemap shouldn't kill the run
        log.warning("sitemap %s failed: %s", sitemap_url, e)
        return
    for element in root.iter():
        if element.tag == SITEMAP_NS + "sitemap":
            loc = element.find(SITEMAP_NS + "loc")
            if loc is not None and loc.text:
                yield from sitemap_urls(fetcher, loc.text.strip(), depth + 1)
        elif element.tag == SITEMAP_NS + "url":
            loc = element.find(SITEMAP_NS + "loc")
            if loc is not None and loc.text:
                yield loc.text.strip()


class SitemapJsonLdSource:
    """Subclasses set name and sitemaps, and implement classify()/category()."""

    name = None
    sitemaps = ()

    def classify(self, url):
        """'place', 'event' or None for a sitemap URL."""
        raise NotImplementedError

    def category(self, place):
        """Destination category for a parsed place dict."""
        raise NotImplementedError

    def place_key(self, url):
        """Stable source_id for a place page URL: its trailing path segment."""
        return url.rstrip("/").rsplit("/", 1)[-1]

    def scrape(self, fetcher, max_pages=0):
        """Yields ('place', dict) and ('event', dict) tuples."""
        urls = {"place": [], "event": []}
        for sitemap in self.sitemaps:
            for url in sitemap_urls(fetcher, sitemap):
                kind = self.classify(url)
                if kind in urls:
                    urls[kind].append(url)
        log.info("%s: %d place pages, %d event pages",
                 self.name, len(urls["place"]), len(urls["event"]))
        if max_pages:
            urls = {kind: pages[:max_pages] for kind, pages in urls.items()}

        for url in urls["place"]:
            for obj in self._objects(fetcher, url):
                place = jsonld.parse_place(obj, url)
                if place and "lat" in place:
                    place["source_id"] = self.place_key(url)
                    place["category"] = self.category(place)
                    yield "place", place
                    break  # one destination per place page

        for url in urls["event"]:
            for obj in self._objects(fetcher, url):
                event = jsonld.parse_event(obj, url)
                if event:
                    event["source_id"] = url.rstrip("/").rsplit("/", 1)[-1]
                    event["page_url"] = url
                    yield "event", event

    def _objects(self, fetcher, url):
        try:
            return jsonld.extract_objects(fetcher.get(url))
        except Exception as e:  # noqa: BLE001 — skip broken pages, keep the run alive
            log.warning("fetch %s failed: %s", url, e)
            return []
