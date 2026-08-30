"""Source registry.

Wikidata supplies destinations (CC0 open data, one query per category);
English Heritage's own site supplies its properties and is the route to
event listings. National Trust contributes events only — one listing page
per property — while its properties keep coming from Wikidata. That source
stops itself the moment the site answers with a bot-protection challenge
rather than working around one. Historic Houses supplies the privately
owned houses both of the big charities leave out. See each module's
docstring.
"""

from .english_heritage import EnglishHeritage
from .historic_houses import HistoricHouses
from .national_trust import NationalTrust
from .wikidata import Wikidata

IMPLEMENTED = [Wikidata, EnglishHeritage, NationalTrust, HistoricHouses]

# Researched, not yet implemented:
#   ngs.py       National Garden Scheme open days (garden events)
#   airfields.py air show calendars
