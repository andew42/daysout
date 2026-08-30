"""Dates read out of a URL.

Some sites put the date in the address and nothing structured on the page,
which makes the URL the most reliable thing about the event: chosen by the
site, unchanged by a restyle, and already in the sitemap.
"""

import unittest
from datetime import date

from daysout_scraper import slugdate

TODAY = date(2026, 8, 30)


class TestParse(unittest.TestCase):

    def check(self, url, start, end=None):
        self.assertEqual(slugdate.parse(url, today=TODAY), (start, end or start),
                         url)

    def test_iso_dates(self):
        self.check("https://x.org/whats-on/evening-airshow-2026-09-15",
                   "2026-09-15")

    def test_day_and_month_with_a_year(self):
        self.check("https://x.org/whats-on/airshow-15-september-2026",
                   "2026-09-15")
        self.check("https://x.org/whats-on/airshow-15th-sept-2026",
                   "2026-09-15")

    def test_month_then_day(self):
        self.check("https://x.org/events/september-15-2026-race-day",
                   "2026-09-15")

    def test_a_range(self):
        self.check("https://x.org/whats-on/joust-29-to-31-august-2026",
                   "2026-08-29", "2026-08-31")
        self.check("https://x.org/whats-on/fair-5-6-september-2026",
                   "2026-09-05", "2026-09-06")

    def test_a_slug_without_a_year_takes_the_next_occurrence(self):
        # Just ahead of today: this year.
        self.check("https://x.org/whats-on/airshow-15-september", "2026-09-15")
        # Well behind today: next year, because it has been and gone.
        self.check("https://x.org/whats-on/snowdrops-10-february", "2027-02-10")

    def test_a_recently_past_date_is_not_pushed_a_year_out(self):
        # Three weeks ago. Saying "next August" would be a lie.
        self.check("https://x.org/whats-on/airshow-9-august", "2026-08-09")

    def test_urls_with_no_date_yield_nothing(self):
        for url in ("https://x.org/whats-on/",
                    "https://x.org/visit/tickets-and-prices",
                    "https://x.org/collection/aircraft-hall-2"):
            self.assertIsNone(slugdate.parse(url, today=TODAY), url)

    def test_an_impossible_date_is_refused(self):
        self.assertIsNone(
            slugdate.parse("https://x.org/e/thing-2026-02-31", today=TODAY))


class TestTitle(unittest.TestCase):

    def test_the_date_is_dropped_from_the_title(self):
        self.assertEqual(
            slugdate.title_from("https://x.org/whats-on/evening-airshow-15-september-2026"),
            "Evening Airshow")

    def test_a_range_is_dropped_too(self):
        self.assertEqual(
            slugdate.title_from("https://x.org/whats-on/joust-29-to-31-august-2026"),
            "Joust")
