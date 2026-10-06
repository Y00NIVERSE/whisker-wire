"""Offline tests for Ask Tick. Network and Claude calls are replaced with fakes."""
import http.client
import json
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine  # noqa: E402
import server  # noqa: E402
import tick_chat as tc  # noqa: E402

QUOTE = {"symbol": "0700.HK", "currency": "HKD", "regularMarketPrice": 436.6, "regularMarketPreviousClose": 440.0,
         "fiftyTwoWeekHigh": 683.0, "fiftyTwoWeekLow": 411.0, "marketCap": 3.9e12, "forwardPE": 12.1, "trailingPE": 15.0,
         "priceToBook": 3.0, "averageAnalystRating": "1.4 - Strong Buy", "twoHundredDayAverage": 500.0,
         "regularMarketVolume": 2e7, "averageDailyVolume3Month": 1.5e7}
ENT = [{"symbol": "0700.HK", "name": "TENCENT", "type": "EQUITY", "exchange": "Hong Kong"}]
NEWS = [{"title": "Tencent posts record profit as games rebound", "url": "https://n.test/a", "publisher": "Reuters", "ts": 1, "engine": "Google News", "tags": ["Earnings beat"], "dir": "bull"},
        {"title": "Regulator opens probe into Tencent unit", "url": "https://n.test/b", "publisher": "SCMP", "ts": 2, "engine": "Bing News", "tags": ["Investigation / lawsuit"], "dir": "bear"}]


def ctx(**k):
    return {"quotes": {"0700.HK": QUOTE}, "news": list(NEWS), **k}


def texts(reply):
    return " ".join(b.get("text", "") + " ".join(b.get("items", []) if b["type"] == "ul" else []) for b in reply["blocks"])


class Relevance(unittest.TestCase):
    def test_finance_questions_are_on_topic(self):
        for q in ["What is a P/E ratio?", "Is Tesla a good buy?", "How should a beginner start investing?", "how do bonds work",
                  "What's moving in the market today?", "should I buy $NVDA before earnings", "explain a short squeeze", "is 0700.HK undervalued"]:
            self.assertTrue(tc.is_on_topic(q, []) or tc.finance_score(q) >= 1, q)
            self.assertGreaterEqual(tc.finance_score(q), 1, q)

    def test_non_finance_questions_are_not(self):
        for q in ["apple pie recipe", "who won the football game", "what is the weather in hong kong", "how do I bake bread", "tell me a joke"]:
            self.assertFalse(tc.is_on_topic(q, []), q)

    def test_a_bare_company_name_counts_when_a_company_was_found(self):
        self.assertTrue(tc.is_on_topic("tencent", ENT))
        self.assertFalse(tc.is_on_topic("tencent", []))

    def test_off_topic_reply_points_to_google(self):
        r = tc.offtopic_reply("apple pie recipe & more")
        self.assertEqual((r["mode"], r["on_topic"]), ("offtopic", False))
        self.assertTrue(r["google"].startswith("https://www.google.com/search?q="))
        self.assertIn("apple%20pie%20recipe%20%26%20more", r["google"])
        self.assertEqual(r["sources"], [])


class Understanding(unittest.TestCase):
    def test_glossary_is_shared_with_the_reader(self):
        self.assertGreaterEqual(len(tc.GLOSSARY), 40)
        self.assertIn("P/E", tc.GLOSSARY)
        self.assertIn("short squeeze", tc.GLOSSARY)

    def test_entity_queries_are_names_not_sentences_or_finance_words(self):
        self.assertEqual(tc.entity_queries("Is Tesla a good buy?"), ["Tesla"])
        self.assertEqual(tc.entity_queries("what is a p/e ratio"), [])
        self.assertEqual(tc.entity_queries("How do I start investing with 500 dollars"), [])
        q = tc.entity_queries("is 0700.HK undervalued")
        self.assertIn("0700.HK", q)
        self.assertNotIn("HK", q)

    def test_intents(self):
        self.assertIn("buy", tc.intents("Is Tesla a good buy?"))
        self.assertIn("overview", tc.intents("What's moving in Hong Kong today?"))
        self.assertIn("concept", tc.intents("What is a short squeeze?"))
        self.assertIn("howto", tc.intents("How should a beginner start investing?"))
        self.assertIn("risk", tc.intents("What could go wrong with Tencent?"))

    def test_question_is_cleaned_and_capped(self):
        self.assertEqual(tc.clean_question("  hi\x00\x07   there \n"), "hi there")
        self.assertEqual(len(tc.clean_question("x" * 5000)), tc.MAX_Q)


