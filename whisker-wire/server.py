#!/usr/bin/env python3
"""Whisker Wire: local server. Run `python server.py` and open http://127.0.0.1:8787

Standard library only. Binds to localhost, keeps no accounts and no logs of what you read.
"""
import argparse
import json
import mimetypes
import re
import sys
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import engine
import memory
import tick_chat
from markets import market_list, valid_market
from signals import SIGNALS

WEB = (Path(__file__).parent / "web").resolve()
CSP = ("default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _signals():
    return {"signals": [{k: s[k] for k in ("id", "label", "dir", "cat", "weight", "pattern", "note")} for s in SIGNALS]}


def _mk(q):
    """The market the browser asked for; anything unknown quietly becomes the default."""
    return valid_market((q.get("market") or [""])[0])


def _health(market="us"):
    f = engine.get_feed(market)
    return {"sources": f["health"], "sec_configured": bool(engine.sec_agent())}


def _post_sec(body):
    try:
        contact = engine.save_sec_contact(f"{body.get('name', '')} {body.get('email', '')}")
    except ValueError:
        raise ValueError("Enter your name and a real email address.")
    return {"ok": True, "configured": True, "contact": contact}


def _post_chat(body):
    hist = body.get("history")
    try:
        mem = memory.for_chat()
    except Exception:
        mem = None   # a broken memory file must never stop Tick from answering
    return tick_chat.answer(body.get("q", ""), body.get("market", "us"), hist if isinstance(hist, list) else None, mem)


# path -> (largest body accepted in bytes, handler)
POST_ROUTES = {"/api/sec-contact": (2048, _post_sec), "/api/chat": (8192, _post_chat), "/api/memory": (8192, memory.handle)}

ROUTES = {
    "/api/feed": lambda q: engine.get_feed(_mk(q)),
    "/api/quotes": lambda q: engine.get_quotes(_mk(q)),
    "/api/undervalued": lambda q: engine.get_undervalued(_mk(q)),
    "/api/markets": lambda q: {"markets": market_list()},
    "/api/filings": lambda q: engine.get_filings(),
    "/api/signals": lambda q: _signals(),
    "/api/chat-status": lambda q: tick_chat.status(),
    "/api/memory": lambda q: memory.get_all(),
    "/api/track": lambda q: engine.get_track(),
    "/api/health": lambda q: _health(_mk(q)),
    "/api/ticker": lambda q: engine.get_ticker(q.get("symbol", [""])[0]),
    "/api/article": lambda q: engine.get_article(q.get("url", [""])[0]),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "WhiskerWire/0.1"

    def _send(self, code, body, ctype, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _host_ok(self):
        # DNS-rebinding guard: only answer requests addressed to this machine by name or loopback IP.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def do_POST(self):
        # The only writes and paid lookups: saving the SEC contact and asking Tick. Guarded against cross-site
        # requests: same-origin only, JSON only (a cross-origin page cannot send that without a preflight we never grant).
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
            return self._json(403, {"error": "cross-site request refused"})
        route = POST_ROUTES.get(urllib.parse.urlparse(self.path).path)
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
        try:
            return self._json(200, fn(body))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception:
            return self._json(502, {"error": "Tick could not reach her sources just now. Try again in a moment."})

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/api/"):
            fn = ROUTES.get(u.path)
            if not fn:
                return self._json(404, {"error": "unknown endpoint"})
            try:
                return self._json(200, fn(urllib.parse.parse_qs(u.query)))
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
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Whisker Wire running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)", flush=True)
    if not engine.sec_agent():
        print("SEC filings are off: add your contact to whisker-wire/sec_contact.txt (see README).", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
