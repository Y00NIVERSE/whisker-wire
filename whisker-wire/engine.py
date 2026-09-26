"""Whisker Wire engine: fetch, cluster, score. Standard library only."""
import concurrent.futures as cf
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from signals import SIGNALS, MAINSTREAM, TICKER_STOP

ROOT = Path(__file__).parent
UA_BROWSER = "Mozilla/5.0 (compatible; WhiskerWire/0.1; personal research tool)"
MAX_AGE_H = 36

GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="

# tier "main" = the feeds that make up top headlines; "niche" = everything else.
SOURCES = [
    {"id": "cnbc", "name": "CNBC", "kind": "Mainstream", "tier": "main",
     "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"},
    {"id": "cnbc-inv", "name": "CNBC Investing", "kind": "Mainstream", "tier": "main",
     "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"},
    {"id": "mw", "name": "MarketWatch", "kind": "Mainstream", "tier": "main",
     "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"id": "mw-live", "name": "MarketWatch", "kind": "Mainstream", "tier": "main",
     "url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"},
    {"id": "yf", "name": "Yahoo Finance", "kind": "Mainstream", "tier": "main",
     "url": "https://finance.yahoo.com/news/rssindex"},
    {"id": "nasdaq", "name": "Nasdaq", "kind": "Mainstream", "tier": "main",
     "url": "https://www.nasdaq.com/feed/rssoutbound?category=Stocks"},
    {"id": "sa", "name": "Seeking Alpha", "kind": "Analyst", "tier": "niche",
     "url": "https://seekingalpha.com/market_currents.xml"},
    {"id": "bz", "name": "Benzinga", "kind": "Wire", "tier": "niche", "url": "https://www.benzinga.com/feed"},
    {"id": "inv", "name": "Investing.com", "kind": "Wire", "tier": "niche",
     "url": "https://www.investing.com/rss/news_25.rss"},
    {"id": "fool", "name": "Motley Fool", "kind": "Analyst", "tier": "niche",
     "url": "https://www.fool.com/feeds/index.aspx"},
    {"id": "zh", "name": "ZeroHedge", "kind": "Independent", "tier": "niche",
     "url": "https://feeds.feedburner.com/zerohedge/feed"},
    {"id": "oil", "name": "OilPrice", "kind": "Independent", "tier": "niche", "url": "https://oilprice.com/rss/main"},
    {"id": "fed", "name": "Federal Reserve", "kind": "Government", "tier": "niche",
     "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"id": "fred", "name": "St. Louis Fed", "kind": "Government", "tier": "niche",
     "url": "https://news.research.stlouisfed.org/feed/"},
    {"id": "rsa", "name": "r/SecurityAnalysis", "kind": "Community", "tier": "niche",
     "url": "https://www.reddit.com/r/SecurityAnalysis/top/.rss?t=day"},
    {"id": "tv", "name": "TradingView", "kind": "Community", "tier": "niche", "url": "https://www.tradingview.com/feed/"},
    # Search-driven feeds: these surface stories the top-headline feeds skip.
    {"id": "gn-insider", "name": "Search: insider buys", "kind": "Search", "tier": "niche", "gn": True,
     "url": GN + urllib.parse.quote('("insider buying" OR "insider purchase" OR "bought shares") stock when:2d')},
    {"id": "gn-short", "name": "Search: short reports", "kind": "Search", "tier": "niche", "gn": True,
     "url": GN + urllib.parse.quote('("short seller" OR "short report" OR "SEC investigation") stock when:2d')},
    {"id": "gn-activist", "name": "Search: activists and deals", "kind": "Search", "tier": "niche", "gn": True,
     "url": GN + urllib.parse.quote('("activist investor" OR "13D" OR "takeover bid" OR "tender offer") when:2d')},
    {"id": "gn-guide", "name": "Search: guidance moves", "kind": "Search", "tier": "niche", "gn": True,
     "url": GN + urllib.parse.quote('("raises guidance" OR "cuts guidance" OR "withdraws guidance" OR "profit warning") when:2d')},
    {"id": "gn-under", "name": "Search: undervalued calls", "kind": "Search", "tier": "niche", "gn": True,
     "url": GN + urllib.parse.quote('(undervalued OR "trading below book" OR "deep value") stocks when:3d')},
    {"id": "gn-fda", "name": "Search: FDA and catalysts", "kind": "Search", "tier": "niche", "gn": True,
     "url": GN + urllib.parse.quote('("FDA approval" OR "phase 3" OR "breakthrough designation") stock when:2d')},
]


