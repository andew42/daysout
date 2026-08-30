"""Render a page in a real browser before reading it.

Most of the listing sites we tried publish nothing in their HTML because
they build their listings client-side: the dates a visitor sees are drawn
by JavaScript after load, so a plain fetch returns a shell. Rendering the
page in a headless browser and then reading the result gets at exactly
what a visitor sees, and nothing more.

This is deliberately NOT a way around a site that is refusing us. A site
that answers a plain request with a bot-protection challenge (see
sources/national_trust.py) is saying no, and a browser that solves the
challenge would be evading an access control rather than reading a page.
Rendering is for pages that are freely served but assembled in the client.
The same politeness applies as everywhere else: robots.txt is checked
first, the honest User-Agent is sent, and one page is loaded at a time.

Playwright is an optional dependency. Without it, browser sources report
that they were skipped rather than failing the run, so a machine that
hasn't installed it still scrapes everything else.
"""

import logging
import os

log = logging.getLogger(__name__)

# An explicit Chromium to launch, rather than the build Playwright expects
# to have downloaded itself. Set DAYSOUT_CHROMIUM to reuse a browser that is
# already on the machine — a system chromium, or one a different Playwright
# version installed — which saves a few hundred megabytes and survives
# Playwright upgrades bumping their pinned build number.
CHROMIUM_PATH = os.environ.get("DAYSOUT_CHROMIUM", "")

# Common locations, tried in order when DAYSOUT_CHROMIUM isn't set.
CHROMIUM_CANDIDATES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/snap/bin/chromium",
)


def find_chromium():
    """An existing Chromium to use, or '' to let Playwright pick its own."""
    if CHROMIUM_PATH:
        return CHROMIUM_PATH
    for candidate in CHROMIUM_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    # A Playwright browser directory whose build number no longer matches
    # the installed client still holds a perfectly good Chromium.
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if browsers:
        import glob
        for pattern in ("chromium-*/chrome-linux/chrome",
                        "chromium_headless_shell-*/chrome-linux/headless_shell"):
            found = sorted(glob.glob(os.path.join(browsers, pattern)))
            if found:
                return found[-1]
    return ""

# A page that hasn't settled in this long is not going to.
LOAD_TIMEOUT_MS = 30000
# After load, give client-side rendering a moment to populate the listing.
SETTLE_MS = 2500

# Scrolling gives a lazy-loaded listing its cue. Bounded so a page that
# grows for ever (an infinite feed) cannot hold up the run.
SCROLL_STEPS = 8
SCROLL_SETTLE_MS = 800

# A consent banner is shown to every visitor, and dismissing it is what a
# visitor does — it governs cookies, not access to the content. It matters
# here because consent managers hold back the scripts that draw a listing
# until a choice is made: a National Garden Scheme page rendered to 250 KB
# of which 130 KB was Cookiebot's own cookie tables, and no gardens.
#
# Declining is tried before accepting. Content usually loads on either
# choice, and refusing cookies we have no use for is the better default
# than accepting tracking on a site we are only reading.
CONSENT_SELECTORS = (
    # Cookiebot — decline first, then accept.
    "#CybotCookiebotDialogBodyButtonDecline",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    # OneTrust, Civic, and the common aria labels.
    "#onetrust-reject-all-handler",
    "#onetrust-accept-btn-handler",
    "#ccc-reject-settings",
    "#ccc-recommended-settings",
    "[aria-label='Reject all cookies']",
    "[aria-label='Accept all cookies']",
)
CONSENT_TIMEOUT_MS = 2000


class BrowserUnavailable(Exception):
    """Playwright or its browser isn't installed."""


def available():
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


class Renderer:
    """Renders pages in one long-lived browser.

    Used as a context manager so the browser starts once per run rather
    than once per page — launching Chromium costs about a second, which
    matters across a few dozen pages.
    """

    def __init__(self, user_agent):
        self.user_agent = user_agent
        self._playwright = None
        self._browser = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable(
                "playwright is not installed (pip install playwright)") from e

        self._playwright = sync_playwright().start()
        executable = find_chromium()
        launch = {"headless": True}
        if executable:
            launch["executable_path"] = executable
            log.info("using Chromium at %s", executable)
        try:
            self._browser = self._playwright.chromium.launch(**launch)
        except Exception as e:  # noqa: BLE001 — no browser binary, usually
            self._playwright.stop()
            self._playwright = None
            raise BrowserUnavailable(f"could not start Chromium: {e}") from e
        return self

    def __exit__(self, *exc):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def render(self, url):
        """Returns the page's HTML after client-side rendering has settled.

        Waiting for `load` and then a fixed moment is not enough for a
        listing that arrives as you scroll, which is how a lot of them are
        built — the first version of this saw a National Garden Scheme
        page grow by 130 KB and still carry no dates, because what
        rendered was the page furniture and not the gardens. So scroll to
        the bottom, giving lazy content its cue, and settle again.
        """
        page = self._browser.new_page(user_agent=self.user_agent)
        try:
            page.goto(url, wait_until="load", timeout=LOAD_TIMEOUT_MS)
            # networkidle is unreliable on pages with polling or analytics,
            # so wait a fixed moment for the listing to populate instead.
            page.wait_for_timeout(SETTLE_MS)
            if self._dismiss_consent(page):
                # Scripts held back by the consent manager start now.
                page.wait_for_timeout(SETTLE_MS)
            self._scroll_through(page)
            return page.content()
        finally:
            page.close()

    def _dismiss_consent(self, page):
        """Answer a cookie banner, as a visitor would. True if one was there."""

        for selector in CONSENT_SELECTORS:
            try:
                button = page.locator(selector).first
                if button.count() == 0 or not button.is_visible():
                    continue
                button.click(timeout=CONSENT_TIMEOUT_MS)
            except Exception as e:  # noqa: BLE001 — no banner, or it moved
                log.debug("consent %s on %s: %s", selector, page.url, e)
                continue
            log.info("dismissed a cookie banner via %s", selector)
            return True
        return False

    def _scroll_through(self, page):
        """Scroll to the bottom in steps, waiting for content to arrive.

        Stops early once the page stops growing, so a short page costs
        almost nothing and an infinite one cannot run away with us.
        """
        previous = 0
        for _ in range(SCROLL_STEPS):
            try:
                height = page.evaluate("document.body.scrollHeight")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception as e:  # noqa: BLE001 — a page that won't scroll is fine
                log.debug("scrolling %s failed: %s", page.url, e)
                return
            page.wait_for_timeout(SCROLL_SETTLE_MS)
            if height == previous:
                return
            previous = height
