"""Polite HTTP fetching: robots.txt, per-host rate limiting, honest
User-Agent, and an on-disk cache so re-runs don't hammer the sources."""

import hashlib
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

USER_AGENT = ("daysout-scraper/0.1 "
              "(personal days-out planner; low volume; "
              "https://github.com/andew42/daysout)")

REQUEST_INTERVAL_SECONDS = 1.0
CACHE_TTL_SECONDS = 20 * 60 * 60  # just under a day so daily runs refetch


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

    def get(self, url):
        """Fetch a URL as text, honouring robots.txt, the rate limit and the
        cache. Raises FetchDisallowed / requests exceptions on failure."""
        cache_file = self.cache_dir / hashlib.sha256(url.encode()).hexdigest()
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS:
            return cache_file.read_text(encoding="utf-8")

        if not self._allowed(url):
            raise FetchDisallowed(f"robots.txt disallows {url}")

        self._throttle(url)
        response = self.session.get(url, timeout=60)
        response.raise_for_status()
        cache_file.write_text(response.text, encoding="utf-8")
        return response.text


class FetchDisallowed(Exception):
    pass
