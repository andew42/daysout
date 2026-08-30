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

Measured on the house server, 30 August 2026, against the events page
above: robots.txt **allows** it (nothing under /visit is disallowed), and
the site still answers with a 118,419-byte Radware bot-protection
challenge carrying no JSON-LD at all. So neither robots.txt nor the URL
shape is what stops us — the site declines to serve automated clients.

We do not work around that: no disguised User-Agent, no solving the
challenge, no rotating identities. What this module does instead is
*notice*. A single canary request runs before the sitemap, so a refusal
costs one request rather than a 1,279-entry crawl, and the run says it
was refused instead of reporting an empty site. If the site ever serves
these pages, this source starts working with no further changes.

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

    # Probed before the sitemap to find out cheaply whether the site is
    # serving us at all. If it stops existing the crawl still proceeds —
    # a dead canary must not silently disable the source.
    CANARY = ("https://www.nationaltrust.org.uk/visit/"
              "oxfordshire-buckinghamshire-berkshire/stowe-gardens/events")

    def __init__(self):
        # Set when the site answers with a challenge, so the rest of the
        # run stops asking instead of collecting hundreds of refusals.
        self.blocked = False
        # Read by the pipeline for the run message: "no places found" alone
        # cannot tell a refusal apart from patterns that no longer match,
        # and that ambiguity has cost time before.
        self.failure_note = ""

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

        if self._refused(fetcher):
            return

        for kind, item in super().scrape(fetcher, max_pages=max_pages):
            if kind == "event":
                slug = self.property_slug(item.get("page_url", ""))
                title = re.sub(r"[^a-z0-9]+", "-",
                               item.get("title", "").lower()).strip("-")
                item["source_id"] = f"{slug}-{title}-{item['start_date']}"[:200]
            yield kind, item

    def _refused(self, fetcher):
        """One request, before the sitemap: is the site serving us today?"""

        try:
            body = fetcher.get(self.CANARY)
        except Exception as e:  # noqa: BLE001 — the canary is a probe, not a gate
            log.info("%s: canary %s did not load (%s); crawling anyway",
                     self.name, self.CANARY, e)
            return False
        if looks_like_a_challenge(body):
            self._record_refusal(self.CANARY, body)
            return True
        return False

    def _record_refusal(self, url, body):
        self.blocked = True
        self.failure_note = ("the site answered with a bot-protection "
                             "challenge; robots.txt permits these pages, but "
                             "we don't work around a refusal")
        log.warning(
            "%s: %s answered with a bot-protection challenge (%d bytes) "
            "instead of the page — stopping. That is the site refusing "
            "automated clients, and we don't work around it.",
            self.name, url, len(body))

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
            self._record_refusal(url, body)
            return []

        return jsonld.extract_objects(body)
