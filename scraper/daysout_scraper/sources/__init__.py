"""Source registry. A source is implemented when it can actually be scraped;
placeholders document where the next ones should come from."""

from .english_heritage import EnglishHeritage
from .national_trust import NationalTrust

# Order matters only for log readability.
IMPLEMENTED = [NationalTrust, EnglishHeritage]

# Researched but not yet implemented — see each module's docstring:
#   ngs.py       National Garden Scheme open days (garden events)
#   airfields.py Aviation museums and air show calendars
