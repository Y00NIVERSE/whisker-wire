"""Offline tests for accounts. Nothing here calls a real Supabase project: the crypto and cookie logic
are pure and fully testable; everything that would hit the network is exercised with mocks."""
import base64
import hashlib
import hmac as hmac_mod
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

import auth  # noqa: E402
import cloud_memory  # noqa: E402
import mailing  # noqa: E402
import memory  # noqa: E402
import server  # noqa: E402

SECRET = "test-jwt-secret-does-not-need-to-be-real"


def make_jwt(claims, secret=SECRET, alg_header=None):
    def b64(d):
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
    head = b64(json.dumps(alg_header or {"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps(claims).encode())
    sig = b64(hmac_mod.new(secret.encode(), f"{head}.{payload}".encode(), hashlib.sha256).digest())
    return f"{head}.{payload}.{sig}"


CLOUD_ENV = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon", "SUPABASE_SERVICE_KEY": "svc", "SUPABASE_JWT_SECRET": SECRET}


class ConfigTest(unittest.TestCase):
    def test_needs_all_four_pieces(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(auth.cloud_enabled())
        with mock.patch.dict("os.environ", {**CLOUD_ENV, "SUPABASE_JWT_SECRET": ""}, clear=True):
            self.assertFalse(auth.cloud_enabled())
        with mock.patch.dict("os.environ", CLOUD_ENV, clear=True):
            self.assertTrue(auth.cloud_enabled())

    def test_cookies_are_only_secure_when_a_real_domain_is_configured(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(auth.cookie_secure())
        with mock.patch.dict("os.environ", {"ALLOWED_HOSTS": "example.com"}, clear=True):
            self.assertTrue(auth.cookie_secure())


class JwtTest(unittest.TestCase):
    def test_valid_token_round_trips(self):
        tok = make_jwt({"sub": "user-1", "email": "a@b.com", "exp": time.time() + 3600, "aud": "authenticated"})
        claims = auth.verify_jwt(tok, SECRET)
        self.assertEqual((claims["sub"], claims["email"]), ("user-1", "a@b.com"))

    def test_wrong_secret_is_rejected(self):
        tok = make_jwt({"sub": "u", "exp": time.time() + 3600})
        self.assertIsNone(auth.verify_jwt(tok, "a-different-secret"))

    def test_expired_token_is_rejected(self):
        tok = make_jwt({"sub": "u", "exp": time.time() - 10})
        self.assertIsNone(auth.verify_jwt(tok, SECRET))

    def test_tampered_payload_is_rejected(self):
        tok = make_jwt({"sub": "u", "exp": time.time() + 3600})
        head, payload, sig = tok.split(".")
        forged_payload = base64.urlsafe_b64encode(json.dumps({"sub": "attacker", "exp": time.time() + 3600}).encode()).rstrip(b"=").decode()
        self.assertIsNone(auth.verify_jwt(f"{head}.{forged_payload}.{sig}", SECRET))

    def test_wrong_audience_is_rejected(self):
        tok = make_jwt({"sub": "u", "exp": time.time() + 3600, "aud": "some-other-app"})
        self.assertIsNone(auth.verify_jwt(tok, SECRET))

    def test_garbage_is_rejected_not_raised(self):
        self.assertIsNone(auth.verify_jwt("not-a-jwt-at-all", SECRET))
        self.assertIsNone(auth.verify_jwt("", SECRET))
        self.assertIsNone(auth.verify_jwt("a.b", SECRET))


class CookieTest(unittest.TestCase):
    def test_session_cookies_are_httponly_and_carry_the_tokens(self):
        headers = auth.session_cookies({"access_token": "AT", "refresh_token": "RT"})
        self.assertEqual(len(headers), 2)
        self.assertTrue(any("sb_at=AT" in h and "HttpOnly" in h for h in headers))
        self.assertTrue(any("sb_rt=RT" in h and "HttpOnly" in h for h in headers))
        self.assertTrue(all("Secure" not in h for h in headers))   # no ALLOWED_HOSTS set in the test environment

    def test_clearing_cookies_sets_max_age_zero(self):
        headers = auth.session_cookies(None, clear=True)
        self.assertTrue(all("Max-Age=0" in h for h in headers))

    def test_secure_flag_follows_hosted_mode(self):
        with mock.patch.dict("os.environ", {"ALLOWED_HOSTS": "example.com"}):
            headers = auth.session_cookies({"access_token": "AT", "refresh_token": "RT"})
        self.assertTrue(all("Secure" in h for h in headers))

    def test_read_cookies_parses_a_request_header(self):
        got = auth.read_cookies("sb_at=abc123; sb_rt=def456; other=ignored")
        self.assertEqual((got[auth.ACCESS_COOKIE], got[auth.REFRESH_COOKIE]), ("abc123", "def456"))

    def test_read_cookies_handles_missing_or_malformed_header(self):
        self.assertEqual(auth.read_cookies(None), {})
        self.assertEqual(auth.read_cookies(""), {})
        self.assertEqual(auth.read_cookies(";;;not a cookie;;;"), {})


class CurrentUserTest(unittest.TestCase):
    def test_local_mode_never_touches_the_network(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(auth, "refresh_session") as r:
            user, cookies = auth.current_user("sb_at=" + make_jwt({"sub": "u", "exp": time.time() + 3600}))
        self.assertEqual((user, cookies), (None, None))
        r.assert_not_called()

    def test_valid_access_cookie_is_accepted_without_a_refresh_call(self):
        tok = make_jwt({"sub": "user-1", "email": "a@b.com", "exp": time.time() + 3600, "aud": "authenticated"})
        with mock.patch.dict("os.environ", CLOUD_ENV, clear=True), mock.patch.object(auth, "refresh_session") as r:
            user, cookies = auth.current_user(f"sb_at={tok}")
        self.assertEqual(user, {"id": "user-1", "email": "a@b.com"})
        self.assertIsNone(cookies)
        r.assert_not_called()

    def test_expired_access_token_refreshes_using_the_refresh_cookie(self):
        expired = make_jwt({"sub": "user-1", "exp": time.time() - 5})
        fresh = make_jwt({"sub": "user-1", "email": "a@b.com", "exp": time.time() + 3600, "aud": "authenticated"})
        with mock.patch.dict("os.environ", CLOUD_ENV, clear=True), \
                mock.patch.object(auth, "refresh_session", return_value={"access_token": fresh, "refresh_token": "new-rt"}) as r:
            user, cookies = auth.current_user(f"sb_at={expired}; sb_rt=old-rt")
        r.assert_called_once_with("old-rt")
        self.assertEqual(user["email"], "a@b.com")
        self.assertTrue(any("sb_at=" + fresh in c for c in cookies))

    def test_dead_refresh_token_clears_cookies_instead_of_looping(self):
        with mock.patch.dict("os.environ", CLOUD_ENV, clear=True), mock.patch.object(auth, "refresh_session", return_value=None):
            user, cookies = auth.current_user("sb_rt=revoked")
        self.assertIsNone(user)
        self.assertTrue(cookies and all("Max-Age=0" in c for c in cookies))

    def test_no_cookies_at_all_is_just_logged_out(self):
        with mock.patch.dict("os.environ", CLOUD_ENV, clear=True):
            self.assertEqual(auth.current_user(""), (None, None))
            self.assertEqual(auth.current_user(None), (None, None))


class SignUpSignInTest(unittest.TestCase):
    def test_short_password_is_rejected_before_any_network_call(self):
        with mock.patch.object(auth, "_request") as r:
            with self.assertRaises(auth.AuthError):
                auth.sign_up("a@b.com", "short")
        r.assert_not_called()

    def test_successful_signup_returns_a_session(self):
        with mock.patch.object(auth, "_request", return_value={"access_token": "AT", "refresh_token": "RT", "user": {"email": "a@b.com"}}):
            session = auth.sign_up("a@b.com", "longenough1")
        self.assertEqual(session["access_token"], "AT")

    def test_signup_pending_email_confirmation_is_not_a_hard_failure(self):
        with mock.patch.object(auth, "_request", return_value={"user": {"id": "u1"}}):
            with self.assertRaises(auth.AuthError) as cm:
                auth.sign_up("a@b.com", "longenough1")
        self.assertTrue(cm.exception.pending)

    def test_supabase_error_strings_are_translated_to_plain_english(self):
        self.assertIn("don't match", auth._friendly("Invalid login credentials"))
        self.assertIn("already exists", auth._friendly("User already registered"))
        self.assertIn("at least", auth._friendly("Password should be at least 6 characters"))

    def test_sign_in_raises_friendly_error_on_bad_credentials(self):
        def boom(*a, **k):
            raise auth.AuthError("That email and password don't match.")
        with mock.patch.object(auth, "_request", side_effect=boom):
            with self.assertRaises(auth.AuthError):
                auth.sign_in("a@b.com", "wrongpassword")

    def test_sign_out_never_raises_even_if_supabase_is_down(self):
        with mock.patch.object(auth, "_request", side_effect=ConnectionError("down")):
            auth.sign_out("some-token")   # must not raise


class CloudMemoryTest(unittest.TestCase):
    """The request-building and response-shaping logic, against a fake PostgREST."""

    def test_get_all_shapes_match_the_local_version(self):
        calls = []

        def fake(method, path, body=None, prefer=None):
            calls.append((method, path))
            if path.startswith("profile"):
                return [{"experience": "beginner", "markets": ["hk"]}]
            if path.startswith("watchlist"):
                return [{"symbol": "TSLA"}, {"symbol": "NVDA"}]
            if path.startswith("thesis"):
                return [{"id": 1, "symbol": "TSLA", "name": "Tesla", "note": "note", "invalidate_if": None,
                         "review_below": None, "review_above": None, "created_at": "2026-01-01T00:00:00+00:00",
                         "updated_at": "2026-01-02T00:00:00+00:00", "snap": {"price": 300.0}}]
            return []
        with mock.patch.object(cloud_memory, "_rest", side_effect=fake):
            a = cloud_memory.get_all("user-1")
        self.assertEqual(a["cloud"], True)
        self.assertEqual((a["experience"], a["markets"], a["watchlist"]), ("beginner", ["hk"], ["TSLA", "NVDA"]))
        t = a["theses"][0]
        self.assertIsInstance(t["created"], int)
        self.assertIsInstance(t["updated"], int)
        self.assertEqual(t["snap"]["price"], 300.0)
        self.assertTrue(all("user-1" in c[1] for c in calls))   # every query was scoped to this user

    def test_set_watch_normalises_dedupes_and_writes_delete_then_insert(self):
        with mock.patch.object(cloud_memory, "_rest", return_value=[]) as r:
            cloud_memory.set_watch("user-1", ["tsla", "TSLA", " nvda "])
        methods = [c.args[0] for c in r.call_args_list]
        self.assertEqual(methods, ["GET", "DELETE", "POST"])
        posted = r.call_args_list[-1].args[2]
        self.assertEqual([row["symbol"] for row in posted], ["TSLA", "NVDA"])
        self.assertTrue(all(row["user_id"] == "user-1" for row in posted))

    def test_set_watch_over_the_limit_is_rejected_without_writing(self):
        with mock.patch.object(cloud_memory, "_rest") as r:
            with self.assertRaises(ValueError):
                cloud_memory.set_watch("user-1", [f"T{i}" for i in range(memory.MAX_WATCH + 1)])
        r.assert_not_called()

    def test_set_watch_rejects_bad_ticker_without_writing(self):
        with mock.patch.object(cloud_memory, "_rest") as r:
            with self.assertRaises(ValueError):
                cloud_memory.set_watch("user-1", ["<script>"])
        r.assert_not_called()

    def test_save_thesis_update_checks_ownership(self):
        with mock.patch.object(cloud_memory, "_rest", return_value=[]):   # empty = no row matched id+user_id
            with self.assertRaises(ValueError):
                cloud_memory.save_thesis("user-1", {"id": 999, "symbol": "TSLA", "note": "a real note here"})

    def test_forget_all_deletes_from_every_table(self):
        with mock.patch.object(cloud_memory, "_rest", return_value=[]) as r:
            cloud_memory.forget_all("user-1")
        deleted = {c.args[1].split("?")[0] for c in r.call_args_list if c.args[0] == "DELETE"}
        self.assertEqual(deleted, set(cloud_memory.REQUIRED_TABLES))

    def test_drift_works_unchanged_against_a_cloud_shaped_thesis(self):
        import memory
        t = {"created": 1_700_000_000, "review_below": None, "review_above": None,
             "snap": {"price": 100.0, "currency": "USD"}}
        d = memory.drift(t, {"price": 80.0, "currency": "USD"}, now=1_700_000_000 + 86400)
        self.assertGreater(d["points"], 0)


class ServerGateTest(unittest.TestCase):
    """Route guarding, with the network entirely mocked out."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("GET", path)
        r = c.getresponse()
        return r.status, r.read()

    def test_local_mode_serves_the_app_directly(self):
        # The signup/login markup ships on every page (JS shows it only in cloud mode); the server
        # itself never swaps in a different page based on login state any more.
        with mock.patch.object(auth, "cloud_enabled", return_value=False):
            code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Whisker Wire", body)

    def test_hosted_mode_still_serves_the_real_app_while_logged_out(self):
        # The whole point of the soft gate: a stranger sees the real wire, not a landing page.
        with mock.patch.object(auth, "cloud_enabled", return_value=True), mock.patch.object(auth, "current_user", return_value=(None, None)):
            code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Whisker Wire", body)

    def test_hosted_mode_shows_the_app_once_logged_in(self):
        with mock.patch.object(auth, "cloud_enabled", return_value=True), \
                mock.patch.object(auth, "current_user", return_value=({"id": "u1", "email": "a@b.com"}, None)):
            code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Whisker Wire", body)

    def test_public_routes_stay_public_in_hosted_mode_while_logged_out(self):
        with mock.patch.object(auth, "cloud_enabled", return_value=True), mock.patch.object(auth, "current_user", return_value=(None, None)):
            for path in ("/api/markets", "/api/feed", "/api/undervalued", "/api/filings", "/api/track"):
                self.assertNotEqual(self.get(path)[0], 401, path)

    def test_personal_routes_require_login_only_in_hosted_mode(self):
        with mock.patch.object(auth, "cloud_enabled", return_value=False):
            self.assertNotEqual(self.get("/api/memory")[0], 401)
        with mock.patch.object(auth, "cloud_enabled", return_value=True), mock.patch.object(auth, "current_user", return_value=(None, None)):
            self.assertEqual(self.get("/api/memory")[0], 401)
            self.assertEqual(self.post_json("/api/chat", {"q": "hi"})[0], 401)
        with mock.patch.object(auth, "cloud_enabled", return_value=True), \
                mock.patch.object(auth, "current_user", return_value=({"id": "u1", "email": "a@b.com"}, None)):
            self.assertNotEqual(self.get("/api/memory")[0], 401)

    def test_auth_endpoints_stay_reachable_while_logged_out(self):
        with mock.patch.object(auth, "cloud_enabled", return_value=True), mock.patch.object(auth, "current_user", return_value=(None, None)):
            code, _ = self.get("/api/auth/me")
        self.assertEqual(code, 200)

    def test_sec_contact_endpoint_is_disabled_once_hosted(self):
        with mock.patch.object(auth, "cloud_enabled", return_value=True), mock.patch.object(auth, "current_user", return_value=({"id": "u1", "email": "a@b.com"}, None)):
            self.assertEqual(self.get("/api/sec-contact")[0], 404)

    def post_json(self, path, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_an_unexpected_auth_error_returns_a_clean_502_not_a_crash(self):
        with mock.patch.object(auth, "sign_up", side_effect=KeyError("unexpected shape")):
            code, body = self.post_json("/api/auth/signup", {"email": "a@b.com", "password": "longenough1"})
        self.assertEqual(code, 502)
        self.assertIn("error", body)

    def test_signup_sets_cookies_and_subscribes_when_opted_in(self):
        session = {"access_token": "AT", "refresh_token": "RT", "user": {"email": "a@b.com"}}
        with mock.patch.object(auth, "sign_up", return_value=session), mock.patch.object(mailing, "subscribe") as sub:
            c = http.client.HTTPConnection("127.0.0.1", self.port)
            c.request("POST", "/api/auth/signup", body=json.dumps({"email": "a@b.com", "password": "longenough1", "newsletter": True}),
                      headers={"Content-Type": "application/json"})
            r = c.getresponse()
            set_cookie = r.getheader("Set-Cookie")
            body = json.loads(r.read())
        self.assertEqual(r.status, 200)
        self.assertEqual(body, {"ok": True, "email": "a@b.com"})
        self.assertIn("sb_at=AT", set_cookie)
        sub.assert_called_once_with("a@b.com")

    def test_signup_never_subscribes_without_explicit_opt_in(self):
        session = {"access_token": "AT", "refresh_token": "RT", "user": {"email": "a@b.com"}}
        with mock.patch.object(auth, "sign_up", return_value=session), mock.patch.object(mailing, "subscribe") as sub:
            self.post_json("/api/auth/signup", {"email": "a@b.com", "password": "longenough1"})
        sub.assert_not_called()

    def test_logout_clears_cookies(self):
        with mock.patch.object(auth, "read_cookies", return_value={}):
            c = http.client.HTTPConnection("127.0.0.1", self.port)
            c.request("POST", "/api/auth/logout", body="{}", headers={"Content-Type": "application/json"})
            r = c.getresponse()
            set_cookie = r.getheader("Set-Cookie")
            r.read()
        self.assertIn("Max-Age=0", set_cookie)


if __name__ == "__main__":
    unittest.main()
