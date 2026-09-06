"""Turvey House — a Bedfordshire house whose what's-on page is hand-written.

A Wix site with no structured data of any kind: no JSON-LD, no events app,
no API behind it. Under half a megabyte of markup there are about 1,500
characters of actual content, and the events are rich-text blocks a person
typed. Each is one `[data-testid="richTextElement"]` holding a title, a
date and a booking link on separate lines:

    Backyard Ultra Solo
    Saturday 10th October
    backyard-ultra.co.uk

**A date with no year is read as this year and dropped once it is past —
never rolled forward.** This is the opposite of what `blenheim` does with
the same shape, and the difference is the page rather than the parser.
Measured 6 Sep 2026, this one still advertised "Sunday 2nd August" and
three other August dates, a month after they happened; Blenheim's had
already taken its August entries down. Rolling an undated year forward
here does not recover a future event, it invents one — "Outdoor Theatre:
Kaspar Prince of Cats, 2 August 2027" is a show nobody has scheduled.
A page that does not clear itself cannot be asked what year it means, so a
stale entry is dropped and a genuine one written without its year is lost
with it. That is the trade this project makes everywhere else too.

Two things on the page must not become events, and both would if a parser
only looked for dates:

  * **A cancellation notice**, which reads "CANCELLED. We regret to
    inform that the Outdoor Film Club have cancelled their dates…" and
    ends with the dates being cancelled. A block that says so is skipped.
  * **"Previous Events Include:"**, followed by eight blocks naming things
    like "Steam Fayre" and "Large Car Shows". They carry no date, so
    requiring one keeps them out, but they are the reason a title alone is
    never enough here.

One block gives dates and no title at all — the name is in an image — so
a title is required as well.
"""

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from .. import dates

log = logging.getLogger(__name__)

BASE = "https://www.turveyhouse.co.uk"
LISTING = f"{BASE}/whats-on"

# "2-3PM", "7-9PM": times, and their digits are not days.
TIME_RE = re.compile(r"\b\d{1,2}(?:[.:]\d{2})?\s*[-–]?\s*\d{0,2}\s*[ap]\.?m\.?\b",
                     re.I)

MONTHS = "|".join(sorted(dates.MONTHS, key=len, reverse=True))

DAY_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)\b(?:\s+({MONTHS})\b)?(?:\s+(\d{{4}}))?",
    re.I)

# The page's own word for an event that is not happening.
CANCELLED_RE = re.compile(r"\bcancel", re.I)

# A line that is the booking link rather than the event: "Book Tickets
# Here", or a bare domain standing in for one.
LINK_LINE_RE = re.compile(r"^(book\b|buy\b|tickets?\b)|^[\w.-]+\.(uk|com|org|net)$",
                          re.I)

VENUE_NAME = "Turvey House"
VENUE_POSTCODE = "MK43 8EL"


class Turvey:

    name = "turvey-house"
    category = "historic-house"
    site_url = LISTING

    def __init__(self, today=None):
        self.today = today or date.today()

    def scrape(self, fetcher, max_pages=0):

        try:
            body = fetcher.get(LISTING)
        except Exception as e:  # noqa: BLE001 — the run, not one block
            log.warning("%s: %s failed: %s", self.name, LISTING, e)
            return

        blocks = parse_listing(body, self.today)
        if max_pages:
            blocks = blocks[:max_pages]

        for event in blocks:
            event["category"] = self.category
            yield "event", event

        log.info("%s: %d event(s) still to come", self.name, len(blocks))

    def link_event(self, event):
        return None


def parse_listing(body, today=None):
    """Every event still to come on the what's-on page."""

    today = today or date.today()
    soup = BeautifulSoup(body, "html.parser")

    found = []
    for block in soup.select('[data-testid="richTextElement"]'):
        for line_break in block.find_all("br"):
            line_break.replace_with("\n")
        lines = [" ".join(line.split())
                 for line in block.get_text("\n").split("\n")]
        lines = [line for line in lines if line]

        event = _event(lines, block, today)
        if event:
            found.append(event)
    return found


def _event(lines, block, today):
    """The event a block describes, or None."""

    if len(lines) < 2 or CANCELLED_RE.search(" ".join(lines)):
        return None

    span = title = None
    for line in lines:
        if span is None:
            span = date_range(line, today)
            if span:
                continue
        if title is None and not LINK_LINE_RE.match(line):
            title = line
    if not span or not title:
        return None

    link = block.find("a", href=True)
    href = (link["href"] if link else "").strip()
    return {
        "source_id": f"{_slug(title)}-{span[0]}",
        "title": title[:160],
        "description": "",
        "url": href if href.startswith("http") else LISTING,
        "start_date": span[0],
        "end_date": span[1],
        # One venue, and no block repeats its address.
        "location_name": VENUE_NAME,
        "location_postcode": VENUE_POSTCODE,
    }


def date_range(text, today):
    """'Tuesday 6th August - Monday 31st August' -> two ISO dates, or None.

    A year written on the page is believed. A year left off is taken to be
    this one, and if that date has gone the entry is stale rather than
    next year's — see the module docstring.
    """

    parts = _days(text)
    if not parts:
        return None

    first, last = parts[0], parts[-1]
    if not first[1]:  # "21st - 23rd August" names its month once
        first = (first[0], last[1], first[2])
    if not first[1] or not last[1]:
        return None

    start = _date(first, today)
    end = _date(last, today)
    if not start or not end or end < start:
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


def _date(part, today):
    """The date this part names, or None when it has already gone."""

    day, month, year = part
    try:
        moment = date(year or today.year, month, day)
    except ValueError:  # 31 September, 29 February in a common year
        return None
    if year:
        return moment
    # No year on the page: this year, or nothing. Rolling it forward
    # would turn a listing nobody has taken down into next year's news.
    return moment if moment >= today else None


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
