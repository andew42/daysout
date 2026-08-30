"""A candidate dropped for good must actually leave the database.

Deleting a row from CANDIDATES is not enough: ensure() only ever inserts,
so an old row sits in the table for ever, spending requests on every
scrape and reporting the same failure.
"""

import sqlite3
import unittest

from daysout_scraper.sources import seed_sources

from schema import SCHEMA


class TestRetired(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def add(self, name):
        self.db.execute(
            "INSERT INTO sources (name, url, kind, category, enabled, notes,"
            " added) VALUES (?, 'https://x.example/', 'auto', 'art', 1, '',"
            " '2026-01-01')", (name,))
        self.db.commit()

    def names(self):
        return {row[0] for row in self.db.execute("SELECT name FROM sources")}

    def test_a_retired_candidate_is_deleted_from_an_existing_database(self):
        for name, _ in seed_sources.RETIRED:
            self.add(name)
        seed_sources.ensure(self.db)
        for name, _ in seed_sources.RETIRED:
            self.assertNotIn(name, self.names(), name)

    def test_it_is_not_seeded_back(self):
        seed_sources.ensure(self.db)
        seed_sources.ensure(self.db)
        for name, _ in seed_sources.RETIRED:
            self.assertNotIn(name, self.names(), name)

    def test_its_events_go_with_it(self):
        name = seed_sources.RETIRED[0][0]
        self.add(name)
        self.db.execute(
            "INSERT INTO destinations (name, category, lat, lon, source,"
            " source_id, first_seen, last_seen) VALUES ('A venue', 'art',"
            " 51.0, -2.0, ?, 'v', '2026-01-01', '2026-01-01')", (name,))
        destination = self.db.execute(
            "SELECT id FROM destinations WHERE source = ?", (name,)).fetchone()[0]
        self.db.execute(
            "INSERT INTO events (destination_id, title, start_date, end_date,"
            " source, source_id, last_seen) VALUES (?, 'Open house',"
            " '2026-09-05', '2026-09-05', ?, 'e', '2026-01-01')",
            (destination, name))
        self.db.commit()

        seed_sources.ensure(self.db)
        for table in ("events", "destinations"):
            left = self.db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE source = ?", (name,)).fetchone()[0]
            self.assertEqual(left, 0, f"{table} left behind")

    def test_a_retired_name_is_not_still_a_candidate(self):
        retired = {name for name, _ in seed_sources.RETIRED}
        candidates = {row[0] for row in seed_sources.CANDIDATES}
        self.assertEqual(retired & candidates, set(),
                         "a retired source must not also be seeded")
