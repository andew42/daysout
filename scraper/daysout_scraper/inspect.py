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

from . import jsonld, sources
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

    # Coordinates are the one field a destination cannot do without; if the
    # page carries them outside JSON-LD, say where.
    for meta in soup.find_all("meta"):
        name = (meta.get("property") or meta.get("name") or "").lower()
        if any(word in name for word in ("latitude", "longitude", "geo")):
            print(f"    <meta {name}={meta.get('content')!r}>")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help=f"one of: {', '.join(s.name for s in sources.IMPLEMENTED)}")
    parser.add_argument("--kind", default="place", choices=["place", "event"])
    parser.add_argument("--count", type=int, default=2, help="pages to inspect")
    parser.add_argument("--cache", default="", help="page cache dir")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    matches = [s for s in sources.IMPLEMENTED if s.name == args.source]
    if not matches:
        sys.exit(f"unknown source {args.source}")
    source = matches[0]()

    data = os.environ.get("DAYSOUT_DATA") or "data"
    fetcher = Fetcher(args.cache or str(Path(data) / "scrape-cache"))

    found = 0
    for sitemap in source.sitemaps:
        for url in sitemap_urls(fetcher, sitemap):
            if source.classify(url) != args.kind:
                continue
            try:
                describe(fetcher.get(url), url)
            except Exception as e:  # noqa: BLE001 — diagnostics never fail the caller
                print(f"\n=== {url}\n    FETCH FAILED: {e}")
            found += 1
            if found >= args.count:
                return
    if found == 0:
        print(f"no {args.kind} URLs matched in the sitemap(s) for {args.source}")


if __name__ == "__main__":
    main()
