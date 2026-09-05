"""Waddesdon Manor — the Rothschild house, read from its own REST API.

A National Trust property, but not a National Trust site: waddesdon.org.uk
is the Rothschild Foundation's own WordPress, it does not challenge us,
and `refusedHosts` covers nationaltrust.org.uk alone. Nothing here works
around anything — robots.txt is `Disallow:` with nothing after it, so the
whole site is permitted.

The pages are no use and the API is excellent, which is the whole design.
Measured 5 Sep 2026:

  * /whats-on/ and each event page carry JSON-LD of type WebPage,
    Organization and BreadcrumbList — no Event, no dates. Scraping them
    would mean reading a 273 KB page per event.
  * The Events Calendar is not installed (/wp-json/tribe/... 404s), but
    the site registers its own post type, `rothschild_event`, published
    at **/wp-json/wp/v2/events** with 46 events and real dates in `meta`.

So this is not a `sources` row: every kind a row can take reads
structured data or a documented feed, and this site publishes neither on
its pages — `wpevents` speaks The Events Calendar's API, which is a
different shape entirely. It is a source in code reading one endpoint,
and it costs two requests a run rather than 46 page fetches. That matters
here: robots.txt asks for `Crawl-delay: 10`, which the Fetcher does not
implement, so a page crawl would be both slow and ruder than asked.

Three things about the data are worth knowing.

**The post date is not the event date.** WordPress's own `date` is when
the entry was published; the event's own dates are
`meta.rothschild_event_start_date` / `_end_date`. Reading `date` would
put every event on the day somebody typed it up.

**Half the feed is over.** 22 of the 46 had already finished, some in
2025, because nothing takes an old event down. They are dropped here on
`end_date`, the way `wpevents` asks the API for future events only —
storing them would leave the stale purge to notice, and they would sit in
`scrape_runs` counts looking like contribution.

**A date is a date, never a moment.** The API writes both
"2026-10-18T13:08:53" and "2026-08-14T00:00:00+01:00", and that offset is
the trap: as an instant, midnight on the 14th British time is 23:00 on
the *13th* UTC, so anything that parses these into a datetime and
converts can move an event a day earlier. `dates.to_iso` takes the
published calendar date and never builds a moment, which is the same rule
`EventsView.formatDate` follows at the other end.

The `event-locations` taxonomy names places *inside* the estate — Wine
Cellars, South Front, Aviary Glade — so it is deliberately not used as
the venue: passing "Wine Cellars" to the pipeline would geocode a second
destination and drop a pin with no address of its own. Every event here
happens at the manor, whose postcode the site gives for satnav.
`event-categories` is used, since an event's own category counts as well
as its venue's: the Chilli Fest is food at a historic house.
"""

import json
import logging
from datetime import date

from .. import dates
from .feeds import _plain

log = logging.getLogger(__name__)

BASE = "https://waddesdon.org.uk"
EVENTS_API = f"{BASE}/wp-json/wp/v2/events"
CATEGORIES_API = f"{BASE}/wp-json/wp/v2/event-categories"

# WordPress caps per_page at 100 and there are 46 events, so one request
# gets the lot; the loop is what keeps that true as the programme grows.
PER_PAGE = 100

# The site's own categories, mapped onto the ones the app filters by.
# Matched on the term's name rather than its slug: the slugs carry an
# import artefact ("arts-culture-3339", but plain "exhibitions"), and the
# names do not. Anything unmapped — Evening, Families, Tours & Talks —
# is the house itself, which is what the venue already is.
CATEGORIES = {
    "food & wine": "food",
    "arts & culture": "art",
    "exhibitions": "art",
    "nature": "garden",
}

VENUE_NAME = "Waddesdon Manor"
# "For satellite navigation users, our postcode is HP18 0JH" — the same
# one as the postal address, unlike Lamport Hall.
VENUE_POSTCODE = "HP18 0JH"


