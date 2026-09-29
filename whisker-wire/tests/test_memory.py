"""Offline tests for Tick remembers. Every test uses its own temporary database; nothing touches your real one."""
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine  # noqa: E402
import memory  # noqa: E402
import server  # noqa: E402
import tick_chat as tc  # noqa: E402

QUOTE = {"symbol": "TSLA", "quoteType": "EQUITY", "currency": "USD", "shortName": "Tesla, Inc.", "regularMarketPrice": 300.0,
         "regularMarketPreviousClose": 295.0, "fiftyTwoWeekHigh": 498.0, "fiftyTwoWeekLow": 250.0, "forwardPE": 120.0,
         "priceToBook": 15.0, "averageAnalystRating": "2.0 - Buy", "marketCap": 1e12, "twoHundredDayAverage": 340.0}
DAY = 86400


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        memory.DB = str(Path(self.tmp.name) / "m.db")

    def tearDown(self):
        memory.DB = None
        self.tmp.cleanup()


class Storage(Base):
    def test_profile_round_trip_and_validation(self):
        memory.set_profile("Beginner", ["hk", "sg", "hk", "atlantis"])
        a = memory.get_all()
        self.assertEqual((a["experience"], a["markets"]), ("beginner", ["hk", "sg"]))   # unknown market dropped, duplicates merged
        with self.assertRaises(ValueError):
            memory.set_profile("guru", [])
        memory.set_profile("", [])
        self.assertIsNone(memory.get_all()["experience"])

    def test_watchlist_is_normalised_deduped_ordered_and_capped(self):
        memory.set_watch(["tsla", " nvda ", "TSLA", "0700.hk"])
        self.assertEqual(memory.get_all()["watchlist"], ["TSLA", "NVDA", "0700.HK"])
        memory.set_watch(["NVDA", "AAPL"])
        self.assertEqual(memory.get_all()["watchlist"], ["NVDA", "AAPL"])
        for bad in (["drop table;"], ["<script>"], [""], ["A" * 30]):
            with self.assertRaises(ValueError, msg=bad):
                memory.set_watch(bad)
        with self.assertRaises(ValueError):
            memory.set_watch([f"T{i}" for i in range(memory.MAX_WATCH + 1)])

    def test_thesis_create_update_delete(self):
        tid = memory.save_thesis({"symbol": "tsla", "note": "Robotaxi optionality is underpriced.", "invalidate_if": "Deliveries fall two quarters in a row",
                                  "review_below": "250", "review_above": 400}, snap={"price": 300.0}, name="Tesla")
        t = memory.get_all()["theses"][0]
        self.assertEqual((t["symbol"], t["review_below"], t["review_above"], t["snap"]["price"], t["name"]), ("TSLA", 250.0, 400.0, 300.0, "Tesla"))
        memory.save_thesis({"id": tid, "symbol": "TSLA", "note": "Changed my mind about the reason.", "review_below": ""})
        t = memory.get_all()["theses"][0]
        self.assertEqual((t["note"], t["review_below"], t["snap"]["price"]), ("Changed my mind about the reason.", None, 300.0))   # the saved snapshot survives edits
        memory.delete_thesis(tid)
        self.assertEqual(memory.get_all()["theses"], [])

    def test_thesis_validation(self):
        ok = {"symbol": "TSLA", "note": "A perfectly good reason."}
        for bad in ({**ok, "note": "no"}, {**ok, "symbol": "not a ticker!"}, {**ok, "review_below": "abc"}, {**ok, "review_below": -5},
                    {**ok, "review_below": 300, "review_above": 200}):
            with self.assertRaises(ValueError, msg=bad):
                memory.save_thesis(bad)
        for i in range(memory.MAX_THESES):
            memory.save_thesis({**ok, "symbol": f"T{i}"})
        with self.assertRaises(ValueError):
            memory.save_thesis(ok)

    def test_text_is_cleaned_and_capped(self):
        memory.save_thesis({"symbol": "X1", "note": ("word " * 400) + "\x00\x07"})
        self.assertLessEqual(len(memory.get_all()["theses"][0]["note"]), memory.MAX_NOTE)
        self.assertNotIn("\x00", memory.get_all()["theses"][0]["note"])

    def test_forget_everything_empties_the_file(self):
        memory.set_profile("some", ["uk"]); memory.set_watch(["TSLA"]); memory.save_thesis({"symbol": "TSLA", "note": "My private reasoning here."})
        n = memory.forget_all()
        self.assertEqual(n, {"profile": 2, "watch": 1, "thesis": 1})
        a = memory.get_all()
        self.assertEqual((a["experience"], a["markets"], a["watchlist"], a["theses"]), (None, [], [], []))
        self.assertNotIn(b"private reasoning", Path(memory.db_path()).read_bytes())   # deleted text is not left in the file

    def test_default_location_is_outside_the_project_folder(self):
        memory.DB = None
        with mock.patch.dict("os.environ", {}, clear=False):
            p = memory.db_path()
        self.assertIn("WhiskerWire", str(p))
        self.assertNotIn(str(Path(memory.__file__).parent), str(p))   # not in a folder that may sync to the cloud
        with mock.patch.dict("os.environ", {"WHISKER_WIRE_DATA": self.tmp.name}):
            self.assertEqual(memory.db_path(), Path(self.tmp.name) / "tick_memory.db")

    def test_export_is_the_whole_memory(self):
        memory.set_watch(["TSLA"])
        e = memory.export_all()
        self.assertEqual(e["watchlist"], ["TSLA"])
        self.assertIn("exported", e)
        json.dumps(e)


