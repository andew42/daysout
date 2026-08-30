"""National Trust: read a property's events, and take no for an answer.

Two things have to hold at once. The events a property publishes must
actually be read — from the listing page as well as from individual event
pages — and a bot-protection challenge must stop the run rather than being
worked around or mistaken for an empty site.
"""

import sqlite3
import unittest

from daysout_scraper.pipeline import run_source
from daysout_scraper.sources.national_trust import NationalTrust, looks_like_a_challenge

from schema import SCHEMA

BASE = "https://www.nationaltrust.org.uk"
INDEX = f"{BASE}/visit/oxfordshire-buckinghamshire-berkshire/stowe-gardens/events"
EVENT = f"{INDEX}/autumn-lantern-walk"
PROPERTY = f"{BASE}/visit/oxfordshire-buckinghamshire-berkshire/stowe-gardens"

SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{PROPERTY}</loc><lastmod>2026-08-27</lastmod></url>
  <url><loc>{INDEX}</loc><lastmod>2026-08-28</lastmod></url>
  <url><loc>{EVENT}</loc><lastmod>2026-08-28</lastmod></url>
</urlset>"""


def event_jsonld(name, start, end):
    return f"""{{"@context": "https://schema.org", "@type": "Event",
      "name": "{name}", "startDate": "{start}", "endDate": "{end}",
      "location": {{"@type": "Place", "name": "Stowe Gardens",
        "address": {{"@type": "PostalAddress", "postalCode": "MK18 5EQ"}}}}}}"""


def page(*objects):
    scripts = "".join(
        f'<script type="application/ld+json">{o}</script>' for o in objects)
    return f"<html><head>{scripts}</head><body></body></html>"


# A property's events page lists several events at once — the reason to
# read it rather than fetching an page per event.
INDEX_PAGE = page(
    event_jsonld("Autumn lantern walk", "2026-10-24", "2026-10-26"),
    event_jsonld("Halloween trail", "2026-10-28", "2026-10-31"),
)
# The same first event, on its own page.
EVENT_PAGE = page(event_jsonld("Autumn lantern walk", "2026-10-24", "2026-10-26"))

CHALLENGE_PAGE = (
    "<html><head><title>Radware Page</title></head><body>"
    "<div>Request unsuccessful. Please enable JavaScript and cookies to continue.</div>"
    + "<!-- padding -->" * 200 + "</body></html>")


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def get(self, url, api=False, render=False):
        self.fetched.append(url.rstrip("/"))
        return self.pages[url.rstrip("/")]


def fetcher(index=INDEX_PAGE, event=EVENT_PAGE, prop=None):
    pages = {f"{BASE}/sitemap.xml": SITEMAP, INDEX: index, EVENT: event}
    if prop is not None:
        pages[PROPERTY] = prop
    return FakeFetcher(pages)


class TestClassification(unittest.TestCase):

    def test_a_propertys_events_page_is_read(self):
        # The shape that was being missed entirely.
        self.assertEqual(NationalTrust().classify(INDEX), "event")

    def test_an_individual_event_page_is_read(self):
        self.assertEqual(NationalTrust().classify(EVENT), "event")

    def test_whats_on_is_the_same_shape(self):
        self.assertEqual(
            NationalTrust().classify(f"{BASE}/visit/wiltshire/stourhead/whats-on"),
            "event")

    def test_property_pages_are_left_to_wikidata(self):
        # Not an oversight: crawling 1,279 property pages daily to re-derive
        # what Wikidata already gives us would be rude for no gain — and it
        # would spend the run's first requests on the pages most likely to
        # be challenged, before reaching any events.
        self.assertIsNone(NationalTrust().classify(PROPERTY))

    def test_unrelated_pages_are_ignored(self):
        for url in (f"{BASE}/", f"{BASE}/visit/yorkshire",
                    f"{BASE}/membership/join/events"):
            self.assertIsNone(NationalTrust().classify(url), url)


class TestEvents(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        # The property, as Wikidata supplies it — what the events link to.
        self.db.execute(
            "INSERT INTO destinations (name, category, lat, lon, source,"
            " source_id, first_seen, last_seen) VALUES ('Stowe Gardens',"
            " 'garden', 52.0, -1.0, 'wikidata', 'Q1', '2026-01-01', '2026-01-01')")
        self.db.commit()

    def events(self):
        return self.db.execute(
            "SELECT e.title, e.start_date, d.name FROM events e "
            "JOIN destinations d ON d.id = e.destination_id ORDER BY e.title"
        ).fetchall()

    def test_every_event_on_the_listing_page_is_kept(self):
        ok, message = run_source(self.db, fetcher(), NationalTrust())
        self.assertTrue(ok, message)
        self.assertEqual(self.events(), [
            ("Autumn lantern walk", "2026-10-24", "Stowe Gardens"),
            ("Halloween trail", "2026-10-28", "Stowe Gardens"),
        ])

    def test_an_event_on_both_pages_is_one_row(self):
        # Named after the page it was found on, every event on the listing
        # would be called "events" and overwrite the others — and the one
        # with its own page would be stored twice.
        run_source(self.db, fetcher(), NationalTrust())
        titles = [row[0] for row in self.events()]
        self.assertEqual(len(titles), len(set(titles)))

    def test_rerun_updates_rather_than_duplicates(self):
        run_source(self.db, fetcher(), NationalTrust())
        run_source(self.db, fetcher(), NationalTrust())
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)


class TestRefusal(unittest.TestCase):
    """A challenge is the site saying no. Notice it, and stop."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)

    def test_a_challenge_page_is_not_read_as_content(self):
        self.assertTrue(looks_like_a_challenge(CHALLENGE_PAGE))
        self.assertFalse(looks_like_a_challenge(INDEX_PAGE))

    def test_a_challenge_stops_the_run_rather_than_collecting_refusals(self):
        f = fetcher(index=CHALLENGE_PAGE, event=CHALLENGE_PAGE)
        ok, message = run_source(self.db, f, NationalTrust())

        self.assertFalse(ok)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
        # One page requested, not every page in the sitemap. Which page
        # comes first is up to the sitemap's dates and is not the point.
        pages = [u for u in f.fetched if u != f"{BASE}/sitemap.xml"]
        self.assertEqual(len(pages), 1, pages)

    def test_the_canary_stops_us_before_crawling_the_sitemap(self):
        # A refusal should cost one request, not a crawl of every URL the
        # sitemap lists.
        f = fetcher(index=CHALLENGE_PAGE, event=CHALLENGE_PAGE)
        f.pages[NationalTrust.CANARY] = CHALLENGE_PAGE
        run_source(self.db, f, NationalTrust())
        self.assertEqual(f.fetched, [NationalTrust.CANARY])

    def test_the_run_says_it_was_refused_rather_than_empty(self):
        f = fetcher(index=CHALLENGE_PAGE, event=CHALLENGE_PAGE)
        f.pages[NationalTrust.CANARY] = CHALLENGE_PAGE
        _, message = run_source(self.db, f, NationalTrust())
        self.assertIn("bot-protection challenge", message)

    def test_a_missing_canary_does_not_disable_the_source(self):
        # The canary is a probe. If that one page 404s, the crawl must
        # still happen rather than the source quietly switching itself off.
        f = fetcher()  # no CANARY page: fetching it raises KeyError
        ok, message = run_source(self.db, f, NationalTrust())
        self.assertTrue(ok, message)
        # The sitemap and the pages it lists were still visited.
        self.assertIn(f"{BASE}/sitemap.xml", f.fetched)
        self.assertIn(INDEX, f.fetched)

    def test_a_blocked_run_purges_nothing(self):
        run_source(self.db, fetcher(), NationalTrust())
        self.db.execute(
            "INSERT INTO destinations (name, category, lat, lon, source,"
            " source_id, first_seen, last_seen) VALUES ('Stowe Gardens',"
            " 'garden', 52.0, -1.0, 'wikidata', 'Q1', '2026-01-01', '2026-01-01')")
        self.db.commit()
        before = self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0]

        run_source(self.db, fetcher(index=CHALLENGE_PAGE, event=CHALLENGE_PAGE),
                   NationalTrust())
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM destinations").fetchone()[0],
            before)
