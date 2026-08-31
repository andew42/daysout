"""Candidate event sources seeded into the `sources` table.

These are starting points, not proven feeds. Which of them actually
publish machine-readable events is decided by running discovery against
them (`python3 -m daysout_scraper.discover`) on a machine that can reach
them, and the answer is recorded in each row's last_status. A site that
turns out to publish nothing usable stays in the table, disabled, so the
next person does not waste time rediscovering that.

Rows are inserted if absent and never overwritten, so anything you add or
disable by hand survives an upgrade — and a source removed through the web
UI is recorded in removed_sources and never seeded again.
"""

from .. import db as dbmod

# (name, url, kind, category, notes)
CANDIDATES = [
    # Gardens — open days are inherently dated, which is exactly what the
    # events view wants.
    ("ngs-open-gardens", "https://ngs.org.uk/gardens-open-this-coming-week/",
     "auto", "garden", "National Garden Scheme open gardens this week"),
    ("ngs-find-a-garden", "https://ngs.org.uk/find-a-garden/",
     "auto", "garden", "National Garden Scheme garden search"),

    # Privately owned houses open to the public — the gap left by the
    # National Trust and English Heritage.
    ("invitation-to-view", "https://www.invitationtoview.co.uk/",
     "auto", "historic-house", "Private house tours by invitation"),

    # Craft, food, music, art.
    ("creative-crafts", "https://www.creativecrafts-online.co.uk/",
     "auto", "craft", "Creative Crafts Association craft and gift fairs"),
    # An iCal feed, which is the nicest thing a source can be: published
    # for subscription, machine-readable by design, and nothing to guess
    # at. kind is 'ical' rather than 'auto' because the URL is a query
    # string ("?feed=...") that a probe would fetch as a web page.
    # Categorised as craft: an antiques and collectors fair is not quite
    # that, but it is the nearest of the eight categories the UI offers
    # and a new one would mean touching the filters, the colours and the
    # settings page for one source.
    ("iacf-newark", "https://www.iacf.co.uk/?feed=iacf-newark-events-ical",
     "ical", "craft", "IACF antiques and collectors fairs at Newark"),
    ("festival-calendar-art", "https://www.thefestivalcalendar.co.uk/art-festivals.php",
     "auto", "art", "The Festival Calendar: art festivals"),
    ("festival-calendar-food", "https://www.thefestivalcalendar.co.uk/food-festivals.php",
     "auto", "food", "The Festival Calendar: food festivals"),
    ("festival-calendar-music", "https://www.thefestivalcalendar.co.uk/music-festivals.php",
     "auto", "music", "The Festival Calendar: music festivals"),
    ("food-festivals-uk", "https://rosemaryandporkbelly.co.uk/food-festivals-uk/",
     "auto", "food", "Food and drink festival listing"),

    # Gardens with their own event programmes.
    # The one listing site that does publish Event JSON-LD. Its five events
    # are read correctly but none can be placed yet: they name RHS gardens
    # as their venue and none of those gardens is in destinations under a
    # matching name. Left enabled — the pipeline now logs the venue name of
    # every unplaced event, so the next run says exactly which names to look
    # for rather than inviting another guess.
    ("rhs-events", "https://www.rhs.org.uk/",
     "auto", "garden", "RHS shows and garden events"),
]

# Corrections to rows an earlier release seeded with a URL that turned out
# to 404, applied only when the row still holds that exact wrong value, so
# anything edited by hand is left alone.
URL_FIXES = [
    ("rhs-events", "https://www.rhs.org.uk/events", "https://www.rhs.org.uk/"),
]

# A source that is one venue: every event happens at the same address and
# the feed may not repeat it. Used only as a fallback — an event that
# brings its own postcode keeps it — but without one an event has nowhere
# to go and the pipeline drops it.
#
# NOT YET VERIFIED against the feed: the sandbox cannot reach the site, so
# whether the feed's own LOCATION carries the address is a question the
# deploy answers. If it does, this fallback never fires.
VENUES = [
    ("iacf-newark", "Newark Showground", "NG24 2NY"),
]

