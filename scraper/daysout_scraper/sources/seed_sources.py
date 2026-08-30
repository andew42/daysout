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
    ("historic-houses", "https://www.historichouses.org/",
     "auto", "historic-house", "Historic Houses: independently owned houses"),
    ("invitation-to-view", "https://www.invitationtoview.co.uk/",
     "auto", "historic-house", "Private house tours by invitation"),

    # Craft, food, music, art.
    ("uk-craft-fairs", "https://www.ukcraftfairs.com/calendar",
     "auto", "craft", "UK Craft Fairs calendar"),
    ("creative-crafts", "https://www.creativecrafts-online.co.uk/",
     "auto", "craft", "Creative Crafts Association craft and gift fairs"),
    ("festival-calendar-art", "https://www.thefestivalcalendar.co.uk/art-festivals.php",
     "auto", "art", "The Festival Calendar: art festivals"),
    ("festival-calendar-food", "https://www.thefestivalcalendar.co.uk/food-festivals.php",
     "auto", "food", "The Festival Calendar: food festivals"),
    ("festival-calendar-music", "https://www.thefestivalcalendar.co.uk/music-festivals.php",
     "auto", "music", "The Festival Calendar: music festivals"),
    ("food-festivals-uk", "https://rosemaryandporkbelly.co.uk/food-festivals-uk/",
     "auto", "food", "Food and drink festival listing"),

    # Open studios and art trails.
    ("brighton-open-houses", "https://aoh.org.uk/",
     "auto", "art", "Brighton Artists Open Houses"),

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
    ("historic-houses", "https://www.historichouses.org/whats-on/",
     "https://www.historichouses.org/"),
    ("rhs-events", "https://www.rhs.org.uk/events", "https://www.rhs.org.uk/"),
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
    ("historic-houses", "listing built client-side; retry rendered"),
    ("invitation-to-view", "listing built client-side; retry rendered"),
    ("brighton-open-houses", "listing built client-side; retry rendered"),
    ("creative-crafts", "listing built client-side; retry rendered"),
    ("festival-calendar-art", "listing built client-side; retry rendered"),
    ("festival-calendar-food", "listing built client-side; retry rendered"),
    ("festival-calendar-music", "listing built client-side; retry rendered"),
    ("food-festivals-uk", "a blog, but its festival roundups may render dates"),
    ("uk-craft-fairs",
     "no structured data in the served HTML, and its server returns malformed "
     "HTTP headers that break a plain fetch — a browser sidesteps both"),
]

# Nothing here yet: every candidate is worth one rendered attempt before
# being written off. Sources that still yield nothing after rendering belong
# here, with the reason.
DISABLE = []

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

    for name, wrong_url, right_url in URL_FIXES:
        db.execute(
            "UPDATE sources SET url = ? WHERE name = ? AND url = ?",
            (right_url, name, wrong_url))

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
