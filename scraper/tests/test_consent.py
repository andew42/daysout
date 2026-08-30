"""Rendering past a cookie banner and a lazy listing.

Both came from the real thing. A National Garden Scheme page rendered to
250 KB of which 130 KB was Cookiebot's own cookie tables and none was
gardens — that is what a consent manager holding back the page's scripts
looks like. And waiting a fixed moment after load never sees a listing
that arrives as you scroll.

A consent banner governs cookies, not access: answering one is what every
visitor does. This declines where a decline button exists.
"""

import http.server
import tempfile
import threading
import unittest

from daysout_scraper import browser
from daysout_scraper.fetch import USER_AGENT, Fetcher

# The listing only appears once consent is answered — the shape that
# defeated the renderer on the real site.
BEHIND_CONSENT = """<!doctype html><html><head><title>Gardens</title></head>
<body>
  <div id="banner">
    <p>We use cookies</p>
    <button id="CybotCookiebotDialogBodyButtonDecline">Decline</button>
    <button id="CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll">Allow all</button>
  </div>
  <div id="listing">Loading…</div>
  <script>
    document.querySelectorAll('#banner button').forEach(function (b) {
      b.addEventListener('click', function () {
        document.getElementById('banner').remove();
        document.getElementById('listing').textContent =
          'The Old Rectory, open Saturday 5 September';
      });
    });
  </script>
</body></html>"""

# Rows arrive only as the page is scrolled.
LAZY = """<!doctype html><html><head><title>More gardens</title></head>
<body><div id="rows">start</div><script>
  window.addEventListener('scroll', function () {
    var rows = document.getElementById('rows');
    if (rows.dataset.done) return;
    rows.dataset.done = '1';
    rows.textContent = 'Hill House, open Sunday 6 September';
  });
  document.body.style.height = '4000px';
</script></body></html>"""

PAGES = {"/consent": BEHIND_CONSENT, "/lazy": LAZY}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
        else:
            body = PAGES.get(self.path, "<html></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(browser.available() and browser.find_chromium() is not None,
                     "playwright not installed")
class RendererTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def render(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        fetcher = Fetcher(tempfile.mkdtemp())
        with browser.Renderer(USER_AGENT) as renderer:
            fetcher.renderer = renderer
            return fetcher.get(url, render=True)

    def test_a_listing_behind_a_cookie_banner_is_reached(self):
        html = self.render("/consent")
        self.assertIn("The Old Rectory", html)
        self.assertNotIn("We use cookies", html)

    def test_a_listing_that_needs_scrolling_is_reached(self):
        self.assertIn("Hill House", self.render("/lazy"))


@unittest.skipUnless(browser.available() and browser.find_chromium() is not None,
                     "playwright not installed")
class FreshFetchTest(unittest.TestCase):
    """A cached copy cannot show whether a renderer change worked."""

    def test_fresh_skips_the_cache(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)

        url = f"http://127.0.0.1:{server.server_address[1]}/lazy"
        fetcher = Fetcher(tempfile.mkdtemp())
        first = fetcher.get(url)
        # Poison the cache: an ordinary read returns it, a fresh one does not.
        import hashlib
        cache_file = fetcher.cache_dir / hashlib.sha256(url.encode()).hexdigest()
        cache_file.write_text("STALE", encoding="utf-8")

        self.assertEqual(fetcher.get(url), "STALE")
        self.assertEqual(fetcher.get(url, fresh=True), first)
