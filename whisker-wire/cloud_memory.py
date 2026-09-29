"""Tick remembers, hosted version: the same feature as memory.py, one row per person instead of one
shared file. Only used when auth.cloud_enabled() is true. The validation rules, the wording, the limits,
and the thesis-drift maths are shared with memory.py on purpose, so a note behaves identically whether
it lives in a local file or in your account: this module only swaps out where the bytes are kept.

Talks to Supabase's Postgres over its REST interface (PostgREST) using the service key, so no database
driver is needed and the app stays standard-library-only. The service key bypasses row security, so
every query here filters by user_id itself; nothing in this file trusts a user_id it did not itself
authenticate (see auth.py, which is the only place a user_id enters the system).
"""
import datetime as dt
import json
import time
import urllib.error
import urllib.request

import memory  # validation, limits, wording and the pure drift/snapshot maths are shared, not duplicated
from auth import config
from markets import MARKETS

REQUIRED_TABLES = ("profile", "watchlist", "thesis")


def _iso_to_epoch(s):
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()) if s else int(time.time())


def _rest(method, path, body=None, prefer=None, timeout=10):
    c = config()
    headers = {"apikey": c["service_key"], "Authorization": f"Bearer {c['service_key']}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{c['url']}/rest/v1/{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else []
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise ConnectionError(f"Database returned HTTP {e.code}: {raw[:200]}")
    except (urllib.error.URLError, TimeoutError):
        raise ConnectionError("Could not reach the database")


def _thesis_out(row):
    """Same shape memory.py hands back, so the front end and drift() cannot tell the difference."""
    return {"id": row["id"], "symbol": row["symbol"], "name": row.get("name"), "note": row["note"],
            "invalidate_if": row.get("invalidate_if"), "review_below": row.get("review_below"), "review_above": row.get("review_above"),
            "created": _iso_to_epoch(row.get("created_at")), "updated": _iso_to_epoch(row.get("updated_at")),
            "snap": row.get("snap")}


def get_all(user_id):
    profs = _rest("GET", f"profile?user_id=eq.{user_id}&select=experience,markets")
    prof = profs[0] if profs else {}
    watch = _rest("GET", f"watchlist?user_id=eq.{user_id}&select=symbol&order=added_at.asc")
    theses = _rest("GET", f"thesis?user_id=eq.{user_id}&select=*&order=updated_at.desc")
    return {
        "cloud": True, "experience": prof.get("experience"), "markets": prof.get("markets") or [],
        "watchlist": [r["symbol"] for r in watch], "theses": [_thesis_out(r) for r in theses],
        "location": "your account (stored in the cloud, not on this device)",
        "limits": {"watch": memory.MAX_WATCH, "theses": memory.MAX_THESES, "note": memory.MAX_NOTE, "invalidate_if": memory.MAX_IF},
    }


def for_chat(user_id):
    a = get_all(user_id)
    return {"experience": a["experience"], "markets": a["markets"], "watchlist": a["watchlist"],
            "theses": {t["symbol"]: t for t in a["theses"]}}


def set_profile(user_id, experience, markets):
    exp = (experience or "").strip().lower() or None
    if exp not in (None, *memory.EXPERIENCE):
        raise ValueError("Pick beginner, some experience, or experienced.")
    mk = [m for m in dict.fromkeys(markets or []) if m in MARKETS]
    _rest("POST", "profile", {"user_id": user_id, "experience": exp, "markets": mk}, prefer="resolution=merge-duplicates")


def set_watch(user_id, symbols):
    clean = []
    for s in symbols or []:
        s = memory.clean_symbol(s)
        if s not in clean:
            clean.append(s)
    if len(clean) > memory.MAX_WATCH:
        raise ValueError(f"The watchlist holds up to {memory.MAX_WATCH} tickers.")
    old = {r["symbol"]: r["added_at"] for r in _rest("GET", f"watchlist?user_id=eq.{user_id}&select=symbol,added_at")}
    _rest("DELETE", f"watchlist?user_id=eq.{user_id}")
    if clean:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        _rest("POST", "watchlist", [{"user_id": user_id, "symbol": s, "added_at": old.get(s, now_iso)} for s in clean])


def save_thesis(user_id, body, snap=None, name=None):
    sym = memory.clean_symbol(body.get("symbol"))
    note = memory.clean_text(body.get("note"), memory.MAX_NOTE)
    if len(note) < 5:
        raise ValueError("Write a sentence or two: why do you own or watch this?")
    inv = memory.clean_text(body.get("invalidate_if"), memory.MAX_IF) or None
    below = memory.clean_price(body.get("review_below"), "The review-below price")
    above = memory.clean_price(body.get("review_above"), "The review-above price")
    if below and above and below >= above:
        raise ValueError("The review-below price must be lower than the review-above price.")
    tid = body.get("id")
    if tid:
        row = {"note": note, "invalidate_if": inv, "review_below": below, "review_above": above,
               "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        out = _rest("PATCH", f"thesis?id=eq.{int(tid)}&user_id=eq.{user_id}", row, prefer="return=representation")
        if not out:
            raise ValueError("That note no longer exists.")
        return int(tid)
    count = _rest("GET", f"thesis?user_id=eq.{user_id}&select=id")
    if len(count) >= memory.MAX_THESES:
        raise ValueError(f"You can keep up to {memory.MAX_THESES} notes. Delete one first.")
    row = {"user_id": user_id, "symbol": sym, "name": name, "note": note, "invalidate_if": inv,
           "review_below": below, "review_above": above, "snap": snap}
    out = _rest("POST", "thesis", row, prefer="return=representation")
    return out[0]["id"]


def delete_thesis(user_id, tid):
    _rest("DELETE", f"thesis?id=eq.{int(tid)}&user_id=eq.{user_id}")


def forget_all(user_id):
    counts = {t: len(_rest("GET", f"{t}?user_id=eq.{user_id}&select=user_id" if t != "thesis" else f"{t}?user_id=eq.{user_id}&select=id")) for t in REQUIRED_TABLES}
    for t in REQUIRED_TABLES:
        _rest("DELETE", f"{t}?user_id=eq.{user_id}")
    return counts


def _lookup(symbol):
    return memory._lookup(symbol)   # pure Yahoo lookup, no local state involved


def add_thesis(user_id, body):
    sym = memory.clean_symbol(body.get("symbol"))
    if body.get("id"):
        return save_thesis(user_id, body)
    qt, name, score = _lookup(sym)
    return save_thesis(user_id, body, snap=memory.snap_from_quote(qt, score), name=name)


def check(user_id, tid):
    import tick_chat
    rows = _rest("GET", f"thesis?id=eq.{int(tid)}&user_id=eq.{user_id}&select=*")
    if not rows:
        raise ValueError("That note no longer exists.")
    t = _thesis_out(rows[0])
    qt, name, score = _lookup(t["symbol"])
    news = tick_chat.about_entity(tick_chat.search_news(f'{name} {t["symbol"].split(".")[0]} stock', "us", limit=10),
                                  {"symbol": t["symbol"], "name": name}, limit=10)
    return {"id": t["id"], "symbol": t["symbol"], "checked": int(time.time()), **memory.drift(t, memory.snap_from_quote(qt, score), news)}


def export_all(user_id):
    return {"exported": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **get_all(user_id)}


def handle(user_id, body):
    """Same dispatch as memory.handle, one person's rows instead of the shared local file."""
    op = body.get("op")
    extra = {}
    if op == "profile":
        set_profile(user_id, body.get("experience"), body.get("markets"))
    elif op == "watch_set":
        set_watch(user_id, body.get("symbols"))
    elif op == "thesis_save":
        add_thesis(user_id, body)
    elif op == "thesis_delete":
        delete_thesis(user_id, body.get("id"))
    elif op == "check":
        extra["drift"] = check(user_id, body.get("id"))
    elif op == "forget":
        if body.get("confirm") != "forget":
            raise ValueError("Confirm to forget everything.")
        extra["deleted"] = forget_all(user_id)
    else:
        raise ValueError("Unknown request.")
    return {**get_all(user_id), **extra}
