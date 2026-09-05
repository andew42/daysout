"""Runs sources against the shared database: upsert everything the source
reports, link events to destinations, then age out rows it stopped
reporting. Every run is recorded in scrape_runs for the UI status footer."""

import logging
import re

from . import db as dbmod
from . import postcode as postcodemod

log = logging.getLogger(__name__)


def _normalise_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _venue(event):
    """Where an event happens: (display name, postcode, label to create by).

    Sources disagree on shape and the disagreement was losing events. A
    feed row hands over a trimmed name and a 'venue_postcode'; a source
    written in code yields the raw JSON-LD fields, so its postcode arrives
    as 'location_postcode' and its location name is the whole address line
    ("Manchester Central Library, St Peters Square, Manchester M2 5PD").
    Read both spellings, take the first comma-separated part as the name,
    and fall back to digging the postcode out of the address prose.

    Some sites publish an address with no venue name at all — RHS gives
    every flower show a postalCode and no location.name — so when there is
    a postcode but nothing to call the place, the event's own title is the
    label. It is a name of convenience rather than a real venue name, but
    a show pinned at the right postcode is what the map is for; the
    alternative was dropping five flower shows over a missing field.
    """

    full = event.get("venue_full") or event.get("location_name") or ""
    name = full.split(",")[0].strip()
    postcode = (event.get("venue_postcode")
                or event.get("location_postcode")
                or postcodemod.find(full, event.get("description", "")))
    label = name or (event.get("title", "").strip() if postcode else "")
    return name, postcode, label


def run_source(db, fetcher, source, max_pages=0):
    """Returns (ok, message). Never raises: failures are recorded."""
    run_id = dbmod.start_run(db, source.name)
    run_start = dbmod.now()
    places = events = linked = 0
    venues = set()
    name_to_source_id = {}

    try:
        pending_events = []
        unplaced = []
        unlocated = []
        for kind, item in source.scrape(fetcher, max_pages=max_pages):
            if kind == "place":
                # A source may publish an address without coordinates, which
                # every source until now happened to carry. Geocode from the
                # postcode as event venues already are; a place with neither
                # cannot be sorted by distance, so it would be invisible.
                if "lat" not in item:
                    coordinates = dbmod.geocode(db, item.get("postcode", ""))
                    if not coordinates:
                        unlocated.append(
                            f"{item.get('name', '?')} "
                            f"({item.get('postcode') or 'no postcode'})")
                        continue
                    item["lat"], item["lon"] = coordinates
                dbmod.upsert_destination(db, source.name, item)
                name_to_source_id[_normalise_name(item["name"])] = item["source_id"]
                places += 1
            else:
                pending_events.append(item)
        db.commit()

        # A feed source contributes events and their venues rather than a
        # catalogue of places, so "no places" is normal for it.
        if places == 0 and pending_events:
            pass
        # A run that found no places at all means the sitemap was unreachable
        # or the URL patterns no longer match — never a genuinely empty
        # source. Purging on that would wipe good data on a network blip.
        elif places == 0:
            # A source that knows why it found nothing says so: "no places
            # found" alone cannot tell a site refusing us apart from URL
            # patterns that no longer match, and confusing the two has
            # cost real time.
            note = getattr(source, "failure_note", "")
            message = (f"nothing found — {note}; nothing purged" if note else
                       "no places found (source unreachable, blocked, or its "
                       "patterns/queries are wrong); nothing purged")
            log.warning("%s: %s", source.name, message)
            dbmod.finish_run(db, run_id, ok=False, message=message)
            return False, message

        # Events last so every place of this run is available to link against.
        for event in pending_events:
            events += 1
            venue_name, venue_postcode, venue_label = _venue(event)

            # Where does this event happen? In order of confidence: the
            # source says so, a place from this run matches by name, a
            # destination we already hold matches by name (an event listing
            # rarely repeats the postcode of a place someone else catalogued),
            # or we create the venue from its own postcode.
            key = source.link_event(event) or \
                name_to_source_id.get(_normalise_name(venue_name))
            destination_id = dbmod.find_destination_id(db, source.name, key) if key else None

            if destination_id is None:
                destination_id = dbmod.find_destination_id_by_name(db, venue_name)

            if destination_id is None:
                # Matching by name uses only a name the site actually
                # published; the title fallback is for creating a venue,
                # never for claiming an event belongs to a place we hold.
                created = dbmod.ensure_venue(
                    db, source.name, venue_label, venue_postcode,
                    event.get("category") or "venue", event.get("url", ""),
                    event.get("location_places") or ())
                if created:
                    destination_id = dbmod.find_destination_id(db, source.name, created)

            if destination_id is None:
                # Record what we couldn't place and why: an event with no
                # venue at all is a different problem from one naming a
                # venue we don't hold, and the counts alone can't tell them
                # apart.
                unplaced.append(
                    f"{event.get('title', '?')[:40]!r} @ "
                    f"{venue_name or '(no venue named)'} "
                    f"{'postcode ' + venue_postcode if venue_postcode else '(no postcode)'}")
                continue
            dbmod.touch_destination(db, destination_id, source.name)
            # Every event, not just ones that create their venue: the
            # venues that need a link are the ones we already hold.
            dbmod.backfill_venue_url(db, destination_id, event.get("url", ""))
            if dbmod.upsert_event(db, source.name, event, destination_id):
                linked += 1
                venues.add(destination_id)

        # Only a complete crawl knows what no longer exists. A bounded run
        # (--max-pages, used for verification) has not looked at the rest of
        # the source, so purging would delete rows that are still fine.
        # A feed source catalogues no places — its venues come from the
        # events — so leading with "0 places" reported a success as though
        # it were a failure. Say what it actually did instead.
        if places:
            counts = f"{places} places, {linked}/{events} events linked"
        else:
            venue_word = "venue" if len(venues) == 1 else "venues"
            counts = f"{linked}/{events} events linked at {len(venues)} {venue_word}"

        if max_pages:
            message = f"{counts} (partial run, nothing purged)"
        else:
            dbmod.purge_stale(db, source.name, run_start)
            message = counts
        db.commit()
        log.info("%s: %s", source.name, message)
        for description in unplaced[:10]:
            log.info("%s: could not place %s", source.name, description)
        if unlocated:
            log.info("%s: %d place(s) skipped with no geocodable postcode: %s",
                     source.name, len(unlocated), "; ".join(unlocated[:5]))
        dbmod.finish_run(db, run_id, ok=True, message=message)
        return True, message
    except Exception as e:  # noqa: BLE001 — record the failure, don't crash the run
        db.rollback()
        log.exception("%s failed", source.name)
        dbmod.finish_run(db, run_id, ok=False, message=str(e)[:300])
        return False, str(e)
