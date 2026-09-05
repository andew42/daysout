"""Source registry.

Wikidata supplies destinations (CC0 open data, one query per category),
National Trust properties among them; English Heritage's own site supplies
its properties and is the route to event listings. Historic Houses supplies
the privately owned houses both of the big charities leave out, and
Shuttleworth its own air shows — one venue whose pages carry no structured
data at all. UK Craft Fairs is a listing site that can only be rendered,
never fetched, because its server's headers are malformed; its calendar is
the index and each fair's own page carries the Event JSON-LD and the
postcode. Lamport Hall is a second single venue with no structured data,
and the only one whose dates state no year at all. Waddesdon is the
opposite case: its pages carry nothing either, but the site publishes its
own events REST API, so it is read in two requests rather than crawled.
Food festivals is a blog roundup with no postcode anywhere, placed by town
through the gazetteer. NGS reads open gardens from the find-a-garden API.
See each module's docstring.

There was a National Trust events source here. It never contributed: the
site answers automated clients with a bot-protection challenge, and we do
not work around one. It has been removed rather than kept waiting for that
to change — NT properties still reach the map from Wikidata, which is
where they always came from.
"""

from .english_heritage import EnglishHeritage
from .foodfestivals import FoodFestivals
from .historic_houses import HistoricHouses
from .lamporthall import LamportHall
from .ngs import NGS
from .shuttleworth import Shuttleworth
from .ukcraftfairs import UKCraftFairs
from .waddesdon import Waddesdon
from .wikidata import Wikidata

IMPLEMENTED = [Wikidata, EnglishHeritage, HistoricHouses,
               Shuttleworth, UKCraftFairs, LamportHall, Waddesdon,
               FoodFestivals, NGS]

# Researched, not yet implemented:
#   airfields.py air show calendars
