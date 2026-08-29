"""Runs sources against the shared database: upsert everything the source
reports, link events to destinations, then age out rows it stopped
reporting. Every run is recorded in scrape_runs for the UI status footer."""

import logging
import re

from . import db as dbmod

log = logging.getLogger(__name__)


def _normalise_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def run_source(db, fetcher, source, max_pages=0):
    """Returns (ok, message). Never raises: failures are recorded."""
    run_id = dbmod.start_run(db, source.name)
    run_start = dbmod.now()
    places = events = linked = 0
    name_to_source_id = {}

    try:
        pending_events = []
        for kind, item in source.scrape(fetcher, max_pages=max_pages):
            if kind == "place":
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
            message = ("no places found (source unreachable, blocked, or its "
                       "patterns/queries are wrong); nothing purged")
            log.warning("%s: %s", source.name, message)
            dbmod.finish_run(db, run_id, ok=False, message=message)
            return False, message

        # Events last so every place of this run is available to link against.
        for event in pending_events:
            events += 1
            destination = source.link_event(event) or \
                name_to_source_id.get(_normalise_name(event.get("location_name", "")))
            if not destination:
                # An event from a listing site names a venue we may never
                # have seen. Create it from its postcode so the event has a
                # location and can be sorted by distance.
                destination = dbmod.ensure_venue(
                    db, source.name, event.get("location_name", ""),
                    event.get("venue_postcode", ""),
                    event.get("category") or "venue")
            if not destination:
                continue
            event["destination_source_id"] = destination
            if dbmod.upsert_event(db, source.name, event):
                linked += 1

        # Only a complete crawl knows what no longer exists. A bounded run
        # (--max-pages, used for verification) has not looked at the rest of
        # the source, so purging would delete rows that are still fine.
        if max_pages:
            message = f"{places} places, {linked}/{events} events linked (partial run, nothing purged)"
        else:
            dbmod.purge_stale(db, source.name, run_start)
            message = f"{places} places, {linked}/{events} events linked"
        db.commit()
        log.info("%s: %s", source.name, message)
        dbmod.finish_run(db, run_id, ok=True, message=message)
        return True, message
    except Exception as e:  # noqa: BLE001 — record the failure, don't crash the run
        db.rollback()
        log.exception("%s failed", source.name)
        dbmod.finish_run(db, run_id, ok=False, message=str(e)[:300])
        return False, str(e)
