"""Diagnose what a source's pages actually contain.

Sites change their markup, and a source that suddenly finds no places or
no events is usually a parser problem rather than a network one. This
prints exactly what the JSON-LD engine sees on a few real pages — the
object types, the fields that matter, and what the page looks like when
there is no JSON-LD at all — so the parser can be corrected against
evidence instead of guesswork.

    python3 -m daysout_scraper.inspect --source national_trust --kind place
    python3 -m daysout_scraper.inspect --source english_heritage --kind event

Uses the same polite fetcher as a scrape, so pages already fetched this
run come from the cache rather than hitting the site again.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from . import browser, jsonld, sources
from . import fetch as fetch_module
from .fetch import Fetcher
from .sitemap_source import sitemap_urls

INTERESTING = ("geo", "address", "startDate", "endDate", "location", "url", "name")


def _short(value, limit=160):
    text = value if isinstance(value, str) else json.dumps(value)
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")


def describe(html, url):
    print(f"\n=== {url}")
    print(f"    {len(html)} bytes of HTML")

    objects = jsonld.extract_objects(html)
    print(f"    {len(objects)} top-level JSON-LD object(s)")
    for obj in objects:
        print(f"  @type = {obj.get('@type')!r}")
        keys = sorted(k for k in obj if not k.startswith("@"))
        print(f"    keys: {', '.join(keys[:18])}")
        for field in INTERESTING:
            if field in obj:
                print(f"    {field}: {_short(obj[field])}")

    soup = BeautifulSoup(html, "html.parser")
    if not objects:
        print("    NO JSON-LD — looking for other embedded data:")
        for script in soup.find_all("script"):
            script_id = script.get("id") or ""
            script_type = script.get("type") or ""
            if script_id or "json" in script_type:
                print(f"      <script id={script_id!r} type={script_type!r}> "
                      f"{len(script.string or '')} chars")
        print(f"    title: {soup.title.string.strip()[:120] if soup.title else '(none)'}")

        # Without JSON-LD the dates have to come out of the markup, so show
        # the elements a hand-written parser would target.
        for element in soup.find_all("time")[:6]:
            print(f"      <time datetime={element.get('datetime')!r}> "
                  f"{_short(element.get_text(strip=True), 60)}")
        seen = 0
        for element in soup.find_all(attrs={"class": True}):
            classes = " ".join(element.get("class"))
            if "date" in classes.lower() and seen < 6:
                print(f"      <{element.name} class={classes[:60]!r}> "
                      f"{_short(element.get_text(strip=True), 60)}")
                seen += 1
        for meta in soup.find_all("meta"):
            name = (meta.get("property") or meta.get("name") or "").lower()
            if "date" in name or "time" in name:
                print(f"      <meta {name}={_short(meta.get('content') or '', 60)!r}>")

    # Coordinates are the one field a destination cannot do without; if the
    # page carries them outside JSON-LD, say where.
    for meta in soup.find_all("meta"):
        name = (meta.get("property") or meta.get("name") or "").lower()
        if any(word in name for word in ("latitude", "longitude", "geo")):
            print(f"    <meta {name}={meta.get('content')!r}>")


def url_shapes(fetcher, source, limit=25):
    """Summarise a sitemap by URL shape.

    Shows what page types the site actually publishes, which is how you
    find the URL pattern you should be matching when the one you guessed
    turns out to hold the wrong kind of page.
    """
    from collections import Counter

    shapes = Counter()
    examples = {}
    total = 0
    for sitemap in source.sitemaps:
        for url in sitemap_urls(fetcher, sitemap):
            total += 1
            path = url.split("//", 1)[-1].split("/", 1)[-1].strip("/")
            segments = path.split("/") if path else []
            # Keep the leading literal segments, mark the rest as slugs.
            shape = "/".join(segments[:2] + ["<slug>"] * max(0, len(segments) - 2))
            shapes[shape] += 1
            examples.setdefault(shape, url)

    print(f"{total} URLs in {source.name} sitemap(s); {len(shapes)} distinct shapes")
    for shape, count in shapes.most_common(limit):
        classified = source.classify(examples[shape])
        marker = f"  [matched as {classified}]" if classified else ""
        print(f"  {count:6d}  {shape}{marker}")
        print(f"          e.g. {examples[shape]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help=f"one of: {', '.join(s.name for s in sources.IMPLEMENTED)}")
    parser.add_argument("--kind", default="place", choices=["place", "event"])
    parser.add_argument("--count", type=int, default=2, help="pages to inspect")
    parser.add_argument("--cache", default="", help="page cache dir")
    parser.add_argument("--url-shapes", action="store_true",
                        help="summarise the sitemap by URL shape instead of "
                             "inspecting pages")
    parser.add_argument("--browser", action="store_true",
                        help="render each page in a headless browser first, "
                             "for sites that build their listing client-side")
    parser.add_argument("--newest", action="store_true",
                        help="inspect the most recently modified pages rather "
                             "than the first ones in the sitemap (the first "
                             "ones are often years out of date)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    matches = [s for s in sources.IMPLEMENTED if s.name == args.source]
    if not matches:
        sys.exit(f"unknown source {args.source}")
    source = matches[0]()

    data = os.environ.get("DAYSOUT_DATA") or "data"
    fetcher = Fetcher(args.cache or str(Path(data) / "scrape-cache"))

    renderer = None
    if args.browser:
        if not browser.available():
            sys.exit("playwright is not installed (pip install playwright)")
        renderer = browser.Renderer(fetch_module.USER_AGENT).__enter__()
        fetcher.renderer = renderer

    if args.url_shapes:
        if not getattr(source, "sitemaps", None):
            sys.exit(f"{args.source} is not a sitemap-based source")
        url_shapes(fetcher, source)
        return

    candidates = []
    for sitemap in source.sitemaps:
        for url, lastmod in sitemap_urls(fetcher, sitemap, with_lastmod=True):
            if source.classify(url) == args.kind:
                candidates.append((lastmod, url))

    if not candidates:
        print(f"no {args.kind} URLs matched in the sitemap(s) for {args.source}")
        return
    if args.newest:
        candidates.sort(reverse=True)  # ISO 8601 sorts correctly as text

    for lastmod, url in candidates[:args.count]:
        try:
            describe(fetcher.get(url, render=args.browser), url)
            print(f"    sitemap lastmod: {lastmod or '(none)'}")
        except Exception as e:  # noqa: BLE001 — diagnostics never fail the caller
            print(f"\n=== {url}\n    FETCH FAILED: {e}")


if __name__ == "__main__":
    main()
