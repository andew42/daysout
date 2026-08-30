"""Report what a page's DOM would give a hand-written parser.

When a site publishes no Event JSON-LD the next question is whether the
dates a visitor sees are in the markup at all. If they are, a parser can
read them; if the page is a shell whose listing never arrives, there is
nothing to parse and the source should be disabled rather than guessed
at. This module answers that question with evidence: how big the page
is, what date-carrying elements and date-looking text it holds, and
which links look like individual events.

It is a diagnostic only — nothing in the scrape path depends on it — and
it is deliberately format-agnostic, because the whole point is to look at
a page that fits none of the formats we know how to read.
"""

import re

from bs4 import BeautifulSoup

from . import jsonld

# Paths that look like a single event or open day rather than a section
# front page. Shared with sources/feeds.py, which uses it to choose which
# sitemap entries are worth fetching.
EVENT_URL_HINT_RE = re.compile(
    r"/(events?|whats-on|what-s-on|fairs?|festivals?|shows?|exhibitions?|"
    r"open-gardens?|find-a-garden|gardens?-open|open-days?|visit)\b",
    re.IGNORECASE)

MONTHS = ("january|february|march|april|may|june|july|august|september|"
          "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")

# "Saturday 6 September", "6 Sep 2026", "2026-09-06", "06/09/2026" — the
# shapes a listing uses for a human reader.
DATE_TEXT_RE = re.compile(
    rf"\b(\d{{1,2}}\s+({MONTHS})\b|({MONTHS})\s+\d{{1,2}}\b|"
    rf"\d{{4}}-\d{{2}}-\d{{2}}\b|\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b)",
    re.IGNORECASE)

LIMIT = 8  # per category: enough to see the shape, short enough to read


