"""Work out how a site publishes its events.

Given a URL, report which machine-readable formats it offers: an iCal
feed, schema.org Event JSON-LD, an RSS/Atom feed, a sitemap. The scraper
uses this to choose an extractor for a source whose kind is 'auto', and it
doubles as the diagnostic for judging whether a candidate site is worth
adding at all — the development sandbox cannot reach these sites, so the
house server runs it and reports back.
"""

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import ical, jsonld

log = logging.getLogger(__name__)

ICAL_HINT_RE = re.compile(r"\.ics(\?|$)|/ical|webcal:|format=ical", re.IGNORECASE)


def probe(fetcher, url, render=False):
    """Returns a report dict describing what this URL offers.

    render=True reads the page as a browser would, which is the only way
    to see a listing that is assembled client-side.
    """

    report = {"url": url, "formats": [], "notes": [], "event_count": 0,
              "ical_urls": [], "feed_urls": [], "sitemap_urls": []}

    try:
        body = fetcher.get(url, render=render)
    except Exception as e:  # noqa: BLE001 — a probe reports failure, never raises
        report["notes"].append(f"fetch failed: {e}")
        return report

    # An .ics response is its own answer.
    if body.lstrip().startswith("BEGIN:VCALENDAR"):
        events = list(ical.parse(body))
        report["formats"].append("ical")
        report["event_count"] = len(events)
        report["notes"].append(f"iCal feed with {len(events)} event(s)")
        return report

    objects = jsonld.extract_objects(body)
    events = [o for o in objects if jsonld.parse_event(o, url)]
    if events:
        report["formats"].append("jsonld")
        report["event_count"] = len(events)
        report["notes"].append(f"{len(events)} Event JSON-LD object(s) on the page itself")
    elif objects:
        types = sorted({str(o.get("@type")) for o in objects})
        report["notes"].append(f"JSON-LD present but no Events: {', '.join(types[:6])}")

    soup = BeautifulSoup(body, "html.parser")

    # Calendar and feed links, both as <link rel=alternate> and plain hrefs.
    for link in soup.find_all("link"):
        href = link.get("href") or ""
        link_type = (link.get("type") or "").lower()
        if "calendar" in link_type or ICAL_HINT_RE.search(href):
            report["ical_urls"].append(urljoin(url, href))
        elif "rss" in link_type or "atom" in link_type:
            report["feed_urls"].append(urljoin(url, href))
    for anchor in soup.find_all("a", href=True):
        if ICAL_HINT_RE.search(anchor["href"]):
            report["ical_urls"].append(urljoin(url, anchor["href"]))

    report["ical_urls"] = sorted(set(report["ical_urls"]))[:5]
    report["feed_urls"] = sorted(set(report["feed_urls"]))[:5]
    if report["ical_urls"]:
        report["formats"].append("ical-link")
    if report["feed_urls"]:
        report["formats"].append("rss")

    # A sitemap means the site can be crawled for per-event pages.
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for candidate in ("/sitemap.xml", "/sitemap_index.xml"):
        try:
            head = fetcher.get(root + candidate)[:400]
        except Exception:  # noqa: BLE001 — absence is the normal case
            continue
        if "<urlset" in head or "<sitemapindex" in head:
            report["sitemap_urls"].append(root + candidate)
            report["formats"].append("sitemap")
            break

    if not report["formats"]:
        report["notes"].append(
            f"no machine-readable events found ({len(body)} bytes of HTML)")
    return report


