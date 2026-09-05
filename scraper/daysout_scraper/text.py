"""Turning somebody else's markup into the text we store.

Every string that reaches the database came out of another site's
template, and templates escape. `plain` is the one place that undoes it,
so a name shows as "Knights' Tournament" on the map rather than
"Knights&#39; Tournament" — which is what the reader actually sees, since
the frontend quite correctly escapes what it interpolates.

It decodes **twice**: the WordPress REST API double-encodes, so
"Knights&amp;#39; Tournament" survives one pass as "Knights&#39;
Tournament". Stripping tags first with the parser and unescaping after
covers both a value that is markup and one that is merely escaped.

This lived in sources/feeds.py, which read sources out of a database
table. That engine is gone — every source is written in code now — but
the escaping problem belongs to anybody reading anybody else's site.
"""

import html

from bs4 import BeautifulSoup


def plain(value):
    """WordPress gives a string or {'rendered': '<p>…</p>'}; want the text."""

    if isinstance(value, dict):
        value = value.get("rendered", "")
    text = str(value or "")
    text = " ".join(BeautifulSoup(text, "html.parser").get_text(" ").split())
    return " ".join(html.unescape(text).split())
