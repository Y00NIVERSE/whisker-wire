"""Yahoo throttles server addresses (HTTP 429). The market lists must try the other host, then back off and say so."""
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine  # noqa: E402


def _err(code):
    return urllib.error.HTTPError("https://query1.finance.yahoo.com/x", code, "x", {}, io.BytesIO(b""))


class _Op:
    def __init__(self, fail=None, quotes=()):
        self.fail, self.quotes = fail, quotes

    def open(self, req, timeout=0):
        if self.fail:
            raise _err(self.fail)
        import json
        return io.BytesIO(json.dumps({"finance": {"result": [{"quotes": list(self.quotes)}]}}).encode())


class Throttled(unittest.TestCase):
    def setUp(self):
        engine._cache.clear()
        engine._screen_fail.clear()
        self.spec = engine.MARKETS["sg"]["screen"]

    def test_the_second_host_is_tried_when_the_first_is_throttled(self):
        hosts = []

        def session(force=False, host=engine.YF):
            hosts.append(host)
            return (_Op(fail=429) if host == engine.YF else _Op(quotes=[{"symbol": "D05.SI", "currency": self.spec["currencies"][0]}])), "crumb"

        with mock.patch.object(engine, "_yahoo_session", session):
            quotes = engine._screen_market(self.spec)
        self.assertEqual([q["symbol"] for q in quotes], ["D05.SI"])
        self.assertEqual(hosts[:2], list(engine.YF_HOSTS))

    def test_when_every_host_throttles_the_message_is_plain_and_yahoo_is_left_alone_for_a_while(self):
        calls = []

        def session(force=False, host=engine.YF):
            calls.append(host)
            return _Op(fail=429), "crumb"

        with mock.patch.object(engine, "_yahoo_session", session):
            with self.assertRaises(ValueError) as cm:
                engine.get_undervalued("sg")
            first = len(calls)
            self.assertIn("limiting", str(cm.exception))
            self.assertNotIn("publisher", str(cm.exception))
            engine._cache.clear()
            with self.assertRaises(ValueError):
                engine.get_undervalued("sg")
            self.assertEqual(len(calls), first)          # the cooldown: no second round of requests

    def test_other_errors_are_not_hidden_as_throttling(self):
        def session(force=False, host=engine.YF):
            return _Op(fail=500), "crumb"

        with mock.patch.object(engine, "_yahoo_session", session):
            with self.assertRaises(urllib.error.HTTPError):
                engine.get_undervalued("sg")
        self.assertNotIn("sg", engine._screen_fail)


if __name__ == "__main__":
    unittest.main()
