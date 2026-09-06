"""Chenies Manor House — a Tudor manor with famous tulip and dahlia gardens.

The tidiest listing any source here reads. Measured 6 Sep 2026, `/events/`
carries each event as a `.ce-card` with everything needed and nothing to
untangle:

    <a href="https://www.cheniesmanorhouse.co.uk/event/tulip-festival/"
       class="ce-card">
      <div class="ce-card__body">
        <h2 class="ce-card__title">Tulip Festival</h2>
        <p class="ce-card__dates">3 May 2027 – 31 May 2027</p>
        <p class="ce-card__excerpt">We are famous for our Tulips…</p>

Both dates carry their year, so nothing is inferred here — unlike Lamport
Hall, which states none, or Blenheim, which states some.

**`dates.parse_range` cannot read this shape, and fails quietly.** Given
"3 May 2027 – 31 May 2027" it returns ('2027-05-03', '2027-05-03'): its
pattern is built for "5 - 6 December 2026", where the year is written once
at the end, so it matches the first complete date and stops. A month-long
festival would have become a one-day event, and nothing would have looked
wrong. So the two sides are split on the dash and read separately.

The site is WordPress and registers an `event` post type, but
`/wp-json/wp/v2/event` answers with no `meta` and an empty `acf` — the
API knows the events and none of their dates, exactly as Stonor's does.
The listing has both, so the listing is what this reads, in one request.
"""

import logging
import re

from bs4 import BeautifulSoup

from .. import dates

log = logging.getLogger(__name__)

BASE = "https://www.cheniesmanorhouse.co.uk"
LISTING = f"{BASE}/events/"

# "3 May 2027 – 31 May 2027": an en dash on this site, but a hyphen, an em
# dash or the word "to" are all the same thing to a reader.
SPLIT_RE = re.compile(r"\s+(?:[-–—]|to)\s+")

# "Chenies, Rickmansworth, Herts, WD3 6ER" — the address in the page's own
# Find Us panel.
VENUE_NAME = "Chenies Manor House"
VENUE_POSTCODE = "WD3 6ER"


class Chenies:

    name = "chenies-manor"
    category = "historic-house"
    site_url = LISTING

    def scrape(self, fetcher, max_pages=0):

        try:
            body = fetcher.get(LISTING)
        except Exception as e:  # noqa: BLE001 — the run, not one card
            log.warning("%s: %s failed: %s", self.name, LISTING, e)
            return

        cards = parse_listing(body)
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
            # Named, not counted: a date shape we have stopped reading
            # looks exactly like a card that gives no date.
            log.info("%s: no date on %d: %s", self.name, len(undated),
                     "; ".join(t[:34] for t in undated[:8]))

    def link_event(self, event):
        return None


def parse_listing(body):
    """[(title, event or None)] for every card on the events page.

    The same event appears once per card, but the page repeats a card in
    more than one section, so a link seen twice is one event.
    """

    soup = BeautifulSoup(body, "html.parser")
    found, seen = [], set()
    for card in soup.select(".ce-card"):
        heading = card.select_one(".ce-card__title")
        title = (" ".join(heading.get_text(" ", strip=True).split())
                 if heading else "")
        url = (card.get("href") or "").strip()
        if not title or (url and url in seen):
            continue
        seen.add(url)
        found.append((title, _event(card, title, url)))
    return found


def _event(card, title, url):
    """The event a card describes, or None when its dates cannot be read."""

    when = card.select_one(".ce-card__dates")
    span = date_range(when.get_text(" ", strip=True) if when else "")
    if not span:
        return None
    start, end = span

    excerpt = card.select_one(".ce-card__excerpt")
    return {
        # An annual festival keeps its page and changes its dates.
        "source_id": f"{url.rstrip('/').rsplit('/', 1)[-1] or _slug(title)}-{start}",
        "title": title[:160],
        "description": (" ".join(excerpt.get_text(" ", strip=True).split())[:400]
                        if excerpt else ""),
        "url": url or LISTING,
        "start_date": start,
        "end_date": end,
        # One venue, and the cards never repeat its address.
        "location_name": VENUE_NAME,
        "location_postcode": VENUE_POSTCODE,
    }


def date_range(text):
    """'3 May 2027 – 31 May 2027' -> ('2027-05-03', '2027-05-31').

    Each side is a complete date here, which is the shape
    `dates.parse_range` reads as one date and stops. Split first, then let
    it read each half; a single date comes back as itself twice, which is
    how the store holds a one-day event.
    """

    text = " ".join(str(text or "").split())
    if not text:
        return None

    parts = SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        start, _ = dates.parse_range(parts[0])
        end, _ = dates.parse_range(parts[1])
        if start and end:
            # A range that runs backwards is a typo, not a range.
            return (start, end) if end >= start else None

    # Either there was no dash, or one side was not a date on its own —
    # "3 - 31 May 2027" names its month and year once, at the end, which
    # is the shape parse_range was built for. Reading the whole string
    # covers both, and a single date comes back as itself twice, which is
    # how the store holds a one-day event.
    start, end = dates.parse_range(text)
    return (start, end) if start and end else None


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
