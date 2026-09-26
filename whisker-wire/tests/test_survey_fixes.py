"""Offline tests for the changes driven by the persona survey. Run: python -m unittest discover -s tests"""
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine  # noqa: E402
import server  # noqa: E402
import track  # noqa: E402


def item(title, pub, kind="Wire", ts=None):
    return {"title": title, "publisher": pub, "link": "https://x.test/" + pub + str(abs(hash(title)) % 999),
            "summary": "", "ts": ts or time.time() - 300, "src_id": "t", "kind": kind}


def story(items):
    return engine.build_story(engine.cluster(items)[0], time.time())


class ScoreWorking(unittest.TestCase):
    def test_parts_add_up_to_score(self):
        s = story([item("Acme (ACME) raises guidance as CEO buys shares", "Benzinga"),
                   item("Acme (ACME) raises guidance as CEO buys shares", "Seeking Alpha")])
        p = s["parts"]
        total = sum(x["pts"] for x in p["signals"]) + p["fresh"] + p["outlets"] + p["ticker"] + p["question"]
        self.assertEqual(total, s["score"])

    def test_single_unknown_outlet_cannot_be_urgent(self):
        s = story([item("Acme (ACME) CEO buys $2 million of shares after guidance raise", "simplywall.st")])
        self.assertGreaterEqual(s["score"], 8)
        self.assertEqual(s["level"], "watch")
        self.assertTrue(s["parts"]["capped"])

    def test_corroborated_or_official_or_major_can_be_urgent(self):
        two = story([item("Acme (ACME) CEO buys $2 million of shares after guidance raise", "simplywall.st"),
                     item("Acme (ACME) CEO buys $2 million of shares after guidance raise", "Benzinga")])
        major = story([item("Acme (ACME) CEO buys $2 million of shares after guidance raise", "CNBC")])
        gov = story([item("Acme (ACME) CEO buys $2 million of shares after guidance raise", "SEC", kind="Government")])
        self.assertEqual((two["level"], major["level"], gov["level"]), ("urgent", "urgent", "urgent"))

    def test_no_signal_cap_is_reported(self):
        s = story([item("Local bakery (BAKE) opens second shop", "CNBC")])
        self.assertEqual(s["score"], 3)


