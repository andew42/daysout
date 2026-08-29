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

from . import db as dbmod
from . import sources
from .fetch import Fetcher
from .pipeline import run_source
from .sources import feeds, seed_sources


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

    db = dbmod.connect(args.db)
    fetcher = Fetcher(args.cache or str(Path(args.db).parent / "scrape-cache"))

    # Sources written in code, plus every enabled row of the sources table.
    seed_sources.ensure(db)
    wanted = args.sources.split(",") if args.sources else []
    selected = [s() for s in sources.IMPLEMENTED if not wanted or s.name in wanted]
    selected += [s for s in feeds.load_enabled(db) if not wanted or s.name in wanted]
    if not selected:
        available = [s.name for s in sources.IMPLEMENTED] + \
                    [s.name for s in feeds.load_enabled(db)]
        sys.exit(f"no matching sources; available: {', '.join(available)}")

    any_ok = False
    for source in selected:
        ok, _ = run_source(db, fetcher, source, max_pages=args.max_pages)
        any_ok = any_ok or ok

    if any_ok and not args.keep_seed:
        dbmod.purge_seed(db)
        db.commit()
    db.close()
    sys.exit(0 if any_ok else 1)


if __name__ == "__main__":
    main()
