"""Track record: after a story is flagged, did the stock beat the market? Measured locally, honestly.

Every Urgent or Watch story with a ticker and a clear direction is logged once (per ticker, direction
and day) with the stock and S&P 500 (SPY) price at that moment. After 1 and 5 trading days the excess
return versus SPY is filled in from daily closes. Results only mean something with a real sample, so
`report()` says "collecting" until there is one.
"""
import datetime as dt
import sqlite3
import threading
import time
from pathlib import Path

DB = Path(__file__).parent / "data" / "track.db"
MIN_SAMPLE = 20            # below this the UI must say "not enough data"
_cycle = threading.Lock()  # one observe/evaluate pass at a time

SCHEMA = """CREATE TABLE IF NOT EXISTS seen (
  id TEXT PRIMARY KEY, title TEXT, first_seen INTEGER, score INTEGER, level TEXT, dir TEXT,
  ticker TEXT, px0 REAL, spy0 REAL, r1 REAL, r5 REAL)"""


def connect(path=None):
    p = Path(path) if path else DB
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute(SCHEMA)
    return con


def _day(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()


def excess_returns(stock, spy, first_seen, px0, spy0):
    """stock/spy: [(epoch, close)] daily bars. Returns (r1, r5): excess return vs SPY after 1 and 5
    trading days counted from the first full session after the story was seen. None until that bar exists."""
    seen_day = _day(first_seen)
    spy_by_day = {_day(t): c for t, c in spy}
    after = [(t, c) for t, c in stock if _day(t) > seen_day]

    def at(n):
        if len(after) < n:
            return None
        t, c = after[n - 1]
        sc = spy_by_day.get(_day(t))
        if not (px0 and spy0 and sc):
            return None
        return (c / px0 - 1) - (sc / spy0 - 1)

    return at(1), at(5)


_last_eval = 0.0
EVAL_EVERY = 3600  # daily bars only change once a day; no need to ask Yahoo more than hourly


def observe(stories, now, price_fn, series_fn):
    """Log new flagged stories, then (at most hourly) fill in returns for older ones. Thread-safe."""
    global _last_eval
    if not _cycle.acquire(blocking=False):
        return
    try:
        con = connect()
        fresh = []
        for s in stories:
            if s["level"] not in ("urgent", "watch") or s["dir"] not in ("bull", "bear") or not s["tickers"]:
                continue
            key = f"{s['tickers'][0]}:{s['dir']}:{_day(s['ts'])}"
            if not con.execute("SELECT 1 FROM seen WHERE id=?", (key,)).fetchone():
                fresh.append((key, s))
        spy_now = price_fn("SPY") if fresh else None   # no lookups at all when nothing is new
        logged = 0
        for key, s in fresh:
            if logged >= 20 or not spy_now:
                break
            px = price_fn(s["tickers"][0])
            if not px:
                continue  # not a real, priced ticker (headline false positive)
            con.execute("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)",
                        (key, s["title"][:200], int(now), s["score"], s["level"], s["dir"], s["tickers"][0], px, spy_now))
            logged += 1
        con.commit()
        if now - _last_eval >= EVAL_EVERY:
            _last_eval = now
            _evaluate(con, now, series_fn)
        con.close()
    finally:
        _cycle.release()


def _evaluate(con, now, series_fn):
    rows = con.execute("SELECT id, ticker, first_seen, px0, spy0 FROM seen WHERE r5 IS NULL "
                       "AND first_seen < ? AND first_seen > ?", (now - 26 * 3600, now - 25 * 86400)).fetchall()
    cache = {}

    def series(sym):
        if sym not in cache:
            try:
                cache[sym] = series_fn(sym)
            except Exception:
                cache[sym] = []
        return cache[sym]

    for key, tk, first_seen, px0, spy0 in rows[:40]:
        r1, r5 = excess_returns(series(tk), series("SPY"), first_seen, px0, spy0)
        if r1 is not None:
            con.execute("UPDATE seen SET r1=?, r5=? WHERE id=?", (r1, r5, key))
    con.commit()


def summarize(rows):
    """rows: dicts with level, dir, r1, r5. Signed excess: positive means the call was right."""
    out = []
    for level in ("urgent", "watch"):
        for d in ("bull", "bear"):
            grp = [r for r in rows if r["level"] == level and r["dir"] == d]
            g = {"level": level, "dir": d, "n1": 0, "n5": 0, "hit1": None, "hit5": None, "avg1": None, "avg5": None}
            for horizon in ("1", "5"):
                vals = [(r["r" + horizon] if d == "bull" else -r["r" + horizon]) for r in grp if r["r" + horizon] is not None]
                g["n" + horizon] = len(vals)
                if vals:
                    g["hit" + horizon] = sum(v > 0 for v in vals) / len(vals)
                    g["avg" + horizon] = sum(vals) / len(vals)
            if grp:
                out.append(g)
    return out


def report(now=None):
    now = now or time.time()
    try:
        con = connect()
        rows = [dict(zip(("level", "dir", "r1", "r5", "first_seen"), r)) for r in
                con.execute("SELECT level, dir, r1, r5, first_seen FROM seen")]
        con.close()
    except sqlite3.Error:
        rows = []
    n5 = sum(r["r5"] is not None for r in rows)
    return {
        "logged": len(rows), "measured_5d": n5, "enough": n5 >= MIN_SAMPLE, "min_sample": MIN_SAMPLE,
        "days_running": round((now - min(r["first_seen"] for r in rows)) / 86400, 1) if rows else 0,
        "groups": summarize(rows),
    }
