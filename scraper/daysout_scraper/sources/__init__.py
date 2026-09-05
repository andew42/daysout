"""Source registry.

Wikidata supplies destinations (CC0 open data, one query per category);
English Heritage's own site supplies its properties and is the route to
event listings. National Trust contributes events only — one listing page
per property — while its properties keep coming from Wikidata. That source
stops itself the moment the site answers with a bot-protection challenge
rather than working around one. Historic Houses supplies the privately
owned houses both of the big charities leave out, and Shuttleworth its
own air shows — one venue whose pages carry no structured data at all.
UK Craft Fairs is a listing site that can only be rendered, never fetched,
because its server's headers are malformed; its calendar is the index and
each fair's own page carries the Event JSON-LD and the postcode. Lamport
Hall is a second single venue with no structured data, and the only one
whose dates state no year at all. Waddesdon is the opposite case: its
pages carry nothing either, but the site publishes its own events REST
API, so it is read in two requests rather than crawled.
See each module's docstring.
"""

from .english_heritage import EnglishHeritage
from .foodfestivals import FoodFestivals
from .historic_houses import HistoricHouses
from .lamporthall import LamportHall
from .national_trust import NationalTrust
from .shuttleworth import Shuttleworth
from .ukcraftfairs import UKCraftFairs
from .waddesdon import Waddesdon
from .wikidata import Wikidata

IMPLEMENTED = [Wikidata, EnglishHeritage, NationalTrust, HistoricHouses,
               Shuttleworth, UKCraftFairs, LamportHall, Waddesdon,
               FoodFestivals]

# Researched, not yet implemented:
#   ngs.py       National Garden Scheme open days (garden events)
#   airfields.py air show calendars
