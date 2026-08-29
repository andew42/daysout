"""Polite HTTP fetching: robots.txt, per-host rate limiting, honest
User-Agent, and an on-disk cache so re-runs don't hammer the sources."""

import hashlib
import logging
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = ("daysout-scraper/0.1 "
              "(personal days-out planner; low volume; "
              "https://github.com/andew42/daysout)")

REQUEST_INTERVAL_SECONDS = 1.0
CACHE_TTL_SECONDS = 20 * 60 * 60  # just under a day so daily runs refetch

# Transient server-side conditions worth waiting out (never 4xx except 429:
# those mean the request itself is wrong, and retrying just adds load).
# A site that hasn't answered in half a minute isn't going to; a source
# probe that waits a full minute three times over drags out every run.
TIMEOUT_SECONDS = 30

RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5


class Fetcher:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._robots = {}
        self._last_request = {}

    def _allowed(self, url):
        host = urlparse(url).netloc
        if host not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                response = self.session.get(f"https://{host}/robots.txt", timeout=30)
                parser.parse(response.text.splitlines() if response.ok else [])
            except requests.RequestException:
                parser.parse([])
            self._robots[host] = parser
        return self._robots[host].can_fetch(USER_AGENT, url)

    def _throttle(self, url):
        host = urlparse(url).netloc
        elapsed = time.monotonic() - self._last_request.get(host, 0)
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request[host] = time.monotonic()

    def get(self, url, api=False):
        """Fetch a URL as text, honouring robots.txt, the rate limit and the
        cache. Raises FetchDisallowed / requests exceptions on failure.

        api=True is for a documented API endpoint the operator publishes for
        programmatic use. robots.txt governs crawling a site's pages — a
        query endpoint is commonly disallowed there precisely so crawlers
        don't wander through infinite generated URLs, which says nothing
        about a client calling it as the API it is. Rate limiting, the
        honest User-Agent and the cache still apply, so we stay a
        well-behaved client either way. Never set this to get past a site
        that is refusing us (see sources/national_trust.py).
        """
        cache_file = self.cache_dir / hashlib.sha256(url.encode()).hexdigest()
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS:
            return cache_file.read_text(encoding="utf-8")

        if not api and not self._allowed(url):
            raise FetchDisallowed(f"robots.txt disallows {url}")

        # Busy or rate-limited is a "come back shortly", not a failure: a
        # shared query service returning 502 for one request is routine and
        # shouldn't lose a whole category for the day.
        for attempt in range(RETRY_ATTEMPTS):
            self._throttle(url)
            response = self.session.get(url, timeout=TIMEOUT_SECONDS)
            if response.status_code not in RETRY_STATUS or attempt == RETRY_ATTEMPTS - 1:
                break
            delay = RETRY_BACKOFF_SECONDS * (2 ** attempt)
            log.info("%s returned %d, retrying in %.0fs",
                     urlparse(url).netloc, response.status_code, delay)
            time.sleep(delay)

        response.raise_for_status()
        cache_file.write_text(response.text, encoding="utf-8")
        return response.text


class FetchDisallowed(Exception):
    pass