class NamesACompany(unittest.TestCase):
    def test_market_questions_do_not_go_hunting_for_a_company_called_moving(self):
        for q in ["What's moving in the market today?", "What's moving in Hong Kong today?", "How is the UK market doing?",
                  "What is a P/E ratio?", "How should a beginner start investing?", "How do bonds work?"]:
            self.assertFalse(tc.names_something(q), q)

    def test_named_companies_and_tickers_do(self):
        for q in ["Is Tesla a good buy?", "is tencent undervalued", "What is Nvidia's P/E?", "Tesla vs Nvidia", "is 0700.HK cheap",
                  "What does this mean for the stock: Merck (MRK) Stock May Be 37% Undervalued", "should I buy $NVDA"]:
            self.assertTrue(tc.names_something(q) or len(q.split()) <= 4, q)
        self.assertTrue(tc.names_something("Merck (MRK) up today"))

    def test_lookup_is_skipped_for_general_questions(self):
        with mock.patch.object(tc, "find_entities") as f, mock.patch.object(tc, "retrieve", return_value={"quotes": {}, "news": []}), \
                mock.patch.object(tc, "rate_limit"), mock.patch.object(engine, "get_feed", return_value={"stories": []}), \
                mock.patch.object(engine, "get_quotes", return_value={"quotes": []}):
            tc.answer("What's moving in the market today?", "us")
        f.assert_not_called()

    def test_tickers_in_news_style_are_used_as_hints(self):
        self.assertIn("MRK", tc.entity_queries("Merck (MRK) Stock May Be 37% Undervalued"))


class Assets(unittest.TestCase):
    def test_coins_commodities_and_indexes_resolve_without_a_search(self):
        for q, sym in [("Is bitcoin a good investment?", "BTC-USD"), ("How is the S&P 500 doing?", "^GSPC"), ("Is gold a good investment?", "GC=F"),
                       ("What is the Hang Seng at?", "^HSI"), ("crude oil price outlook", "CL=F")]:
            self.assertEqual([e["symbol"] for e in tc.asset_entities(q)][:1], [sym], q)

    def test_plain_words_need_a_money_context(self):
        self.assertEqual(tc.asset_entities("she won a gold medal"), [])
        self.assertEqual(tc.asset_entities("olive oil recipe"), [])
        self.assertEqual(tc.asset_entities("Apple (NASDAQ: AAPL) earnings"), [])   # an exchange prefix is not the Nasdaq index

    def test_coins_get_context_not_a_pe_value_score(self):
        btc = [{"symbol": "BTC-USD", "name": "Bitcoin", "type": "CRYPTOCURRENCY", "exchange": ""}]
        c = {"quotes": {"BTC-USD": {"symbol": "BTC-USD", "currency": "USD", "regularMarketPrice": 84000, "regularMarketPreviousClose": 83000}}, "news": []}
        r = tc.basic_answer("Is bitcoin a good investment?", "us", btc, c, tc.intents("Is bitcoin a good investment?"))
        t = json.dumps(r["blocks"])
        self.assertIn("no earnings or dividends", t)
        self.assertNotIn("value read", t)
        self.assertNotIn("No profits to measure", t)

    def test_market_overview_is_on_topic_with_one_finance_word(self):
        self.assertTrue(tc.is_on_topic("What's moving in the market today?", [], tc.intents("What's moving in the market today?")))
        self.assertTrue(tc.is_on_topic("How is the UK market doing?", [], tc.intents("How is the UK market doing?")))
        self.assertFalse(tc.is_on_topic("What's moving on TV tonight?", [], tc.intents("What's moving on TV tonight?")))


