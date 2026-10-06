"""A public site must not share one notes file between strangers, must not trust a forgeable client IP,
and must not let slow or numerous connections pile up. Everything here runs offline."""
import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth  # noqa: E402
import server  # noqa: E402

HOSTED = {"PORT": "10000"}


class SharedStateOffWhenPublic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request(method, path, body=None if body is None else json.dumps(body), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data or b"{}")

    def test_public_site_without_accounts_has_no_server_side_notes(self):
        with mock.patch.dict(os.environ, HOSTED), mock.patch.object(auth, "cloud_enabled", return_value=False):
            self.assertEqual(self.call("GET", "/api/memory")[0], 404)
            self.assertEqual(self.call("POST", "/api/memory", {"op": "forget", "confirm": True})[0], 404)

    def test_public_site_does_not_let_strangers_set_the_sec_contact(self):
        with mock.patch.dict(os.environ, HOSTED), mock.patch.object(auth, "cloud_enabled", return_value=False):
            self.assertEqual(self.call("POST", "/api/sec-contact", {"name": "Eve", "email": "eve@example.com"})[0], 404)

    def test_the_page_is_told_so_it_can_say_it(self):
        with mock.patch.dict(os.environ, HOSTED), mock.patch.object(auth, "cloud_enabled", return_value=False):
            code, me = self.call("GET", "/api/auth/me")
        self.assertEqual(code, 200)
        self.assertTrue(me["hosted"])
        self.assertFalse(me["memory"])

    def test_your_own_computer_keeps_the_notes_file(self):
        env = {k: v for k, v in os.environ.items() if k != "PORT"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(auth, "cloud_enabled", return_value=False):
            self.assertEqual(self.call("GET", "/api/memory")[0], 200)
            code, me = self.call("GET", "/api/auth/me")
        self.assertTrue(me["memory"])
        self.assertFalse(me["hosted"])

    def test_accounts_mode_keeps_notes_per_person_even_when_public(self):
        with mock.patch.dict(os.environ, HOSTED), mock.patch.object(auth, "cloud_enabled", return_value=True), \
                mock.patch.object(auth, "current_user", return_value=(None, None)):
            self.assertEqual(self.call("GET", "/api/memory")[0], 401)   # login, not 404: the feature exists, per account

    def test_tick_never_reads_the_shared_file_on_a_public_site(self):
        with mock.patch.dict(os.environ, HOSTED), mock.patch.object(auth, "cloud_enabled", return_value=False), \
                mock.patch.object(server.memory, "for_chat", side_effect=AssertionError("must not be read")):
            self.assertIsNone(server._memory_for_chat(None))


class FakeRequest:
    """Just enough of a request handler for _client_ip: headers and the socket peer."""
    def __init__(self, headers, peer="10.9.9.9"):
        self.headers = headers
        self.client_address = (peer, 5555)

    _client_ip = server.Handler._client_ip


class ClientIp(unittest.TestCase):
    def ip(self, headers, hosted=True):
        env = HOSTED if hosted else {}
        with mock.patch.dict(os.environ, env):
            if not hosted:
                os.environ.pop("PORT", None)
            return FakeRequest(headers)._client_ip()

    def test_locally_headers_are_ignored(self):
        self.assertEqual(self.ip({"X-Forwarded-For": "1.2.3.4", "CF-Connecting-IP": "5.6.7.8"}, hosted=False), "10.9.9.9")

    def test_a_forged_left_end_of_x_forwarded_for_does_not_pick_the_bucket(self):
        # a visitor typed 1.1.1.1; our proxies appended the real address after it
        self.assertEqual(self.ip({"X-Forwarded-For": "1.1.1.1, 203.0.113.7"}), "203.0.113.7")

    def test_cloudflares_own_header_wins(self):
        self.assertEqual(self.ip({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "1.1.1.1, 9.9.9.9"}), "203.0.113.7")

    def test_junk_falls_back_to_the_peer_instead_of_filling_the_table(self):
        self.assertEqual(self.ip({"CF-Connecting-IP": "not-an-ip"}), "10.9.9.9")
        self.assertEqual(self.ip({"X-Forwarded-For": "<script>"}), "10.9.9.9")

    def test_no_headers_means_the_peer(self):
        self.assertEqual(self.ip({}), "10.9.9.9")


class ConnectionLimits(unittest.TestCase):
    def test_a_stalled_client_is_dropped_not_waited_on_forever(self):
        self.assertEqual(server.Handler.timeout, server.CONN_TIMEOUT)
        self.assertTrue(0 < server.CONN_TIMEOUT <= 60)

    def test_connections_past_the_cap_are_refused_immediately(self):
        srv = server.BoundedServer(("127.0.0.1", 0), server.Handler)
        try:
            for _ in range(server.MAX_CONNECTIONS):
                self.assertTrue(srv._slots.acquire(blocking=False))
            with mock.patch.object(srv, "shutdown_request") as closed, \
                    mock.patch.object(ThreadingHTTPServer, "process_request") as spawned:
                srv.process_request(object(), ("1.2.3.4", 1))
            closed.assert_called_once()
            spawned.assert_not_called()
        finally:
            srv.server_close()

    def test_a_finished_connection_frees_its_slot(self):
        srv = server.BoundedServer(("127.0.0.1", 0), server.Handler)
        try:
            self.assertTrue(srv._slots.acquire(blocking=False))
            with mock.patch.object(ThreadingHTTPServer, "process_request_thread"):
                srv.process_request_thread(object(), ("1.2.3.4", 1))
            for _ in range(server.MAX_CONNECTIONS):   # every slot is free again, so all of them can be taken
                self.assertTrue(srv._slots.acquire(blocking=False))
        finally:
            srv.server_close()


class PageIsSelfContained(unittest.TestCase):
    def test_no_page_loads_anything_from_a_third_party(self):
        web = Path(server.WEB)
        for page in ("index.html", "privacy.html", "styles.css", "fonts.css"):
            text = (web / page).read_text(encoding="utf-8")
            self.assertNotIn("googleapis", text, page)
            self.assertNotIn("gstatic", text, page)
        self.assertNotIn("googleapis", server.CSP)
        self.assertNotIn("gstatic", server.CSP)

    def test_every_font_the_css_names_is_actually_shipped(self):
        import re
        web = Path(server.WEB)
        for name in re.findall(r"url\((/fonts/[^)]+)\)", (web / "fonts.css").read_text(encoding="utf-8")):
            self.assertTrue((web / name.lstrip("/")).is_file(), name)


if __name__ == "__main__":
    unittest.main()
