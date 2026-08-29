"""Candidate event sources seeded into the `sources` table.

These are starting points, not proven feeds. Which of them actually
publish machine-readable events is decided by running discovery against
them (`python3 -m daysout_scraper.discover`) on a machine that can reach
them, and the answer is recorded in each row's last_status. A site that
turns out to publish nothing usable stays in the table, disabled, so the
next person does not waste time rediscovering that.

Rows are inserted if absent and never overwritten, so anything you add or
disable by hand survives an upgrade.
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
    ("historic-houses", "https://www.historichouses.org/whats-on/",
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
    ("rhs-events", "https://www.rhs.org.uk/events",
     "auto", "garden", "RHS shows and garden events"),
]


def ensure(db):
    """Insert any candidate that isn't in the table yet."""
    added = 0
    for name, url, kind, category, notes in CANDIDATES:
        cursor = db.execute(
            """INSERT OR IGNORE INTO sources
                 (name, url, kind, category, enabled, notes, added)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (name, url, kind, category, notes, dbmod.now()))
        added += cursor.rowcount
    db.commit()
    return added
