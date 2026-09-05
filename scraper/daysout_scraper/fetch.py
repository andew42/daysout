"""Polite HTTP fetching: robots.txt, per-host rate limiting, honest
User-Agent, and an on-disk cache so re-runs don't hammer the sources."""

import hashlib
import logging
import re
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

# Phrases that appear on a bot-protection interstitial rather than on a
# page of the site. Seeing one means the site declined to serve us, which
# is a different thing from a page having no events on it — and the
# difference matters, because one is worth retrying tomorrow and the other
# means our patterns are wrong.
CHALLENGE_MARKERS = (
    "radware",
    "captcha-delivery",
    "request unsuccessful",
    "incapsula",
    "are you a human",
    "enable javascript and cookies to continue",
)


# <meta charset="utf-8"> or the older http-equiv form, in the head.
META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.I)


def decoded(response):
    """The body as text, believing the document over the default.

    `requests` follows RFC 2616 and reads "text/html" with no charset as
    ISO-8859-1. That default is two decades stale: Blenheim serves UTF-8
    under a bare "content-type: text/html", so its "Salon Privé" arrived
    as "Salon PrivÃ©" and would have gone into the database that way — the
    frontend escapes what it interpolates, so mojibake stored is mojibake
    a reader sees.

    When the header names a charset it is right and is used. Otherwise the
    document is asked, as a browser asks it, and UTF-8 is the fallback
    rather than Latin-1.
    """

    if "charset" in response.headers.get("content-type", "").lower():
        return response.text

    match = META_CHARSET_RE.search(response.content[:4096])
    declared = match.group(1).decode("ascii", "ignore") if match else "utf-8"
    try:
        return response.content.decode(declared, errors="replace")
    except LookupError:  # a charset nobody has heard of
        return response.content.decode("utf-8", errors="replace")


def looks_like_a_challenge(html):
    """True if this is an interstitial refusing us rather than page content.

    Deliberately checked against the start of the document only: the words
    below are common enough that a real page could mention one in passing,
    but a challenge page says it up front and carries little else.

    Lives here rather than with any one source because it describes what a
    *server* returned. It arrived with the National Trust source, which is
    gone; `feedhunt` and the sources that report "nobody is turning us
    away" still need it.
    """
    head = html[:4000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


class Fetcher:
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._robots = {}
        self._last_request = {}
        # Set by the runner when a source needs pages rendered; see browser.py.
        self.renderer = None

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

    def get(self, url, api=False, render=False, fresh=False):
        """Fetch a URL as text, honouring robots.txt, the rate limit and the
        cache. Raises FetchDisallowed / requests exceptions on failure.

        render=True loads the page in a headless browser first, for sites
        that build their listings client-side. Rendered and plain fetches
        are cached separately because they return different content. It
        does not relax any check: robots.txt is still consulted and the
        rate limit still applies.

        fresh=True skips *reading* the cache, for diagnostics that need to
        see what the site returns now rather than what it returned earlier.

        api=True is for a documented API endpoint the operator publishes for
        programmatic use. robots.txt governs crawling a site's pages — a
        query endpoint is commonly disallowed there precisely so crawlers
        don't wander through infinite generated URLs, which says nothing
        about a client calling it as the API it is. Rate limiting, the
        honest User-Agent and the cache still apply, so we stay a
        well-behaved client either way. Never set this to get past a site
        that is refusing us (see looks_like_a_challenge above).
        """
        cache_key = ("render:" if render else "") + url
        cache_file = self.cache_dir / hashlib.sha256(cache_key.encode()).hexdigest()
        # fresh=True is for diagnostics: a cached page cannot tell you
        # whether a change to the renderer worked, and reading a stale copy
        # while believing otherwise is worse than not looking. It still
        # writes to the cache, so the next ordinary fetch benefits.
        if (not fresh and cache_file.exists()
                and time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS):
            return cache_file.read_text(encoding="utf-8")

        if not api and not self._allowed(url):
            raise FetchDisallowed(f"robots.txt disallows {url}")

        if render:
            if self.renderer is None:
                raise RenderUnavailable(f"no renderer configured for {url}")
            self._throttle(url)
            text = self.renderer.render(url)
            cache_file.write_text(text, encoding="utf-8")
            return text

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
        text = decoded(response)
        cache_file.write_text(text, encoding="utf-8")
        return text


class FetchDisallowed(Exception):
    pass


class RenderUnavailable(Exception):
    """A source asked for a rendered page but no browser is available."""
