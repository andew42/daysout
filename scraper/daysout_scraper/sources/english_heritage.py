"""English Heritage properties and events.

Crawls www.english-heritage.org.uk via its sitemap. Place pages live at
/visit/places/<slug>/ with Place JSON-LD; event pages under /visit/whats-on/
don't reference the place in their URL, so events are linked by matching the
JSON-LD location name against the place names found in the same run.

NOTE: as with the National Trust source, verify the first run with
--max-pages 20 from a network that can reach the site.
"""

import re

from ..sitemap_source import SitemapJsonLdSource

PLACE_RE = re.compile(r"^https://www\.english-heritage\.org\.uk/visit/places/[^/]+/?$")
EVENT_RE = re.compile(r"^https://www\.english-heritage\.org\.uk/visit/whats-on/[^/]+/?$")

GARDEN_WORDS = re.compile(r"\bgardens?\b", re.IGNORECASE)


class EnglishHeritage(SitemapJsonLdSource):

    name = "english_heritage"
    sitemaps = ("https://www.english-heritage.org.uk/sitemap.xml",)

    def classify(self, url):
        if PLACE_RE.match(url):
            return "place"
        if EVENT_RE.match(url):
            return "event"
        return None

    def category(self, place):
        text = place["name"] + " " + place["description"]
        return "garden" if GARDEN_WORDS.search(text) else "historic-house"

    def link_event(self, event):
        # No place slug in the URL; the pipeline falls back to matching
        # the event's location name against this run's place names.
        return None
