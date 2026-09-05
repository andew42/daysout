"""Blenheim Palace — one Oxfordshire palace, dated only on its listing.

Everything is on `/whats-on/` and nothing is anywhere else. Measured
5 Sep 2026, `discover` on an event page returns the verdict "no dates in
the DOM at all": no JSON-LD, no `<time>`, no date-classed element, not one
date-looking phrase. The individual pages describe an event and never say
when it is. **So the usual index/detail split is inverted here — the
listing is the only thing worth reading, and following its links would
cost 24 requests for nothing.**

Each event is a `.portfolio-item` card:

    <div class="portfolio-item yes mb-4 f-summer f-freeap f-2026">
      <h2><a href="whats-on/events/life-through-a-royal-lens/">
          Life Through a Royal Lens Exhibition</a></h2>
      <small class="date-attr">Sunday 12th July - Sunday 27th September</small>

**The `f-2026` class is not the year, however much it looks like one.**
Only 14 of the 24 cards carry an `f-<year>` at all, and it disagrees with
the date text where both exist — it is a filter tag for the page's own
year buttons, not a statement about the event. The dates are read from
`.date-attr` and the class is ignored.

`.date-attr` is prose, in these shapes, all from real cards:

  * a range with no year — "Tuesday 1st September - Wednesday 11th November"
  * a range with the year at the end — "Saturday 24th October - Sunday 1st November 2026"
  * a range with a year at each end — "Friday 13th November 2026 - Sunday 3rd January 2027"
  * a range naming its month once — "Wednesday 2nd - Sunday 6th September 2026"
  * one day, with or without a time — "Tuesday 29th September at 18.00"
  * and things that are not dates at all: "Open daily 10.15 - 17.15",
    "Returning in 2027", "Learn More"

**The year is inferred from the end of the range, not the start.** Anchor
on the start and "Sunday 12th July - Sunday 27th September" — an
exhibition running right now — reads as beginning eight weeks ago, which
is far enough past that the next-occurrence rule throws it to next July
and inverts the range. The end is what says whether an event is still on,
so the end takes the next occurrence and the start is then pulled to
whichever year keeps it before the end. That is what carries
"13th November - 3rd January" across the new year without either date
being written with one.
"""

import logging
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from .. import dates

log = logging.getLogger(__name__)

BASE = "https://www.blenheimpalace.com"
LISTING = f"{BASE}/whats-on/"

# "18.00", "10.15 - 17.15" — removed before days are read, or their
# numbers read as days.
TIME_RE = re.compile(r"\b\d{1,2}[.:]\d{2}\b")

MONTHS = "|".join(sorted(dates.MONTHS, key=len, reverse=True))

# "13th November 2026", "2nd", "29th September" — the month and year are
# each optional, because a range may name them once for both ends.
DAY_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)\b(?:\s+({MONTHS})\b)?(?:\s+(\d{{4}}))?",
    re.I)

# How far past an event may end before it is read as next year's.
GRACE = timedelta(days=31)

VENUE_NAME = "Blenheim Palace"
VENUE_POSTCODE = "OX20 1PP"


class Blenheim:

    name = "blenheim-palace"
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

        undated = [title for title, event in cards if event is None]
        for _, event in cards:
            if event:
                event["category"] = self.category
                yield "event", event

        log.info("%s: %d card(s), %d dated", self.name, len(cards),
                 len(cards) - len(undated))
        if undated:
            # Named, not counted: "Open daily" is a real answer and a
            # shape we have stopped reading looks just like it.
            log.info("%s: no date on %d: %s", self.name, len(undated),
                     "; ".join(t[:34] for t in undated[:8]))

    def link_event(self, event):
        return None


def parse_listing(body, today=None):
    """[(title, event or None)] for every card on the what's-on page."""

    today = today or date.today()
    soup = BeautifulSoup(body, "html.parser")
    found = []
    for card in soup.select(".portfolio-item"):
        heading = card.find(["h2", "h3"])
        title = (" ".join(heading.get_text(" ", strip=True).split())
                 if heading else "")
        if not title:
            continue

        when = card.find(class_="date-attr")
        text = " ".join(when.get_text(" ", strip=True).split()) if when else ""
        found.append((title, _event(title, text, card, today)))
    return found


def _event(title, text, card, today):
    """The event a card describes, or None when it names no date."""

    span = date_range(text, today)
    if not span:
        return None
    start, end = span

    link = card.find("a", href=True)
    href = (link["href"] if link else "").strip()
    if href and not href.startswith("http"):
        href = f"{BASE}/{href.lstrip('/')}"

    return {
        # An annual event keeps its link and changes its dates, so the
        # start is part of the key.
        "source_id": f"{_slug(title)}-{start}",
        "title": title[:160],
        "description": "",
        "url": href or LISTING,
        "start_date": start,
        "end_date": end,
        # One venue: every card here happens at the palace, and no card
        # repeats the address.
        "location_name": VENUE_NAME,
        "location_postcode": VENUE_POSTCODE,
    }


def date_range(text, today=None):
    """'Sunday 12th July - Sunday 27th September' -> two ISO dates.

    ('', '') is not returned: anything unreadable comes back as None, so
    a caller cannot mistake it for a date.
    """

    today = today or date.today()
    parts = _days(text)
    if not parts:
        return None

    first, last = parts[0], parts[-1]
    # A range naming its month once — "2nd - 6th September" — leaves the
    # first end without one.
    if not first[1]:
        first = (first[0], last[1], first[2])
    if not first[1] or not last[1]:
        return None

    end = _resolve(last, today)
    if not end:
        return None
    if len(parts) == 1:
        return end.isoformat(), end.isoformat()

    start = _before(first, end)
    if not start:
        return None
    return start.isoformat(), end.isoformat()


def _days(text):
    """[(day, month or None, year or None)] in the order written."""

    text = TIME_RE.sub(" ", " ".join(str(text or "").split()))
    found = []
    for match in DAY_RE.finditer(text):
        month = match.group(2)
        found.append((int(match.group(1)),
                      dates.MONTHS[month.lower()] if month else None,
                      int(match.group(3)) if match.group(3) else None))
    return found


def _resolve(part, today):
    """The end of the range as a real date, taking the next occurrence.

    The end rather than the start, because the end is what says whether
    an event is still running: an exhibition that opened in July and runs
    to September is on today, and anchoring on its start would read it as
    beginning next July.
    """

    day, month, year = part
    if year:
        return _date(year, month, day)
    for candidate in (today.year, today.year + 1):
        moment = _date(candidate, month, day)
        if moment and moment >= today - GRACE:
            return moment
    return None


def _before(part, end):
    """The start of the range: the same date at or before the end."""

    day, month, year = part
    if year:
        moment = _date(year, month, day)
        return moment if moment and moment <= end else None
    # "13th November - 3rd January" ends in the year after it starts.
    for candidate in (end.year, end.year - 1):
        moment = _date(candidate, month, day)
        if moment and moment <= end:
            return moment
    return None


def _date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:  # 31 September, and 29 February in a common year
        return None


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
