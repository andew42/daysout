"""Minimal iCalendar (RFC 5545) reader for event feeds.

Plenty of venues and listing sites publish a .ics feed. It is the nicest
event source there is — machine-readable by design, no markup guessing,
and offered deliberately for subscription — so it's worth reading directly
rather than pulling a dependency in for the handful of fields we need.

Only what an event listing needs is parsed: SUMMARY, DTSTART, DTEND,
LOCATION, DESCRIPTION, URL, UID.
"""

import html
import re

# A long value is continued on the next line, which begins with a space or
# tab (RFC 5545 §3.1).
FOLD_RE = re.compile(r"\r?\n[ \t]")

# "DTSTART;VALUE=DATE:20260829" -> name DTSTART, params, value
LINE_RE = re.compile(r"^(?P<name>[A-Za-z0-9-]+)(?P<params>;[^:]*)?:(?P<value>.*)$")

ESCAPES = {"\\n": "\n", "\\N": "\n", "\\,": ",", "\\;": ";", "\\\\": "\\"}


def _unescape(text):
    """iCalendar escaping first, then HTML entities.

    The two are unrelated and both turn up. RFC 5545 escapes commas,
    semicolons and newlines; on top of that a WordPress export writes its
    post text straight into SUMMARY and DESCRIPTION with the entities
    still in it, so "Antiques &amp; Collectors" and a curly apostrophe as
    "&#8217;" arrive here. The frontend escapes what it interpolates,
    quite correctly, so an entity left in the database is one the reader
    actually sees — the same trap as JSON-LD inside a <script>.
    """
    for escaped, plain in ESCAPES.items():
        text = text.replace(escaped, plain)
    return html.unescape(text).strip()


def _date(value):
    """iCal date/date-time to an ISO date: 20260829T103000Z -> 2026-08-29."""
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) < 8:
        return ""
    return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"


def parse(text):
    """Yields dicts with title/start_date/end_date/description/url/location_name/uid."""

    text = FOLD_RE.sub("", text)
    event = None

    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line == "BEGIN:VEVENT":
            event = {}
            continue
        if line == "END:VEVENT":
            if event and event.get("title") and event.get("start_date"):
                # An all-day DTEND is exclusive: a one-day event ends the
                # next morning, which would otherwise read as two days.
                if event.pop("end_exclusive", False) and event["end_date"] > event["start_date"]:
                    event["end_date"] = _minus_a_day(event["end_date"])
                event.setdefault("end_date", event["start_date"])
                yield event
            event = None
            continue
        if event is None:
            continue

        match = LINE_RE.match(line)
        if not match:
            continue
        name = match.group("name").upper()
        params = (match.group("params") or "").upper()
        value = match.group("value")

        if name == "SUMMARY":
            event["title"] = _unescape(value)[:300]
        elif name == "DTSTART":
            event["start_date"] = _date(value)
        elif name == "DTEND":
            event["end_date"] = _date(value)
            event["end_exclusive"] = "VALUE=DATE" in params
        elif name == "DESCRIPTION":
            event["description"] = _unescape(value)[:400]
        elif name == "URL":
            event["url"] = value.strip()
        elif name == "LOCATION":
            event["location_name"] = _unescape(value)[:200]
        elif name == "UID":
            event["uid"] = value.strip()


def _minus_a_day(iso_date):
    from datetime import date, timedelta
    try:
        year, month, day = (int(part) for part in iso_date.split("-"))
        return (date(year, month, day) - timedelta(days=1)).isoformat()
    except ValueError:
        return iso_date