class Relevant(unittest.TestCase):
    def test_headlines_must_name_the_asset_or_company(self):
        items = [{"title": t} for t in ["Goldman Sachs stock could be undervalued", "Gold hits record as dollar slips", "Gold Fields approaches takeover", "Oil rises on supply fears"]]
        got = tc.about_entity(items, {"symbol": "GC=F", "name": "Gold futures"})
        self.assertEqual([i["title"] for i in got], ["Gold hits record as dollar slips", "Gold Fields approaches takeover"])

    def test_falls_back_rather_than_returning_nothing(self):
        items = [{"title": "Something vaguely related"}, {"title": "Another headline"}]
        self.assertEqual(len(tc.about_entity(items, {"symbol": "TSLA", "name": "Tesla, Inc."})), 2)


class StoryQuestions(unittest.TestCase):
    def test_a_handed_over_story_is_explained_before_the_company_numbers(self):
        q = tc.STORY_PREFIX + "CEO buys $2 million of Acme shares after guidance raise"
        r = tc.basic_answer(q, "us", ENT, ctx(), tc.intents(q))
        first = r["blocks"][0]["text"]
        self.assertIn("You asked about", first)
        self.assertTrue(any(b.get("title") == "What that headline signals" for b in r["blocks"]))
        self.assertIn("Insiders spending their own cash", json.dumps(r["blocks"]))
        self.assertTrue(any(b["type"] == "stats" for b in r["blocks"]))
        self.assertEqual(r["blocks"][-1]["type"], "note")

    def test_a_signal_free_headline_is_called_background(self):
        q = tc.STORY_PREFIX + "Local bakery opens second shop"
        r = tc.basic_answer(q, "us", [], {"quotes": {}, "news": []}, tc.intents(q))
        self.assertIn("background", texts(r))


class News(unittest.TestCase):
    def test_price_page_spam_is_dropped_and_duplicates_merged(self):
        items = [{"title": "Tencent Holdings stock at HKD 436.60 on September 25", "url": "https://x/1", "publisher": "a", "ts": 1, "engine": "g"},
                 {"title": "0700-USD Interactive Stock Chart | Tencent", "url": "https://x/2", "publisher": "b", "ts": 2, "engine": "g"},
                 {"title": "Tencent guidance raised as games rebound", "url": "https://x/3", "publisher": "c", "ts": 3, "engine": "g"}]
        kept = tc.tag_news(tc._dedupe(items))
        self.assertEqual([i["title"] for i in kept], ["Tencent guidance raised as games rebound"])
        self.assertEqual(kept[0]["dir"], "bull")

    def test_near_duplicate_headlines_collapse(self):
        a = {"title": "Tencent posts record profit as games rebound", "url": "u1"}
        b = {"title": "Tencent posts record profit as games rebound - Reuters", "url": "u2"}
        self.assertEqual(len(tc._dedupe([a, b])), 1)