def thesis(**k):
    base = {"created": 1_700_000_000, "snap": {"price": 100.0, "currency": "USD", "fpe": 10.0, "rating_num": 2.0, "rating": "2.0 - Buy", "score": 60},
            "review_below": None, "review_above": None}
    return {**base, **k}


NOW = 1_700_000_000 + 10 * DAY
BEAR = {"title": "Regulator opens probe", "dir": "bear", "ts": 1_700_000_000 + 2 * DAY, "url": "https://n.test/1"}


class Drift(unittest.TestCase):
    def run_drift(self, t=None, **cur):
        now_snap = {"price": 102.0, "currency": "USD", "fpe": 10.2, "rating_num": 2.0, "rating": "2.0 - Buy", "score": 60, **cur}
        return memory.drift(t or thesis(), now_snap, news=cur.pop("news", []), now=NOW)

    def test_quiet_market_holds_up(self):
        d = self.run_drift()
        self.assertEqual((d["status"], d["points"]), ("holding", 0))
        self.assertIn("+2.0%", " ".join(d["facts"]))

    def test_points_always_add_up_and_each_has_a_reason(self):
        t = thesis(review_below=90)
        d = memory.drift(t, {"price": 80.0, "currency": "USD", "fpe": 14.0, "rating_num": 2.6, "rating": "2.6 - Hold", "score": 40}, news=[BEAR, dict(BEAR, title="Second bad headline")], now=NOW)
        self.assertEqual(sum(b["pts"] for b in d["breakdown"]), d["points"])
        self.assertTrue(all(b["label"] for b in d["breakdown"]))
        self.assertEqual(d["status"], "pressure")
        labels = " ".join(b["label"] for b in d["breakdown"])
        for want in ("down 20%", "review line", "Forward P/E rose", "Analyst view weakened", "Value read fell", "2 negative headlines"):
            self.assertIn(want, labels)

    def test_a_fall_alone_is_worth_a_look_and_a_crossed_line_is_pressure(self):
        self.assertEqual(memory.drift(thesis(), {"price": 84.0, "currency": "USD"}, now=NOW)["status"], "look")   # -16%: 2 points
        self.assertEqual(memory.drift(thesis(review_below=95), {"price": 94.0, "currency": "USD"}, now=NOW)["status"], "look")   # line crossed: 3 points
        self.assertEqual(memory.drift(thesis(review_below=95), {"price": 84.0, "currency": "USD"}, now=NOW)["status"], "pressure")

    def test_only_headlines_since_the_note_count(self):
        old = dict(BEAR, ts=1_600_000_000)
        self.assertEqual(memory.drift(thesis(), {"price": 100.0, "currency": "USD"}, news=[old, old], now=NOW)["points"], 0)
        self.assertEqual(memory.drift(thesis(), {"price": 100.0, "currency": "USD"}, news=[BEAR], now=NOW)["points"], 1)
        good = dict(BEAR, dir="bull")
        self.assertEqual(memory.drift(thesis(), {"price": 100.0, "currency": "USD"}, news=[good], now=NOW)["points"], 0)

    def test_an_old_note_asks_to_be_re_read(self):
        d = memory.drift(thesis(), {"price": 100.0, "currency": "USD"}, now=1_700_000_000 + 100 * DAY)
        self.assertTrue(any("re-read" in b["label"] for b in d["breakdown"]))

    def test_a_big_rise_is_flagged_but_not_punished(self):
        d = memory.drift(thesis(), {"price": 140.0, "currency": "USD"}, now=NOW)
        self.assertEqual(d["points"], 0)
        self.assertIn("still holds at this price", " ".join(d["facts"]))

    def test_a_missing_price_is_reported_honestly(self):
        d = memory.drift(thesis(), {"price": None}, now=NOW)
        self.assertEqual(d["status"], "unknown")

    def test_a_note_without_a_saved_snapshot_still_works(self):
        d = memory.drift(thesis(snap=None), {"price": 50.0, "currency": "USD"}, now=NOW)
        self.assertIn("no price was saved", " ".join(d["facts"]))


