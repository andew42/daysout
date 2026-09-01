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
    # Every IACF fair, from the one feed the site offers for exactly that:
    # its calendar page links it as "Add all iacf fairs to my calendar".
    # That is better than the three per-venue feeds it replaces, because
    # IACF runs more than three — Newark, Ardingly, Shepton Mallet, Builth
    # Wells, Norfolk, Runway and Newbury are all linked from that page —
    # and better than reading the calendar page, which carries no Event
    # JSON-LD and no events API behind it (measured 1 Sep 2026: every
    # wp-json event route 404s).
    #
    # No venue_name/venue_postcode here, unlike the per-venue rows: one
    # source covering many showgrounds has no single address to fall back
    # on, so each event must carry its own in LOCATION. Newark and
    # Ardingly do; the deploy step says which of the rest do.
    ("iacf", "https://www.iacf.co.uk/?feed=iacf-all-events-ical",
     "ical", "antiques", "IACF antiques and collectors fairs, every venue"),
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
    # Nothing here at present. The IACF rows that used one are gone: a
    # source spanning seven showgrounds cannot have a single fallback
    # address, so its events carry their own.
]

# What to show a person instead of the address the scraper fetches. A feed
# row's url is a .ics or a "?feed=..." query string: right to fetch and no
# use to click, and the Sources page was offering it as the link. Blank
# means the url is fit to show, which it is for an ordinary site.
#
# The site root rather than a guessed per-fair page: it is the one address
# here we know exists. Each event carries its own link from the feed, so
# this is only the row's.
SITE_URLS = [
    ("iacf", "https://www.iacf.co.uk/antiques-fair-calendar/"),
]

# Categories corrected after the fact. Applied only where the row still
# holds the old value, so a re-categorisation by hand survives. ensure()
# only ever inserts, so without this an existing row keeps what it was
# seeded with for ever.
CATEGORY_FIXES = [
    # Nothing here at present: the row that needed re-filing is retired.
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
    # Replaced by the single 'iacf' row above, which reads every venue
    # from the site's own combined feed. RETIRED rather than SUPERSEDED:
    # these leave no code source behind to be hidden, and their events
    # must go with them — nothing would refresh them once the row is
    # gone, so they would sit in the events list for ever, duplicating
    # the same fairs the new source now reports.
    ("iacf-newark", "replaced by the combined iacf feed"),
    ("iacf-ardingly", "replaced by the combined iacf feed"),
    ("iacf-shepton-mallet", "replaced by the combined iacf feed"),
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

    for name, site_url in SITE_URLS:
        db.execute(
            "UPDATE sources SET site_url = ? WHERE name = ? AND site_url = ''",
            (site_url, name))

    for name, was, becomes in CATEGORY_FIXES:
        db.execute(
            "UPDATE sources SET category = ? WHERE name = ? AND category = ?",
            (becomes, name, was))

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