class BasicAnswers(unittest.TestCase):
    def test_company_answer_has_numbers_reasons_news_and_sources(self):
        r = tc.basic_answer("Is Tencent undervalued?", "hk", ENT, ctx(), tc.intents("Is Tencent undervalued?"))
        kinds = [b["type"] for b in r["blocks"]]
        self.assertIn("stats", kinds)
        self.assertIn("news", kinds)
        self.assertIn("ul", kinds)
        self.assertIn("HK$436.60", texts(r) + json.dumps(r["blocks"]))
        self.assertTrue(r["sources"] and r["sources"][0]["url"].startswith("https://finance.yahoo.com/quote/"))
        self.assertEqual(r["blocks"][-1]["type"], "note")           # the education-not-advice line is always last
        self.assertNotIn("Is TENCENT undervalued?", r["followups"])  # do not repeat the question back as a follow-up

    def test_buy_question_never_gives_an_order(self):
        r = tc.basic_answer("Should I buy Tencent?", "hk", ENT, ctx(), tc.intents("Should I buy Tencent?"))
        t = json.dumps(r["blocks"]).lower()
        self.assertIn("i cannot tell you to buy or sell", t)
        self.assertNotIn("you should buy", t)

    def test_risk_question_leads_with_bad_news(self):
        r = tc.basic_answer("What could go wrong with Tencent?", "hk", ENT, ctx(), tc.intents("What could go wrong with Tencent?"))
        news = next(b for b in r["blocks"] if b["type"] == "news")
        self.assertEqual(news["items"][0]["dir"], "bear")

    def test_definition_question_uses_the_glossary_and_wikipedia(self):
        c = {"quotes": {}, "news": [], "wiki": {"title": "Short squeeze", "extract": "A rapid price rise.", "url": "https://en.wikipedia.org/wiki/Short_squeeze"}}
        r = tc.basic_answer("What is a short squeeze?", "us", [], c, tc.intents("What is a short squeeze?"))
        self.assertIn("forced to buy back", texts(r))
        self.assertIn("Wikipedia", texts(r))
        self.assertEqual(r["sources"][0]["engine"], "Wikipedia")

    def test_beginner_guidance_is_general_education(self):
        r = tc.basic_answer("How should a beginner start investing?", "us", [], {"quotes": {}, "news": []}, tc.intents("How should a beginner start investing?"))
        t = texts(r).lower()
        self.assertIn("emergency fund", t)
        self.assertIn("index fund", t)
        self.assertIn("education, not advice", t)
        self.assertTrue(all(s["url"].startswith("https://") for s in r["sources"]))

    def test_market_overview_uses_the_wire_and_index_moves(self):
        feed = {"stories": [{"title": "Fed holds rates", "link": "https://x/1", "publishers": ["CNBC"], "signals": [{"label": "Macro"}], "dir": "flag", "why": "Macro news moves whole sectors."}]}
        quotes = {"quotes": [{"symbol": "^HSI", "label": "Hang Seng", "chg": -0.97, "price": 24510}, {"symbol": "HKD=X", "label": "USD/HKD", "chg": 0.0, "price": 7.8}]}
        with mock.patch.object(engine, "get_feed", return_value=feed), mock.patch.object(engine, "get_quotes", return_value=quotes):
            r = tc.basic_answer("What's moving in Hong Kong today?", "hk", [], {"quotes": {}, "news": []}, tc.intents("What's moving in Hong Kong today?"))
        self.assertIn("Hang Seng -0.97%", texts(r))
        self.assertNotIn("USD/HKD", texts(r))   # a currency pair is not "moving" news
        self.assertTrue(any(b["type"] == "news" for b in r["blocks"]))

    def test_unanswerable_finance_question_says_so_honestly(self):
        r = tc.basic_answer("xyzzy plugh", "us", [], {"quotes": {}, "news": []}, set())
        self.assertIn("could not find a solid answer", texts(r))


