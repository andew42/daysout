"""National Garden Scheme open gardens.

Private gardens opening for charity on named days, which is as close to a
purpose-built source for this app as exists: the whole point of an NGS
garden is that it is open on Sunday and shut the rest of the year.

Two rows were seeded for this and neither could work. They pointed at
ngs.org.uk pages and were switched to `kind='browser'` on the theory that
the listing was built client-side — an earlier diagnostic recorded that
rendering added 130 KB of Cookiebot tables and no gardens at all. That was
true and the conclusion drawn from it was wrong. Measured 5 Sep 2026,
`/gardens-open-this-coming-week/` **is not a listing**: it is a hub page
of regional links ("East of England — Click here"), so there were never
any gardens on it to render. Rendering the wrong page harder was never
going to help.

Following those links leads off ngs.org.uk entirely, to a separate
application at findagarden.ngs.org.uk, whose Vue bundle names its own
JSON API — `https://api.findagarden.ngs.org.uk/api`, with `/gardens`,
`/gardens/filters` and `/geocode`. `/gardens` answers with every garden
currently listed, and it is the best-shaped data any source here has had:
name, full address **with postcode**, description, tags, real
**coordinates**, and a list of dated openings. One request for the lot, no
rendering, no geocoding, nothing to parse out of prose. ngs.org.uk's
robots.txt disallows its own faceted-search query strings, the usual
crawler trap; findagarden serves no robots.txt at all and this reads one
documented endpoint once, not a facet crawl.

**An opening is a day, or it is a window, and only one of those is an
event.** The API mixes both in the same list, distinguished by an
undocumented `garden_opening_type_id`. Rather than guess at that enum,
the rule here is what the dates themselves say — measured across all
2,342 opening records: types 1, 2 and 5 are **100%** same-day (1,889
records, span always zero), while types 3 and 4 have a median span of 182
days and a maximum of 364. Those long ones are "by arrangement": a season
in which you may ring the owner and ask, not a day you can turn up. So a
record whose start and end fall on the same date is an event and anything
longer is not, which needs no knowledge of what the numbers mean and does
not break when a sixth type appears.

Cancelled openings are skipped — the feed flags them and keeps them — as
are ones already past, and a garden with no future dated opening is not
published as a place at all. An NGS garden is somebody's private garden;
a pin for one with no open day is a pin for somewhere you cannot go.

Gardens are yielded as places carrying their own coordinates, so the
pipeline never geocodes them, and each opening links to its garden by id
through `link_event` rather than by matching names.
"""

import json
import logging
import re
from datetime import date

from .. import dates

log = logging.getLogger(__name__)

API = "https://api.findagarden.ngs.org.uk/api/gardens"
SITE = "https://findagarden.ngs.org.uk"


class NGS:

    name = "ngs-open-gardens"
    category = "garden"

    def __init__(self, today=None):
        # Injectable so a test can state the day it reasons about: which
        # openings are past is the one thing here that moves on its own.
        self.today = today or date.today().isoformat()

    def scrape(self, fetcher, max_pages=0):

        try:
            body = fetcher.get(API, api=True)
        except Exception as e:  # noqa: BLE001 — the run, not one garden
            log.warning("%s: %s failed: %s", self.name, API, e)
            return

        gardens = json.loads(body).get("results") or []
        if max_pages:
            gardens = gardens[:max_pages]

        skipped = Skipped()
        published = openings = 0
        for garden in gardens:
            days = open_days(garden, self.today, skipped)
            if not days:
                continue
            place = parse_place(garden)
            if not place:
                continue

            yield "place", place
            published += 1
            for start in days:
                openings += 1
                yield "event", parse_event(garden, place, start, self.category)

        log.info("%s: %d garden(s) listed, %d with a future open day, "
                 "%d opening(s)", self.name, len(gardens), published, openings)
        log.info("%s: skipped %d by-arrangement window(s), %d cancelled, "
                 "%d past", self.name, skipped.windows, skipped.cancelled,
                 skipped.past)

    def link_event(self, event):
        # By the garden's own id rather than by matching names: two
        # gardens can share a name, and the feed's id cannot.
        return event.get("place_source_id")


class Skipped:
    """Why openings were left out, so the log can say rather than imply."""

    def __init__(self):
        self.windows = self.cancelled = self.past = 0


def open_days(garden, today, skipped=None):
    """The dates this garden is open, from today on.

    A record covering one day is an open day; one covering months is a
    by-arrangement window, which is a season you may ring the owner in
    and not a day anybody can turn up.
    """

    skipped = skipped or Skipped()
    days = []
    for opening in garden.get("openings") or []:
        start = dates.to_iso(opening.get("start_date"))
        end = dates.to_iso(opening.get("end_date"))
        if not start or not end:
            continue
        if start != end:
            skipped.windows += 1
            continue
        if opening.get("canceled"):
            skipped.cancelled += 1
            continue
        if start < today:
            skipped.past += 1
            continue
        days.append(start)
    return sorted(set(days))


def parse_place(garden):
    """The garden as a destination, or None if it cannot be placed."""

    name = " ".join(str(garden.get("name") or "").split())
    position = garden.get("position") or {}
    lat, lon = position.get("lat"), position.get("lng")
    if not name or lat is None or lon is None:
        return None

    return {
        "source_id": str(garden.get("id")),
        "name": name[:160],
        "category": "garden",
        "description": " ".join(str(garden.get("description") or "").split())[:500],
        "url": garden_url(garden),
        "postcode": (garden.get("postcode") or "").strip(),
        # The feed's own coordinates, so the pipeline never geocodes these
        # and a garden down a lane is where the feed says, not where its
        # postcode's centroid is.
        "lat": lat,
        "lon": lon,
    }


def parse_event(garden, place, start, category):
    """One open day at one garden."""

    return {
        "source_id": f"{garden.get('id')}-{start}",
        # The garden's name alone would repeat its venue's, so say what
        # the event is: the garden is open that day.
        "title": f"{place['name']} open day"[:160],
        "description": place["description"],
        "url": place["url"],
        "start_date": start,
        "end_date": start,
        "category": category,
        # Linked by the garden's own id, not by name: two gardens can
        # share a name and the feed's id is unambiguous.
        "place_source_id": place["source_id"],
    }


def garden_url(garden):
    """The garden's page in the finder: /garden/<id>/<name-slug>."""
    slug = re.sub(r"[^a-z0-9]+", "-",
                  str(garden.get("name") or "").lower()).strip("-")
    return f"{SITE}/garden/{garden.get('id')}/{slug}"
