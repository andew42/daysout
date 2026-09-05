"""Lamport Hall — a Northamptonshire house with its own events programme.

One venue, and nothing machine-readable on it: no Event JSON-LD, no
<time>, no events API (it is not WordPress — /wp-json/tribe/... answers
with the site's own 404 page), and no date in the URL. What it does have
is a single date-classed element per page, which is what makes it
readable at all. Measured 5 Sep 2026 against the live site:

  * /events/ is the index — 18 links of the shape /events/<slug>/ and
    no dates of its own, so it says which events exist and nothing more.
  * /events/<slug>/ carries exactly one <div class="eventdetails">, one
    <h2> (the title) and one <p class="timedatetext"> (the date):

        <h2>Raymond Yui and Kyle Nash-Baker in Concert</h2>
        <p class="timedatetext">6th November, 6.00pm - 9.00pm</p>

**No date here carries a year** — all 18 read "6th November" or
"Thursday 22nd October" — so `dates.parse_range` cannot read them: it
requires a 4-digit year, for the good reason that guessing one is how an
event lands twelve months out. The year is inferred here instead, where
the surrounding fact justifies it: this is a what's-on page, so its dates
are the coming ones. `_with_year` takes the next occurrence, allowing a
month of grace so a multi-day event already under way is not thrown a
year forward.

Three date shapes, all from real pages:

  * one day — "Thursday 22nd October, 10:30am-3:30pm"
  * several days sharing one month, named once at the end —
    "5th, 6th, 8th, 9th, 10th, 12th & 13th December"
  * several days each naming its own — "Thursday 22nd October &
    Thursday 29th October, 11am-12pm"

so a day takes the first month named *after* it, which is the one rule
that reads all three. Days are then grouped into runs of touching days
and each run is one event, the way `ical._merge_runs` joins a fair
published a day at a time: the Christmas Market's "Saturday 5th & Sunday
6th and Saturday 12th & Sunday 13th December" is two weekends, not a
nine-day market.

Times are stripped before any of that, because they are full of numbers
that read exactly like days: "10am-4pm" would otherwise contribute a 10
and a 4. Only a number carrying an ordinal suffix is taken as a day —
every one of the 18 pages writes them "5th", "22nd", "1st" — which is a
far narrower target than "a number near a month".

Three pages state no day at all: "Selected dates throughout December",
"Wednesday-Friday May-September" and "Wednesdays-Sundays throughout
September" are real programmes, but no precise date can be read from
them and inventing one would put a visitor at a locked gate. They are
skipped and named in the log, so a shape we cannot yet read stays
distinguishable from a page that has no date.
"""

import logging
import re
from datetime import date, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .. import dates

log = logging.getLogger(__name__)

BASE = "https://www.lamporthall.co.uk"
INDEX = f"{BASE}/events/"

# /events/<slug>/ and nothing deeper; the index itself has no slug.
EVENT_RE = re.compile(r"^/events/([^/]+)/?$")

# "10am-4pm", "6.00pm - 9.00pm", "10:30am-3:30pm" — removed before days
# are read, or their numbers would be read as days.
TIME_RE = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*[ap]m\b", re.I)

# A day is a number with an ordinal suffix. Every page writes them that
# way, and requiring the suffix is what keeps a stray number out.
DAY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.I)

MONTH_RE = re.compile(
    r"\b(" + "|".join(sorted(dates.MONTHS, key=len, reverse=True)) + r")\b",
    re.I)

# How far into the past a date may fall before it is read as next year's.
# A multi-day event that started last week is still on; one three months
# gone is last year's page, not this year's.
GRACE = timedelta(days=31)

# The site gives two: "NN6 9HD, (NN6 9EZ for satnav)". The satnav one is
# the entrance, and this is a tool for driving somewhere.
VENUE_NAME = "Lamport Hall"
VENUE_POSTCODE = "NN6 9EZ"


class LamportHall:

    name = "lamport-hall"
    category = "historic-house"

    def scrape(self, fetcher, max_pages=0):

        try:
            index = fetcher.get(INDEX)
        except Exception as e:  # noqa: BLE001 — the run, not one page
            log.warning("%s: index %s failed: %s", self.name, INDEX, e)
            return

        pages = event_urls(index)
        log.info("%s: %d event page(s) on the index", self.name, len(pages))
        if max_pages:
            pages = pages[:max_pages]

        undated = []
        for url in pages:
            try:
                body = fetcher.get(url)
            except Exception as e:  # noqa: BLE001 — one page, not the run
                log.warning("fetch %s failed: %s", url, e)
                continue
            events = parse_event(body, url)
            if not events:
                undated.append(url.rstrip("/").rsplit("/", 1)[-1])
            for event in events:
                event["category"] = self.category
                yield "event", event

        if undated:
            # Which pages, not just how many: a date shape we do not read
            # yet looks exactly like a page that has no date.
            log.info("%s: no date read on %d of %d page(s): %s",
                     self.name, len(undated), len(pages), ", ".join(undated[:8]))

    def link_event(self, event):
        return None