class Operations(Base):
    def test_adding_a_note_saves_todays_numbers_and_rejects_unknown_tickers(self):
        with mock.patch.object(memory, "_lookup", return_value=(QUOTE, "Tesla, Inc.", 32)):
            memory.handle({"op": "thesis_save", "symbol": "tsla", "note": "Autonomy is underpriced.", "review_below": 250})
        t = memory.get_all()["theses"][0]
        self.assertEqual((t["name"], t["snap"]["price"], t["snap"]["score"], t["snap"]["rating_num"]), ("Tesla, Inc.", 300.0, 32, 2.0))
        with mock.patch.object(tc, "quote_snapshots", return_value={}):
            with self.assertRaises(ValueError) as cm:
                memory.handle({"op": "thesis_save", "symbol": "ZZZZZ", "note": "A note for nothing at all."})
        self.assertIn("Yahoo does not know", str(cm.exception))
        self.assertEqual(len(memory.get_all()["theses"]), 1)   # nothing half-saved

    def test_check_compares_with_live_numbers_and_headlines(self):
        with mock.patch.object(memory, "_lookup", return_value=(QUOTE, "Tesla, Inc.", 32)):
            memory.handle({"op": "thesis_save", "symbol": "TSLA", "note": "Autonomy is underpriced."})
        tid = memory.get_all()["theses"][0]["id"]
        cheaper = dict(QUOTE, regularMarketPrice=240.0)
        news = [{"title": "Tesla recall widens", "url": "https://n/1", "publisher": "x", "ts": int(time.time()) + 5, "engine": "g", "tags": ["Recall / outage"], "dir": "bear"},
                {"title": "Tesla faces new probe", "url": "https://n/2", "publisher": "y", "ts": int(time.time()) + 5, "engine": "g", "tags": [], "dir": "bear"}]
        with mock.patch.object(memory, "_lookup", return_value=(cheaper, "Tesla, Inc.", 32)), mock.patch.object(tc, "search_news", return_value=news):
            out = memory.handle({"op": "check", "id": tid})
        d = out["drift"]
        self.assertEqual(d["symbol"], "TSLA")
        self.assertEqual(d["status"], "pressure")   # -20% and two negative headlines
        self.assertEqual(len(d["news"]), 2)

    def test_forget_needs_confirmation_and_unknown_ops_are_refused(self):
        memory.set_watch(["TSLA"])
        with self.assertRaises(ValueError):
            memory.handle({"op": "forget"})
        self.assertEqual(memory.get_all()["watchlist"], ["TSLA"])
        with self.assertRaises(ValueError):
            memory.handle({"op": "rm -rf"})
        out = memory.handle({"op": "forget", "confirm": "forget"})
        self.assertEqual(out["watchlist"], [])


