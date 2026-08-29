"""National Trust properties and events.

Crawls www.nationaltrust.org.uk via its sitemap. Place pages live at
/visit/<region>/<place> and carry Place JSON-LD with coordinates; event
pages live below the place page (…/<place>/events/… or …/whats-on…) and
carry Event JSON-LD, so the owning place is derived from the URL path.

NOTE: URL patterns were designed from the site's public structure but the
first run should be checked with --max-pages 20 from a network that can
reach the site (this repo's development environment could not).
"""

import re

from ..sitemap_source import SitemapJsonLdSource

PLACE_RE = re.compile(r"^https://www\.nationaltrust\.org\.uk/visit/[^/]+/[^/]+/?$")
EVENT_RE = re.compile(r"^https://www\.nationaltrust\.org\.uk/visit/[^/]+/([^/]+)/(events|whats-on)/[^/]+/?$")

GARDEN_WORDS = re.compile(r"\bgardens?\b", re.IGNORECASE)


class NationalTrust(SitemapJsonLdSource):

    name = "national_trust"
    sitemaps = ("https://www.nationaltrust.org.uk/sitemap.xml",)

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
        """Owning place slug straight from the event page URL."""
        match = EVENT_RE.match(event.get("page_url", ""))
        return match.group(1) if match else None
