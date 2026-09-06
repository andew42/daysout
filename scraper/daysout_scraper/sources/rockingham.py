"""Rockingham Castle — a Northamptonshire castle above the Welland valley.

WordPress, and the `event` post type exists, but `/wp-json/wp/v2/event`
answers with `meta: null` and an empty `acf`: the API knows the three
events and none of their dates, as Stonor's and Chenies' do. The listing
has them, in `.post` cards under `#events-category`:

    <h2 class="title">Autumn Artisan Fair</h2>
    <div class="entry-meta cf">Saturday 26th &amp; Sunday 27th September</div>
    <div class="description"><p>The Artisan Market will showcase…</p></div>

**Three cards, three ways of writing when.** Every one of them matters,
because reading any as another puts a visitor at a shut castle:

  * "Saturday 26th & Sunday 27th September" — two days that happen to
    touch, so one two-day event.
  * "Tuesdays ~ 6th, 13th & 20th October - 10am - 2pm" — three separate
    Tuesdays, a fortnight apart. Not a range: the castle is shut on the
    7th.
  * "Wednesday 28th - Saturday 31st October" — a genuine four-day run.

So a dash between two days means the days between them are included and a
comma or an ampersand means they are not, and only after that are
touching days joined into runs. That order matters: expanding the dash
first lets "28th - 31st" become one event by the same rule that joins
"26th & 27th", rather than needing a second kind of answer.

Times are stripped before any of it — "10am - 2pm" is a dash between two
numbers and would otherwise read as a range of days.

Years are absent and inferred as the next occurrence, the way Lamport
Hall's are: this page keeps itself current, unlike Turvey's, which is why
the two differ on what a missing year means.
"""

import logging
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from .. import dates

log = logging.getLogger(__name__)

BASE = "https://rockinghamcastle.com"
LISTING = f"{BASE}/events/"

# "10am - 2pm", "10.30am": removed first, or the dash between them reads
# as a range and their digits as days.
TIME_RE = re.compile(r"\b\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m\.?\b", re.I)

MONTHS = "|".join(sorted(dates.MONTHS, key=len, reverse=True))

# A day is a number carrying an ordinal suffix; the month may follow it or
# be named once for the group.
DAY_RE = re.compile(rf"(\d{{1,2}})(?:st|nd|rd|th)\b(?:\s*({MONTHS})\b)?", re.I)

# What sits between two days decides whether the days between them count.
# A dash joins them into a run; a comma or an ampersand keeps them apart.
# The test is not that the gap *is* a dash, because a weekday sits in it —
# "28th - Saturday 31st October" — which is what made the castle's
# Halloween week read as two single days.
RANGE_SEPARATOR_RE = re.compile(r"[-–—]|\bto\b")
LIST_SEPARATOR_RE = re.compile(r"[,&]|\band\b")

# How far past a date may be before it is read as next year's.
GRACE = timedelta(days=31)

VENUE_NAME = "Rockingham Castle"
VENUE_POSTCODE = "LE16 8TH"


class Rockingham:

    name = "rockingham-castle"
    category = "historic-house"
    site_url = LISTING

    def __init__(self, today=None):
        self.today = today or date.today()

    def scrape(self, fetcher, max_pages=0):

        try:
            body = fetcher.get(LISTING)
        except Exception as e:  # noqa: BLE001 — the run, not one card
            log.warning("%s: %s failed: %s", self.name, LISTING, e)
            return

        cards = parse_listing(body, self.today)
        if max_pages:
            cards = cards[:max_pages]

        undated = [title for title, events in cards if not events]
        count = 0
        for _, events in cards:
            for event in events:
                event["category"] = self.category
                count += 1
                yield "event", event

        log.info("%s: %d card(s), %d event(s)", self.name, len(cards), count)
        if undated:
            # Named, not counted: a way of writing a date that we have
            # stopped reading looks just like a card that gives none.
            log.info("%s: no date on %d: %s", self.name, len(undated),
                     "; ".join(t[:34] for t in undated[:8]))

    def link_event(self, event):
        return None


def parse_listing(body, today=None):
    """[(title, [event, ...])] for every card on the events page.

    A card can be more than one event: three Tuesdays a fortnight apart
    are three days out, not one that lasts a month.
    """

    today = today or date.today()
    soup = BeautifulSoup(body, "html.parser")

    found = []
    for card in soup.select("#events-category .post"):
        heading = card.select_one("h2.title")
        title = (" ".join(heading.get_text(" ", strip=True).split())
                 if heading else "")
        if not title:
            continue

        when = card.select_one(".entry-meta")
        runs = date_runs(when.get_text(" ", strip=True) if when else "", today)
        link = card.find("a", href=True)
        description = card.select_one(".description")

        found.append((title, [{
            # A card with three Tuesdays is three rows, so the slug alone
            # would have them overwrite each other.
            "source_id": f"{_slug(title)}-{start}",
            "title": title[:160],
            "description": (" ".join(description.get_text(" ", strip=True).split())[:400]
                            if description else ""),
            "url": (link["href"] if link else "") or LISTING,
            "start_date": start,
            "end_date": end,
            # One venue; no card repeats its address.
            "location_name": VENUE_NAME,
            "location_postcode": VENUE_POSTCODE,
        } for start, end in runs]))
    return found


def date_runs(text, today=None):
    """'Wednesday 28th - Saturday 31st October' -> [('2026-10-28', '2026-10-31')].

    A dash includes the days between; a comma or an ampersand does not.
    Touching days are then joined, so "26th & 27th" is one two-day event
    and "6th, 13th & 20th" is three.
    """

    today = today or date.today()
    days = _days(text, today)
    if not days:
        return []

    runs = []
    for day in sorted(set(days)):
        if runs and day - runs[-1][1] == timedelta(days=1):
            runs[-1][1] = day
        else:
            runs.append([day, day])
    return [(start.isoformat(), end.isoformat()) for start, end in runs]


def _days(text, today):
    """Every date the text names, ranges expanded into the days they cover."""

    text = TIME_RE.sub(" ", " ".join(str(text or "").split()))
    matches = list(DAY_RE.finditer(text))
    if not matches:
        return []

    # A group shares the month named after its last day: "26th & 27th
    # September" gives the 26th no month of its own.
    months = [(m.start(), dates.MONTHS[m.group(1).lower()])
              for m in re.finditer(rf"\b({MONTHS})\b", text, re.I)]

    found = []
    previous = None
    for index, match in enumerate(matches):
        month = next((number for at, number in months if at > match.start()), None)
        moment = _resolve(int(match.group(1)), month, today)
        if not moment:
            previous = None
            continue

        gap = text[matches[index - 1].end():match.start()] if index else ""
        if (previous and RANGE_SEPARATOR_RE.search(gap)
                and not LIST_SEPARATOR_RE.search(gap)):
            # A dash: everything between the two ends is open too.
            day = previous
            while day < moment:
                day += timedelta(days=1)
                found.append(day)
        found.append(moment)
        previous = moment
    return found


def _resolve(day, month, today):
    """The next occurrence of that day and month, or None.

    This page keeps itself current — its September events were listed in
    September — so a date already gone is next year's rather than a
    listing nobody has cleared. Turvey's is the other way about.
    """

    if not month:
        return None
    for year in (today.year, today.year + 1):
        try:
            moment = date(year, month, day)
        except ValueError:  # 31 September, 29 February in a common year
            continue
        if moment >= today - GRACE:
            return moment
    return None


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
