"""Finding a UK postcode in text.

The postcode is the one field that turns an event into something sortable
by distance — it is all the local Code-Point Open table can geocode — so
it is worth digging out of prose when a site publishes no structured
address. Sites put it in the venue line ("Bolsover Castle, Castle Street,
Bolsover, S44 6PR"), in the description, or nowhere at all.
"""

import re

# Outward code (A9, A99, A9A, AA9, AA99, AA9A) then the inward code.
POSTCODE_RE = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.IGNORECASE)


def find(*texts):
    """The first postcode in any of these strings, normalised, or ''."""
    for text in texts:
        if not text:
            continue
        match = POSTCODE_RE.search(text)
        if match:
            return f"{match.group(1).upper()} {match.group(2).upper()}"
    return ""