# Verdicts from running discovery and a sitemap crawl against each site on
# real hardware (2026-08-29), then re-tried with a browser.
#
# Every one of these publishes a sitemap and JSON-LD, but of type WebPage,
# Organization, Article or BlogPosting rather than Event: their listings are
# assembled in the browser, so the dates never reach the served HTML. That is
# what the browser kind is for — render the page as a visitor's browser does,
# then read the structured data that appears.
#
# This is not a way past a site that is refusing us. National Trust answers
# with a bot-protection challenge, which is a no; it stays disabled and must
# not be given kind='browser'.
BROWSER = [
    ("ngs-open-gardens", "listing built client-side; retry rendered"),
    ("ngs-find-a-garden", "garden search is client-side; retry rendered"),
    ("invitation-to-view", "listing built client-side; retry rendered"),
    ("creative-crafts", "listing built client-side; retry rendered"),
    ("festival-calendar-art", "listing built client-side; retry rendered"),
    ("festival-calendar-food", "listing built client-side; retry rendered"),
    ("festival-calendar-music", "listing built client-side; retry rendered"),
    ("food-festivals-uk", "a blog, but its festival roundups may render dates"),
]

# Nothing here yet: every candidate is worth one rendered attempt before
# being written off. Sources that still yield nothing after rendering belong
# here, with the reason.
DISABLE = []

# Candidates dropped for good, removed from any database that still holds
# them. Deleting the row from CANDIDATES alone is not enough: ensure()
# only ever inserts, so an old row would sit in the table for ever,
# spending requests and reporting the same failure.
RETIRED = [
    ("brighton-open-houses",
     "no events after rendering: an open-houses trail publishes its dates "
     "in prose on a festival page, not per house"),
]

# Candidates a built-in parser now handles. The generic feed row has to go
# — the two share a name, so both would run and the failing one would
# overwrite the other's result — but unlike RETIRED it must NOT be recorded
# as removed: that list is what the Sources page filters out, and the code
# source would vanish from the UI along with the row it replaced.
SUPERSEDED = [
    ("historic-houses",
     "now crawled by the built-in Historic Houses parser (house-sitemap.xml)"),
    ("uk-craft-fairs",
     "now read by the built-in parser: the calendar for discovery, each "
     "fair's own page for its JSON-LD and postcode"),
]


def ensure(db):
    """Insert any candidate that isn't in the table yet, and apply the
    corrections learned from running discovery against the real sites."""

    # A source removed through the web UI stays removed: re-inserting it
    # here would quietly undo the removal on the next run, which is worse
    # than not offering to remove it at all.
    removed = {row[0] for row in db.execute("SELECT name FROM removed_sources")}

    added = 0
    for name, url, kind, category, notes in CANDIDATES:
        if name in removed:
            continue
        cursor = db.execute(
            """INSERT OR IGNORE INTO sources
                 (name, url, kind, category, enabled, notes, added)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (name, url, kind, category, notes, dbmod.now()))
        added += cursor.rowcount

    # Only fill a venue in where the row has none, so a corrected one
    # survives an upgrade the way a hand-edited URL does.
    for name, venue_name, venue_postcode in VENUES:
        db.execute(
            "UPDATE sources SET venue_name = ?, venue_postcode = ?"
            " WHERE name = ? AND venue_name = '' AND venue_postcode = ''",
            (venue_name, venue_postcode, name))

    for name, wrong_url, right_url in URL_FIXES:
        db.execute(
            "UPDATE sources SET url = ? WHERE name = ? AND url = ?",
            (right_url, name, wrong_url))

    for name, reason in RETIRED:
        db.execute("DELETE FROM sources WHERE name = ?", (name,))
        db.execute("DELETE FROM events WHERE source = ?", (name,))
        db.execute(
            "DELETE FROM destinations WHERE source = ?"
            " AND id NOT IN (SELECT destination_id FROM events)", (name,))
        db.execute(
            "INSERT OR REPLACE INTO removed_sources (name, removed_at)"
            " VALUES (?, ?)", (name, dbmod.now()))

    for name, reason in SUPERSEDED:
        db.execute("DELETE FROM sources WHERE name = ?", (name,))

    for name, reason in DISABLE:
        db.execute(
            "UPDATE sources SET enabled = 0, notes = ? WHERE name = ? AND notes NOT LIKE ?",
            (reason, name, f"%{reason[:20]}%"))

    # Sites whose listings only exist after rendering: switch them to the
    # browser scanner and give them another go. Only rows still on their
    # seeded kind are changed, so a hand-tuned row is left alone.
    for name, reason in BROWSER:
        db.execute(
            "UPDATE sources SET kind = 'browser', enabled = 1, notes = ? "
            "WHERE name = ? AND kind IN ('auto', 'sitemap')",
            (reason, name))

    db.commit()
    return added
