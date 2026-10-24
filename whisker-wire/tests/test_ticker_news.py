"""A company's news search: US tickers are fine as search words, 'BN4.SI' is not, so other markets search by name."""
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine  # noqa: E402


def feed(*titles):
    items = "".join(f"<item><title>{t} - Biz Times</title><link>https://example.com/{i}</link>"
                    f"<pubDate>Sat, 24 Oct 2026 01:00:00 GMT</pubDate><source>Biz Times</source></item>"
                    for i, t in enumerate(titles))
    return ("<rss><channel>" + items + "</channel></rss>").encode()


class Names(unittest.TestCase):
    def test_legal_suffixes_are_dropped_and_shouting_is_softened(self):
        self.assertEqual(engine.news_names({"shortName": "Keppel", "longName": "Keppel Ltd."}), ["Keppel"])
        self.assertEqual(engine.news_names({"shortName": "TENCENT", "longName": "Tencent Holdings Limited"}), ["Tencent"])
        self.assertEqual(engine.news_names({"shortName": "DBS", "longName": "DBS Group Holdings Ltd"}), ["DBS"])
        self.assertEqual(engine.news_names({"longName": "Sembcorp Industries Ltd"}), ["Sembcorp Industries"])

    def test_missing_or_silly_names_give_nothing(self):
        self.assertEqual(engine.news_names({}), [])
        self.assertEqual(engine.news_names({"shortName": "X" * 80}), [])


class Search(unittest.TestCase):
    def run_search(self, sym, meta, titles):
        seen = []

        def fake_get(url, *a, **k):
            seen.append(urllib.parse.unquote(url))
            return feed(*titles), None

        with mock.patch.object(engine, "http_get", fake_get):
            out = engine._ticker_news(sym, meta)
        return out, seen

    def test_a_singapore_ticker_is_searched_by_name_in_the_singapore_edition(self):
        out, seen = self.run_search("BN4.SI", {"shortName": "Keppel", "longName": "Keppel Ltd."},
                                    ["Keppel wins power deal", "Keppel profit rises", "Keppel sells stake", "Unrelated story"])
        self.assertIn('"Keppel"', seen[0])
        self.assertNotIn("BN4", seen[0])
        self.assertIn("gl=SG", seen[0])
        self.assertEqual([n["title"] for n in out], ["Keppel wins power deal", "Keppel profit rises", "Keppel sells stake"])

    def test_a_us_ticker_keeps_the_ticker_search(self):
        out, seen = self.run_search("AAPL", {"shortName": "Apple Inc.", "longName": "Apple Inc."}, ["a", "b", "c"])
        self.assertIn('"AAPL" stock', seen[0])
        self.assertIn("gl=US", seen[0])
        self.assertEqual(len(out), 3)

    def test_too_few_results_widens_the_window_once(self):
        out, seen = self.run_search("BN4.SI", {"shortName": "Keppel"}, ["Keppel one"])
        self.assertEqual(len(seen), 2)
        self.assertIn("when:7d", seen[0])
        self.assertIn("when:30d", seen[1])

    def test_when_few_headlines_name_the_company_the_rest_are_kept(self):
        out, _ = self.run_search("BN4.SI", {"shortName": "Keppel"}, ["Power prices rise", "Gas supply tightens", "Keppel says"])
        self.assertEqual(len(out), 3)


class Endpoint(unittest.TestCase):
    def test_a_dead_chart_still_returns_an_empty_answer_not_an_error(self):
        engine._cache.clear()
        with mock.patch.object(engine, "_chart", side_effect=OSError("down")), \
                mock.patch.object(engine, "http_get", side_effect=OSError("down")):
            r = engine.get_ticker("ZZZ.SI")
        self.assertEqual(r, {"symbol": "ZZZ.SI", "spark": [], "news": []})


if __name__ == "__main__":
    unittest.main()
