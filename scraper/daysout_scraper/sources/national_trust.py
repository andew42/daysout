"""National Trust events, one listing page per property.

Each property publishes its own events index — for example

    https://www.nationaltrust.org.uk/visit/oxfordshire-buckinghamshire-berkshire/stowe-gardens/events

and individual event pages sit below it. Neither shape was being read: the
old patterns matched only `<property>/events/<slug>` pages, so the index
pages — the cheap way to get every event a property is running, one
request each rather than one per event — were classified as neither a
place nor an event and never fetched.

Properties themselves are deliberately not crawled here. Wikidata already
supplies National Trust properties as CC0 open data (see wikidata.py), and
fetching 1,279 property pages daily to re-derive what we hold would be
rude for no gain. Events are the part Wikidata does not have, so events
are what this source goes for.

## On being blocked

This site has served a Radware bot-protection challenge to automated
clients — a ~118 KB page with no content in place of the real HTML. That
is a refusal, and we do not work around it: no disguised User-Agent, no
solving the challenge, no rotating identities. What this module does
instead is *notice*: the first challenge response stops the run with a
message saying so, rather than spending hundreds of requests collecting
challenge pages and reporting them as an empty site.

Crawling is otherwise ordinary and polite — robots.txt is consulted for
every URL by the fetcher, so any path the site disallows is skipped
whatever this module asks for, and requests stay at one per second with
an honest User-Agent.
"""

import logging
import re

from .. import jsonld
from ..sitemap_source import SitemapJsonLdSource

log = logging.getLogger(__name__)

BASE = r"^https://www\.nationaltrust\.org\.uk/visit"

# A property's events listing: /visit/<region>/<property>/events
EVENTS_INDEX_RE = re.compile(BASE + r"/([^/]+)/([^/]+)/(?:events|whats-on)/?$")

# One event below that listing: /visit/<region>/<property>/events/<slug>
EVENT_PAGE_RE = re.compile(BASE + r"/([^/]+)/([^/]+)/(?:events|whats-on)/([^/]+)/?$")

# Phrases that appear on a bot-protection interstitial rather than on a page
# of the site. Seeing one means the site declined to serve us, which is a
# different thing from a page having no events on it.
CHALLENGE_MARKERS = (
    "radware",
    "captcha-delivery",
    "request unsuccessful",
    "incapsula",
    "are you a human",
    "enable javascript and cookies to continue",
)


def looks_like_a_challenge(html):
    """True if this is an interstitial refusing us rather than page content.

    Deliberately checked against the start of the document only: the words
    below are common enough that a real page could mention one in passing,
    but a challenge page says it up front and carries little else.
    """
    head = html[:4000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


class NationalTrust(SitemapJsonLdSource):

    name = "national_trust"
    sitemaps = ("https://www.nationaltrust.org.uk/sitemap.xml",)

    def __init__(self):
        # Set when the site answers with a challenge, so the rest of the
        # run stops asking instead of collecting hundreds of refusals.
        self.blocked = False

    def classify(self, url):
        # Properties come from Wikidata; see the module docstring. Returning
        # None for them keeps the daily run to the events we actually need.
        if EVENTS_INDEX_RE.match(url) or EVENT_PAGE_RE.match(url):
            return "event"
        return None

    def category(self, place):
        # Unused while places are not crawled, but the engine's interface
        # requires it and re-enabling places should not need this rewritten.
        return "historic-house"

    def property_slug(self, url):
        match = EVENT_PAGE_RE.match(url) or EVENTS_INDEX_RE.match(url)
        return match.group(2) if match else ""

    def link_event(self, event):
        # Only meaningful if property pages are ever crawled again: the
        # pipeline looks this key up among *this* source's destinations, of
        # which there are currently none, and falls through to matching the
        # venue by name. Harmless either way, and correct if places return.
        return self.property_slug(event.get("page_url", "")) or None

    def scrape(self, fetcher, max_pages=0):
        """The generic crawl, with event identities that survive both shapes.

        The engine names an event after the last segment of the page it was
        found on. That is right for a page holding one event and wrong for a
        property's index, where every event on it would be called "events"
        and they would overwrite each other. Worse, an event listed on the
        index *and* on its own page would be stored twice. Naming an event
        after its property, title and start date fixes both: the same event
        is the same row wherever it was read.
        """

        for kind, item in super().scrape(fetcher, max_pages=max_pages):
            if kind == "event":
                slug = self.property_slug(item.get("page_url", ""))
                title = re.sub(r"[^a-z0-9]+", "-",
                               item.get("title", "").lower()).strip("-")
                item["source_id"] = f"{slug}-{title}-{item['start_date']}"[:200]
            yield kind, item

    def _objects(self, fetcher, url):
        """Fetch a page, unless the site has already told us no."""

        if self.blocked:
            return []
        try:
            body = fetcher.get(url)
        except Exception as e:  # noqa: BLE001 — one bad page, keep the run alive
            log.warning("fetch %s failed: %s", url, e)
            return []

        if looks_like_a_challenge(body):
            self.blocked = True
            log.warning(
                "%s: %s answered with a bot-protection challenge (%d bytes) "
                "instead of the page — stopping. That is the site refusing "
                "automated clients, and we don't work around it.",
                self.name, url, len(body))
            return []

        return jsonld.extract_objects(body)
