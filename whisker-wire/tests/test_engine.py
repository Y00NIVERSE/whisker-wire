"""Offline tests: no network needed. Run from whisker-wire/:  python -m unittest discover -s tests -v"""
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine  # noqa: E402
from signals import SIGNALS  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Acme (ACME) raises full-year guidance</title><link>https://example.com/a</link>
<description>&lt;p&gt;Acme said &lt;b&gt;revenue&lt;/b&gt; rose 14%.&lt;/p&gt;</description>
<pubDate>Sat, 26 Sep 2026 12:00:00 GMT</pubDate></item>
<item><title>No link here</title></item>
<item><title>Bad scheme</title><link>javascript:alert(1)</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>4 - ACME INC (0001234567) (Issuer)</title>
<link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/1234567/000112345626000123/0001123456-26-000123-index.htm"/>
<updated>2026-09-26T12:00:00-04:00</updated></entry>
<entry><title>4 - DOE JANE (0007654321) (Reporting)</title>
<link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/1234567/000112345626000123/0001123456-26-000123-index.htm"/>
<updated>2026-09-26T12:00:00-04:00</updated></entry></feed>"""

FORM4 = b"""<?xml version="1.0"?><ownershipDocument>
<issuer><issuerName>ACME INC</issuerName><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable>
<nonDerivativeTransaction><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>10000</value></transactionShares>
<transactionPricePerShare><value>12.50</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionCoding><transactionCode>A</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>500</value></transactionShares>
<transactionPricePerShare><value>0</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>"""


def sig_ids(text):
    return {s["id"] for s in engine.find_signals(text)}


class Parsing(unittest.TestCase):
    def test_rss_parses_and_drops_bad_items(self):
        items = engine.parse_feed(RSS)
        self.assertEqual(len(items), 1)  # no-link and javascript: items are dropped
        self.assertEqual(items[0]["summary"], "Acme said revenue rose 14%.")
        self.assertIsNotNone(items[0]["ts"])

    def test_atom_dedupes_issuer_and_reporting_entries(self):
        rows = engine.parse_edgar_atom(ATOM)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["acc"], "0001123456-26-000123")

    def test_entity_declarations_rejected(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel/></rss>'
        with self.assertRaises(ValueError):
            engine.parse_feed(bomb)

    def test_form4_purchase_only_counts_code_p(self):
        r = engine.parse_form4(FORM4)
        self.assertEqual((r["symbol"], r["insider"], r["role"]), ("ACME", "DOE JANE", "Chief Executive Officer"))
        self.assertEqual(r["buy_usd"], 125000)
        self.assertEqual(r["sell_usd"], 0)


class Safety(unittest.TestCase):
    def test_ssrf_guard(self):
        for bad in ("http://127.0.0.1/", "http://localhost/", "file:///etc/passwd", "ftp://example.com/",
                    "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://10.0.0.5/",
                    "https://example.com:8080/"):
            with self.assertRaises(ValueError, msg=bad):
                engine.assert_public(bad)


class Signals(unittest.TestCase):
    def test_every_pattern_compiles_and_has_copy(self):
        for s in SIGNALS:
            re.compile(s["pattern"], re.I)
            self.assertTrue(s["note"] and s["label"])
            self.assertNotIn("—", s["note"])  # house style: no em dashes

    def test_expected_matches(self):
        cases = {
            "CEO buys $2 million of shares after selloff": "insider-buy",
            "Acme raises full-year guidance on strong demand": "guidance-up",
            "Widget Corp cuts outlook as orders slow": "guidance-down",
            "Firm receives Nasdaq delisting notice": "distress",
            "Hindenburg publishes short report on Acme": "short-report",
            "Board approves $5 billion share repurchase program": "buyback",
            "Drugmaker wins FDA approval for pill": "fda",
            "Activist investor builds 6% stake in retailer": "activist",
            "CFO abruptly resigns ahead of earnings": "exec-exit",
            "Chief financial officer Dana Cole abruptly resigned on Thursday": "exec-exit",
        }
        for text, want in cases.items():
            self.assertIn(want, sig_ids(text), text)

    def test_delisting_threshold_is_not_distress(self):
        self.assertNotIn("distress", sig_ids("Poste falls short of Telecom Italia delisting threshold after takeover bid"))

    def test_tickers(self):
        self.assertEqual(engine.find_tickers("Merck (MRK) wins approval; CEO (CEO) said"), ["MRK"])
        self.assertEqual(engine.find_tickers("Buying $NVDA and (NASDAQ: AMD)"), ["AMD", "NVDA"])
        self.assertEqual(engine.find_tickers("Fed (FOMC) holds rates"), [])


def _item(title, pub, ts=None, summary=""):
    return {"title": title, "publisher": pub, "link": "https://x.test/" + re.sub(r"\W", "", title)[:20] + pub,
            "summary": summary, "ts": ts or time.time() - 600, "src_id": "t", "kind": "Wire"}


class Scoring(unittest.TestCase):
    def test_duplicates_cluster_and_count_publishers(self):
        now = time.time()
        items = [_item("Acme (ACME) raises full-year guidance", "Benzinga"),
                 _item("Acme raises full year guidance, shares jump", "Seeking Alpha"),
                 _item("Fed holds rates steady", "CNBC")]
        groups = engine.cluster(items)
        self.assertEqual(len(groups), 2)
        story = engine.build_story(next(g for g in groups if len(g["items"]) == 2), now)
        self.assertEqual(story["n_pub"], 2)
        self.assertTrue(story["corroborated"])
        self.assertEqual(story["tickers"], ["ACME"])

    def test_overlooked_needs_zero_mainstream_coverage(self):
        now = time.time()
        niche = engine.build_story(engine.cluster([_item("CEO buys $1 million of shares in Tiny Corp", "simplywall.st")])[0], now)
        main = engine.build_story(engine.cluster([_item("CEO buys $1 million of shares in Tiny Corp", "CNBC")])[0], now)
        self.assertTrue(niche["overlooked"])
        self.assertFalse(main["overlooked"])

    def test_question_headline_is_demoted(self):
        now = time.time()
        a = engine.build_story(engine.cluster([_item("Acme raises guidance", "Benzinga")])[0], now)
        b = engine.build_story(engine.cluster([_item("Did Acme just raise guidance?", "Benzinga")])[0], now)
        self.assertLess(b["score"], a["score"])

    def test_no_signal_never_urgent(self):
        s = engine.build_story(engine.cluster([_item("Local bakery opens second shop", "CNBC")])[0], time.time())
        self.assertEqual(s["level"], "normal")


class Radar(unittest.TestCase):
    base = dict(symbol="CHEAP", longName="Cheap Co", regularMarketPrice=10, regularMarketPreviousClose=9.8,
                fiftyTwoWeekHigh=16, fiftyTwoWeekLow=8.5, trailingPE=14, forwardPE=9,
                priceToBook=1.1, marketCap=5e9, averageAnalystRating="1.9 - Buy",
                regularMarketVolume=3e6, averageDailyVolume3Month=1.5e6, twoHundredDayAverage=11)

    def test_cheap_profitable_scores_high_with_reasons(self):
        r = engine.analyze_quote(dict(self.base), "undervalued_large_caps")
        self.assertGreaterEqual(r["score"], 70)
        self.assertTrue(r["good"] and r["warn"])
        self.assertAlmostEqual(r["off_high"], -37.5)

    def test_unprofitable_microcap_is_penalised(self):
        q = dict(self.base, trailingPE=None, forwardPE=None, priceToBook=None, marketCap=1e8)
        r = engine.analyze_quote(q, "undervalued_growth_stocks")
        self.assertLess(r["score"], 40)
        self.assertTrue(any("No profits" in w for w in r["warn"]))

    def test_negative_book_value_warns_and_scores_nothing_for_pb(self):
        r = engine.analyze_quote(dict(self.base, priceToBook=-5.2), "undervalued_growth_stocks")
        self.assertTrue(any("Negative book value" in w for w in r["warn"]))
        self.assertFalse(any("book value" in g for g in r["good"]))

    def test_crowded_shorts_capped(self):
        self.assertLessEqual(engine.analyze_quote(dict(self.base), "most_shorted_stocks")["score"], 45)

    def test_missing_prices_skipped(self):
        self.assertIsNone(engine.analyze_quote({"symbol": "X"}, "undervalued_large_caps"))


class Reader(unittest.TestCase):
    def test_extracts_article_paragraphs_and_skips_chrome(self):
        html = ("<html><head><title>T</title><meta property='og:title' content='Big News'></head><body>"
                "<nav><p>Navigation paragraph that should never be included in output at all.</p></nav>"
                "<article><p>First paragraph of the article, long enough to count as real prose.</p>"
                "<p>Second paragraph of the article, also long enough to be kept by the filter.</p>"
                "<p>Third paragraph of the article, again long enough to be considered content.</p></article>"
                "<footer><p>Footer paragraph that is long enough but must be skipped by the parser.</p></footer>"
                "</body></html>")
        p = engine._Extract()
        p.feed(html)
        self.assertEqual(len(p.p_art), 3)
        self.assertEqual(p.og, "Big News")
        self.assertFalse(any("Navigation" in t or "Footer" in t for t in p.p_all))


if __name__ == "__main__":
    unittest.main()