class TrackRecord(unittest.TestCase):
    def bars(self, start, closes):
        return [(start + i * 86400, c) for i, c in enumerate(closes)]

    def test_excess_return_math_and_horizons(self):
        seen = 1_700_000_000
        stock = self.bars(seen, [100, 102, 103, 104, 105, 106, 110])   # bar 0 is the seen day
        spy = self.bars(seen, [400, 401, 402, 403, 404, 405, 408])
        r1, r5 = track.excess_returns(stock, spy, seen + 3600, 100, 400)
        self.assertAlmostEqual(r1, (102 / 100 - 1) - (401 / 400 - 1))
        self.assertAlmostEqual(r5, (106 / 100 - 1) - (405 / 400 - 1))

    def test_not_enough_bars_yet_returns_none(self):
        seen = 1_700_000_000
        r1, r5 = track.excess_returns(self.bars(seen, [100, 101, 102]), self.bars(seen, [400, 401, 402]), seen, 100, 400)
        self.assertIsNotNone(r1)
        self.assertIsNone(r5)

    def test_summary_flips_sign_for_bearish_calls(self):
        rows = [{"level": "urgent", "dir": "bear", "r1": -0.02, "r5": -0.04},
                {"level": "urgent", "dir": "bear", "r1": 0.01, "r5": 0.02},
                {"level": "urgent", "dir": "bull", "r1": 0.03, "r5": None}]
        g = {(x["level"], x["dir"]): x for x in track.summarize(rows)}
        bear = g[("urgent", "bear")]
        self.assertEqual((bear["n5"], bear["hit5"]), (2, 0.5))
        self.assertAlmostEqual(bear["avg5"], (0.04 - 0.02) / 2)
        self.assertEqual(g[("urgent", "bull")]["n5"], 0)

    def test_observe_logs_once_per_ticker_direction_day_and_skips_unpriced(self):
        with tempfile.TemporaryDirectory() as d:
            old = track.DB
            track.DB = Path(d) / "t.db"
            try:
                now = time.time()
                mk = lambda tk, lvl="urgent", dr="bull": {"level": lvl, "dir": dr, "tickers": [tk], "title": tk, "score": 9, "ts": now}
                stories = [mk("ACME"), mk("ACME"), mk("FAKE"), mk("NOPE", lvl="normal"), mk("ZZZ", dr="flag")]
                price = lambda s: None if s == "FAKE" else 100.0
                track.observe(stories, now, price, lambda s: [])
                track.observe(stories, now, price, lambda s: [])   # second pass must not duplicate
                rep = track.report(now)
                self.assertEqual(rep["logged"], 1)
                self.assertFalse(rep["enough"])
            finally:
                track.DB = old

    def test_idle_cycle_makes_no_price_lookups(self):
        with tempfile.TemporaryDirectory() as d:
            old, old_eval = track.DB, track._last_eval
            track.DB = Path(d) / "t.db"
            try:
                now = time.time()
                calls = []
                price = lambda s: calls.append(s) or 100.0
                st = [{"level": "urgent", "dir": "bull", "tickers": ["ACME"], "title": "t", "score": 9, "ts": now}]
                track.observe(st, now, price, lambda s: [])
                first = len(calls)
                track.observe(st, now + 90, price, lambda s: [])   # nothing new, evaluation not due
                self.assertGreater(first, 0)
                self.assertEqual(len(calls), first)
            finally:
                track.DB, track._last_eval = old, old_eval

    def test_evaluation_fills_returns_for_old_rows(self):
        with tempfile.TemporaryDirectory() as d:
            old = track.DB
            track.DB = Path(d) / "t.db"
            try:
                seen = 1_700_000_000
                con = track.connect()
                con.execute("INSERT INTO seen VALUES ('ACME:bull:x','t',?,9,'urgent','bull','ACME',100,400,NULL,NULL)", (seen,))
                con.commit()
                mk = lambda base: [(seen + i * 86400, base + i) for i in range(8)]
                track._evaluate(con, seen + 10 * 86400, lambda s: mk(100) if s == "ACME" else mk(400))
                r1, r5 = con.execute("SELECT r1, r5 FROM seen").fetchone()
                self.assertIsNotNone(r1)
                self.assertIsNotNone(r5)
                con.close()
            finally:
                track.DB = old


class SecContact(unittest.TestCase):
    def test_valid_and_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.txt"
            self.assertEqual(engine.save_sec_contact("  Jane   Doe  jane@example.com ", p), "Jane Doe jane@example.com")
            self.assertEqual(p.read_text().strip(), "Jane Doe jane@example.com")
            for bad in ("", "jane@example.com", "Jane Doe", "Jane <x> jane@example.com", "J" * 200 + " a@b.co",
                        "Jane Doe jane@example.com\nX-Evil: 1 a@b.co"):
                with self.assertRaises(ValueError, msg=bad):
                    engine.save_sec_contact(bad, p)


class PostGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.file = Path(cls.tmp.name) / "c.txt"
        cls._old = engine.CONTACT_FILE
        engine.CONTACT_FILE = cls.file
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        engine.CONTACT_FILE = cls._old
        cls.tmp.cleanup()

    def post(self, body, headers=None, path="/api/sec-contact"):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        h = {"Content-Type": "application/json", **(headers or {})}
        c.request("POST", path, body=body if isinstance(body, str) else json.dumps(body), headers=h)
        r = c.getresponse()
        return r.status, r.read()

    def test_good_request_writes_file(self):
        code, _ = self.post({"name": "Jane Doe", "email": "jane@example.com"})
        self.assertEqual(code, 200)
        self.assertEqual(self.file.read_text().strip(), "Jane Doe jane@example.com")

    def test_refusals(self):
        good = {"name": "Jane Doe", "email": "jane@example.com"}
        self.file.unlink(missing_ok=True)
        self.assertEqual(self.post(good, {"Origin": "https://evil.example"})[0], 403)      # cross-site
        self.assertEqual(self.post(good, {"Host": "evil.example.com"})[0], 403)             # DNS rebinding
        self.assertEqual(self.post(json.dumps(good), {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post({"name": "x", "email": "nope"})[0], 400)
        self.assertEqual(self.post("not json")[0], 400)
        self.assertEqual(self.post(good, path="/api/other")[0], 404)
        self.assertFalse(self.file.exists(), "no refused request may write the file")


if __name__ == "__main__":
    unittest.main()
