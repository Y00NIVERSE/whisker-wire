"""Accounts, for the hosted version only.

Local/offline mode (no SUPABASE_URL set) is completely unaffected by this file: server.py never calls
into it, and the app behaves exactly as before, one shared local memory, no login. Set SUPABASE_URL to
switch the running server into hosted mode, where every visitor gets their own account and their own
"Tick remembers" data, stored in Supabase's Postgres instead of a local SQLite file.

Passwords are never handled here beyond forwarding them once, over HTTPS, to Supabase Auth (GoTrue),
which does the hashing and storage. This file: talks to that API, verifies the session token it hands
back (a standard HS256 JWT, checked with stdlib hmac so no JWT library is needed), and turns that into
an HttpOnly cookie pair this server issues itself. The browser never talks to Supabase directly and
never sees a Supabase key, matching how every other feature in this app works (chat, memory, filings
all go through this server, never straight from the browser to a third party).
"""
import base64
import hmac
import http.cookies
import json
import os
import time
import urllib.error
import urllib.request

SESSION_MAX_AGE = 30 * 24 * 3600   # 30 days, refreshed on every visit while the refresh token is valid
ACCESS_COOKIE, REFRESH_COOKIE = "sb_at", "sb_rt"
MIN_PASSWORD = 8


def config():
    return {
        "url": (os.environ.get("SUPABASE_URL") or "").rstrip("/"),
        "anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
        "service_key": os.environ.get("SUPABASE_SERVICE_KEY", ""),
        "jwt_secret": os.environ.get("SUPABASE_JWT_SECRET", ""),
    }


def cloud_enabled():
    c = config()
    return bool(c["url"] and c["anon_key"] and c["service_key"] and c["jwt_secret"])


def cookie_secure():
    """Cookies only get the Secure flag when the site is actually served over HTTPS (real hosting).
    Forcing Secure during local http:// testing would make the browser silently refuse to store them."""
    return bool(os.environ.get("ALLOWED_HOSTS"))


# ---------------------------------------------------------------- talking to Supabase Auth (GoTrue)
class AuthError(ValueError):
    """Message is already phrased for the person signing up or logging in."""
    def __init__(self, message, pending=False):
        super().__init__(message)
        self.pending = pending   # True for "check your email to confirm" - not a failure, just no session yet


def _request(method, url, body=None, headers=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            payload = {}
        msg = payload.get("error_description") or payload.get("msg") or payload.get("error") or payload.get("message")
        if e.code == 429:
            raise AuthError("Too many attempts. Wait a minute and try again.")
        if e.code in (400, 401, 403, 422) and msg:
            raise AuthError(_friendly(msg))
        raise ConnectionError(f"Supabase returned HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError):
        raise ConnectionError("Could not reach the account service")


def _friendly(msg):
    low = msg.lower()
    if "already registered" in low or "already exists" in low or "user_already_exists" in low:
        return "An account with that email already exists. Try logging in instead."
    if "invalid login" in low or "invalid_credentials" in low or "invalid email or password" in low:
        return "That email and password don't match."
    if "password" in low and ("short" in low or "at least" in low or "weak" in low):
        return f"Password must be at least {MIN_PASSWORD} characters."
    if "email" in low and ("invalid" in low or "unable to validate" in low):
        return "Enter a real email address."
    if "email not confirmed" in low:
        return "Please confirm your email first: check your inbox for a link from us."
    return msg[:200]


def _auth_url(path):
    return config()["url"] + "/auth/v1/" + path


def _session_from(payload):
    """Supabase can also return {'user': ..., 'session': None} when email confirmation is required."""
    if not payload.get("access_token"):
        return None
    return {"access_token": payload["access_token"], "refresh_token": payload.get("refresh_token", ""),
            "user": payload.get("user") or {}}


def sign_up(email, password):
    c = config()
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    payload = _request("POST", _auth_url("signup"), {"email": email, "password": password}, {"apikey": c["anon_key"]})
    session = _session_from(payload)
    if session:
        return session
    if payload.get("id") or payload.get("user"):
        raise AuthError("Account created. Check your email to confirm it, then log in.", pending=True)
    raise AuthError("Could not create the account. Try again.")


def sign_in(email, password):
    c = config()
    payload = _request("POST", _auth_url("token?grant_type=password"), {"email": email, "password": password}, {"apikey": c["anon_key"]})
    session = _session_from(payload)
    if not session:
        raise AuthError("That email and password don't match.")
    return session


def refresh_session(refresh_token):
    c = config()
    payload = _request("POST", _auth_url("token?grant_type=refresh_token"), {"refresh_token": refresh_token}, {"apikey": c["anon_key"]})
    return _session_from(payload)


def sign_out(access_token):
    c = config()
    try:
        _request("POST", _auth_url("logout"), {}, {"apikey": c["anon_key"], "Authorization": f"Bearer {access_token}"})
    except Exception:
        pass   # the cookies get cleared regardless; a failed revoke is not worth failing logout over


# ---------------------------------------------------------------- verifying a session token (no network call)
def _b64url_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_jwt(token, secret):
    """Check a Supabase access token's signature and expiry using stdlib hmac. No library, no network."""
    try:
        head_b64, payload_b64, sig_b64 = token.split(".")
        sig = _b64url_decode(sig_b64)
        expected = hmac.new(secret.encode(), f"{head_b64}.{payload_b64}".encode(), "sha256").digest()
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None
    if claims.get("exp", 0) <= time.time():
        return None
    if claims.get("aud") not in (None, "authenticated"):
        return None
    return claims


# ---------------------------------------------------------------- cookies
def session_cookies(session, clear=False):
    """Set-Cookie header values for a session, or to clear one (clear=True)."""
    out = []
    for name, value in ((ACCESS_COOKIE, session["access_token"] if session else ""), (REFRESH_COOKIE, session["refresh_token"] if session else "")):
        c = http.cookies.SimpleCookie()
        c[name] = value
        c[name]["httponly"] = True
        c[name]["path"] = "/"
        c[name]["samesite"] = "Lax"
        if cookie_secure():
            c[name]["secure"] = True
        c[name]["max-age"] = 0 if clear else SESSION_MAX_AGE
        out.append(c[name].OutputString())
    return out


def read_cookies(header):
    jar = http.cookies.SimpleCookie()
    try:
        jar.load(header or "")
    except http.cookies.CookieError:
        return {}
    return {k: v.value for k, v in jar.items()}


def current_user(cookie_header):
    """(user, new_cookie_headers_or_None). user is {"id", "email"} or None. Transparently refreshes an
    expired access token using the refresh cookie, so a visitor is not logged out every hour for no reason."""
    if not cloud_enabled():
        return None, None
    cookies = read_cookies(cookie_header)
    secret = config()["jwt_secret"]
    at = cookies.get(ACCESS_COOKIE)
    if at:
        claims = verify_jwt(at, secret)
        if claims:
            return {"id": claims.get("sub"), "email": claims.get("email")}, None
    rt = cookies.get(REFRESH_COOKIE)
    if not rt:
        return None, None
    try:
        session = refresh_session(rt)
    except Exception:
        return None, None
    if not session:
        return None, session_cookies(None, clear=True)
    claims = verify_jwt(session["access_token"], secret)
    if not claims:
        return None, None
    return {"id": claims.get("sub"), "email": claims.get("email")}, session_cookies(session)
