"""Source registry.

Wikidata supplies destinations (CC0 open data, one query per category);
English Heritage's own site supplies its properties and is the route to
event listings. National Trust scraping is disabled — the site serves a
bot-protection challenge instead of content, and we don't evade that; its
properties come from Wikidata instead. See each module's docstring.
"""

from .english_heritage import EnglishHeritage
from .wikidata import Wikidata

IMPLEMENTED = [Wikidata, EnglishHeritage]

# Present but deliberately not run:
#   national_trust.py  site blocks automated access (see its docstring)
# Researched, not yet implemented:
#   ngs.py       National Garden Scheme open days (garden events)
#   airfields.py air show calendars
