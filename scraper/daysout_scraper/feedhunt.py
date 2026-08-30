"""Look for a sanctioned way into a site's events.

Some sites decline to serve their pages to automated clients. Working
around that is not an option, so the question becomes whether the same
site offers a route it *does* sanction — a calendar feed, an RSS file, a
documented API, or simply a sitemap detailed enough to be useful on its
own.

That last one is worth stating plainly, because it is the one people
overlook. A sitemap is published precisely so that automated clients can
discover what a site holds; a server that hands one over is not being
circumvented when we read it. It carries URLs and last-modified dates,
and on many sites the URL slug carries the event's name and its dates too
("...-legendary-joust-29-to-31-aug"). Where that is true, a site can be
useful to us even when its pages are closed to us.

    python3 -m daysout_scraper.feedhunt --url https://www.example.org/

Reports what the site publishes, whether any of it is a feed, and how
much a URL list alone would actually tell us.
"""

import argparse
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .fetch import USER_AGENT, Fetcher
from .sitemap_source import sitemap_urls
from .sources.national_trust import looks_like_a_challenge

log = logging.getLogger(__name__)

# Paths a site commonly publishes a calendar or feed under. Probed once
# each, politely, which is what a person hunting for a feed would do.
CONVENTIONAL_FEEDS = (
    "events.ics", "events/feed", "events/rss", "events.rss",
    "feed", "rss", "rss.xml", "calendar.ics", "whats-on/feed",
)

FEED_URL_RE = re.compile(r"\.(ics|rss|atom)$|/(feed|rss|atom)/?$", re.IGNORECASE)

# Tighter than the crawler's hint pattern, which deliberately includes
# section fronts like /visit because they are worth *fetching*. Here we
# count pages that are about events: an individual event, or a venue's
# own events listing. The first cut required a slug *below* the events
# segment, which quietly excluded every "<property>/events" page and left
# the report counting national campaign pages only.
EVENT_PATH_RE = re.compile(r"/(events?|whats-on|what-s-on)(/|$)", re.IGNORECASE)

# Longest first: "oct" would otherwise match inside "october" and the
# word boundary that follows would then fail.
MONTHS = ("january|february|march|april|june|july|august|september|october|"
          "november|december|sept|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec")

# Dates as they appear in a slug: "29-to-31-aug", "-5-september-2026",
# "-2026-08-29-". If these are there, a URL list alone carries the one
# field an events view cannot do without.
SLUG_DATE_RE = re.compile(
    rf"(\d{{1,2}}-(to|and)-\d{{1,2}}-({MONTHS})|"
    rf"\d{{1,2}}-({MONTHS})\b|\b({MONTHS})-\d{{1,2}}\b|"
    rf"\d{{4}}-\d{{2}}-\d{{2}})",
    re.IGNORECASE)


def robots_report(fetcher, base):
    """What robots.txt says, including any sitemaps it points at."""

    host = urlparse(base).netloc
    print(f"=== robots.txt for {host}")
    sitemaps = []
    try:
        response = fetcher.session.get(f"https://{host}/robots.txt", timeout=30)
        body = response.text if response.ok else ""
        print(f"    HTTP {response.status_code}, {len(body)} bytes")
    except Exception as e:  # noqa: BLE001 — diagnostics never fail the caller
        print(f"    could not be read: {e}")
        return sitemaps

    for line in body.splitlines():
        if line.lower().startswith("sitemap:"):
            url = line.split(":", 1)[1].strip()
            sitemaps.append(url)
            print(f"    declares sitemap: {url}")
    if not sitemaps:
        print("    declares no sitemap")
    print(f"    may we fetch {base}? {fetcher._allowed(base)}")
    return sitemaps


def sitemap_report(fetcher, sitemaps):
    """What the sitemap holds, and whether a URL list alone would do."""

    pairs = []
    for sitemap in sitemaps:
        pairs.extend(sitemap_urls(fetcher, sitemap, with_lastmod=True))

    print(f"\n=== sitemap: {len(pairs)} URL(s) from {len(sitemaps)} file(s)")
    if not pairs:
        print("    nothing to work with")
        return []

    feeds = [url for url, _ in pairs if FEED_URL_RE.search(url)]
    print(f"    feed-shaped URLs (.ics/.rss/.atom/feed): {len(feeds)}")
    for url in feeds[:10]:
        print(f"      {url}")

    events = [(url, mod) for url, mod in pairs if EVENT_PATH_RE.search(url)]
    print(f"    event-shaped URLs: {len(events)}")

    dated = [(url, mod) for url, mod in events if SLUG_DATE_RE.search(url)]
    print(f"    ...of which carry a date in the slug: {len(dated)}")
    if events:
        share = 100 * len(dated) / len(events)
        print(f"    ({share:.0f}% — a URL list is only useful for events "
              f"whose dates are in the URL)")

    print("    newest event URLs:")
    for url, mod in sorted(events, key=lambda p: p[1], reverse=True)[:8]:
        marker = "  [dated]" if SLUG_DATE_RE.search(url) else ""
        print(f"      {mod or '(no lastmod)'}  {url}{marker}")

    shapes = Counter()
    for url, _ in pairs:
        path = urlparse(url).path.strip("/")
        segments = path.split("/") if path else []
        shapes["/".join(segments[:2] + ["<slug>"] * max(0, len(segments) - 2))] += 1
    print("    most common URL shapes:")
    for shape, count in shapes.most_common(8):
        print(f"      {count:7d}  /{shape}")
    return [url for url, _ in pairs]


def probe_conventional_feeds(fetcher, base):
    """Try the usual feed paths. A 404 is an answer; so is a challenge."""

    print("\n=== conventional feed paths")
    for path in CONVENTIONAL_FEEDS:
        url = urljoin(base, path)
        try:
            body = fetcher.get(url)
        except Exception as e:  # noqa: BLE001
            print(f"    {url}\n        no: {str(e)[:110]}")
            continue
        if looks_like_a_challenge(body):
            print(f"    {url}\n        bot-protection challenge ({len(body)} bytes)")
            continue
        head = body.lstrip()[:200].replace("\n", " ")
        if head.startswith("BEGIN:VCALENDAR"):
            print(f"    {url}\n        FOUND: iCal, {len(body)} bytes")
        elif head.startswith("<?xml") or "<rss" in head[:100].lower():
            print(f"    {url}\n        FOUND: XML/RSS, {len(body)} bytes — {head[:100]}")
        else:
            # Served, but HTML. A site that has no feed at this path
            # usually answers with its ordinary 404 page, and calling that
            # a find would send someone off after nothing.
            print(f"    {url}\n        not a feed: HTML, {len(body)} bytes "
                  f"(probably an error page) — {head[:80]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="site root to examine")
    parser.add_argument("--cache", default="", help="page cache dir")
    parser.add_argument("--skip-probes", action="store_true",
                        help="read robots.txt and the sitemap only, making no "
                             "requests for pages that may not exist")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    data = os.environ.get("DAYSOUT_DATA") or "data"
    fetcher = Fetcher(args.cache or str(Path(data) / "scrape-cache"))

    base = args.url if args.url.endswith("/") else args.url + "/"
    declared = robots_report(fetcher, base)
    sitemap_report(fetcher, declared or [urljoin(base, "sitemap.xml")])
    if not args.skip_probes:
        probe_conventional_feeds(fetcher, base)


if __name__ == "__main__":
    main()
