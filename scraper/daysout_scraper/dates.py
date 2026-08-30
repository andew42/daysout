"""Every date a source publishes, reduced to one ISO form.

Dates are stored as text and compared as text: an event is current when
`end_date >= '2026-08-30'`. That comparison is only meaningful if every
date is ISO. Stonor's events API answers "02/05/2026 10:00:00", whose
first ten characters are the right length and the wrong order, so they
were stored as "02/05/2026" — and '0' sorts before '2', so all five of
its events failed `end_date >= today` and vanished from the site while
every count still said 5/5 linked.

Anything not recognised comes back empty rather than approximately
right: a wrong date is worse than a missing one, because it puts a real
event on a day nobody is expecting it.
"""

import re
from datetime import date

# 2026-05-02, optionally with a time after a space or T.
ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")

# 02/05/2026 and 2/5/26 — day first, as UK sites write it. Never
# month-first: this is a UK-only tool, and guessing between the two on
# ambiguous days is how an event lands three months out.
SLASHED_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?:[T ].*)?$")

# 02-05-2026: the same day-first order with dashes, which ISO_RE would
# never match because its year comes last.
DASHED_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})(?:[T ].*)?$")


def to_iso(value):
    """'02/05/2026 10:00:00' -> '2026-05-02'. Unrecognised -> ''."""

    text = str(value or "").strip()
    if not text:
        return ""

    match = ISO_RE.match(text)
    if match:
        return _valid(*(int(part) for part in match.groups()))

    for pattern in (SLASHED_RE, DASHED_RE):
        match = pattern.match(text)
        if match:
            day, month, year = (int(part) for part in match.groups())
            if year < 100:
                year += 2000
            return _valid(year, month, day)

    return ""


def _valid(year, month, day):
    """The ISO string, or '' when those numbers are not a real date."""
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


MONTHS = {name: number for number, names in enumerate(
    [("january", "jan"), ("february", "feb"), ("march", "mar"),
     ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
     ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"),
     ("november", "nov"), ("december", "dec")], start=1)
    for name in names}

_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))

# "5 - 6 December 2026", "18 - 20 September 2026", "4 September 2026",
# "29 August - 1 September 2026" — how a British listing writes a run of
# days. The year appears once, at the end, however many days it spans.
_RANGE_RE = re.compile(
    rf"(?P<d1>\d{{1,2}})\s*(?:(?P<m1>{_MONTH_NAMES})\b)?"
    rf"(?:\s*(?:-|–|—|to)\s*(?P<d2>\d{{1,2}})\s*(?:(?P<m2>{_MONTH_NAMES})\b)?)?"
    rf"\s*(?P<year>\d{{4}})",
    re.IGNORECASE)


def parse_range(text):
    """'5 - 6 December 2026' -> ('2026-12-05', '2026-12-06').

    Returns ('', '') for anything it cannot read. A single day comes back
    as the same date twice, which is how the store holds a one-day event.
    """
    match = _RANGE_RE.search(" ".join(str(text or "").split()))
    if not match:
        return "", ""

    year = int(match.group("year"))
    # A range written "5 - 6 December" names its month once, at the end.
    month2 = match.group("m2") or match.group("m1")
    month1 = match.group("m1") or month2
    if not month1:
        return "", ""

    start = _valid(year, MONTHS[month1.lower()], int(match.group("d1")))
    if not match.group("d2"):
        return (start, start) if start else ("", "")

    end = _valid(year, MONTHS[month2.lower()], int(match.group("d2")))
    # "29 December - 2 January 2027" runs into the next year.
    if start and end and end < start:
        end = _valid(year + 1, MONTHS[month2.lower()], int(match.group("d2")))
    return (start, end) if start and end else ("", "")
