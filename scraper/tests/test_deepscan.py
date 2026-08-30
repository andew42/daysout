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