class Waddesdon:

    name = "waddesdon"
    category = "historic-house"

    def __init__(self, today=None):
        # Injectable so a test can state the day it is reasoning about:
        # which events are over is the one thing here that changes on its
        # own, and a test that asks the calendar drifts into passing for
        # the wrong reason.
        self.today = today or date.today().isoformat()

    def scrape(self, fetcher, max_pages=0):

        try:
            categories = _categories(fetcher)
        except Exception as e:  # noqa: BLE001 — a category is not a reason to stop
            log.warning("%s: categories unavailable, filing all as %s: %s",
                        self.name, self.category, e)
            categories = {}

        seen = over = 0
        for record in self._records(fetcher, max_pages):
            seen += 1
            event = parse_event(record, categories, self.category)
            if not event:
                continue
            if event["end_date"] < self.today:
                over += 1
                continue
            yield "event", event

        log.info("%s: %d event(s) published, %d already over", self.name, seen, over)

    def _records(self, fetcher, max_pages=0):
        """Every event the API holds, a page at a time.

        A short page is the last one, so the next page is only asked for
        when this one came back full — which is also why no 400 for
        running off the end has to be handled.
        """

        page = 1
        while True:
            url = f"{EVENTS_API}?per_page={PER_PAGE}&page={page}"
            try:
                body = fetcher.get(url, api=True)
            except Exception as e:  # noqa: BLE001 — the run, not one event
                log.warning("%s: %s failed: %s", self.name, url, e)
                return

            records = json.loads(body)
            yield from records

            if len(records) < PER_PAGE or (max_pages and page >= max_pages):
                return
            page += 1

    def link_event(self, event):
        return None


def _categories(fetcher):
    """Term id -> the app's category, for the terms we map."""

    body = fetcher.get(f"{CATEGORIES_API}?per_page={PER_PAGE}", api=True)
    found = {}
    for term in json.loads(body):
        mapped = CATEGORIES.get(_plain(term.get("name")).lower())
        if mapped:
            found[term.get("id")] = mapped
    return found


def parse_event(record, categories, default_category):
    """An event dict for one API record, or None."""

    meta = record.get("meta") or {}
    start = dates.to_iso(meta.get("rothschild_event_start_date"))
    if not start:
        return None

    # An event with no end is a one-day event, which the store holds as
    # the same date twice.
    end = dates.to_iso(meta.get("rothschild_event_end_date")) or start
    if end < start:
        end = start

    title = _plain(record.get("title"))
    if not title:
        return None

    return {
        # The post id, not the slug: it is the site's own key and it
        # survives an event being renamed.
        "source_id": str(record.get("id")),
        "title": title,
        "description": _description(record, meta),
        "url": record.get("link") or f"{BASE}/whats-on/",
        "start_date": start,
        "end_date": end,
        "category": _category(record, categories, default_category),
        # One venue: the taxonomy's locations are rooms and lawns within
        # it, and an event given one of those as its venue would be
        # geocoded into a destination of its own.
        "location_name": VENUE_NAME,
        "location_postcode": VENUE_POSTCODE,
    }


def _category(record, categories, default_category):
    """The most specific mapped category on the record, or the default.

    An event carries several — the Chilli Fest is Families *and* Food &
    Wine — so the mapped one wins over the house, and the order of
    CATEGORIES decides between two mapped ones so the answer does not
    depend on the order the API happens to list terms in.
    """

    mapped = {categories[term] for term in record.get("event-categories") or []
              if term in categories}
    for category in CATEGORIES.values():
        if category in mapped:
            return category
    return default_category


def _description(record, meta):
    """The excerpt, kept honest about when the event actually runs.

    `start`/`end` are a span, and for a third of these that span is not
    when you can turn up: "Every Friday and Saturday" runs 6-28 November,
    and a reader given only those two dates would arrive on a Tuesday.
    The site's own summary of when is prepended in that case, and left
    out when it is only restating the dates.
    """

    text = _plain(record.get("excerpt"))[:400]
    when = _plain(meta.get("rothschild_event_date_range_display"))
    if when and not _is_plain_dates(when):
        return f"{when}. {text}".strip()
    return text


def _is_plain_dates(when):
    """Does this say only which dates, rather than which days of them?

    "18 October" and "4 December - 6 December" restate start and end;
    "Every Friday until 26 June" and "Various dates" do not.
    """

    words = {word for word in when.lower().replace("-", " ").split()
             if word.isalpha()}
    return words <= set(dates.MONTHS)
