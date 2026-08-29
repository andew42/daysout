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

        # Events last so every place of this run is available to link against.
        for event in pending_events:
            events += 1
            destination = source.link_event(event) or \
                name_to_source_id.get(_normalise_name(event.get("location_name", "")))
            if not destination:
                continue
            event["destination_source_id"] = destination
            if dbmod.upsert_event(db, source.name, event):
                linked += 1
        dbmod.purge_stale(db, source.name, run_start)
        db.commit()

        message = f"{places} places, {linked}/{events} events linked"
        log.info("%s: %s", source.name, message)
        dbmod.finish_run(db, run_id, ok=True, message=message)
        return True, message
    except Exception as e:  # noqa: BLE001 — record the failure, don't crash the run
        db.rollback()
        log.exception("%s failed", source.name)
        dbmod.finish_run(db, run_id, ok=False, message=str(e)[:300])
        return False, str(e)