def main():
    """Probe every source in the table and record what each one offers."""

    import argparse
    import os
    import sys
    from pathlib import Path

    from . import db as dbmod
    from .fetch import USER_AGENT, Fetcher
    from .sources import seed_sources

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="")
    parser.add_argument("--url", default="", help="probe one URL instead of the table")
    parser.add_argument("--browser", action="store_true",
                        help="render the URL in a headless browser before "
                             "probing, for client-side-rendered listings")
    parser.add_argument("--deep", action="store_true",
                        help="when a page carries no dates, report what it "
                             "does carry: iframes, search forms, and any "
                             "repeated row-shaped blocks")
    parser.add_argument("--disable-empty", action="store_true",
                        help="disable sources that offer nothing usable")
    parser.add_argument("--all", action="store_true",
                        help="also probe disabled sources (their verdicts are "
                             "already recorded in notes; re-probing them costs "
                             "a minute and buries the live output in noise)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    data = os.environ.get("DAYSOUT_DATA") or "data"
    path = args.db or str(Path(data) / "daysout.db")
    if not Path(path).exists():
        sys.exit(f"database {path} not found — start the server once to create it")

    db = dbmod.connect(path)
    fetcher = Fetcher(str(Path(path).parent / "scrape-cache"))

    if args.url:
        if args.browser:
            from . import browser
            if not browser.available():
                sys.exit("playwright is not installed (pip install playwright)")
            with browser.Renderer(USER_AGENT) as renderer:
                fetcher.renderer = renderer
                print(describe(probe(fetcher, args.url, render=True)))
                inspect_dom(fetcher, args.url, rendered=True, deep=args.deep)
            return
        print(describe(probe(fetcher, args.url)))
        inspect_dom(fetcher, args.url, deep=args.deep)
        return

    added = seed_sources.ensure(db)
    if added:
        print(f"seeded {added} candidate source(s)")

    query = "SELECT name, url FROM sources"
    if not args.all:
        query += " WHERE enabled = 1"
    rows = db.execute(query + " ORDER BY name").fetchall()
    disabled = db.execute(
        "SELECT COUNT(*) FROM sources WHERE enabled = 0").fetchone()[0]
    print(f"probing {len(rows)} enabled source(s)"
          f"{f', skipping {disabled} disabled (--all to include)' if disabled and not args.all else ''}\n")
    usable = 0
    for name, url in rows:
        report = probe(fetcher, url)
        print(f"# {name}")
        print(describe(report))
        print()
        status = ", ".join(report["formats"]) or "nothing usable"
        db.execute("UPDATE sources SET last_status = ? WHERE name = ?", (status, name))
        if report["formats"]:
            usable += 1
        elif args.disable_empty:
            db.execute("UPDATE sources SET enabled = 0 WHERE name = ?", (name,))
            print(f"  (disabled {name})\n")
    db.commit()
    print(f"{usable}/{len(rows)} source(s) publish something machine-readable")


def inspect_dom(fetcher, url, rendered=False, deep=False):
    """Print what a hand-written parser would have to work with.

    A source that publishes no Event JSON-LD is not automatically a dead
    end — the dates may still be in the markup. Print the evidence, and
    when the page was rendered print the un-rendered page beside it, so
    "rendering made no difference" is something the log shows rather than
    something we assume. Both fetches come from the cache the probe just
    filled.
    """

    from . import domscan

    try:
        plain = domscan.scan(fetcher.get(url), url)
    except Exception as e:  # noqa: BLE001 — a diagnostic never fails the caller
        print(f"    DOM scan failed: {e}")
        return

    print("    --- DOM as served")
    print(domscan.describe(plain, indent="      "))

    rendered_report = None
    if rendered:
        try:
            rendered_report = domscan.scan(fetcher.get(url, render=True), url)
        except Exception as e:  # noqa: BLE001
            print(f"    rendered DOM scan failed: {e}")
        else:
            print("    --- DOM after rendering")
            print(domscan.describe(rendered_report, indent="      "))
            change = rendered_report["bytes"] - plain["bytes"]
            print(f"      rendering changed the page by {change:+d} bytes")

    if deep:
        # When the dates are not there, the next question is why. Look at
        # the rendered page if we have one — an un-rendered shell explains
        # nothing.
        try:
            body = fetcher.get(url, render=rendered)
            print("    --- what IS on the page")
            print(domscan.describe_deep(domscan.deep_scan(body), indent="      "))
        except Exception as e:  # noqa: BLE001
            print(f"    deep scan failed: {e}")

    print(f"    VERDICT: {domscan.verdict(plain, rendered_report)}")


def describe(report):
    """One readable block per probe, for the deploy log."""

    lines = [f"=== {report['url']}"]
    lines.append(f"    formats: {', '.join(report['formats']) or 'none'}")
    for note in report["notes"]:
        lines.append(f"    {note}")
    for key, label in (("ical_urls", "iCal"), ("feed_urls", "feed"),
                       ("sitemap_urls", "sitemap")):
        for found in report[key]:
            lines.append(f"    {label}: {found}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
