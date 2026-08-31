"""JSON-LD strings arrive HTML-escaped, and have to be decoded.

Script content is raw text in HTML5: the parser decodes entities in a
page's markup and leaves them exactly as written inside
<script type="application/ld+json">. A site whose templating escapes the
block anyway therefore hands us "Members&#39; Event", and since the
frontend escapes what it interpolates — quite correctly — an entity left
in here is one the reader actually sees, on the events list and the map.

Seen live on the house server, 31 Aug 2026: English Heritage destinations
stored as "Kit&#39;s Coty House and Little Kit&#39;s Coty House" and
"Medieval Merchant&#39;s House".
"""

import unittest

from bs4 import BeautifulSoup

from daysout_scraper import jsonld

PAGE = """<html><body>
<p>Members&#39; Event in the markup</p>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event",
 "name":"Members&#39; Event",
 "description":"Tea &amp; cake in the undercroft",
 "url":"https://www.english-heritage.org.uk/e?a=1&amp;b=2",
 "startDate":"2026-09-05",
 "location":{"@type":"Place","name":"Kit&#39;s Coty House",
   "address":{"@type":"PostalAddress","postalCode":"ME20 7EZ"}}}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Place",
 "name":"Medieval Merchant&#39;s House",
 "geo":{"@type":"GeoCoordinates","latitude":50.89854,"longitude":-1.405456}}
</script>
</body></html>"""

URL = "https://www.english-heritage.org.uk/visit/places/kits-coty/"


class TestWhyTheEntitiesSurvive(unittest.TestCase):

    def test_the_parser_decodes_markup_but_not_script_content(self):
        # This is the whole reason _text has to unescape: the same entity
        # is decoded in one place and not the other.
        soup = BeautifulSoup(PAGE, "html.parser")
        self.assertEqual(soup.p.get_text(), "Members' Event in the markup")
        self.assertIn("Members&#39; Event", jsonld.extract_objects(PAGE)[0]["name"])


class TestAnEventsText(unittest.TestCase):

    def event(self):
        return jsonld.parse_event(jsonld.extract_objects(PAGE)[0], URL)

    def test_the_title_is_decoded(self):
        self.assertEqual(self.event()["title"], "Members' Event")

    def test_the_description_is_decoded(self):
        self.assertEqual(self.event()["description"], "Tea & cake in the undercroft")

    def test_the_venue_name_is_decoded(self):
        # It becomes a destination name and a map pin.
        self.assertEqual(self.event()["location_name"], "Kit's Coty House")

    def test_an_escaped_ampersand_in_a_url_is_decoded(self):
        # "&amp;" between query parameters is HTML escaping, not part of
        # the address.
        self.assertEqual(self.event()["url"],
                         "https://www.english-heritage.org.uk/e?a=1&b=2")

    def test_nothing_else_is_disturbed(self):
        event = self.event()
        self.assertEqual(event["start_date"], "2026-09-05")
        self.assertEqual(event["location_postcode"], "ME20 7EZ")


class TestAPlacesText(unittest.TestCase):

    def test_the_name_is_decoded(self):
        place = jsonld.parse_place(jsonld.extract_objects(PAGE)[1], URL)
        self.assertEqual(place["name"], "Medieval Merchant's House")


class TestDecodingIsSingleNotRepeated(unittest.TestCase):
    """Once, because that is what the data is: English Heritage escapes
    singly. Unescaping again would turn text that means "&amp;" into "&"."""

    def test_a_doubly_escaped_string_decodes_one_level(self):
        self.assertEqual(jsonld._text("Bed &amp;amp; Breakfast"),
                         "Bed &amp; Breakfast")

    def test_plain_text_is_untouched(self):
        self.assertEqual(jsonld._text("Tea & cake"), "Tea & cake")

    def test_an_empty_value_stays_empty(self):
        self.assertEqual(jsonld._text(None), "")
        self.assertEqual(jsonld._text(""), "")


if __name__ == "__main__":
    unittest.main()
