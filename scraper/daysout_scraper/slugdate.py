"""Read an event's dates out of its URL.

Some sites publish a page per event with the date in the address —
"/whats-on/evening-airshow-15-august-2026" — and no structured data on the
page at all. The URL is then the most reliable thing about the event: it
is chosen by the site, it does not change when the page is restyled, and
it is already in the sitemap, so the dates cost nothing extra to read.

A slug with no year is dated by the next time that day comes round, which
is what a person reading it would assume. A little slack backwards keeps
an event that started a fortnight ago from being pushed a year out.
"""

import re
from datetime import date, timedelta

MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Longest first: "sep" would otherwise match inside "september" and leave
# "tember" behind.
MONTHS = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
ORDINAL = r"(?:st|nd|rd|th)?"

ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RANGE_RE = re.compile(
    rf"\b(\d{{1,2}}){ORDINAL}-(?:to-|and-)?(\d{{1,2}}){ORDINAL}-({MONTHS})\b"
    rf"(?:-(\d{{4}}))?", re.IGNORECASE)
DAY_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}}){ORDINAL}-({MONTHS})\b(?:-(\d{{4}}))?", re.IGNORECASE)
MONTH_DAY_RE = re.compile(
    rf"\b({MONTHS})-(\d{{1,2}}){ORDINAL}\b(?:-(\d{{4}}))?", re.IGNORECASE)

# How far back a slug without a year may be read as this year rather than
# next: an event that ran a fortnight ago is still worth showing as past,
# and pushing it twelve months forward would be a lie.
BACKWARD_SLACK = timedelta(days=45)


def _normalise(url):
    """Path only, lower case, everything non-alphanumeric a single dash."""
    path = url.split("://", 1)[-1]
    path = path.split("/", 1)[-1] if "/" in path else ""
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")


def _resolve(day, month, year, today):
    """A real date, choosing the year when the slug does not give one."""
    if year:
        try:
            return date(int(year), month, day)
        except ValueError:
            return None
    for candidate in (today.year, today.year + 1, today.year - 1):
        try:
            resolved = date(candidate, month, day)
        except ValueError:
            continue
        if resolved >= today - BACKWARD_SLACK:
            return resolved
    return None


def parse(url, today=None):
    """(start, end) as ISO dates from the URL, or None if it carries none."""

    today = today or date.today()
    slug = _normalise(url)

    match = ISO_RE.search(slug)
    if match:
        try:
            start = date(int(match.group(1)), int(match.group(2)),
                         int(match.group(3)))
        except ValueError:
            return None
        return start.isoformat(), start.isoformat()

    match = RANGE_RE.search(slug)
    if match:
        month = MONTH_NUMBERS[match.group(3).lower()]
        start = _resolve(int(match.group(1)), month, match.group(4), today)
        end = _resolve(int(match.group(2)), month, match.group(4), today)
        if start and end and end >= start:
            return start.isoformat(), end.isoformat()
        if start:
            return start.isoformat(), start.isoformat()
        return None

    for pattern, day_first in ((DAY_MONTH_RE, True), (MONTH_DAY_RE, False)):
        match = pattern.search(slug)
        if not match:
            continue
        day = int(match.group(1) if day_first else match.group(2))
        month = MONTH_NUMBERS[(match.group(2) if day_first
                               else match.group(1)).lower()]
        start = _resolve(day, month, match.group(3), today)
        if start:
            return start.isoformat(), start.isoformat()
    return None


# "15", "15th", "2026" — the date parts, once the month names are gone.
NUMBER_RE = re.compile(rf"^\d+{ORDINAL}$")
JOINING_WORDS = ("to", "and")


def title_from(url):
    """A readable title from the last path segment, minus its date.

    For a page that offers nothing better. The slug is the site's own
    wording, so "evening-airshow-15-september-2026" reads as "Evening
    Airshow" — which is what the page is called.
    """

    segment = url.rstrip("/").rsplit("/", 1)[-1]
    words = [word for word in re.split(r"[^A-Za-z0-9]+", segment) if word]
    kept = [word for word in words
            if not NUMBER_RE.match(word.lower())
            and word.lower() not in MONTH_NUMBERS
            and word.lower() not in JOINING_WORDS]
    return " ".join(kept).title()
