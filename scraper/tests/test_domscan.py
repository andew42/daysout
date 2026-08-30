"""The DOM diagnostic has to tell the two failure modes apart.

A listing site that publishes no Event JSON-LD is either worth a
hand-written parser (the dates are in the markup) or a dead end (the page
is a shell). Getting that verdict wrong costs either a wasted parser or a
source thrown away that had data in it, so pin both cases.
"""

import unittest

from daysout_scraper import domscan

LISTING = """
<html><head><title>Gardens open this week</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}
</script></head>
<body>
  <ul class="garden-list">
    <li><a href="/find-a-garden/the-old-rectory/">The Old Rectory</a>
        <time datetime="2026-09-06">Saturday 6 September</time>
        <span class="opening-dates">6 September 2026, 2pm-5pm</span></li>
    <li><a href="/find-a-garden/hill-house/">Hill House</a>
        <time datetime="2026-09-07">Sunday 7 September</time></li>
  </ul>
</body></html>
"""

SHELL = """
<html><head><title>Gardens open this week</title></head>
<body><div id="root"></div><script src="/app.js"></script></body></html>
"""

EVENT_PAGE = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event","name":"Joust",
 "startDate":"2026-09-06","location":{"@type":"Place","name":"Bolsover Castle"}}
</script></body></html>
"""


class TestScan(unittest.TestCase):
    def test_reads_the_elements_a_parser_would_target(self):
        report = domscan.scan(LISTING, "https://example.org/open-this-week/")
        self.assertEqual(report["event_objects"], 0)
        self.assertIn("BreadcrumbList", report["jsonld_types"])
        self.assertEqual([t[0] for t in report["times"]],
                         ["2026-09-06", "2026-09-07"])
        self.assertTrue(any("opening-dates" in element[1]
                            for element in report["date_elements"]))
        self.assertTrue(report["date_text"])
        self.assertEqual([link[0] for link in report["event_links"]],
                         ["/find-a-garden/the-old-rectory/",
                          "/find-a-garden/hill-house/"])

    def test_shell_page_yields_nothing(self):
        report = domscan.scan(SHELL, "https://example.org/open-this-week/")
        self.assertEqual(report["times"], [])
        self.assertEqual(report["date_text"], [])
        self.assertEqual(report["event_links"], [])

    def test_describe_is_printable_for_both(self):
        for html in (LISTING, SHELL):
            text = domscan.describe(domscan.scan(html, "https://example.org/"))
            self.assertIn("JSON-LD types:", text)
            self.assertIn("date-looking text", text)


class TestVerdict(unittest.TestCase):
    def scan(self, html):
        return domscan.scan(html, "https://example.org/x")

    def test_structured_events_need_no_parser(self):
        self.assertIn("no DOM parser needed",
                      domscan.verdict(self.scan(EVENT_PAGE)))

    def test_dates_in_elements_are_worth_a_parser(self):
        self.assertIn("hand-written", domscan.verdict(self.scan(LISTING)))

    def test_rendering_that_changes_nothing_is_a_dead_end(self):
        plain = self.scan(SHELL)
        self.assertIn("disable the source", domscan.verdict(plain, plain))

    def test_rendering_that_fills_the_page_is_not_called_a_dead_end(self):
        verdict = domscan.verdict(self.scan(SHELL), self.scan(LISTING))
        self.assertIn("hand-written", verdict)
