#!/usr/bin/env python3
"""Whisker Wire server. Run `python server.py` and open http://127.0.0.1:8787

Two modes, chosen entirely by whether SUPABASE_URL etc. are set (see auth.py):

- Local/offline (default): no accounts, no gate, one shared "Tick remembers" file on this computer.
  Exactly how this app has always worked. Binds to localhost only. If a host assigns PORT but accounts
  are not set up, it still runs as a public preview, but with server-side notes and the SEC-contact
  form switched off, because one shared file must never be writable by strangers.
- Hosted (cloud mode): set SUPABASE_URL/SUPABASE_ANON_KEY/SUPABASE_SERVICE_KEY/SUPABASE_JWT_SECRET and
  ALLOWED_HOSTS. The wire, Value Radar and filings stay open to anyone, so a visitor can scroll around
  before deciding anything; a free account is only asked for at the two personal features, Ask Tick and
  Tick remembers, each kept separately per person. See DEPLOY.md for the one-time setup.

Standard library only either way.
"""
import argparse
import ipaddress
import json
import mimetypes
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import auth
import cloud_memory
import engine
import mailing
import memory
import tick_chat
from markets import market_list, valid_market
from signals import SIGNALS

mimetypes.add_type("font/woff2", ".woff2")   # not every Python version knows it, and X-Content-Type-Options is nosniff

