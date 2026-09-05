"""Rows left behind by a source that no longer exists.

`purge_stale` only removes what a *running* source stopped reporting, so
deleting a source outright leaves its events and venues in the database
with nothing to refresh them and nothing to take them away. The house
server was still serving events from sources retired days earlier, and
still listing their scrape_runs in /api/status as though they were
sources.

This is the one purge that deletes on the strength of code rather than of
a run, so what it must *not* touch matters as much as what it removes.
"""

import sqlite3
import unittest

from daysout_scraper import db as dbmod

from schema import SCHEMA

KNOWN = ["english_heritage", "waddesdon"]


class TestPurgingUnknownSources(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def add(self, source, venue="A venue", event="An event"):
        self.db.execute(
            "INSERT INTO destinations (name, category, lat, lon, source,"
            " source_id, first_seen, last_seen) VALUES (?, 'garden', 51.0,"
            " -2.0, ?, ?, '2026-01-01', '2026-01-01')",
            (venue, source, f"{source}-venue"))
        destination = self.db.execute(
            "SELECT id FROM destinations WHERE source = ? ORDER BY id DESC",
            (source,)).fetchone()[0]
        if event:
            self.db.execute(
                "INSERT INTO events (destination_id, title, start_date,"
                " end_date, source, source_id, last_seen) VALUES (?, ?,"
                " '2026-09-05', '2026-09-05', ?, ?, '2026-01-01')",
                (destination, event, source, f"{source}-e"))
        self.db.execute(
            "INSERT INTO scrape_runs (source, started_at, ok, message)"
            " VALUES (?, '2026-01-01', 1, 'done')", (source,))
        self.db.commit()
        return destination

    def counts(self, source):
        return (
            self.db.execute("SELECT COUNT(*) FROM events WHERE source = ?",
                            (source,)).fetchone()[0],
            self.db.execute("SELECT COUNT(*) FROM destinations WHERE source = ?",
                            (source,)).fetchone()[0],
            self.db.execute("SELECT COUNT(*) FROM scrape_runs WHERE source = ?",
                            (source,)).fetchone()[0],
        )

    def test_a_source_that_no_longer_exists_is_removed_entirely(self):
        self.add("national_trust")
        removed = dbmod.purge_unknown_sources(self.db, KNOWN)
        self.assertEqual(removed, (1, 1, 1))
        self.assertEqual(self.counts("national_trust"), (0, 0, 0))

    def test_a_source_that_still_exists_is_left_alone(self):
        self.add("waddesdon")
        dbmod.purge_unknown_sources(self.db, KNOWN)
        self.assertEqual(self.counts("waddesdon"), (1, 1, 1))

    def test_the_demo_seed_is_not_an_unknown_source(self):
        # It has its own purge, which waits until a real source has data;
        # removing it here would empty a fresh database before its first
        # scrape finished.
        self.add("seed")
        dbmod.purge_unknown_sources(self.db, KNOWN)
        self.assertEqual(self.counts("seed"), (1, 1, 1))

    def test_history_alone_is_enough_to_be_purged(self):
        # A source may leave nothing but scrape_runs, which /api/status
        # was reporting as though it were still a source.
        self.db.execute(
            "INSERT INTO scrape_runs (source, started_at, ok, message)"
            " VALUES ('ngs-find-a-garden', '2026-01-01', 0, 'no places found')")
        self.db.commit()
        self.assertEqual(dbmod.purge_unknown_sources(self.db, KNOWN), (1, 0, 0))
        self.assertEqual(self.counts("ngs-find-a-garden"), (0, 0, 0))

    def test_a_venue_another_source_is_using_survives(self):
        # Destinations cascade to their events, so deleting a venue a
        # living source still has events at would take those with it.
        destination = self.add("iacf-newark", venue="Newark Showground")
        self.db.execute(
            "INSERT INTO events (destination_id, title, start_date, end_date,"
            " source, source_id, last_seen) VALUES (?, 'A fair we still read',"
            " '2026-10-15', '2026-10-15', 'waddesdon', 'w-1', '2026-01-01')",
            (destination,))
        self.db.commit()

        dbmod.purge_unknown_sources(self.db, KNOWN)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0], 1,
            "the venue is still in use and must stay")
        self.assertEqual(
            self.db.execute("SELECT title FROM events").fetchall(),
            [("A fair we still read",)])

    def test_nothing_to_do_is_not_a_change(self):
        self.add("english_heritage")
        self.assertEqual(dbmod.purge_unknown_sources(self.db, KNOWN), (0, 0, 0))

    def test_every_source_at_once(self):
        for name in ["national_trust", "iacf-newark", "stonor-whats-on"]:
            self.add(name)
        sources, events, destinations = dbmod.purge_unknown_sources(self.db, KNOWN)
        self.assertEqual((sources, events, destinations), (3, 3, 3))
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
