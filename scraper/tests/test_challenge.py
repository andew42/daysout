"""Telling a refusal apart from an empty page.

A bot-protection interstitial and a page with nothing on it look the same
to a parser and mean opposite things: one is the site declining to serve
us, worth reporting as such and retrying another day, the other means our
patterns are wrong. Confusing the two has cost real time here.

These checks arrived with the National Trust source and outlived it. That
source is gone; the detector is not, because `feedhunt` reports on any
site and several sources say "nobody is turning us away" on the strength
of it.
"""

import unittest

from daysout_scraper.fetch import looks_like_a_challenge

CHALLENGE_PAGE = """<html><head><title>Request unsuccessful</title></head>
  <body>Incapsula incident ID: 1234-5678. Radware Bot Manager Captcha.
  </body></html>"""

REAL_PAGE = """<html><head><title>Events at Stowe Gardens</title></head>
  <body><h1>What's on</h1>
    <script type="application/ld+json">{"@type": "Event"}</script>
  </body></html>"""


class TestLooksLikeAChallenge(unittest.TestCase):

    def test_an_interstitial_is_recognised(self):
        self.assertTrue(looks_like_a_challenge(CHALLENGE_PAGE))

    def test_an_ordinary_page_is_not(self):
        self.assertFalse(looks_like_a_challenge(REAL_PAGE))

    def test_each_marker_on_its_own(self):
        for marker in ["Radware", "captcha-delivery", "Request unsuccessful",
                       "Incapsula", "Are you a human",
                       "Enable JavaScript and cookies to continue"]:
            self.assertTrue(looks_like_a_challenge(f"<html>{marker}</html>"),
                            marker)

    def test_only_the_start_of_the_document_counts(self):
        # A real page may mention one of these words in passing — a news
        # item about CAPTCHAs is not a refusal. A challenge says it up
        # front and carries little else.
        buried = "<html><body>" + ("garden open day. " * 400) + "incapsula"
        self.assertFalse(looks_like_a_challenge(buried))

    def test_an_empty_body_is_not_a_refusal(self):
        self.assertFalse(looks_like_a_challenge(""))


if __name__ == "__main__":
    unittest.main()
