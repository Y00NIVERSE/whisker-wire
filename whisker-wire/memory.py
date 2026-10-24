"""Tick remembers: a small, visible, local memory. No AI, no cloud, no account.

It stores only what you type: how experienced you are, which markets you follow, a watchlist, and thesis notes
(why you own or watch something, and what would change your mind). It never stores holdings amounts or account
details, and it is never sent to a search engine or an AI service. Tick reads it to tailor answers and to run the
"thesis drift" check: has the reason you wrote down weakened since you wrote it?

The database lives in your per-user app-data folder, not in the project folder: the project often sits in a synced
folder (OneDrive, Dropbox), and this file should stay on this computer.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from markets import MARKETS

MAX_WATCH = 50
MAX_THESES = 30
MAX_NOTE = 600
MAX_IF = 200
EXPERIENCE = ("beginner", "some", "experienced")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.^=&-]{0,11}$")
DB = None   # tests point this at a temporary file


def data_dir():
    env = os.environ.get("WHISKER_WIRE_DATA")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "WhiskerWire"


def db_path():
    return Path(DB) if DB else data_dir() / "tick_memory.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watch (symbol TEXT PRIMARY KEY, added INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS thesis (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, name TEXT, note TEXT NOT NULL,
  invalidate_if TEXT, review_below REAL, review_above REAL, created INTEGER NOT NULL, updated INTEGER NOT NULL, snap TEXT);
"""


def connect():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=5)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# ---------------------------------------------------------------- validation
def clean_text(s, limit):
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", " ", str(s or ""))
    return re.sub(r"[ \t]+", " ", s).strip()[:limit]


def clean_symbol(s):
    s = str(s or "").strip().upper()
    if not SYMBOL_RE.match(s):
        raise ValueError("That does not look like a ticker. Use the full symbol, for example TSLA or 0700.HK.")
    return s


def clean_price(v, label):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.")
    if not 0 < f < 1e9:
        raise ValueError(f"{label} must be a positive number.")
    return f


# ---------------------------------------------------------------- reading
def _thesis(row):
    d = dict(row)
    d["snap"] = json.loads(d["snap"]) if d.get("snap") else None
    return d


def get_all():
    con = connect()
    try:
        prof = {r["k"]: r["v"] for r in con.execute("SELECT k, v FROM profile")}
        return {
            "experience": prof.get("experience") or None,
            "markets": json.loads(prof.get("markets") or "[]"),
            "watchlist": [r["symbol"] for r in con.execute("SELECT symbol FROM watch ORDER BY rowid")],   # the order you gave
            "theses": [_thesis(r) for r in con.execute("SELECT * FROM thesis ORDER BY updated DESC")],
            "location": str(db_path()),
            "limits": {"watch": MAX_WATCH, "theses": MAX_THESES, "note": MAX_NOTE, "invalidate_if": MAX_IF},
        }
    finally:
        con.close()


def for_chat():
    """What Tick may use while answering: read-only, and never sent anywhere outside this computer."""
    a = get_all()
    return {"experience": a["experience"], "markets": a["markets"], "watchlist": a["watchlist"],
            "theses": {t["symbol"]: t for t in a["theses"]}}


