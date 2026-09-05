"""Source registry — every source the scraper runs.

There is no other kind. A `sources` table used to hold listing sites as
rows, with a generic engine that picked an extractor by kind (ical,
jsonld, sitemap, browser, wpevents, auto), so adding a site was an INSERT
rather than a release. The idea was sound and the results were not: these
sites differ so much that reading one takes a parser written against it,
and rows added without that investigation reported an empty site for
ever. What survived from the table is here, written in code.

Wikidata supplies destinations (CC0 open data, one query per category),
National Trust properties among them; English Heritage's own site
supplies its properties and is the route to its event listings. Historic
Houses supplies the privately owned houses both of the big charities
leave out. Shuttleworth and Lamport Hall are single venues whose pages
carry nothing machine-readable — Lamport's dates state no year at all.
Waddesdon and NGS are the opposite: their pages carry nothing either, but
each publishes a JSON API, so they are read in a request or two rather
than crawled. UK Craft Fairs can only be rendered, never fetched, because
its server's headers are malformed. Food festivals is a blog roundup with
no postcode anywhere, placed by town through the gazetteer. IACF is one
iCal feed covering seven showgrounds. RHS is five big shows, each with
Event JSON-LD on its own page and none on the listing.
See each module's docstring.
"""

from .english_heritage import EnglishHeritage
from .foodfestivals import FoodFestivals
from .historic_houses import HistoricHouses
from .iacf import IACF
from .lamporthall import LamportHall
from .ngs import NGS
from .rhs import RHS
from .shuttleworth import Shuttleworth
from .ukcraftfairs import UKCraftFairs
from .waddesdon import Waddesdon
from .wikidata import Wikidata

IMPLEMENTED = [Wikidata, EnglishHeritage, HistoricHouses, Shuttleworth,
               UKCraftFairs, LamportHall, Waddesdon, FoodFestivals, NGS,
               IACF, RHS]

# Researched, not yet implemented:
#   airfields.py air show calendars
