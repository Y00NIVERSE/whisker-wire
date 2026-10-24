"""Offline tests for the multi-market support. Run: python -m unittest discover -s tests"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine  # noqa: E402
import markets  # noqa: E402
import server  # noqa: E402

OTHER = [m for m in markets.MARKETS if m != "us"]


class Config(unittest.TestCase):
    def test_expected_markets_exist(self):
        for m in ("us", "cn", "hk", "sg", "uk", "jp", "in", "au", "ca", "eu"):
            self.assertIn(m, markets.MARKETS)

    def test_unknown_market_falls_back_to_default(self):
        self.assertEqual(markets.valid_market("zz"), "us")
        self.assertEqual(markets.valid_market(None), "us")
        self.assertEqual(server._mk({"market": ["hk"]}), "hk")
        self.assertEqual(server._mk({"market": ["<script>"]}), "us")
        self.assertEqual(server._mk({}), "us")

    def test_every_other_market_is_complete(self):
        for m in OTHER:
            c = markets.MARKETS[m]
            self.assertTrue(c["sources"], m)
            self.assertTrue(any(s.get("gn") for s in c["sources"]), f"{m} needs search sources")
            self.assertTrue(c["strip"], m)
            self.assertTrue(c["screen"]["exchanges"] and c["screen"]["currencies"], m)
            self.assertTrue(c["filings"], m)
            self.assertIsNotNone(c["kw"], m)

    def test_source_ids_are_unique_across_markets(self):
        ids = [s["id"] for s in engine.SOURCES] + [s["id"] for m in OTHER for s in markets.MARKETS[m]["sources"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_strip_symbols_are_valid_for_the_chart_api(self):
        for m in OTHER:
            for sym, label in markets.MARKETS[m]["strip"]:
                self.assertRegex(sym, engine.SYM_RE.pattern, sym)
                self.assertTrue(label)

    def test_market_list_shape(self):
        rows = markets.market_list()
        self.assertEqual(rows[0]["id"], "us")
        self.assertTrue(all({"id", "name", "short", "filings", "has_screen"} <= set(r) for r in rows))

    def test_sources_use_https_or_google_news(self):
        for m in OTHER:
            for s in markets.MARKETS[m]["sources"]:
                self.assertTrue(s["url"].startswith("https://"), s["id"])


class Tickers(unittest.TestCase):
    def test_exchange_prefixed_tickers_become_yahoo_symbols(self):
        cases = {
            "Tencent (HKG: 0700) gains": "0700.HK",
            "Tencent (HKEX: 00700) gains": "0700.HK",
            "DBS Group (SGX: D05) results": "D05.SI",
            "Vodafone (LON: VOD) falls": "VOD.L",
            "Moutai (SHA: 600519) rises": "600519.SS",
            "Toyota (TYO: 7203) profit": "7203.T",
            "Infosys (NSE: INFY) upgraded": "INFY.NS",
            "BHP (ASX: BHP) dividend": "BHP.AX",
            "Shopify (TSX: SHOP) guidance": "SHOP.TO",
        }
        for text, want in cases.items():
            self.assertIn(want, engine.find_tickers(text), text)

    def test_yahoo_style_symbols_in_text(self):
        self.assertIn("0700.HK", engine.find_tickers("Tencent (0700.HK) shares rose 4%"))
        self.assertIn("D05.SI", engine.find_tickers("DBS D05.SI hits record"))
        self.assertIn("RELIANCE.NS", engine.find_tickers("RELIANCE.NS gains"))

    def test_us_tickers_still_work_and_prose_is_not_a_ticker(self):
        self.assertEqual(engine.find_tickers("Apple (NASDAQ: AAPL) and $NVDA"), ["AAPL", "NVDA"])
        self.assertEqual(engine.find_tickers("the U.S. economy and e.g. the U.K. market"), [])

    def test_bad_hk_and_china_codes_are_rejected(self):
        self.assertIsNone(engine.yahoo_symbol("HKG", "ABC"))
        self.assertIsNone(engine.yahoo_symbol("SHA", "ABC"))
        self.assertEqual(engine.yahoo_symbol("HKG", "00005"), "0005.HK")

    def test_company_short_names_and_jargon_are_not_tickers(self):
        for word in ("DBS", "OCBC", "UOB", "DRHP", "OFS", "FTSE", "SEBI", "HKEX", "RNS"):
            self.assertEqual(engine.find_tickers(f"Group ({word}) reports"), [], word)


class Relevance(unittest.TestCase):
    def test_search_results_must_be_local(self):
        kw = markets.MARKETS["hk"]["kw"]
        self.assertTrue(kw.search("Tencent shares jump 4% on gaming approvals"))
        self.assertTrue(kw.search("Hang Seng falls as property stocks slide"))
        self.assertFalse(kw.search("Baillie Gifford UK Growth Trust (BGUK) Executes Share Buyback at 213p"))

    def test_feed_keeps_regional_outlets_but_filters_search_noise(self):
        engine._cache.clear()
        now = time.time()

        def item(title, pub, gn):
            return {"title": title, "link": "https://x.test/" + str(abs(hash(title))), "summary": "", "ts": now - 300,
                    "source": pub if gn else "", "publisher": pub, "src_id": "t", "kind": "Search" if gn else "Mainstream"}

        direct = {"id": "d", "name": "SCMP", "kind": "Mainstream", "tier": "niche", "url": "https://scmp.test"}
        search = {"id": "g", "name": "Search: x", "kind": "Search", "tier": "niche", "gn": True, "url": "https://gn.test"}
        rows = {"d": [item("Solar startup raises funds", "SCMP", False)],
                "g": [item("Tencent buyback lifts shares", "Reuters", True), item("UK trust buyback 213p", "RNS", True)]}
        old_src, old_fetch, old_par = markets.MARKETS["hk"]["sources"], engine.fetch_source, engine.run_parallel
        try:
            markets.MARKETS["hk"]["sources"] = [direct, search]
            engine.fetch_source = lambda src: (src, rows[src["id"]], {"id": src["id"], "name": src["name"], "kind": src["kind"], "ok": True, "count": 1, "ms": 1})
            engine.run_parallel = lambda fn, items, **k: [fn(i) for i in items]
            titles = {s["title"] for s in engine.get_feed("hk")["stories"]}
        finally:
            markets.MARKETS["hk"]["sources"], engine.fetch_source, engine.run_parallel = old_src, old_fetch, old_par
            engine._cache.clear()
        self.assertIn("Solar startup raises funds", titles)        # regional outlet: kept even with no local keyword
        self.assertIn("Tencent buyback lifts shares", titles)      # search result that is local: kept
        self.assertNotIn("UK trust buyback 213p", titles)          # search result that is not: dropped


class Radar(unittest.TestCase):
    def q(self, sym, cur, mcap, fpe=8, pb=1.0):
        return {"symbol": sym, "longName": sym, "currency": cur, "regularMarketPrice": 60, "regularMarketPreviousClose": 59,
                "fiftyTwoWeekHigh": 100, "fiftyTwoWeekLow": 55, "trailingPE": 12, "forwardPE": fpe, "priceToBook": pb,
                "marketCap": mcap, "averageAnalystRating": "2.0 - Buy", "twoHundredDayAverage": 70}

    def test_groups_split_by_size_and_keep_currency(self):
        quotes = [self.q(f"L{i}.HK", "HKD", 1e10) for i in range(engine.LARGE_CAP_COUNT)] + \
                 [self.q(f"M{i}.HK", "HKD", 1e9) for i in range(30)]
        picks = engine.rank_market_screen(quotes)
        self.assertEqual({p["list"] for p in picks}, {"large", "mid"})
        self.assertEqual({p["currency"] for p in picks}, {"HKD"})
        self.assertLessEqual(len(picks), 28)
        self.assertEqual([p["score"] for p in picks], sorted((p["score"] for p in picks), reverse=True))

    def test_micro_cap_warning_only_applies_to_dollar_stocks(self):
        usd = engine.analyze_quote(self.q("A", "USD", 1e8), "undervalued_large_caps")
        jpy = engine.analyze_quote(self.q("B", "JPY", 1e8), "large")   # 1e8 yen is not a micro-cap
        self.assertTrue(any("Micro-cap" in w for w in usd["warn"]))
        self.assertFalse(any("Micro-cap" in w for w in jpy["warn"]))

    def test_wording_is_currency_neutral(self):
        r = engine.analyze_quote(self.q("A", "SGD", 5e9, fpe=8), "large")
        self.assertFalse(any("$" in g for g in r["good"]))


class Undated(unittest.TestCase):
    def test_items_without_a_date_are_not_treated_as_fresh(self):
        xml = (b'<?xml version="1.0"?><rss><channel>'
               b'<item><title>Dated</title><link>https://x.test/a</link><pubDate>Sat, 26 Sep 2026 12:00:00 GMT</pubDate></item>'
               b'<item><title>Undated</title><link>https://x.test/b</link></item></channel></rss>')
        engine.http_get, real = (lambda *a, **k: (xml, "utf-8")), engine.http_get
        try:
            _s, items, h = engine.fetch_source({"id": "t", "name": "T", "kind": "Wire", "url": "https://x.test/feed"})
        finally:
            engine.http_get = real
        self.assertEqual([i["title"] for i in items], ["Dated"])


if __name__ == "__main__":
    unittest.main()