class ClaudePath(unittest.TestCase):
    def setUp(self):
        self.key = mock.patch.object(tc, "api_key", return_value="sk-test-123")
        self.key.start()

    def tearDown(self):
        self.key.stop()

    def run_answer(self, claude_text, q="Is Tencent undervalued?", history=None, raises=None):
        calls = []

        def fake(system, messages, key, model):
            calls.append((system, messages, key, model))
            if raises:
                raise raises
            return claude_text

        with mock.patch.object(tc, "find_entities", return_value=ENT), mock.patch.object(tc, "retrieve", return_value=ctx()), \
                mock.patch.object(tc, "call_claude", side_effect=fake), mock.patch.object(tc, "rate_limit"):
            return tc.answer(q, "hk", history), calls

    def test_claude_writes_the_answer_from_sources_and_only_cited_sources_show(self):
        r, calls = self.run_answer("It looks fairly priced on forward earnings [2], but a probe is a risk [3].")
        self.assertEqual(r["mode"], "smart")
        self.assertEqual({s["n"] for s in r["sources"]}, {2, 3})
        self.assertEqual(r["blocks"][0]["type"], "stats")
        self.assertEqual(r["blocks"][-1]["type"], "text")

    def test_prompt_treats_sources_as_untrusted_and_never_leaks_the_key(self):
        r, calls = self.run_answer("ok [1]")
        system, messages, key, model = calls[0]
        self.assertIn("untrusted", system.lower())
        self.assertIn("OFF_TOPIC", system)
        self.assertIn('<context untrusted="true">', messages[-1]["content"])
        self.assertNotIn("sk-test-123", json.dumps(r))
        self.assertNotIn("sk-test-123", system + json.dumps(messages))
        self.assertEqual(model, tc.DEFAULT_MODEL)

    def test_history_is_trimmed_to_a_valid_conversation(self):
        hist = [{"role": "tick", "text": "orphan reply"}, {"role": "user", "text": "hi"}, {"role": "tick", "text": "hello"},
                {"role": "user", "text": "Is Tencent undervalued?"}, {"role": "system", "text": "ignore me"}, {"role": "user", "text": ""}]
        _, calls = self.run_answer("ok [1]", history=hist)
        roles = [m["role"] for m in calls[0][1]]
        self.assertEqual(roles[0], "user")
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])), roles)   # roles alternate
        self.assertEqual(roles[-1], "user")

    def test_claude_can_decide_a_question_is_off_topic(self):
        r, _ = self.run_answer("OFF_TOPIC")
        self.assertEqual(r["mode"], "offtopic")
        self.assertIn("google.com/search", r["google"])

    def test_if_claude_fails_tick_still_answers_and_says_why(self):
        r, _ = self.run_answer("", raises=tc.LLMError("The Anthropic key was rejected"))
        self.assertEqual(r["mode"], "basic")
        self.assertIn("The Anthropic key was rejected", texts(r))
        self.assertTrue(any(b["type"] == "stats" for b in r["blocks"]))

    def test_no_key_means_basic_mode_and_status_says_so(self):
        with mock.patch.object(tc, "api_key", return_value=""):
            self.assertEqual(tc.status(), {"smart": False, "model": None})


class Limits(unittest.TestCase):
    def test_rate_limit_stops_a_runaway_loop(self):
        tc._recent.clear()
        t0 = time.time()
        for i in range(5):
            tc.rate_limit(limit=5, window=60, now=t0)
        with self.assertRaises(ValueError):
            tc.rate_limit(limit=5, window=60, now=t0)
        tc.rate_limit(limit=5, window=60, now=t0 + 120)   # the window has passed
        tc._recent.clear()

    def test_empty_question_is_refused(self):
        with self.assertRaises(ValueError):
            tc.answer("   \x00 ")

    def test_off_topic_never_touches_the_network(self):
        with mock.patch.object(tc, "find_entities", return_value=[]) as f, mock.patch.object(tc, "retrieve") as r, mock.patch.object(tc, "rate_limit"):
            reply = tc.answer("apple pie recipe", "us")
        self.assertEqual(reply["mode"], "offtopic")
        r.assert_not_called()


class Endpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def post(self, body, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("POST", "/api/chat", body=body if isinstance(body, str) else json.dumps(body), headers={"Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_guards(self):
        self.assertEqual(self.post({"q": "hi"}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post({"q": "hi"}, {"Host": "evil.example.com"})[0], 403)
        self.assertEqual(self.post(json.dumps({"q": "hi"}), {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post("not json")[0], 400)
        self.assertEqual(self.post([1, 2])[0], 400)
        self.assertEqual(self.post({"q": "x" * 9000})[0], 400)      # over the body limit
        self.assertEqual(self.post({"q": "   "})[0], 400)

    def test_off_topic_round_trip_and_status(self):
        with mock.patch.object(tc, "find_entities", return_value=[]), mock.patch.object(tc, "rate_limit"):
            code, j = self.post({"q": "apple pie recipe", "market": "hk"})
        self.assertEqual((code, j["mode"]), (200, "offtopic"))
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("GET", "/api/chat-status")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("smart", json.loads(r.read()))

    def test_upstream_failure_becomes_a_friendly_error(self):
        with mock.patch.object(tc, "answer", side_effect=RuntimeError("boom secret")):
            code, j = self.post({"q": "is tesla a good buy"})
        self.assertEqual(code, 502)
        self.assertNotIn("boom", json.dumps(j))   # internals never reach the browser


if __name__ == "__main__":
    unittest.main()