WEB = (Path(__file__).parent / "web").resolve()
CSP = ("default-src 'self'; style-src 'self'; font-src 'self'; "
       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

# The only two things a visitor needs an account for: asking Tick anything, and Tick remembers (which
# is inherently per-person). Everything else - the wire, Value Radar, filings, reading an article - is
# open to anyone, logged in or not, so there is something real to look at before ever being asked to sign up.
PROTECTED_WHEN_CLOUD = {"/api/chat", "/api/memory"}

CONN_TIMEOUT = 30    # seconds a client may stall mid-request before its connection is dropped (slow-loris guard)
MAX_CONNECTIONS = 100


def _hosted():
    """True on a host that assigns PORT (Render, Fly, Heroku, ...), i.e. not one person's own computer."""
    return bool(os.environ.get("PORT"))


def _disabled(path):
    """Routes that read or write one file shared by every visitor. That is exactly right on your own
    computer and exactly wrong on a public site: strangers would see and erase each other's notes, or
    overwrite whose name goes to the SEC. So they stay off unless each person has their own storage."""
    cloud = auth.cloud_enabled()
    if path == "/api/sec-contact":
        return cloud or _hosted()          # the operator sets this via SEC_USER_AGENT instead
    if path == "/api/memory":
        return _hosted() and not cloud     # cloud mode keeps it per account instead
    return False


def _signals():
    return {"signals": [{k: s[k] for k in ("id", "label", "dir", "cat", "weight", "pattern", "note")} for s in SIGNALS]}


def _mk(q):
    """The market the browser asked for; anything unknown quietly becomes the default."""
    return valid_market((q.get("market") or [""])[0])


def _health(market="us"):
    f = engine.get_feed(market)
    return {"sources": f["health"], "sec_configured": bool(engine.sec_agent())}


def _post_sec(body, user, ip):
    try:
        contact = engine.save_sec_contact(f"{body.get('name', '')} {body.get('email', '')}")
    except ValueError:
        raise ValueError("Enter your name and a real email address.")
    return {"ok": True, "configured": True, "contact": contact}


def _memory_for_chat(user):
    if not user and _disabled("/api/memory"):
        return None   # the shared file belongs to nobody in particular, so it must never colour a stranger's answer
    try:
        return cloud_memory.for_chat(user["id"]) if user else memory.for_chat()
    except Exception:
        return None   # a broken memory backend must never stop Tick from answering


def _post_chat(body, user, ip):
    hist = body.get("history")
    # Logged-in users get their own bucket; anonymous ones are limited per-IP, not lumped into one
    # shared bucket that a single visitor could exhaust for everybody else.
    return tick_chat.answer(body.get("q", ""), body.get("market", "us"), hist if isinstance(hist, list) else None,
                            _memory_for_chat(user), rate_key=(user or {}).get("id") or "ip:" + ip)


def _post_memory(body, user, ip):
    return cloud_memory.handle(user["id"], body) if user else memory.handle(body)


def _noop(body, user, ip):
    return None   # /api/auth/* are handled specially in do_POST, since they must set cookies


def _get_article(q, user, ip):
    # The only GET route that makes the server fetch an arbitrary third-party URL, so - unlike the
    # other read-only routes, which just read local/cached data - it needs its own throttle.
    tick_chat.rate_limit("article:" + ip, limit=20, window=600)
    return engine.get_article(q.get("url", [""])[0])


# path -> (largest body accepted in bytes, handler(body, user, ip))
POST_ROUTES = {
    "/api/sec-contact": (2048, _post_sec),
    "/api/chat": (8192, _post_chat),
    "/api/memory": (8192, _post_memory),
    "/api/auth/signup": (512, _noop),
    "/api/auth/login": (512, _noop),
    "/api/auth/logout": (256, _noop),
}

ROUTES = {
    "/api/feed": lambda q, u, ip: engine.get_feed(_mk(q)),
    "/api/quotes": lambda q, u, ip: engine.get_quotes(_mk(q)),
    "/api/undervalued": lambda q, u, ip: engine.get_undervalued(_mk(q)),
    "/api/markets": lambda q, u, ip: {"markets": market_list()},
    "/api/filings": lambda q, u, ip: engine.get_filings(),
    "/api/signals": lambda q, u, ip: _signals(),
    "/api/chat-status": lambda q, u, ip: tick_chat.status(),
    "/api/memory": lambda q, u, ip: cloud_memory.get_all(u["id"]) if u else memory.get_all(),
    "/api/track": lambda q, u, ip: engine.get_track(),
    "/api/health": lambda q, u, ip: _health(_mk(q)),
    "/api/ticker": lambda q, u, ip: engine.get_ticker(q.get("symbol", [""])[0]),
    "/api/article": _get_article,
    "/api/auth/me": lambda q, u, ip: {"email": u["email"] if u else None, "cloud": auth.cloud_enabled(),
                                      "hosted": _hosted(), "memory": not _disabled("/api/memory")},
}


class BoundedServer(ThreadingHTTPServer):
    """One thread per connection is fine for a small site, but only if connections cannot pile up forever:
    past MAX_CONNECTIONS the extra ones are dropped at once instead of each costing a thread and its memory."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "WhiskerWire/0.1"
    timeout = CONN_TIMEOUT   # applied to the client socket: a request that stalls is dropped, not waited on forever

    def _send(self, code, body, ctype, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for c in getattr(self, "_set_cookies", None) or []:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _host_ok(self):
        # DNS-rebinding guard: only answer requests addressed to a name this deployment actually owns.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        allowed = {"127.0.0.1", "localhost", "::1"}
        allowed |= {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}
        return host in allowed

    def _user(self):
        """Resolves who (if anyone) is logged in, and queues a refreshed session cookie if needed.
        Cheap and side-effect-free when there is nothing to refresh: no network call in the common case."""
        self._set_cookies = []
        user, new_cookies = auth.current_user(self.headers.get("Cookie"))
        if new_cookies:
            self._set_cookies = new_cookies
        return user

    def _client_ip(self):
        """Who is asking, for rate limiting. Locally that is just the socket peer. On a host the peer is the
        platform's proxy, so we read what the proxy says - but only the parts a visitor cannot forge:
        Cloudflare (Render's edge) overwrites CF-Connecting-IP, whereas X-Forwarded-For is only ever appended
        to, so its left end is whatever the visitor typed and its right end is what our own proxies wrote."""
        peer = self.client_address[0]
        if not _hosted():
            return peer
        cand = (self.headers.get("CF-Connecting-IP") or "").strip()
        if not cand:
            fwd = [p.strip() for p in (self.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
            cand = fwd[-1] if fwd else ""
        try:
            return str(ipaddress.ip_address(cand))   # also keeps junk out of the rate-limit table
        except ValueError:
            return peer

    def do_POST(self):
        # Guarded against cross-site requests: same-origin only, JSON only (a cross-origin page cannot
        # send that without a preflight we never grant).
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
            return self._json(403, {"error": "cross-site request refused"})
        path = urllib.parse.urlparse(self.path).path
        route = POST_ROUTES.get(path)
        if not route:
            return self._json(404, {"error": "unknown endpoint"})
        limit, fn = route
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._json(415, {"error": "send JSON"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= limit:
                raise ValueError("bad size")
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict):
                raise ValueError("bad body")
        except (ValueError, TypeError):
            return self._json(400, {"error": "Send a small JSON object."})

        user = self._user()
        cloud = auth.cloud_enabled()
        if _disabled(path):
            return self._json(404, {"error": "unknown endpoint"})
        if path in ("/api/auth/signup", "/api/auth/login", "/api/auth/logout"):
            return self._auth_action(path, body)
        if cloud and path in PROTECTED_WHEN_CLOUD and not user:
            return self._json(401, {"error": "Please log in first."})
        try:
            return self._json(200, fn(body, user, self._client_ip()))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception:
            return self._json(502, {"error": "Tick could not reach her sources just now. Try again in a moment."})

    def _auth_action(self, path, body):
        try:
            if path == "/api/auth/signup":
                email, password = str(body.get("email", "")).strip().lower(), body.get("password", "")
                try:
                    session = auth.sign_up(email, password)
                except auth.AuthError as e:
                    if e.pending:
                        return self._json(200, {"ok": True, "pending": True, "message": str(e)})
                    raise
                if body.get("newsletter"):
                    mailing.subscribe(email)
                self._set_cookies = auth.session_cookies(session)
                return self._json(200, {"ok": True, "email": session["user"].get("email", email)})
            if path == "/api/auth/login":
                email, password = str(body.get("email", "")).strip().lower(), body.get("password", "")
                session = auth.sign_in(email, password)
                self._set_cookies = auth.session_cookies(session)
                return self._json(200, {"ok": True, "email": session["user"].get("email", email)})
            if path == "/api/auth/logout":
                at = auth.read_cookies(self.headers.get("Cookie")).get(auth.ACCESS_COOKIE)
                if at:
                    auth.sign_out(at)
                self._set_cookies = auth.session_cookies(None, clear=True)
                return self._json(200, {"ok": True})
        except auth.AuthError as e:
            return self._json(400, {"error": str(e)})
        except ConnectionError as e:
            return self._json(502, {"error": str(e)})
        except Exception:
            return self._json(502, {"error": "Could not reach the account service. Try again in a moment."})

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        u = urllib.parse.urlparse(self.path)
        user = self._user()
        cloud = auth.cloud_enabled()
        if u.path.startswith("/api/"):
            if _disabled(u.path):
                return self._json(404, {"error": "unknown endpoint"})
            fn = ROUTES.get(u.path)
            if not fn:
                return self._json(404, {"error": "unknown endpoint"})
            if cloud and u.path in PROTECTED_WHEN_CLOUD and not user:
                return self._json(401, {"error": "Please log in first."})
            try:
                return self._json(200, fn(urllib.parse.parse_qs(u.query), user, self._client_ip()))
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            except urllib.error.HTTPError as e:
                return self._json(502, {"error": f"The publisher refused automated access (HTTP {e.code}). Paste the text instead."})
            except Exception as e:
                return self._json(502, {"error": f"upstream failed: {type(e).__name__}"})
        rel = "index.html" if u.path in ("", "/") else urllib.parse.unquote(u.path).lstrip("/")
        f = (WEB / rel).resolve()
        if WEB not in f.parents or not f.is_file():
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype, cache="no-cache")

    def log_message(self, fmt, *args):  # no request logging: what you read stays private
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default=None)
    args = ap.parse_args()
    port = int(os.environ.get("PORT") or args.port)
    # A host assigns PORT itself (Render, Fly, Heroku, ...); that, not ALLOWED_HOSTS, is the real signal
    # that this isn't a laptop anymore. Binding stayed local-only otherwise, even with ALLOWED_HOSTS set
    # for some other reason, so a forgotten PORT never accidentally opens the machine to the network.
    host = args.host or os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    srv = BoundedServer((host, port), Handler)
    cloud = auth.cloud_enabled()
    print(f"Whisker Wire running at http://{host}:{port}  ({'accounts on' if cloud else 'local mode, no accounts'})", flush=True)
    if cloud and not mailing.enabled():
        print("Mailing list is off: set BUTTONDOWN_API_KEY to collect newsletter sign-ups.", flush=True)
    if not cloud and not engine.sec_agent():
        print("SEC filings are off: add your contact to whisker-wire/sec_contact.txt (see README).", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
