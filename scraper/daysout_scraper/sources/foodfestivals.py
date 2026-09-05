"""Food festivals, from a blog's year-round roundup.

rosemaryandporkbelly.co.uk publishes one page listing food and drink
festivals across the UK, month by month. It is a blog post rather than an
events site, and the seeded row read it as `kind='browser'` on the guess
that "its festival roundups may render dates". That was wrong twice over,
measured 5 Sep 2026: the page is a `BlogPosting` with no Event JSON-LD
for a structured-data kind to find, and its dates were in the served HTML
all along, so rendering was never the missing piece. One plain request
gets the lot.

The shape is plain and stable:

    <h4>February</h4>                       <- the month, as an accordion
    ...
    <h3><a href="http://olneypancakerace.org/">
        Olney Pancake Race, Buckinghamshire</a></h3>
    <p><strong>Tuesday 17 February 2026</strong>. It's flipping
       traditional! …</p>

Each festival is an `<h3>` whose link goes to the festival's own site,
and the `<p>` after it opens with the date. Those dates carry their
year, so `dates.parse_range` reads them as they stand — 124 of the 134
entries, with no inference of the kind Lamport Hall needs.

**What stopped this source working was never the dates.** There is not
one postcode on the page, and all 134 links leave for third-party sites,
so the UK Craft Fairs answer — listing as index, each item's own page for
the address — is not available here: it would mean crawling 134 unrelated
domains. Location survives only as prose in the heading. That is what the
`places` gazetteer is for, and this is the source it was built for: the
heading's parts are offered to the pipeline as candidate towns and the
first one the gazetteer holds wins.

Which is also why the candidates are offered in that order rather than
resolved here. A source cannot see the database, and "Foodies Festival,
Bath, Somerset" cannot know by itself that Bath is the town and Somerset
the county — but the gazetteer holds settlements and not counties, so
handing over both in order lets the lookup answer it. The event's own
title stays the venue label, the way RHS shows are labelled, since what
we know is the festival and roughly where it is, not the field it is in.

Ten entries state no readable date ("Autumn 2026", "2026 dates TBC") and
are skipped and named in the log, and an entry whose place is not a
settlement we hold — "Great British Food Festival, Arley Hall, Cheshire"
— is dropped by the pipeline and named there too. Both are the honest
outcome: a festival at a guessed location is worse than one the map
never shows.
"""

import logging
import re

from bs4 import BeautifulSoup

from .. import dates

log = logging.getLogger(__name__)

URL = "https://rosemaryandporkbelly.co.uk/food-festivals-uk/"

# The heading separates the festival from where it is with either, and
# "Taste of the Caribbean: Crawley" uses the colon.
SPLIT_RE = re.compile(r"[,:]")

# Words that are never a place, so never worth offering the gazetteer.
# "various locations in the village" is a real trailing part here.
NOT_A_PLACE = re.compile(
    r"^(various|several|multiple|across|throughout|around|nationwide|"
    r"venues?|locations?|tbc)\b", re.I)


class FoodFestivals:

    name = "food-festivals-uk"
    category = "food"

    def scrape(self, fetcher, max_pages=0):

        try:
            body = fetcher.get(URL)
        except Exception as e:  # noqa: BLE001 — the run, not one entry
            log.warning("%s: %s failed: %s", self.name, URL, e)
            return

        entries = parse_page(body)
        undated = [title for title, event in entries if event is None]
        events = [event for _, event in entries if event]
        if max_pages:
            events = events[:max_pages]

        for event in events:
            event["category"] = self.category
            yield "event", event

        log.info("%s: %d festival(s), %d dated", self.name,
                 len(entries), len(events))
        if undated:
            # Named, not counted: a date shape we cannot read yet looks
            # exactly like an entry that gives no date.
            log.info("%s: no date read on %d: %s", self.name, len(undated),
                     "; ".join(t[:40] for t in undated[:8]))

    def link_event(self, event):
        return None


def parse_page(body):
    """[(title, event or None)] for every festival the page lists."""

    soup = BeautifulSoup(body, "html.parser")
    entries = []
    for heading in soup.find_all("h3"):
        title = " ".join(heading.get_text(" ", strip=True).split())
        if not title:
            continue
        paragraph = heading.find_next_sibling("p")
        text = (" ".join(paragraph.get_text(" ", strip=True).split())
                if paragraph else "")
        entries.append((title, _event(title, text, heading)))
    return entries


def _event(title, text, heading):
    """The event a heading and its paragraph describe, or None if undated."""

    start, end = dates.parse_range(text)
    if not start:
        return None

    link = heading.find("a", href=True)
    places = place_candidates(title)
    return {
        # The title carries the year's date in the text, not the id, so
        # the start date keeps two runs of an annual festival apart.
        "source_id": f"{_slug(title)}-{start}",
        "title": title,
        "description": _description(text),
        "url": link["href"] if link else URL,
        "start_date": start,
        "end_date": end,
        # No postcode exists anywhere on this page, and no venue name
        # either — so this claims neither. It used to hand over the
        # festival's own name as the venue, which put every stop of a
        # touring festival at the same place: "Foodies Festival" runs in
        # Bath, Oxford, Edinburgh and Glasgow, the first one created the
        # venue, and the rest were matched to it by name. The town is all
        # this page tells us, so the town is what the venue becomes.
        "location_name": "",
        "location_places": places,
    }


def place_candidates(title):
    """Place names worth trying, most likely first.

    "Ludlow Food Festival, Shropshire" hides its town in the festival's
    own name and its county in the tail; "Foodies Festival, Bath,
    Somerset" puts the town in the middle. Offering the tail parts before
    the leading words of the name covers both, and costs nothing when a
    part is a county: the gazetteer holds settlements only, so a county
    matches nothing rather than placing the event fifty miles out.
    """

    parts = [part.strip() for part in SPLIT_RE.split(title) if part.strip()]
    if not parts:
        return []

    candidates = [part for part in reversed(parts[1:])
                  if not NOT_A_PLACE.match(part)]

    # The festival's own name usually opens with its town: "Ludlow Food
    # Festival", "Porthleven Food Festival". Longest first, so "Bishops
    # Stortford" is tried before "Bishops".
    words = parts[0].split()
    for length in (3, 2, 1):
        if len(words) > length:
            candidates.append(" ".join(words[:length]))

    seen, unique = set(), []
    for candidate in candidates:
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _description(text):
    """The prose after the date, which opens the paragraph."""
    # "20 - 22 February 2026. In the heart of England's Rhubarb Triangle."
    without = re.sub(r"^.{0,60}?\d{4}\s*[.,]?\s*", "", text, count=1)
    return (without or text)[:400]


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
