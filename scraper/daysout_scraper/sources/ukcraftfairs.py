"""UK Craft Fairs — the craft, food and gift fair calendar.

This site cannot be fetched, only rendered, and that is a broken server
rather than a refusal. Every plain request times out because the response's
header block contains "Strict Transport Security:" — spaces where the
hyphens belong — which is not a legal header name, so http.client never
finds the blank line before the body and the read hangs until the timeout,
though the response carries a good Content-Length. Measured on the house
server 31 Aug 2026: that took out robots.txt, both sitemap paths, all four
wp-json routes and all nine conventional feed paths, so there is no feed,
no API and no crawlable sitemap here as far as we can ever tell. Chromium
is lenient about the bad header and renders the page in full, and
looks_like_a_challenge is false — nobody is turning us away. Hence
kind = "browser": without it __main__ never starts a Renderer and every
fetch here fails.

Two page shapes, both read off real renders:

  * /calendar is a **single-day** view, headed "Monday, 31 August 2026",
    listing the fairs running that day. Other days are addressed the way
    its own < and > links do: /calendar/1-september-2026. Each fair is an
    <a class="grid-item panel-list"> wrapping a heading and a body:

        <h2 class="h4">Lowther Gardens Food and Drink Festival</h2>
        <p><strong>Lowther Gardens</strong>, Lytham St Annes, Lancashire</p>
        <p>Saturday, <strong>29 August 2026</strong> (3 day event)</p>

    The <strong> date is the fair's START and "(N day event)" its length,
    which is why a page headed the 31st shows fairs dated the 27th and
    29th — they are multi-day fairs still running. A day page carries no
    postcode at all, only a town and a county.

  * /craft-events/<id>/<slug> is the fair's own page, and unlike the
    calendar it publishes Event JSON-LD *and* an address with a postcode
    ("Lowther Gardens West Beach, Lytham St Annes, Lancashire, FY8 5QQ").
    That is the whole reason this source can work: the pipeline geocodes a
    venue from its postcode and drops an event it cannot place, so the
    listing alone would read fairs all day and contribute nothing.

So the calendar is used for discovery — it is the only index the site
offers — and each fair's own page for its details, preferring its
structured data over the listing's markup.
"""

import logging
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from .. import dates, jsonld, postcode as postcodes

log = logging.getLogger(__name__)

CALENDAR = "https://www.ukcraftfairs.com/calendar"

# The site's own < and > links: /calendar/1-september-2026.
MONTH_NAMES = ("january", "february", "march", "april", "may", "june",
               "july", "august", "september", "october", "november",
               "december")

# /craft-events/26533/lowther-gardens-food-and-drink-festival
EVENT_RE = re.compile(r"/craft-events/(\d+)/([^/?#]+)")

# "(3 day event)" — the fair's length, alongside its start date.
DURATION_RE = re.compile(r"\((\d+)\s*day", re.IGNORECASE)

# A planner wants the coming weeks, and each day costs a render. Fairs run
# for several days and every day they run lists them again, so a fortnight
# of pages finds rather more than a fortnight of fairs.
DEFAULT_DAYS = 14

# Each fair's own page is a second render. Bounded so one run cannot walk
# away with the whole site.
MAX_EVENT_PAGES = 80


def day_url(day):
    """The site's own URL for one day's fairs."""
    return f"{CALENDAR}/{day.day}-{MONTH_NAMES[day.month - 1]}-{day.year}"