# ---------------------------------------------------------------- writing
def set_profile(experience, markets):
    exp = (experience or "").strip().lower() or None
    if exp not in (None, *EXPERIENCE):
        raise ValueError("Pick beginner, some experience, or experienced.")
    mk = [m for m in dict.fromkeys(markets or []) if m in MARKETS]
    con = connect()
    try:
        with con:
            if exp:
                con.execute("INSERT INTO profile VALUES ('experience', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (exp,))
            else:
                con.execute("DELETE FROM profile WHERE k='experience'")
            con.execute("INSERT INTO profile VALUES ('markets', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (json.dumps(mk),))
    finally:
        con.close()


def set_watch(symbols):
    """Replace the watchlist, keeping exactly the order given. Symbols already there keep their original added date."""
    clean = []
    for s in symbols or []:
        s = clean_symbol(s)
        if s not in clean:
            clean.append(s)
    if len(clean) > MAX_WATCH:
        raise ValueError(f"The watchlist holds up to {MAX_WATCH} tickers.")
    con = connect()
    try:
        with con:
            old = {r["symbol"]: r["added"] for r in con.execute("SELECT symbol, added FROM watch")}
            con.execute("DELETE FROM watch")
            now = int(time.time())
            for s in clean:
                con.execute("INSERT INTO watch VALUES (?, ?)", (s, old.get(s, now)))
    finally:
        con.close()


def save_thesis(body, snap=None, name=None):
    """Create a note, or update one when body has an id. Only the text you typed and your own price lines are kept."""
    sym = clean_symbol(body.get("symbol"))
    note = clean_text(body.get("note"), MAX_NOTE)
    if len(note) < 5:
        raise ValueError("Write a sentence or two: why do you own or watch this?")
    inv = clean_text(body.get("invalidate_if"), MAX_IF) or None
    below, above = clean_price(body.get("review_below"), "The review-below price"), clean_price(body.get("review_above"), "The review-above price")
    if below and above and below >= above:
        raise ValueError("The review-below price must be lower than the review-above price.")
    now = int(time.time())
    con = connect()
    try:
        with con:
            tid = body.get("id")
            if tid:
                row = con.execute("SELECT * FROM thesis WHERE id=?", (int(tid),)).fetchone()
                if not row:
                    raise ValueError("That note no longer exists.")
                con.execute("UPDATE thesis SET note=?, invalidate_if=?, review_below=?, review_above=?, updated=? WHERE id=?",
                            (note, inv, below, above, now, int(tid)))
                return int(tid)
            if con.execute("SELECT COUNT(*) FROM thesis").fetchone()[0] >= MAX_THESES:
                raise ValueError(f"You can keep up to {MAX_THESES} notes. Delete one first.")
            cur = con.execute("INSERT INTO thesis (symbol, name, note, invalidate_if, review_below, review_above, created, updated, snap) VALUES (?,?,?,?,?,?,?,?,?)",
                              (sym, name, note, inv, below, above, now, now, json.dumps(snap) if snap else None))
            return cur.lastrowid
    finally:
        con.close()


def delete_thesis(tid):
    con = connect()
    try:
        with con:
            con.execute("DELETE FROM thesis WHERE id=?", (int(tid),))
    finally:
        con.close()


def forget_all():
    con = connect()
    try:
        n = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("profile", "watch", "thesis")}
        with con:
            for t in n:
                con.execute(f"DELETE FROM {t}")
        con.execute("VACUUM")   # actually shrink the file, so deleted text is not left lying around
        return n
    finally:
        con.close()


# ---------------------------------------------------------------- thesis drift
def rating_number(text):
    m = re.match(r"\s*([\d.]+)", text or "")
    return float(m.group(1)) if m else None


def snap_from_quote(q, value_score=None):
    """The numbers worth remembering about a stock on the day you wrote your note."""
    return {"price": q.get("regularMarketPrice"), "currency": q.get("currency") or "USD", "fpe": q.get("forwardPE"),
            "pb": q.get("priceToBook"), "rating": q.get("averageAnalystRating"), "rating_num": rating_number(q.get("averageAnalystRating")),
            "score": value_score, "hi": q.get("fiftyTwoWeekHigh"), "lo": q.get("fiftyTwoWeekLow"), "ts": int(time.time())}


def _px(n, cur):
    import tick_chat
    return tick_chat.px(n, cur or "USD")


def drift(t, now_snap, news=(), now=None):
    """Has the reason in this note weakened? A transparent points system: every point has a stated cause.
    Pure function: pass the note, today's numbers and any headlines published since the note."""
    now = now or time.time()
    then = t.get("snap") or {}
    cur = now_snap.get("currency") or then.get("currency") or "USD"
    price, was = now_snap.get("price"), then.get("price")
    pts, facts, breakdown = 0, [], []

    def add(n, label):
        nonlocal pts
        pts += n
        breakdown.append({"label": label, "pts": n})

    if price is None:
        return {"status": "unknown", "label": "Could not check", "points": 0, "breakdown": [], "facts": ["Yahoo did not return a price just now. Try again in a moment."], "news": [], "age_days": int((now - t["created"]) / 86400)}
    if was:
        ch = (price / was - 1) * 100
        facts.append(f"Price {_px(price, cur)} now, {_px(was, cur)} when you wrote this ({ch:+.1f}%).")
        if ch <= -15:
            add(2, f"Price is down {abs(ch):.0f}% since your note")
        elif ch <= -8:
            add(1, f"Price is down {abs(ch):.0f}% since your note")
        elif ch >= 25:
            facts.append(f"It is up {ch:.0f}%: check whether your reason still holds at this price.")
    else:
        facts.append(f"Price now {_px(price, cur)} (no price was saved with this note).")
    if t.get("review_below") and price <= t["review_below"]:
        add(3, f"Price fell to your review line of {_px(t['review_below'], cur)}")
    if t.get("review_above") and price >= t["review_above"]:
        add(1, f"Price reached your review line of {_px(t['review_above'], cur)}: still a good reason to hold?")
    a, b = then.get("fpe"), now_snap.get("fpe")
    if a and b and a > 0 and b > 0:
        facts.append(f"Forward P/E {b:.1f} now, {a:.1f} then.")
        if b >= a * 1.3:
            add(1, f"Forward P/E rose {(b / a - 1) * 100:.0f}%: it is getting pricier")
    ra, rb = then.get("rating_num"), now_snap.get("rating_num")
    if ra and rb:
        if rb >= ra + 0.5:
            add(1, f"Analyst view weakened ({then.get('rating', '?').split(' - ')[-1]} to {now_snap.get('rating', '?').split(' - ')[-1]})")
        elif rb <= ra - 0.5:
            facts.append("Analysts have become more positive since your note.")
    sa, sb = then.get("score"), now_snap.get("score")
    if sa is not None and sb is not None:
        facts.append(f"Whisker Wire value read {sb} now, {sa} then.")
        if sb <= sa - 15:
            add(1, f"Value read fell {sa - sb} points")
    since = [n for n in news if n.get("dir") in ("bear", "flag") and (not n.get("ts") or n["ts"] >= t["created"])]
    if len(since) >= 2:
        add(2, f"{len(since)} negative headlines since your note")
    elif len(since) == 1:
        add(1, "1 negative headline since your note")
    age = int((now - t["created"]) / 86400)
    if age > 90:
        add(1, f"The note is {age} days old: re-read your reasons")
    label, status = ("Thesis under pressure", "pressure") if pts >= 4 else ("Worth a look", "look") if pts >= 2 else ("Holding up", "holding")
    return {"status": status, "label": label, "points": pts, "breakdown": breakdown, "facts": facts, "news": since[:3], "age_days": age}


# ---------------------------------------------------------------- operations that need the network
def _lookup(symbol):
    """Live quote and a name for a symbol, or a clear error if Yahoo does not know it."""
    import engine
    import tick_chat
    qt = tick_chat.quote_snapshots([symbol]).get(symbol)
    if not qt or qt.get("regularMarketPrice") is None:
        raise ValueError(f"Yahoo does not know '{symbol}'. Use the full ticker, for example TSLA or 0700.HK.")
    typ = qt.get("quoteType")
    a = engine.analyze_quote(qt, "memory") if typ in ("EQUITY", "ETF", None) else None
    return qt, qt.get("shortName") or qt.get("longName") or symbol, (a["score"] if a else None)


def add_thesis(body):
    sym = clean_symbol(body.get("symbol"))
    if body.get("id"):
        return save_thesis(body)
    qt, name, score = _lookup(sym)
    return save_thesis(body, snap=snap_from_quote(qt, score), name=name)


def check(tid):
    """Compare a note with today: live numbers plus headlines published since it was written."""
    import tick_chat
    con = connect()
    try:
        row = con.execute("SELECT * FROM thesis WHERE id=?", (int(tid),)).fetchone()
    finally:
        con.close()
    if not row:
        raise ValueError("That note no longer exists.")
    t = _thesis(row)
    qt, name, score = _lookup(t["symbol"])
    news = tick_chat.about_entity(tick_chat.search_news(f'{name} {t["symbol"].split(".")[0]} stock', "us", limit=10),
                                  {"symbol": t["symbol"], "name": name}, limit=10)
    return {"id": t["id"], "symbol": t["symbol"], "checked": int(time.time()), **drift(t, snap_from_quote(qt, score), news)}


def export_all():
    return {"exported": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **get_all()}


def handle(body):
    """The single write endpoint: returns the whole memory afterwards (plus a drift report for a check)."""
    op = body.get("op")
    extra = {}
    if op == "profile":
        set_profile(body.get("experience"), body.get("markets"))
    elif op == "watch_set":
        set_watch(body.get("symbols"))
    elif op == "thesis_save":
        add_thesis(body)
    elif op == "thesis_delete":
        delete_thesis(body.get("id"))
    elif op == "check":
        extra["drift"] = check(body.get("id"))
    elif op == "forget":
        if body.get("confirm") != "forget":
            raise ValueError("Confirm to forget everything.")
        extra["deleted"] = forget_all()
    else:
        raise ValueError("Unknown request.")
    return {**get_all(), **extra}
