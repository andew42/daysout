"""Scraper entry point.

    python -m daysout_scraper [--db PATH] [--sources a,b] [--max-pages N]

Run periodically (systemd timer — see packaging/) to keep the destinations
and events tables fresh. Safe to run while the server is up: both sides use
WAL mode. Demo seed rows are removed once any real source has data.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from . import browser
from . import db as dbmod
from . import runlock
from . import sources
from .fetch import USER_AGENT, Fetcher
from .pipeline import run_source

log = logging.getLogger(__name__)


def default_db():
    data = os.environ.get("DAYSOUT_DATA")
    if not data:
        base = os.environ.get("DAYSOUT")
        data = base + "/data" if base else "data"
    return str(Path(data) / "daysout.db")


def main():
    parser = argparse.ArgumentParser(prog="daysout_scraper", description=__doc__)
    parser.add_argument("--db", default=default_db(), help="path to daysout.db")
    parser.add_argument("--cache", default="", help="page cache dir (default: beside the db)")
    parser.add_argument("--sources", default="",
                        help="comma-separated source names (default: all implemented)")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="limit pages per source — use for a first verification run")
    parser.add_argument("--keep-seed", action="store_true",
                        help="don't remove demo seed rows after a successful run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not Path(args.db).exists():
        sys.exit(f"database {args.db} not found — start the server once to create it")

    # One scrape at a time: the pipeline holds a write transaction for the
    # whole of a source's crawl, so a second scraper dies on "database is
    # locked" rather than merely waiting. Held until the process exits.
    try:
        lock = runlock.acquire(args.db + ".lock")  # noqa: F841 — held by reference
    except runlock.Busy as e:
        sys.exit(f"not scraping: {e}")

    db = dbmod.connect(args.db)
    fetcher = Fetcher(args.cache or str(Path(args.db).parent / "scrape-cache"))

    # Every source is written in code. There was a `sources` table too,
    # and a generic engine that turned a row into a runnable source, so a
    # new listing site was an INSERT rather than a release. It did not
    # earn its keep: the sites differ so much that reading one takes a
    # parser written against it, and rows added blind mostly reported an
    # empty site for ever.
    wanted = args.sources.split(",") if args.sources else []
    selected = [s() for s in sources.IMPLEMENTED if not wanted or s.name in wanted]
    if not selected:
        available = [s.name for s in sources.IMPLEMENTED]
        sys.exit(f"no matching sources; available: {', '.join(available)}")

    # Rendering costs a browser launch, so start one only if a source in
    # this run actually asks for it, and share it across them all.
    browser_sources = [s for s in selected if getattr(s, "kind", "") == "browser"]
    any_ok = False

    def run_all(sources_to_run):
        ok_any = False
        for source in sources_to_run:
            ok, _ = run_source(db, fetcher, source, max_pages=args.max_pages)
            ok_any = ok_any or ok
        return ok_any

    if browser_sources and browser.available():
        try:
            with browser.Renderer(USER_AGENT) as renderer:
                fetcher.renderer = renderer
                any_ok = run_all(selected)
        except browser.BrowserUnavailable as e:
            # No usable browser: run everything else rather than losing the
            # whole scrape to an optional feature.
            log.warning("skipping %d browser source(s): %s",
                        len(browser_sources), e)
            any_ok = run_all([s for s in selected if s not in browser_sources])
    elif browser_sources:
        # Skip them outright rather than letting each one record a failed
        # run saying the same thing.
        log.warning(
            "skipping %d browser source(s): playwright is not installed "
            "(pip install playwright && python3 -m playwright install chromium)",
            len(browser_sources))
        any_ok = run_all([s for s in selected if s not in browser_sources])
    else:
        any_ok = run_all(selected)

    if any_ok and not args.keep_seed:
        dbmod.purge_seed(db)
        db.commit()

    # A source that is deleted outright leaves its rows behind: purge_stale
    # only removes what a *running* source stopped reporting. Done here
    # rather than in the server because this is where the list of sources
    # actually is, and only for a run that read all of them — one asked for
    # a single source knows nothing about the rest.
    if any_ok and not wanted and not args.max_pages:
        dbmod.purge_unknown_sources(db, [s.name for s in sources.IMPLEMENTED])
        db.commit()
    db.close()
    sys.exit(0 if any_ok else 1)


if __name__ == "__main__":
    main()
