"""Extract schema.org JSON-LD from web pages.

Visitor-attraction sites (National Trust, English Heritage and many others)
embed structured data for search engines: Place/TouristAttraction objects
with coordinates, and Event objects with dates. Parsing that is far more
robust than scraping each site's HTML, and one engine serves every source.
"""

import json

from bs4 import BeautifulSoup

PLACE_TYPES = {"Place", "TouristAttraction", "LandmarksOrHistoricalBuildings",
               "Park", "Museum", "LocalBusiness", "TouristDestination"}
EVENT_TYPES = {"Event", "Festival", "ExhibitionEvent", "SocialEvent",
               "ChildrensEvent", "EducationEvent", "VisualArtsEvent"}


def extract_objects(html):
    """All JSON-LD objects on a page, flattening @graph and top-level lists."""
    objects = []
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if "@graph" in item and isinstance(item["@graph"], list):
                objects.extend(o for o in item["@graph"] if isinstance(o, dict))
            else:
                objects.append(item)
    return objects


def _types(obj):
    t = obj.get("@type", [])
    return set(t) if isinstance(t, list) else {t}


def _text(value):
    if isinstance(value, dict):
        return str(value.get("name", "") or value.get("@value", ""))
    return str(value) if value else ""


def _geo(obj):
    geo = obj.get("geo")
    if isinstance(geo, dict):
        try:
            return float(geo["latitude"]), float(geo["longitude"])
        except (KeyError, TypeError, ValueError):
            pass
    return None


def _postcode(obj):
    address = obj.get("address")
    if isinstance(address, dict):
        return _text(address.get("postalCode")).strip()
    return ""


def _date(value):
    """'2026-08-29T10:00:00+01:00' -> '2026-08-29'."""
    text = _text(value)
    return text[:10] if len(text) >= 10 else ""


def parse_place(obj, page_url):
    """A place dict (no category/source_id yet) or None."""
    if not (_types(obj) & PLACE_TYPES):
        return None
    name = _text(obj.get("name")).strip()
    coordinates = _geo(obj)
    if not name:
        return None
    place = {
        "name": name,
        "description": _text(obj.get("description")).strip()[:400],
        "url": _text(obj.get("url")).strip() or page_url,
        "postcode": _postcode(obj),
    }
    if coordinates:
        place["lat"], place["lon"] = coordinates
    return place


def parse_event(obj, page_url):
    """An event dict (location under 'location_name') or None."""
    if not (_types(obj) & EVENT_TYPES):
        return None
    name = _text(obj.get("name")).strip()
    start = _date(obj.get("startDate"))
    if not name or not start:
        return None
    location = obj.get("location")
    if isinstance(location, dict):
        location_name = _text(location.get("name")).strip()
        # A structured address beats scraping a postcode out of prose.
        location_postcode = _postcode(location)
    else:
        location_name = _text(location).strip()
        location_postcode = ""

    return {
        "title": name,
        "description": _text(obj.get("description")).strip()[:400],
        "url": _text(obj.get("url")).strip() or page_url,
        "start_date": start,
        "end_date": _date(obj.get("endDate")) or start,
        "location_name": location_name,
        "location_postcode": location_postcode,
    }
