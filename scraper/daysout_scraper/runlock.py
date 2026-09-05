"""One scrape at a time.

Two scrapers cannot share this database. The pipeline holds a write
transaction for the whole of a source's crawl — upsert_destination runs
inside the loop and the commit comes after the generator is exhausted —
so a source with a few hundred pages holds the lock for minutes. SQLite
lets the second writer wait, but only for db.connect's 30 seconds, and
then the run dies on "database is locked" partway through.

Measured on the house server: the daily timer fires at 05:30, a deploy
landed at 05:42 while it was still going, and the deploy's scrape died on
its first write before reading a single source. The Scrape step is
continue-on-error, so the deploy went green with a crashed scrape inside
it and the database kept the previous day's rows.

Two scrapers running at once is never what anyone wants: they would fetch
the same pages twice and their end-of-run stale purges would race. So
take an exclusive lock and wait for it. Waiting rather than refusing
outright is what the Update button needs — press it during the nightly
run and it should do the work a moment later, not report that it will
not. If the wait runs out, say so plainly and stop: the other run is
doing the same job anyway.
"""

import errno
import fcntl
import logging
import time

log = logging.getLogger(__name__)

# Long enough to outlast a slow source, short enough that a stuck run does
# not hold a deploy open for ever. A full crawl is ~10 minutes.
DEFAULT_WAIT_SECONDS = 900

POLL_SECONDS = 2.0

# Note for anyone testing this: the development sandbox does not honour
# flock between processes — two of them take the same exclusive lock and
# neither waits — while within one process it works. So a green test here
# says nothing about the case that matters, and the deploy checks it on
# the house server instead.


class Busy(Exception):
    """Another scrape holds the lock and did not release it in time."""


def acquire(path, wait_seconds=DEFAULT_WAIT_SECONDS, _sleep=time.sleep):
    """An exclusive lock on `path`, waiting for it. Raises Busy on timeout.

    Returns the open file, which the caller must keep referenced: closing
    it releases the lock, and so does the process exiting, which is what
    makes this safe against a scraper that crashes without cleaning up.
    """

    handle = open(path, "a+")
    deadline = time.monotonic() + max(wait_seconds, 0)
    announced = False

    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError as e:
            if e.errno not in (errno.EACCES, errno.EAGAIN):
                handle.close()
                raise
        if not announced:
            log.info("another scrape is running; waiting up to %ds for it",
                     int(wait_seconds))
            announced = True
        if time.monotonic() >= deadline:
            handle.close()
            raise Busy(
                f"another scrape held {path} for more than {int(wait_seconds)}s")
        _sleep(POLL_SECONDS)
