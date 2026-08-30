"""Browser scanner test against a page that only reveals events after JS.

Skipped where Playwright or a Chromium isn't installed, so the suite still
runs on a machine that hasn't set up browser automation.
"""

import http.server
import sqlite3
import tempfile
import threading
import unittest
from functools import partial

from daysout_scraper import browser
from daysout_scraper.fetch import USER_AGENT, Fetcher
from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.feeds import FeedSource
from schema import SCHEMA

# Nothing in the served HTML; the event is injected after load — the exact
# shape that defeated the plain fetcher on real listing sites.
PAGE = """<!doctype html><html><head><title>Village Fairs</title></head>
<body><div id="listing">Loading…</div><script>
setTimeout(function () {
  var s = document.createElement('script');
  s.type = 'application/ld+json';
  s.textContent = JSON.stringify({
    "@context": "https://schema.org", "@type": "Event",
    "name": "Autumn Craft Fair", "startDate": "2026-09-12",
    "endDate": "2026-09-13",
    "location": {"@type": "Place", "name": "Corsham Town Hall",
                 "address": {"@type": "PostalAddress", "postalCode": "SN13 0HB"}}
  });
  document.head.appendChild(s);
}, 200);
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (b"User-agent: *\nAllow: /\n" if self.path == "/robots.txt"
                else PAGE.encode())
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(browser.available() and browser.find_chromium() is not None,
                     "playwright not installed")
class BrowserSourceTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_reads_events_that_only_exist_after_rendering(self):
        db = sqlite3.connect(":memory:")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO postcodes VALUES ('SN130HB', 51.4333, -2.1833)")
        db.commit()

        url = f"http://127.0.0.1:{self.port}/"
        fetcher = Fetcher(tempfile.mkdtemp())

        # Without a browser the page yields nothing...
        plain = FeedSource((1, "fairs-plain", url, "jsonld", "craft"))
        run_source(db, fetcher, plain)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0,
            "the served HTML should contain no events")

        # ...and with one, the event and its venue both arrive.
        rendered = FeedSource((2, "fairs-browser", url, "browser", "craft"))
        try:
            with browser.Renderer(USER_AGENT) as renderer:
                fetcher.renderer = renderer
                ok, message = run_source(db, fetcher, rendered)
        except browser.BrowserUnavailable as e:
            self.skipTest(f"no usable Chromium: {e}")

        self.assertTrue(ok, message)
        self.assertEqual(
            db.execute("SELECT title, category FROM events").fetchone(),
            ("Autumn Craft Fair", "craft"))
        self.assertEqual(
            db.execute("SELECT name, postcode FROM destinations").fetchone(),
            ("Corsham Town Hall", "SN13 0HB"))


if __name__ == "__main__":
    unittest.main()
