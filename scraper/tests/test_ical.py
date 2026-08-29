"""iCal reader tests, including the fold and exclusive-end-date rules."""

import unittest

from daysout_scraper import ical

FEED = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:joust-2026@example.org
SUMMARY:Legendary Joust
DTSTART;VALUE=DATE:20260829
DTEND;VALUE=DATE:20260901
LOCATION:Bolsover Castle\\, Castle Street
DESCRIPTION:Knights compete\\nAll weekend
URL:https://example.org/joust
END:VEVENT
BEGIN:VEVENT
UID:talk-2026@example.org
SUMMARY:A very long title that the publisher has wrapped across
  two lines in the feed
DTSTART:20260905T190000Z
DTEND:20260905T203000Z
LOCATION:Village Hall
END:VEVENT
BEGIN:VEVENT
SUMMARY:Broken event with no start date
END:VEVENT
END:VCALENDAR
"""


class ICalTest(unittest.TestCase):

    def setUp(self):
        self.events = list(ical.parse(FEED))

    def test_reads_events_and_skips_incomplete_ones(self):
        self.assertEqual(len(self.events), 2)

    def test_all_day_end_date_is_inclusive(self):
        # DTEND 20260901 on an all-day event means it finishes on 31 Aug.
        joust = self.events[0]
        self.assertEqual(joust["start_date"], "2026-08-29")
        self.assertEqual(joust["end_date"], "2026-08-31")

    def test_unescapes_text_and_reads_location(self):
        joust = self.events[0]
        self.assertEqual(joust["title"], "Legendary Joust")
        self.assertEqual(joust["location_name"], "Bolsover Castle, Castle Street")
        self.assertIn("\n", joust["description"])
        self.assertEqual(joust["url"], "https://example.org/joust")

    def test_unfolds_wrapped_lines(self):
        talk = self.events[1]
        self.assertEqual(
            talk["title"],
            "A very long title that the publisher has wrapped across two lines in the feed")

    def test_timed_event_dates(self):
        talk = self.events[1]
        self.assertEqual(talk["start_date"], "2026-09-05")
        self.assertEqual(talk["end_date"], "2026-09-05")


if __name__ == "__main__":
    unittest.main()