# ---------------------------------------------------------------- safe fetching
def assert_public(url):
    """Refuse anything that is not plain http(s) to a public address (SSRF guard)."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("only http(s) URLs are allowed")
    if u.port not in (None, 80, 443):
        raise ValueError("non-standard ports are blocked")
    if _PUBLIC_HOSTS.get(u.hostname, 0) > time.time():
        return  # resolved to public addresses recently; DNS lookups are slow on Windows under load
    for info in socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("private or local addresses are blocked")
    _PUBLIC_HOSTS[u.hostname] = time.time() + 300


_PUBLIC_HOSTS = {}


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_Redirect)


def http_get(url, headers=None, timeout=8, max_bytes=3_000_000):
    assert_public(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA_BROWSER, "Accept": "*/*", **(headers or {})})
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read(max_bytes), r.headers.get_content_charset() or "utf-8"


_cache, _locks, _glock = {}, {}, threading.Lock()


def cached(key, ttl, fn):
    """TTL cache, stale-while-revalidate: an expired value is returned instantly while one
    background thread refreshes it, so the page never waits on slow upstream feeds after first load."""
    with _glock:
        lock = _locks.setdefault(key, threading.Lock())
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]

    def refresh():
        with lock:
            h = _cache.get(key)
            if h and time.time() - h[0] < ttl:
                return h[1]
            val = fn()
            _cache[key] = (time.time(), val)
            return val

    if hit:
        if not lock.locked():
            def bg():
                try:
                    refresh()
                except Exception:
                    pass  # keep serving the stale value
            threading.Thread(target=bg, daemon=True).start()
        return hit[1]
    return refresh()


# ---------------------------------------------------------------- feed parsing
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(s, limit=None):
    s = TAG_RE.sub(" ", html.unescape(html.unescape(s or "")))
    s = WS_RE.sub(" ", s).strip()
    return s[:limit] if limit else s


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return None


def safe_fromstring(data):
    """Parse untrusted XML. Entity declarations are the root of XXE and billion-laughs
    attacks and no legitimate finance feed needs them, so refuse the document outright."""
    if re.search(rb"<!ENTITY", data, re.I):
        raise ValueError("XML entity declarations are not allowed")
    return ET.fromstring(data)


def parse_feed(data):
    root = safe_fromstring(data)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        d = {"title": "", "link": "", "summary": "", "ts": None, "source": ""}
        for c in el:
            t = _local(c.tag)
            if t == "title":
                d["title"] = clean_text(c.text)
            elif t == "link":
                href = c.attrib.get("href") or (c.text or "").strip()
                if href and (not d["link"] or c.attrib.get("rel") in (None, "alternate")):
                    d["link"] = href
            elif t in ("description", "summary"):
                d["summary"] = clean_text(c.text, 500)
            elif t in ("encoded", "content") and not d["summary"]:
                d["summary"] = clean_text(c.text, 500)
            elif t in ("pubDate", "published", "updated", "date"):
                d["ts"] = d["ts"] or parse_date(c.text)
            elif t == "source":
                d["source"] = clean_text(c.text)
        if d["title"] and d["link"].startswith(("http://", "https://")):
            out.append(d)
    return out


def norm_pub(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def fetch_source(src):
    t0 = time.time()
    try:
        data, _ = http_get(src["url"])
        items = parse_feed(data)[:60]
        for it in items:
            if src.get("gn"):
                # Google News titles end with " - Publisher"; the description just repeats the title.
                pub = it["source"]
                if pub and it["title"].endswith(" - " + pub):
                    it["title"] = it["title"][: -len(pub) - 3]
                it["summary"] = ""
                it["publisher"] = pub or "Unknown"
            else:
                it["publisher"] = src["name"]
            it["src_id"], it["kind"] = src["id"], src["kind"]
            it["ts"] = it["ts"] or time.time()
        return src, items, {"id": src["id"], "name": src["name"], "kind": src["kind"], "ok": True,
                            "count": len(items), "ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # one dead source must never take the wire down
        return src, [], {"id": src["id"], "name": src["name"], "kind": src["kind"], "ok": False,
                         "count": 0, "ms": int((time.time() - t0) * 1000), "error": type(e).__name__}


# ---------------------------------------------------------------- tickers and signals
_T1 = re.compile(r"\((?:(?:NASDAQ|NYSE|NYSE American|NYSEARCA|AMEX|OTC|OTCQB|TSX|LSE)\s*:\s*)?([A-Z]{2,5}(?:\.[A-Z])?)\)")
_T2 = re.compile(r"\b(?:NASDAQ|NYSE|AMEX|NYSEARCA|NYSEAMERICAN)\s*:\s*([A-Z]{1,5})\b")
_T3 = re.compile(r"(?<![A-Za-z0-9])\$([A-Z]{1,5})\b")
_SIG = [(s, re.compile(s["pattern"], re.I)) for s in SIGNALS]


def find_tickers(text):
    seen = []
    for rx in (_T2, _T3, _T1):
        for m in rx.finditer(text):
            t = m.group(1)
            if t not in TICKER_STOP and t not in seen:
                seen.append(t)
    return seen[:4]


def find_signals(text):
    return [s for s, rx in _SIG if rx.search(text)]


_STOP = set("the a an of to in on for and at as by with from is are was be its it after over new says say amid vs stock "
            "stocks shares share this that will has have how why what more than into out up down could may".split())


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9$%]+", title.lower()) if w not in _STOP and len(w) > 2}


def cluster(items):
    """Group near-duplicate headlines so one story counts once but keeps every publisher."""
    groups = []
    for it in sorted(items, key=lambda x: x["ts"]):
        it["_tok"] = tokens(it["title"])
        it["_tk"] = find_tickers(it["title"])
        placed = False
        for g in groups:
            j = len(it["_tok"] & g["tok"]) / max(1, len(it["_tok"] | g["tok"]))
            same_t = bool(it["_tk"]) and it["_tk"][0] in g["tickers"]
            if j >= 0.5 or (same_t and j >= 0.3):
                g["items"].append(it)
                g["tok"] |= it["_tok"]
                placed = True
                break
        if not placed:
            groups.append({"items": [it], "tok": set(it["_tok"]), "tickers": list(it["_tk"])})
    return groups


def build_story(g, now):
    items = g["items"]
    lead = max(items, key=lambda i: (len(i["summary"]), -i["ts"]))
    pubs = {}
    for i in items:
        pubs.setdefault(norm_pub(i["publisher"]), i["publisher"])
    n_main = sum(1 for k in pubs if k in MAINSTREAM)
    text = " ".join(i["title"] + " " + i["summary"] for i in items)
    sigs = find_signals(lead["title"] + " " + lead["summary"]) or find_signals(text)
    tickers = g["tickers"] or find_tickers(text)
    first_ts = min(i["ts"] for i in items)
    age_h = max(0.0, (now - first_ts) / 3600)

    top = sorted(sigs, key=lambda s: -s["weight"])[:3]
    sig_score = sum(s["weight"] for s in top)
    recency = 3 if age_h < 1 else 2 if age_h < 3 else 1 if age_h < 8 else 0
    corro = min(len(pubs) - 1, 3)
    score = sig_score + recency + corro + (1 if tickers else 0)
    if not sigs:
        score = min(score, 3)
    elif lead["title"].rstrip().endswith("?"):
        score -= 2  # question headlines ("Undervalued?") are usually engagement bait, not news

    dirs = {s["dir"] for s in top}
    direction = ("mixed" if {"bull", "bear"} <= dirs else "bull" if "bull" in dirs
                 else "bear" if "bear" in dirs else "flag" if dirs else "none")
    overlooked = bool(sigs) and max((s["weight"] for s in sigs), default=0) >= 3 and n_main == 0 and age_h < 24
    return {
        "id": hashlib.sha1(lead["link"].encode()).hexdigest()[:10],
        "title": lead["title"], "link": lead["link"], "summary": lead["summary"],
        "ts": int(first_ts), "tickers": tickers,
        "signals": [{"id": s["id"], "label": s["label"], "dir": s["dir"]} for s in top],
        "why": top[0]["note"] if top else "",
        "dir": direction, "score": score,
        "level": "urgent" if score >= 8 else "watch" if score >= 5 else "normal",
        "publishers": sorted(pubs.values()), "n_pub": len(pubs), "n_main": n_main,
        "kinds": sorted({i["kind"] for i in items}),
        "corroborated": len(pubs) >= 2, "overlooked": overlooked,
        "links": [{"publisher": i["publisher"], "url": i["link"], "title": i["title"]} for i in items[:6]],
    }


def run_parallel(fn, items, deadline=10, workers=32):
    """Run fn over items concurrently; anything not finished by the deadline comes back as None.
    Socket timeouts are per-read, so without this one slow-dripping host could stall everything."""
    ex = cf.ThreadPoolExecutor(max_workers=min(workers, max(1, len(items))))
    futs = [ex.submit(fn, i) for i in items]
    cf.wait(futs, timeout=deadline)
    out = [f.result() if f.done() and not f.exception() else None for f in futs]
    ex.shutdown(wait=False, cancel_futures=True)
    return out


def get_feed():
    def run():
        now = time.time()
        raw, health = [], []
        for src, res in zip(SOURCES, run_parallel(fetch_source, SOURCES)):
            if res is None:
                health.append({"id": src["id"], "name": src["name"], "kind": src["kind"], "ok": False,
                               "count": 0, "ms": 10000, "error": "Timeout"})
                continue
            _src, items, h = res
            raw += [i for i in items if now - i["ts"] < MAX_AGE_H * 3600 and i["ts"] < now + 600]
            health.append(h)
        stories = [build_story(g, now) for g in cluster(raw)]
        stories.sort(key=lambda s: (-s["score"], -s["ts"]))
        return {"generated": int(now), "stories": stories[:160], "health": health, "raw_items": len(raw)}
    return cached("feed", 90, run)


# ---------------------------------------------------------------- markets
YF = "https://query1.finance.yahoo.com"
STRIP = [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("DIA", "Dow"), ("IWM", "Small caps"), ("^VIX", "VIX fear"),
         ("^TNX", "10Y yield"), ("GC=F", "Gold"), ("CL=F", "Oil"), ("BTC-USD", "Bitcoin")]
SYM_RE = re.compile(r"^[A-Za-z0-9.^=\-]{1,12}$")


def _chart(sym, rng, interval="1d"):
    data, _ = http_get(f"{YF}/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={interval}", timeout=10)
    return json.loads(data)["chart"]["result"][0]


def _quote_row(pair):
    sym, label = pair
    try:
        m = _chart(sym, "5d")["meta"]
        price, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
        chg = (price / prev - 1) * 100 if price and prev else m.get("regularMarketChangePercent")
        return {"symbol": sym, "label": label, "price": price, "chg": chg}
    except Exception:
        return {"symbol": sym, "label": label, "price": None, "chg": None}


def get_quotes():
    def run():
        rows = run_parallel(_quote_row, STRIP, deadline=12, workers=9)
        return {"quotes": [r or {"symbol": s, "label": l, "price": None, "chg": None}
                           for r, (s, l) in zip(rows, STRIP)], "generated": int(time.time())}
    return cached("quotes", 45, run)


def get_spark(sym):
    if not SYM_RE.match(sym):
        raise ValueError("bad symbol")

    def run():
        r = _chart(sym.upper(), "6mo")
        closes = [c for c in r["indicators"]["quote"][0].get("close", []) if c is not None]
        return {"symbol": sym.upper(), "closes": [round(c, 2) for c in closes]}
    return cached("spark:" + sym.upper(), 600, run)


def get_ticker(sym):
    if not SYM_RE.match(sym):
        raise ValueError("bad symbol")

    def run():
        q = urllib.parse.quote(f'"{sym.upper()}" stock when:7d')
        try:
            data, _ = http_get(GN + q)
            news = [{"title": re.sub(r" - [^-]+$", "", i["title"]), "url": i["link"], "publisher": i["source"],
                     "ts": int(i["ts"] or 0)} for i in parse_feed(data)[:8]]
        except Exception:
            news = []
        return {"symbol": sym.upper(), "spark": get_spark(sym)["closes"], "news": news}
    return cached("ticker:" + sym.upper(), 300, run)


# ---------------------------------------------------------------- value radar
SCREENERS = [("undervalued_large_caps", "Undervalued large caps"),
             ("undervalued_growth_stocks", "Undervalued growth"),
             ("most_shorted_stocks", "Crowded shorts")]


def _f(q, k):
    v = q.get(k)
    return v if isinstance(v, (int, float)) else None


def analyze_quote(q, list_id):
    price, hi, lo = _f(q, "regularMarketPrice"), _f(q, "fiftyTwoWeekHigh"), _f(q, "fiftyTwoWeekLow")
    if not price or not hi or not lo or hi <= lo:
        return None
    prev = _f(q, "regularMarketPreviousClose")
    pe, fpe, pb = _f(q, "trailingPE"), _f(q, "forwardPE"), _f(q, "priceToBook")
    mcap, vol, avgvol = _f(q, "marketCap"), _f(q, "regularMarketVolume"), _f(q, "averageDailyVolume3Month")
    dma200 = _f(q, "twoHundredDayAverage")
    off_high = (price / hi - 1) * 100
    above_low = (price / lo - 1) * 100
    vs200 = (price / dma200 - 1) * 100 if dma200 else None
    vol_ratio = vol / avgvol if vol and avgvol else None
    rating = q.get("averageAnalystRating") or ""
    rnum = None
    m = re.match(r"([\d.]+)", rating)
    if m:
        rnum = float(m.group(1))

    score, good, warn = 0, [], []
    if off_high <= -10:
        score += min(25, abs(off_high) * 0.8)
        good.append(f"Trades {abs(off_high):.0f}% below its 52-week high, so the market has already punished it.")
    if fpe and fpe > 0:
        if fpe < 12:
            score += 20
            good.append(f"Forward P/E of {fpe:.1f} means you pay about ${fpe:.0f} for each $1 of next year's expected profit. That is low.")
        elif fpe < 18:
            score += 10
            good.append(f"Forward P/E of {fpe:.1f} is reasonable next to the long-run market average near 16 to 20.")
        if pe and pe > 0 and fpe < pe * 0.85:
            score += 12
            good.append("Analysts expect profit to grow (forward P/E is below trailing P/E).")
    if pb and 0 < pb < 1.5:
        score += 12
        good.append(f"Price is {pb:.1f}x book value, close to what the company owns on paper.")
    elif pb and pb < 3:
        score += 5
    if rnum and rnum <= 2.2:
        score += 12
        good.append(f"Analyst consensus is {rating}. (1 = strong buy, 5 = sell.)")
    if vol_ratio and vol_ratio >= 1.5:
        score += 8
        good.append(f"Volume is {vol_ratio:.1f}x its 3-month average: someone is paying attention.")

    if pe is None and (fpe is None or fpe <= 0):
        warn.append("No profits to measure. Cheap-looking ratios do not apply, it may be cheap for a reason.")
        score -= 10
    if pb is not None and pb < 0:
        warn.append("Negative book value: the company owes more than it owns on paper. Common after big buybacks, but it means the P/B ratio tells you nothing here.")
    if vs200 is not None and vs200 < -15:
        warn.append(f"Sits {abs(vs200):.0f}% under its 200-day average. Downtrends can keep going: cheap can get cheaper.")
        score -= 6
    if above_low < 12:
        warn.append("Within 12% of its 52-week low. Wait for the price to stop falling before calling it a bottom.")
    if mcap and mcap < 300_000_000:
        warn.append("Micro-cap: thin trading, wide spreads, easy to get stuck in.")
        score -= 6
    if list_id == "most_shorted_stocks":
        warn.append("Heavily shorted. Squeezes are rare and violent in both directions; treat as speculation.")
        score = min(score, 45)
    if not warn:
        warn.append("Check why it is cheap: read the latest earnings news before believing the ratio.")

    return {
        "symbol": q.get("symbol"), "name": q.get("longName") or q.get("shortName") or q.get("symbol"),
        "list": list_id, "price": price, "chg": (price / prev - 1) * 100 if prev else None,
        "pe": pe, "fpe": fpe, "pb": pb, "mcap": mcap, "hi": hi, "lo": lo,
        "off_high": off_high, "vs200": vs200, "vol_ratio": vol_ratio, "rating": rating,
        "score": int(max(0, min(100, round(score)))), "good": good[:4], "warn": warn[:3],
    }


def _screener(sid):
    data, _ = http_get(f"{YF}/v1/finance/screener/predefined/saved?formatted=false&scrIds={sid}&count=50", timeout=15)
    return json.loads(data)["finance"]["result"][0].get("quotes", [])


def get_undervalued():
    def run():
        out, seen = [], set()
        for sid, label in SCREENERS:
            try:
                rows = [analyze_quote(q, sid) for q in _screener(sid)]
            except Exception:
                continue
            rows = sorted((r for r in rows if r), key=lambda r: -r["score"])[:16]
            for r in rows:
                if r["symbol"] not in seen:
                    seen.add(r["symbol"])
                    r["list_label"] = label
                    out.append(r)
        out.sort(key=lambda r: -r["score"])
        return {"generated": int(time.time()), "picks": out}
    return cached("under", 300, run)


# ---------------------------------------------------------------- SEC EDGAR (needs your contact)
def sec_agent():
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    f = ROOT / "sec_contact.txt"
    if not ua and f.exists():
        ua = f.read_text(encoding="utf-8").strip()
    return ua if ua and "@" in ua else ""


def _sec_get(url):
    time.sleep(0.12)  # stay well under SEC's 10 requests/second limit
    data, _ = http_get(url, headers={"User-Agent": sec_agent()}, timeout=15)
    return data


def parse_form4(xml_bytes):
    """Return open-market purchases (code P) and sales (code S) from a Form 4 XML document."""
    r = safe_fromstring(xml_bytes)
    g = lambda el, path: (el.findtext(path) or "").strip() if el is not None else ""
    issuer = r.find("issuer")
    owner = r.find("reportingOwner")
    title = g(owner, "reportingOwnerRelationship/officerTitle")
    if not title and g(owner, "reportingOwnerRelationship/isDirector") in ("1", "true"):
        title = "Director"
    if not title and g(owner, "reportingOwnerRelationship/isTenPercentOwner") in ("1", "true"):
        title = "10% owner"
    buys = sells = 0.0
    for t in r.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = g(t, "transactionCoding/transactionCode")
        try:
            shares = float(g(t, "transactionAmounts/transactionShares/value") or 0)
            price = float(g(t, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        if code == "P":
            buys += shares * price
        elif code == "S":
            sells += shares * price
    return {"symbol": g(issuer, "issuerTradingSymbol"), "company": g(issuer, "issuerName"),
            "insider": g(owner, "reportingOwnerId/rptOwnerName"), "role": title or "Insider",
            "buy_usd": round(buys), "sell_usd": round(sells)}


_form4_memo = {}


def _form4_for(entry):
    acc = entry["acc"]
    if acc in _form4_memo:
        return _form4_memo[acc]
    res = None
    try:
        idx = _sec_get(entry["link"]).decode("utf-8", "replace")
        m = re.search(r'href="(/Archives/edgar/data/\d+/\d+/[^"/]+\.xml)"', idx)
        if m:
            res = parse_form4(_sec_get("https://www.sec.gov" + m.group(1)))
            res.update(link=entry["link"], ts=entry["ts"])
    except Exception:
        res = None
    _form4_memo[acc] = res
    return res


def parse_edgar_atom(data):
    rows, seen = [], set()
    for e in parse_feed(data):
        acc = re.search(r"(\d{10}-\d{2}-\d{6})", e["link"])
        key = acc.group(1) if acc else e["link"]
        if key in seen:
            continue
        seen.add(key)
        rows.append({"acc": key, "link": e["link"], "title": e["title"], "ts": int(e["ts"] or time.time())})
    return rows


EDGAR = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&company=&dateb=&owner=include&start=0&output=atom&count="


def get_filings():
    if not sec_agent():
        return {"configured": False}

    def run():
        out = {"configured": True, "insider": [], "stakes": [], "generated": int(time.time())}
        try:
            entries = parse_edgar_atom(_sec_get(EDGAR + "100&type=4"))[:50]
            rows = [r for r in run_parallel(_form4_for, entries, deadline=40, workers=3) if r]
            out["insider"] = sorted((r for r in rows if r["buy_usd"] > 0 or r["sell_usd"] > 0),
                                    key=lambda r: -(r["buy_usd"] or 0))
        except Exception as e:
            out["insider_error"] = type(e).__name__
        try:
            out["stakes"] = [{"title": r["title"], "link": r["link"], "ts": r["ts"]}
                             for r in parse_edgar_atom(_sec_get(EDGAR + "40&type=SCHEDULE+13D"))[:20]]
        except Exception as e:
            out["stakes_error"] = type(e).__name__
        return out
    return cached("filings", 240, run)


# ---------------------------------------------------------------- article reader
class _Extract(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = self.art = 0
        self.cur = None
        self.in_title = False
        self.title = self.og = ""
        self.p_art, self.p_all = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "article":
            self.art += 1
        elif tag == "p" and not self.skip:
            self.cur = []
        elif tag == "title":
            self.in_title = True
        elif tag == "meta" and a.get("property") == "og:title":
            self.og = a.get("content") or ""

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "article":
            self.art = max(0, self.art - 1)
        elif tag == "title":
            self.in_title = False
        elif tag == "p" and self.cur is not None:
            t = WS_RE.sub(" ", "".join(self.cur)).strip()
            if len(t) >= 40:
                self.p_all.append(t)
                if self.art:
                    self.p_art.append(t)
            self.cur = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.cur is not None and not self.skip:
            self.cur.append(data)


def get_article(url):
    data, cs = http_get(url, max_bytes=2_500_000, timeout=15)
    p = _Extract()
    p.feed(data.decode(cs, "replace"))
    paras = (p.p_art if len(p.p_art) >= 3 else p.p_all)[:200]
    if len(paras) < 2:
        raise ValueError("Could not extract readable text (paywall or script-rendered page). Paste the text instead.")
    return {"url": url, "title": clean_text(p.og or p.title)[:200], "paragraphs": paras}
