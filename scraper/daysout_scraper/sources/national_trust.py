"""National Trust — DISABLED, the site blocks automated access.

The sitemap crawl works (1279 property pages, 2229 event pages), but the
property and event pages themselves come back as a Radware bot-protection
challenge page ("Radware Page", ~118 KB, no content) rather than the real
HTML. That is the site deliberately refusing automated clients.

We do not work around that. Disguising the scraper as a browser, solving
the challenge, or rotating identities would be circumventing an access
control the site owner put in place on purpose — so this source stays
disabled rather than evasive.

National Trust properties still reach the database: they come from
Wikidata (see wikidata.py), which publishes them as CC0 open data with an
endpoint meant for programmatic queries. Events are the part that is
genuinely lost — if they are wanted later, the sanctioned routes are to
ask the National Trust for data access, or to look for an official feed.

The module is kept (and excluded from sources.IMPLEMENTED) so the URL
patterns and this history are not rediscovered from scratch.
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
        # Note: PLACE_RE also matches region listing pages such as
        # /visit/yorkshire/gardens-parks, which are not properties. If this
        # source is ever revived, that needs a deny-list of listing slugs.
        if PLACE_RE.match(url):
            return "place"
        if EVENT_RE.match(url):
            return "event"
        return None

    def category(self, place):
        text = place["name"] + " " + place["description"]
        return "garden" if GARDEN_WORDS.search(text) else "historic-house"

    def link_event(self, event):
        match = EVENT_RE.match(event.get("page_url", ""))
        return match.group(1) if match else None
