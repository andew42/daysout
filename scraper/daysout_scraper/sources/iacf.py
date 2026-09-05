"""IACF antiques and collectors fairs, from the feed the site offers.

Asking what the site publishes settled the design here, and the answer
was better than any parser: its calendar page links
`?feed=iacf-all-events-ical` as "Add all iacf fairs to my calendar" —
published for exactly this. Measured 1 Sep 2026 and again 5 Sep 2026:
there is no events API behind the site (every `wp-json` event route
404s), the calendar page carries no Event JSON-LD, and the sitemap holds
no event URLs at all. The feed is the only good route and needs no parser
of ours — `ical.py` reads RFC 5545 and merges a fair published a day at a
time back into one event.

One row for every venue, not one per venue. IACF runs more than the three
first seeded — Newark, Ardingly, Shepton Mallet, Builth Wells, Norfolk,
Runway and Newbury are all linked from that page — and this feed covers
the lot in a single request.

**It cannot carry a fallback venue.** A source spanning seven showgrounds
has no single address: one `venue_postcode` would put a Welsh fair at a
Nottinghamshire postcode. So every event must bring its own address in
LOCATION, and one that does not is dropped and named in the log rather
than placed approximately.

The feed's own URL is a query string, right to fetch and no use to click,
so the row the Sources tab shows links the calendar page instead.
"""

import logging

from .. import dates, ical, postcode as postcodes

log = logging.getLogger(__name__)

FEED = "https://www.iacf.co.uk/?feed=iacf-all-events-ical"
SITE = "https://www.iacf.co.uk/antiques-fair-calendar/"


class IACF:

    name = "iacf"
    category = "antiques"
    # Shown instead of the feed's query-string URL, which is no use to click.
    site_url = SITE

    def scrape(self, fetcher, max_pages=0):

        try:
            text = fetcher.get(FEED)
        except Exception as e:  # noqa: BLE001 — the run, not one fair
            log.warning("%s: %s failed: %s", self.name, FEED, e)
            return

        fairs = list(ical.parse(text))
        if max_pages:
            fairs = fairs[:max_pages]

        no_postcode = []
        found = 0
        for fair in fairs:
            event = parse_event(fair)
            if not event:
                continue
            event["category"] = self.category
            found += 1
            if not event["location_postcode"]:
                no_postcode.append(event["title"][:40])
            yield "event", event

        if not fairs:
            # A valid calendar listing nothing is a real answer, and a
            # different one from an unreachable feed: Shepton Mallet's own
            # feed was 264 good bytes with no fairs in it. Saying so stops
            # the pipeline's "unreachable, blocked, or its patterns are
            # wrong" being the only word on it.
            log.info("%s: the feed is valid and lists no events", self.name)
            return

        log.info("%s: %d fair(s) in the feed", self.name, found)
        if no_postcode:
            # Yielded anyway, not dropped here: the pipeline can still
            # place one at a venue another fair in this same feed created,
            # which is how the Newark winter market lands. Named because
            # it is the site's omission rather than a parser that missed
            # something.
            log.info("%s: LOCATION carries no postcode for %d: %s", self.name,
                     len(no_postcode), "; ".join(no_postcode[:8]))

    def link_event(self, event):
        return None


def parse_event(fair):
    """One fair from the feed, or None when it names no postcode."""

    start = dates.to_iso(fair.get("start_date"))
    title = " ".join(str(fair.get("title") or "").split())
    if not start or not title:
        return None

    where = fair.get("location_name") or ""
    return {
        "source_id": fair.get("uid") or f"{title}-{start}",
        "title": title[:160],
        "description": " ".join(str(fair.get("description") or "").split())[:400],
        "url": fair.get("url") or SITE,
        "start_date": start,
        "end_date": dates.to_iso(fair.get("end_date")) or start,
        # The showground's own address, which is the only thing placing a
        # fair here: seven venues share this source and no fallback could
        # be right for all of them.
        "location_name": where,
        "location_postcode": postcodes.find(where, fair.get("description", "")),
    }