def _short(text, limit=70):
    text = " ".join((text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def scan(html, url):
    """What a parser would have to work with on this page."""

    soup = BeautifulSoup(html, "html.parser")
    objects = jsonld.extract_objects(html)

    report = {
        "url": url,
        "bytes": len(html),
        "title": _short(soup.title.string if soup.title else "", 100),
        "jsonld_types": sorted({str(o.get("@type")) for o in objects}),
        "event_objects": sum(1 for o in objects if jsonld.parse_event(o, url)),
        "times": [],
        "date_elements": [],
        "date_text": [],
        "event_links": [],
        "data_scripts": [],
    }

    for element in soup.find_all("time")[:LIMIT]:
        report["times"].append((element.get("datetime"),
                                _short(element.get_text(strip=True))))

    for element in soup.find_all(attrs={"class": True}):
        if len(report["date_elements"]) >= LIMIT:
            break
        classes = " ".join(element.get("class"))
        if "date" in classes.lower() or "when" in classes.lower():
            report["date_elements"].append(
                (element.name, _short(classes, 50),
                 _short(element.get_text(" ", strip=True))))

    # Date-looking text anywhere in the body: the last resort, and the one
    # that says whether the listing arrived at all.
    seen = set()
    for match in DATE_TEXT_RE.finditer(soup.get_text(" ", strip=True)):
        phrase = match.group(0).lower()
        if phrase not in seen:
            seen.add(phrase)
            report["date_text"].append(match.group(0))
        if len(report["date_text"]) >= LIMIT * 2:
            break

    for anchor in soup.find_all("a", href=True):
        if len(report["event_links"]) >= LIMIT:
            break
        if EVENT_URL_HINT_RE.search(anchor["href"]):
            report["event_links"].append(
                (anchor["href"][:100], _short(anchor.get_text(strip=True), 50)))

    # A page that renders from an embedded blob (Next.js, Nuxt, a REST
    # payload inlined at build time) can often be read without a browser.
    for script in soup.find_all("script"):
        script_id = script.get("id") or ""
        script_type = (script.get("type") or "").lower()
        if script_id or "json" in script_type:
            report["data_scripts"].append(
                (script_id, script_type, len(script.string or "")))
    report["data_scripts"] = sorted(
        report["data_scripts"], key=lambda s: -s[2])[:LIMIT]

    return report


def describe(report, indent="    "):
    """A readable block for the deploy log."""

    def line(text):
        lines.append(indent + text)

    lines = []
    line(f"{report['bytes']} bytes | title: {report['title'] or '(none)'}")
    line(f"JSON-LD types: {', '.join(report['jsonld_types']) or '(none)'} "
         f"| Event objects: {report['event_objects']}")

    for datetime_attr, text in report["times"]:
        line(f"  <time datetime={datetime_attr!r}> {text}")
    if not report["times"]:
        line("  <time> elements: none")

    for tag, classes, text in report["date_elements"]:
        line(f"  <{tag} class={classes!r}> {text}")
    if not report["date_elements"]:
        line("  date-classed elements: none")

    line(f"  date-looking text ({len(report['date_text'])} distinct): "
         f"{', '.join(report['date_text'][:10]) or 'NONE'}")

    for href, text in report["event_links"]:
        line(f"  link {href} — {text}")
    if not report["event_links"]:
        line("  event-looking links: none")

    for script_id, script_type, size in report["data_scripts"]:
        line(f"  <script id={script_id!r} type={script_type!r}> {size} chars")

    return "\n".join(lines)


def verdict(plain, rendered=None):
    """One line saying what, if anything, is worth writing a parser for."""

    best = rendered or plain
    if best["event_objects"]:
        return "structured Events present — no DOM parser needed"
    grew = rendered and rendered["bytes"] > plain["bytes"] * 1.05
    if rendered and not grew and not rendered["date_text"]:
        return ("rendering changed nothing and no dates reached the page — "
                "nothing here to parse; disable the source")
    if best["date_text"] and (best["times"] or best["date_elements"]):
        return ("dates ARE in the DOM in identifiable elements — a hand-written "
                "parser could read this listing")
    if best["date_text"]:
        return ("dates appear only as loose text — a parser would have to "
                "regex prose, which is fragile but possible")
    return "no dates in the DOM at all — the listing never reaches the page"

# --- Deeper look: what IS on this page, when the dates are not? ---------
#
# A rendered page that grew by 130 KB and still carries no dates is not
# self-explanatory, and guessing at it is how time gets wasted. These
# answer the three things that would explain it: the listing is inside an
# iframe (invisible to page.content()), it is behind a search form, or it
# simply never arrived.

# A listing is many siblings sharing a class. That repetition is the
# strongest signal that the rows are present, whatever they contain.
MIN_REPEATS = 4
MIN_BLOCK_CHARS = 25


def deep_scan(html):
    """Structure rather than content: where would a listing be hiding?"""

    from collections import Counter

    soup = BeautifulSoup(html, "html.parser")
    report = {"elements": {}, "iframes": [], "forms": [],
              "repeated": [], "longest": []}

    for tag in ("div", "section", "article", "li", "table", "tr",
                "iframe", "form", "input", "button", "template"):
        count = len(soup.find_all(tag))
        if count:
            report["elements"][tag] = count

    # A listing rendered into an iframe never appears in the page's own
    # HTML, so a page can look empty while a visitor sees a full calendar.
    for frame in soup.find_all("iframe")[:LIMIT]:
        report["iframes"].append((frame.get("src") or "(no src)",
                                  _short(frame.get("title") or "", 40)))

    # A listing behind a search form is not missing, it is unasked for.
    for form in soup.find_all("form")[:LIMIT]:
        fields = [i.get("name") or i.get("id") or i.get("type") or "?"
                  for i in form.find_all(("input", "select"))][:6]
        report["forms"].append((form.get("action") or "(no action)",
                                ", ".join(fields) or "(no fields)"))

    classes = Counter()
    examples = {}
    for element in soup.find_all(attrs={"class": True}):
        text = element.get_text(" ", strip=True)
        if len(text) < MIN_BLOCK_CHARS:
            continue
        for name in element.get("class"):
            classes[name] += 1
            examples.setdefault(name, text)
    for name, count in classes.most_common(LIMIT):
        if count >= MIN_REPEATS:
            report["repeated"].append((name, count, _short(examples[name], 80)))

    blocks = sorted(
        (element.get_text(" ", strip=True)
         for element in soup.find_all(("li", "article", "section", "div"))),
        key=len, reverse=True)
    # The longest block is the whole page; what is wanted is the middle of
    # the distribution, where a single listing row lives.
    report["longest"] = [_short(text, 90) for text in blocks[:400]][-LIMIT:]
    return report


def describe_deep(report, indent="    "):
    lines = []

    def line(text):
        lines.append(indent + text)

    line("elements: " + ", ".join(f"{tag}={count}" for tag, count
                                  in sorted(report["elements"].items())))
    for src, title in report["iframes"]:
        line(f"  iframe src={src[:90]} {title}")
    if not report["iframes"]:
        line("  iframes: none (so nothing is hidden inside one)")
    for action, fields in report["forms"]:
        line(f"  form action={action[:60]} fields: {fields}")
    if not report["forms"]:
        line("  forms: none (so the listing is not behind a search)")

    line(f"  repeated blocks (a listing looks like this):")
    for name, count, sample in report["repeated"]:
        line(f"    {count:4d} x .{name} — {sample}")
    if not report["repeated"]:
        line("    none — no repeated row-shaped content on the page")

    line("  smallest of the larger text blocks (a row, if there is one):")
    for text in report["longest"]:
        line(f"    {text}")
    return "\n".join(lines)
