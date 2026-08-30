"""Historic Houses — independently owned houses open to the public.

The gap left by the National Trust and English Heritage: houses in private
hands, which is where a great many of the days out actually are.

The site publishes a sitemap of nothing but house pages —
https://www.historichouses.org/house-sitemap.xml, whose entries look like
https://www.historichouses.org/house/ditchley-park/ — and each house page
carries the address, postcode included. That postcode is the whole point:
it is what the local Code-Point Open table geocodes, and a destination
with no location cannot be sorted by distance and so cannot be shown.

There are no event pages in that sitemap, so this source contributes
places only. Events at these houses come from the houses' own sites.

On reading the address: a house page's postcode is looked for in three
places, most trustworthy first — a schema.org PostalAddress, then an
address block, then the page text. The last is a genuine risk, because a
postcode in a page's footer belongs to the organisation rather than the
house, so the footer and header are removed before it is used, and a page
that only yields a postcode that way says so in the log. The deploy's
"What a Historic Houses page carries" step reports which layer actually
fires, and this comment should be corrected once that is known.
"""

import logging
import re

from bs4 import BeautifulSoup

from .. import jsonld, postcode as postcodes
from ..sitemap_source import sitemap_urls

log = logging.getLogger(__name__)

HOUSE_RE = re.compile(r"^https://www\.historichouses\.org/house/[^/]+/?$")

# Where an address lives when it is not in structured data.
ADDRESS_HINT_RE = re.compile(r"address|location|postcode|find-?us|visit|contact",
                             re.IGNORECASE)

GARDEN_WORDS = re.compile(r"\bgardens?\b", re.IGNORECASE)

# Chrome that carries the charity's own postcode, not the house's.
CHROME_TAGS = ("script", "style", "header", "footer", "nav")


class HistoricHouses:

    name = "historic-houses"
    sitemaps = ("https://www.historichouses.org/house-sitemap.xml",)

    def scrape(self, fetcher, max_pages=0):

        dated = []
        for sitemap in self.sitemaps:
            for url, lastmod in sitemap_urls(fetcher, sitemap, with_lastmod=True):
                if HOUSE_RE.match(url):
                    dated.append((lastmod, url))
        log.info("%s: %d house pages in the sitemap", self.name, len(dated))

        urls = [url for _, url in sorted(dated, reverse=True)]
        if max_pages:
            urls = urls[:max_pages]

        without_postcode = 0
        for url in urls:
            try:
                body = fetcher.get(url)
            except Exception as e:  # noqa: BLE001 — one bad page, not the run
                log.warning("fetch %s failed: %s", url, e)
                continue
            place = parse_house(body, url)
            if place:
                yield "place", place
            else:
                without_postcode += 1

        if without_postcode:
            # Said plainly because it is the difference between "the site
            # changed" and "these few houses publish no address".
            log.info("%s: %d of %d house pages had no postcode",
                     self.name, without_postcode, len(urls))

    def link_event(self, event):
        return None


def parse_house(body, url):
    """A place dict for a house page, or None when it has no postcode.

    Without a postcode there is nothing to geocode, and a destination with
    no location is invisible to every query the site makes.
    """
    soup = BeautifulSoup(body, "html.parser")

    name = description = ""
    found_postcode = ""
    coordinates = None

    for obj in jsonld.extract_objects(body):
        place = jsonld.parse_place(obj, url)
        if not place:
            continue
        name = name or place["name"]
        description = description or place["description"]
        found_postcode = found_postcode or place["postcode"]
        if "lat" in place and coordinates is None:
            coordinates = (place["lat"], place["lon"])
        if found_postcode:
            break

    how = "json-ld"
    if not found_postcode:
        found_postcode, how = _postcode_from_markup(soup)
    if not found_postcode:
        return None

    name = name or _heading(soup) or _slug_name(url)
    if not name:
        return None
    if how == "page-text":
        log.debug("%s: postcode taken from the page text", url)

    place = {
        "source_id": url.rstrip("/").rsplit("/", 1)[-1],
        "name": name,
        "description": description or _summary(soup),
        "url": url,
        "postcode": found_postcode,
        "category": "garden" if GARDEN_WORDS.search(name) else "historic-house",
    }
    if coordinates:
        place["lat"], place["lon"] = coordinates
    return place


def _postcode_from_markup(soup):
    """(postcode, how) — an address block if there is one, else page text."""

    for element in soup.find_all("address"):
        found = postcodes.find(element.get_text(" ", strip=True))
        if found:
            return found, "address-element"

    for element in soup.find_all(attrs={"class": ADDRESS_HINT_RE}):
        found = postcodes.find(element.get_text(" ", strip=True))
        if found:
            return found, "address-class"

    # Last resort. The header and footer carry the organisation's own
    # postcode on every page, so a match there would give every house the
    # same location — worse than having none.
    body = BeautifulSoup(str(soup), "html.parser")
    for tag in body.find_all(CHROME_TAGS):
        tag.decompose()
    found = postcodes.find(body.get_text(" ", strip=True))
    return (found, "page-text") if found else ("", "")


def _heading(soup):
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return " ".join(heading.get_text(" ", strip=True).split())[:160]
    return ""


def _summary(soup):
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return " ".join(meta["content"].split())[:400]
    return ""


def _slug_name(url):
    """"…/house/ditchley-park/" -> "Ditchley Park"."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return " ".join(word.capitalize() for word in slug.split("-"))
