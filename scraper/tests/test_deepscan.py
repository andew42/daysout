"""Why does a page carry no dates? Three answers worth telling apart.

A rendered page that grew by 130 KB and still had no dates in it is not
self-explanatory. Either its listing is inside an iframe (invisible to
the renderer's page.content()), or it is behind a search form and was
never asked for, or it genuinely never arrived. Guessing between those is
how afternoons disappear.
"""

import unittest

from daysout_scraper import domscan

LISTING = """
<html><body>
  <ul>
    <li class="garden-card"><h3>The Old Rectory</h3><p>Open Saturday, teas served</p></li>
    <li class="garden-card"><h3>Hill House</h3><p>Open Sunday, plants for sale</p></li>
    <li class="garden-card"><h3>Manor Cottage</h3><p>Open all weekend, dogs welcome</p></li>
    <li class="garden-card"><h3>Yew Tree Farm</h3><p>Open Saturday only, no dogs</p></li>
    <li class="garden-card"><h3>Willow Bank</h3><p>Open Sunday afternoon, wheelchair access</p></li>
  </ul>
</body></html>"""

BEHIND_A_FORM = """
<html><body>
  <form action="/find"><input name="postcode"><input type="submit"></form>
  <div id="results"></div>
</body></html>"""

IN_AN_IFRAME = """
<html><body>
  <iframe src="https://calendar.example.org/embed" title="What's on"></iframe>
</body></html>"""


class TestDeepScan(unittest.TestCase):

    def test_a_present_listing_shows_as_repeated_blocks(self):
        report = domscan.deep_scan(LISTING)
        names = {name for name, _, _ in report["repeated"]}
        self.assertIn("garden-card", names)
        count = next(c for n, c, _ in report["repeated"] if n == "garden-card")
        self.assertEqual(count, 5)

    def test_a_search_form_is_reported(self):
        report = domscan.deep_scan(BEHIND_A_FORM)
        self.assertEqual(len(report["forms"]), 1)
        self.assertIn("postcode", report["forms"][0][1])
        # And there is no listing to be found, which is the point.
        self.assertEqual(report["repeated"], [])

    def test_an_iframe_is_reported(self):
        report = domscan.deep_scan(IN_AN_IFRAME)
        self.assertEqual(len(report["iframes"]), 1)
        self.assertIn("calendar.example.org", report["iframes"][0][0])

    def test_the_three_cases_read_differently(self):
        described = [domscan.describe_deep(domscan.deep_scan(html))
                     for html in (LISTING, BEHIND_A_FORM, IN_AN_IFRAME)]
        self.assertIn("garden-card", described[0])
        self.assertIn("form action=/find", described[1])
        self.assertIn("iframes: none", described[0])
        self.assertIn("no repeated row-shaped content", described[1])


class TestDateContext(unittest.TestCase):
    """Where a date sits, not just that one is present.

    A Shuttleworth event page carries seven date-looking phrases: the
    event's own, other events' in a carousel, and opening times. "Has
    date-looking text" cannot tell them apart; the enclosing element can.
    """

    PAGE = """<html><body>
      <h1>Military Air Show</h1>
      <div class="panel--content"><span class="event-date">6 September</span></div>
      <div class="opening"><p>Open today: 09:00 - 17:00 until 4 October</p></div>
      <ul class="other-events">
        <li><a href="/events/x"><span class="event-date">31 October</span></a></li>
      </ul>
    </body></html>"""

    def test_it_reports_the_element_each_date_sits_in(self):
        rows = domscan.date_context(self.PAGE)
        found = {(phrase, tag, identifier)
                 for tag, identifier, phrase, _ in rows}
        self.assertIn(("6 September", "span", "event-date"), found)
        self.assertIn(("4 October", "p", ""), found)

    def test_scripts_are_not_mistaken_for_content(self):
        page = ('<html><body><script>var d = "6 September"</script>'
                '<p class="when">7 September</p></body></html>')
        rows = domscan.date_context(page)
        self.assertEqual([(r[2], r[1]) for r in rows], [("7 September", "when")])
