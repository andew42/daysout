"""Reading a page in the encoding it is actually written in.

`requests` follows RFC 2616 and treats "text/html" with no charset as
ISO-8859-1. That default is two decades stale, and Blenheim is the case
in point: it serves UTF-8 under a bare "content-type: text/html", so
"Salon Privé" arrived as "Salon PrivÃ©" and would have been stored that
way. The frontend escapes what it interpolates, so mojibake in the
database is mojibake on the page.

These check the rule, not requests: the header wins when it says
anything, the document is asked when it does not, and UTF-8 is the
fallback rather than Latin-1.
"""

import unittest

from daysout_scraper.fetch import decoded

BODY = '<html><head><meta charset="utf-8"></head><body>Salon Privé</body></html>'


class FakeResponse:
    """Enough of requests.Response for the decision under test.

    `text` deliberately decodes as Latin-1, which is what requests does
    for a headerless text/html — so a test that comes back with the right
    characters proves the header was not believed.
    """

    def __init__(self, body, content_type="text/html", encoding="iso-8859-1"):
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"content-type": content_type}
        self._encoding = encoding

    @property
    def text(self):
        return self.content.decode(self._encoding, errors="replace")


class TestDecoding(unittest.TestCase):

    def test_a_headerless_page_is_read_as_the_document_says(self):
        self.assertIn("Salon Privé", decoded(FakeResponse(BODY)))

    def test_the_header_is_believed_when_it_says_anything(self):
        # A server that declares its charset knows better than the markup,
        # and requests has already applied it.
        response = FakeResponse(BODY, content_type="text/html; charset=utf-8",
                                encoding="utf-8")
        self.assertIn("Salon Privé", decoded(response))

    def test_a_page_that_declares_nothing_is_assumed_utf8(self):
        plain = "<html><body>Salon Privé</body></html>"
        self.assertIn("Salon Privé", decoded(FakeResponse(plain)))

    def test_a_page_that_really_is_latin1_is_honoured(self):
        body = ('<html><head><meta charset="iso-8859-1"></head>'
                '<body>Salon Privé</body></html>').encode("iso-8859-1")
        self.assertIn("Salon Privé", decoded(FakeResponse(body)))

    def test_a_charset_nobody_has_heard_of_does_not_raise(self):
        body = '<html><head><meta charset="totally-made-up"></head><body>x</body></html>'
        self.assertIn("x", decoded(FakeResponse(body)))

    def test_bytes_that_are_not_valid_anywhere_are_replaced_not_fatal(self):
        # One bad byte in a long page should cost that character, not the
        # whole source's run.
        body = b'<html><body>caf\xff and more text</body></html>'
        self.assertIn("and more text", decoded(FakeResponse(body)))


if __name__ == "__main__":
    unittest.main()
