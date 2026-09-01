"""One scrape at a time.

The daily timer fires at 05:30 and a deploy landed at 05:42 while it was
still running: the second scraper waited db.connect's 30 seconds and then
died on "database is locked" inside seed_sources.ensure, before reading a
single source. The Scrape step is continue-on-error, so the deploy went
green with a crashed scrape inside it.

These tests exercise the waiting and the release, but they cannot prove
the thing that actually matters — that one *process* excludes another.
The development sandbox's filesystem does not honour flock across
processes at all (nor lockf): two processes both take the same exclusive
lock happily, while within one process it behaves correctly. So the
cross-process case is checked on the house server by a deploy step, the
same way every other fact about the real world here is.
"""

import os
import tempfile
import unittest

from daysout_scraper import runlock


class TestTheLock(unittest.TestCase):

    def setUp(self):
        handle, path = tempfile.mkstemp()
        os.close(handle)
        self.path = path
        self.addCleanup(os.unlink, path)

    def test_it_is_taken_when_nothing_holds_it(self):
        held = runlock.acquire(self.path)
        self.addCleanup(held.close)
        self.assertFalse(held.closed)

    def test_a_second_scraper_waits_and_then_gives_up(self):
        held = runlock.acquire(self.path)
        self.addCleanup(held.close)

        slept = []
        with self.assertRaises(runlock.Busy):
            runlock.acquire(self.path, wait_seconds=0.01,
                            _sleep=slept.append)
        # It really waited rather than failing on the first attempt.
        self.assertTrue(slept)

    def test_the_lock_is_released_when_the_holder_closes_it(self):
        first = runlock.acquire(self.path)
        first.close()
        second = runlock.acquire(self.path, wait_seconds=0)
        self.addCleanup(second.close)
        self.assertFalse(second.closed)

    def test_waiting_zero_seconds_still_takes_a_free_lock(self):
        held = runlock.acquire(self.path, wait_seconds=0)
        self.addCleanup(held.close)
        self.assertFalse(held.closed)