class UKCraftFairs:

    name = "uk-craft-fairs"
    # Plain fetching can never work here, so the run must start a browser.
    kind = "browser"
    category = "craft"

    def scrape(self, fetcher, max_pages=0):

        days = min(max_pages, DEFAULT_DAYS) if max_pages else DEFAULT_DAYS
        today = date.today()

        # Keyed by the fair's own URL: a three-day fair appears on all
        # three of its days and is one row, not three.
        listings = {}
        for offset in range(days):
            url = day_url(today + timedelta(days=offset))
            try:
                body = fetcher.get(url, render=True)
            except Exception as e:  # noqa: BLE001 — one day, not the run
                log.warning("%s: %s failed: %s", self.name, url, e)
                continue
            found = parse_listing(body)
            for row in found:
                listings.setdefault(row["url"], row)
            log.debug("%s: %d fair(s) on %s", self.name, len(found), url)

        log.info("%s: %d distinct fair(s) across %d day page(s)",
                 self.name, len(listings), days)

        limit = max_pages or MAX_EVENT_PAGES
        no_postcode = []
        for index, url in enumerate(sorted(listings)):
            if index >= limit:
                log.info("%s: stopping after %d event page(s) of %d",
                         self.name, limit, len(listings))
                break
            event = self._event(fetcher, url, listings[url])
            if not event:
                continue
            if not event["location_postcode"]:
                # The pipeline drops these, so say which they were rather
                # than letting the counts imply the parser missed them.
                no_postcode.append(event["title"])
                continue
            yield "event", event

        if no_postcode:
            log.info("%s: no postcode on %d fair page(s): %s",
                     self.name, len(no_postcode), ", ".join(no_postcode[:6]))

    def link_event(self, event):
        return None

    def _event(self, fetcher, url, row):
        """One fair, from its own page where possible and the listing where not."""

        try:
            body = fetcher.get(url, render=True)
        except Exception as e:  # noqa: BLE001 — one fair, not the run
            log.debug("%s: %s failed: %s", self.name, url, e)
            body = ""

        event = _from_jsonld(body, url) if body else None
        if event is None:
            # No structured data on this one: the listing row still has a
            # title and dates, and the page may still carry a postcode.
            event = {
                "title": row["title"],
                "description": "",
                "url": url,
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "location_name": row["venue_name"],
                "location_postcode": "",
            }
        elif row["end_date"] > event["end_date"]:
            # A multi-day fair whose JSON-LD omits endDate would otherwise
            # show as one day; the listing says how long it runs.
            event["end_date"] = row["end_date"]

        if not event["title"] or not event["start_date"]:
            return None

        if not event["location_name"]:
            event["location_name"] = row["venue_name"]
        if not event["location_postcode"] and body:
            # The address is in the page's prose rather than its JSON-LD
            # on at least some fairs, and a postcode is what places it.
            event["location_postcode"] = postcodes.find(
                BeautifulSoup(body, "html.parser").get_text(" ", strip=True))

        event["source_id"] = row["source_id"]
        event["category"] = self.category
        return event


def _from_jsonld(body, url):
    """The first Event object on a fair's page, or None."""

    for obj in jsonld.extract_objects(body):
        parsed = jsonld.parse_event(obj, url)
        if parsed:
            # Its own URL, not whatever the markup claims: that is the
            # link a visitor follows and the key we deduplicate on.
            parsed["url"] = url
            return parsed
    return None


def parse_listing(body):
    """The fairs on one calendar day page.

    A row is an anchor to /craft-events/... that wraps a .panel-list-bottom;
    that pairing is what tells a fair's card apart from the navigation
    links, which point at the same section without carrying a card.
    """

    soup = BeautifulSoup(body, "html.parser")
    rows = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        match = EVENT_RE.search(anchor["href"])
        if not match:
            continue
        bottom = anchor.select_one(".panel-list-bottom")
        if bottom is None:
            continue

        start, end = _row_dates(bottom)
        if not start:
            continue
        venue_name, venue_line = _row_venue(bottom)
        title = _row_title(anchor)
        if not title:
            continue

        url = f"https://www.ukcraftfairs.com/craft-events/{match.group(1)}/{match.group(2)}"
        if url in seen:
            continue
        seen.add(url)
        rows.append({
            "source_id": match.group(1),
            "title": title,
            "url": url,
            "start_date": start,
            "end_date": end,
            "venue_name": venue_name,
            "venue_line": venue_line,
        })
    return rows


def _row_title(anchor):
    heading = anchor.select_one(".panel-list-heading h2") or anchor.find("h2")
    if heading:
        return " ".join(heading.get_text(" ", strip=True).split())[:160]
    return ""


def _row_dates(bottom):
    """(start, end) from '<strong>29 August 2026</strong> (3 day event)'."""

    for paragraph in bottom.find_all("p"):
        strong = paragraph.find("strong")
        if strong is None:
            continue
        start, _ = dates.parse_range(strong.get_text(" ", strip=True))
        if not start:
            continue
        # The date given is the first day; the run length follows it.
        length = DURATION_RE.search(paragraph.get_text(" ", strip=True))
        days = int(length.group(1)) if length else 1
        end = (date.fromisoformat(start) + timedelta(days=max(days, 1) - 1))
        return start, end.isoformat()
    return "", ""


def _row_venue(bottom):
    """('Lowther Gardens', 'Lowther Gardens, Lytham St Annes, Lancashire')."""

    for paragraph in bottom.find_all("p"):
        strong = paragraph.find("strong")
        if strong is None:
            continue
        text = " ".join(strong.get_text(" ", strip=True).split())
        # The other bold paragraph is the date, which is not a venue.
        if dates.parse_range(text)[0]:
            continue
        return text[:160], " ".join(paragraph.get_text(" ", strip=True).split())
    return "", ""