def event_urls(body):
    """The event page URLs linked from the index, in page order.

    The fragment has to go before the path is matched: the index carries
    a back-to-top link, href="/events/#scrolltop", and read as a slug it
    becomes a nineteenth event page that fetches the index again and
    reports no date — which spends a request and, worse, puts a page
    that was never an event into the one log line that says which date
    shapes went unread.
    """

    soup = BeautifulSoup(body, "html.parser")
    host = urlsplit(BASE).netloc
    urls = []
    for anchor in soup.find_all("a", href=True):
        parts = urlsplit(urljoin(BASE, anchor["href"]))
        if parts.netloc != host or not EVENT_RE.match(parts.path):
            continue
        url = urlunsplit(("https", host, parts.path, "", ""))
        if url not in urls:
            urls.append(url)
    return urls


def parse_event(body, url, today=None):
    """The events one Lamport Hall event page describes, oldest first.

    A page is one event, but it may name several separate days — two
    weekends, or four Thursdays — and each run of touching days is its
    own event, since a visitor cannot turn up between them.
    """

    soup = BeautifulSoup(body, "html.parser")
    details = soup.find(class_="eventdetails")
    if not details:
        return []

    heading = details.find("h2")
    title = " ".join(heading.get_text(" ", strip=True).split())[:160] if heading else ""
    if not title:
        return []

    when = details.find(class_="timedatetext")
    if not when:
        return []

    slug = url.rstrip("/").rsplit("/", 1)[-1]
    events = []
    for start, end in date_runs(when.get_text(" ", strip=True), today):
        events.append({
            # A page with two weekends is two rows, so the slug alone
            # would have them overwrite each other on (source, source_id).
            "source_id": f"{slug}-{start}",
            "title": title,
            "description": _description(details),
            "url": url,
            "start_date": start,
            "end_date": end,
            # One venue publishing its own events: every event here
            # happens at the hall, and no page repeats its address.
            "location_name": VENUE_NAME,
            "location_postcode": VENUE_POSTCODE,
        })
    return events


def date_runs(text, today=None):
    """'Saturday 5th & Sunday 6th ... December' -> [('2026-12-05', ...)].

    Runs of touching days come back as one (start, end) pair; separate
    days come back separately. Anything with no day in it comes back
    empty rather than approximately right.
    """

    today = today or date.today()
    days = []
    for day, month in _day_months(text):
        moment = _with_year(month, day, today)
        if moment:
            days.append(moment)

    runs = []
    for moment in sorted(set(days)):
        if runs and moment - runs[-1][1] == timedelta(days=1):
            runs[-1][1] = moment
        else:
            runs.append([moment, moment])
    return [(start.isoformat(), end.isoformat()) for start, end in runs]


def _day_months(text):
    """(day, month) for each day named, taking the month that follows it.

    "5th, 6th & 13th December" names its month once, at the end;
    "22nd October & 29th October" names one per day. Reading forward to
    the next month named covers both, and is why a day with no month
    after it — the end of a truncated phrase — is dropped.
    """

    text = TIME_RE.sub(" ", " ".join(str(text or "").split()))
    months = [(m.start(), dates.MONTHS[m.group(1).lower()])
              for m in MONTH_RE.finditer(text)]

    found = []
    for match in DAY_RE.finditer(text):
        month = next((number for at, number in months if at > match.start()), None)
        if month:
            found.append((int(match.group(1)), month))
    return found


def _with_year(month, day, today):
    """The next occurrence of that day and month, or None.

    The page states no year, so this is the one thing here that is
    inferred rather than read. A what's-on page lists what is coming, so
    the answer is this year's date unless it is well past, and GRACE
    keeps an event that started a fortnight ago from being read as next
    year's.
    """

    for year in (today.year, today.year + 1):
        try:
            moment = date(year, month, day)
        except ValueError:  # 30 February, and 29 February in a common year
            continue
        if moment >= today - GRACE:
            return moment
    return None


def _description(details):
    """The first sentence or two of the page's own prose, or ''."""

    for paragraph in details.find_all("p"):
        if "timedatetext" in (paragraph.get("class") or []):
            continue
        text = " ".join(paragraph.get_text(" ", strip=True).split())
        if len(text) > 40:
            return text[:500]
    return ""