class Endpoint(Base):
    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        super().tearDown()

    def req(self, method, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        h = {"Content-Type": "application/json", **(headers or {})}
        c.request(method, "/api/memory", body=None if body is None else (body if isinstance(body, str) else json.dumps(body)), headers=h)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_read_write_round_trip(self):
        self.assertEqual(self.req("POST", {"op": "profile", "experience": "beginner", "markets": ["hk"]})[0], 200)
        self.assertEqual(self.req("POST", {"op": "watch_set", "symbols": ["tsla", "0700.hk"]})[0], 200)
        code, j = self.req("GET")
        self.assertEqual((code, j["experience"], j["markets"], j["watchlist"]), (200, "beginner", ["hk"], ["TSLA", "0700.HK"]))
        self.assertTrue(j["location"].endswith("m.db"))

    def test_guards(self):
        good = {"op": "watch_set", "symbols": ["TSLA"]}
        self.assertEqual(self.req("POST", good, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", good, {"Host": "evil.example.com"})[0], 403)
        self.assertEqual(self.req("POST", json.dumps(good), {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("POST", "not json")[0], 400)
        self.assertEqual(self.req("POST", {"op": "watch_set", "symbols": ["x" * 9000]})[0], 400)     # over the body limit
        self.assertEqual(self.req("POST", {"op": "profile", "experience": "guru"})[0], 400)
        self.assertEqual(self.req("POST", {"op": "watch_set", "symbols": ["<script>"]})[0], 400)
        self.assertEqual(self.req("GET", headers={"Host": "evil.example.com"})[0], 403)
        self.assertEqual(memory.get_all()["watchlist"], [])   # no refused request changed anything


class InsideChat(Base):
    def mem(self, **k):
        return {"experience": None, "markets": [], "watchlist": [], "theses": {}, **k}

    def th(self):
        return {"id": 1, "symbol": "TSLA", "note": "Robotaxi optionality is underpriced.", "invalidate_if": "Deliveries fall two quarters in a row",
                "created": int(time.time()) - 5 * DAY, "review_below": None, "review_above": None,
                "snap": {"price": 320.0, "currency": "USD", "fpe": 100.0, "rating_num": 2.0, "rating": "2.0 - Buy", "score": 35}}

    ENT = [{"symbol": "TSLA", "name": "Tesla, Inc.", "type": "EQUITY", "exchange": "NASDAQ"}]

    def test_how_are_my_stocks_uses_the_watchlist_and_notes(self):
        m = self.mem(watchlist=["TSLA", "NVDA"], theses={"TSLA": self.th()})
        quotes = {"TSLA": dict(QUOTE, regularMarketPrice=250.0), "NVDA": dict(QUOTE, symbol="NVDA", regularMarketPrice=225.0)}
        with mock.patch.object(tc, "quote_snapshots", return_value=quotes), mock.patch.object(tc, "rate_limit"):
            r = tc.answer("How are my stocks doing?", "us", None, m)
        text = json.dumps(r["blocks"])
        self.assertEqual(r["mode"], "memory")
        self.assertIn("TSLA: $250.00", text)
        self.assertIn("Your note: ", text)
        self.assertIn("NVDA: $225.00", text)
        self.assertNotIn("Robotaxi", text)   # the note text is not repeated in the summary

    def test_with_nothing_saved_tick_says_how_to_start(self):
        with mock.patch.object(tc, "rate_limit"):
            r = tc.answer("how are my stocks doing", "us", None, self.mem())
        self.assertIn("Tick remembers", json.dumps(r["blocks"]))

    def test_asking_about_a_stock_you_wrote_a_note_on_shows_the_note_and_its_status(self):
        m = self.mem(theses={"TSLA": self.th()})
        ctx = {"quotes": {"TSLA": dict(QUOTE, regularMarketPrice=260.0)}, "news": []}
        r = tc.basic_answer("Is Tesla undervalued?", "us", self.ENT, ctx, tc.intents("Is Tesla undervalued?"), m)
        block = next(b for b in r["blocks"] if b.get("title", "").startswith("Your note on TSLA"))
        text = " ".join(block["items"])
        self.assertIn("Robotaxi optionality", text)
        self.assertIn("Status:", text)
        self.assertIn("Deliveries fall two quarters", text)
        self.assertIn("down 19%", text)

    def test_no_note_no_block(self):
        ctx = {"quotes": {"TSLA": QUOTE}, "news": []}
        r = tc.basic_answer("Is Tesla undervalued?", "us", self.ENT, ctx, tc.intents("Is Tesla undervalued?"), self.mem())
        self.assertFalse(any(b.get("title", "").startswith("Your note") for b in r["blocks"]))

    def test_beginners_get_plain_english_and_experts_do_not(self):
        ctx = {"quotes": {"TSLA": QUOTE}, "news": []}
        beginner = tc.basic_answer("Is Tesla undervalued?", "us", self.ENT, ctx, set(), self.mem(experience="beginner"))
        expert = tc.basic_answer("Is Tesla undervalued?", "us", self.ENT, ctx, set(), self.mem(experience="experienced"))
        titles = lambda r: [b.get("title") for b in r["blocks"]]
        self.assertIn("In plain English", titles(beginner))
        self.assertNotIn("In plain English", titles(expert))
        self.assertIn("price divided by", json.dumps(beginner["blocks"]).lower())

    def test_profile_markets_break_ties_between_listings(self):
        with mock.patch.object(tc.engine, "run_parallel", return_value=[("tencent", {"quotes": [
                {"symbol": "TCEHY", "shortname": "Tencent ADR", "quoteType": "EQUITY", "score": 30000},
                {"symbol": "0700.HK", "shortname": "TENCENT", "quoteType": "EQUITY", "score": 20000}]})]):
            plain = tc.find_entities("tencent", "us")
            hk = tc.find_entities("tencent", "us", ("hk",))
        self.assertEqual(plain[0]["symbol"], "TCEHY")
        self.assertEqual(hk[0]["symbol"], "0700.HK")

    def test_notes_never_reach_the_language_model(self):
        """The privacy promise, tested: Claude sees the self-described profile and nothing else that you wrote."""
        m = self.mem(experience="beginner", markets=["hk"], watchlist=["SECRETCO"], theses={"TSLA": self.th()})
        seen = []

        def fake(system, messages, key, model):
            seen.append(json.dumps({"system": system, "messages": messages}))
            return "Looks fairly priced on forward earnings [1]."

        ctx = {"quotes": {"TSLA": QUOTE}, "news": []}
        with mock.patch.object(tc, "api_key", return_value="sk-test"), mock.patch.object(tc, "find_entities", return_value=self.ENT), \
                mock.patch.object(tc, "retrieve", return_value=ctx), mock.patch.object(tc, "call_claude", side_effect=fake), mock.patch.object(tc, "rate_limit"):
            r = tc.answer("Is Tesla undervalued?", "us", None, m)
        sent = seen[0]
        self.assertIn("experience level beginner", sent)
        self.assertIn("Hong Kong", sent)
        for secret in ("Robotaxi", "optionality", "Deliveries fall", "SECRETCO", "320.0", "review"):
            self.assertNotIn(secret, sent, secret)
        # ...but the answer you see still includes your note, added locally afterwards
        self.assertTrue(any(b.get("title", "").startswith("Your note on TSLA") for b in r["blocks"]))

    def test_a_broken_memory_never_stops_tick(self):
        with mock.patch.object(memory, "for_chat", side_effect=RuntimeError("corrupt")), mock.patch.object(tc, "answer", return_value={"ok": 1}) as a:
            self.assertEqual(server._post_chat({"q": "hi"}, None), {"ok": 1})
        self.assertIsNone(a.call_args[0][3])


if __name__ == "__main__":
    unittest.main()
