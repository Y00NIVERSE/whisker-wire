"""Company brief: what a company's annual report says, and what it has just told the SEC.

Three things, for US-listed companies (the SEC publishes these for free, so they can be read automatically):
  - the numbers: five years of revenue, profit, cash flow and debt from the SEC's structured data,
    with a plain-English read of where they are heading;
  - the annual report itself: red-flag phrases, the stated reasons behind the year's changes, and risk
    wording that is new since last year's report;
  - latest developments: recent 8-K filings, each item translated out of SEC code.

Every URL fetched here is built from identifiers the SEC itself issued (a CIK number, an accession number,
a file name checked against a strict pattern), never from anything a visitor typed, so this adds no new way
to point the server somewhere else. Standard library only. Needs the same SEC identity as the Filings tab
(sec_contact.txt, or SEC_USER_AGENT on a host).
"""
import calendar
import datetime
import json
import re
import threading
import time
import urllib.error
from html.parser import HTMLParser

import engine

DATA = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
ORIGINAL_ANNUAL = ("10-K", "20-F", "40-F")
_ACC = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_DOC = re.compile(r"^[\w.\-]+$")
_HEAVY = threading.Semaphore(1)   # one big filing in memory at a time: this runs on small, shared machines


# ---------------------------------------------------------------- finding the company
def _tickers():
    def run():
        d = json.loads(engine._sec_get(TICKERS_URL))
        return {str(r["ticker"]).upper(): (int(r["cik_str"]), str(r["title"])) for r in d.values()}
    return engine.cached("sec:tickers", 86400, run)


def lookup(symbol):
    """(cik, name) for a US-listed ticker, or None (not US-listed: other markets have no automatic filings here)."""
    s = (symbol or "").strip().upper()
    if not engine.SYM_RE.match(s):
        raise ValueError("bad symbol")
    return _tickers().get(s.replace(".", "-"))


def _sec_error(e):
    if isinstance(e, urllib.error.HTTPError):
        return ValueError(f"The SEC did not answer (HTTP {e.code}). Try again in a minute.")
    return e


def _submissions(cik):
    return engine.cached(f"sec:sub:{cik}", 900, lambda: json.loads(
        engine._sec_get(f"{DATA}/submissions/CIK{cik:010d}.json", max_bytes=8_000_000, timeout=25)))


def _recent(sub):
    r = sub.get("filings", {}).get("recent", {})
    n = len(r.get("accessionNumber", []))
    keys = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument", "items")
    return [{k: (r.get(k) or [""] * n)[i] for k in keys} for i in range(n)]


def _doc_url(cik, row):
    acc, doc = row["accessionNumber"], row["primaryDocument"]
    if not _ACC.match(acc) or not _DOC.match(doc or ""):
        raise ValueError("unexpected filing identifier")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"


def _index_url(cik, row):
    acc = row["accessionNumber"]
    if not _ACC.match(acc):
        raise ValueError("unexpected filing identifier")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"


def _epoch(day):
    try:
        return calendar.timegm(time.strptime(day, "%Y-%m-%d"))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- latest developments (8-K)
# Item numbers are the SEC's own. The wording is ours: what it means to someone who has never read an 8-K.
ITEMS = {
    "1.01": ("Signed a major agreement", "info"), "1.02": ("Ended a major agreement", "warn"),
    "1.03": ("Bankruptcy or receivership", "bad"), "1.04": ("Mine safety violation", "warn"),
    "1.05": ("Reported a cybersecurity incident", "warn"),
    "2.01": ("Completed buying or selling a business or assets", "info"),
    "2.02": ("Published results (an earnings release)", "info"), "2.03": ("Took on new debt", "info"),
    "2.04": ("Debt may be called in early (a default trigger)", "bad"),
    "2.05": ("Announced restructuring or job cuts, with costs", "warn"),
    "2.06": ("Wrote down the value of assets (impairment)", "warn"),
    "3.01": ("Told by its exchange it may lose its listing", "bad"),
    "3.02": ("Sold unregistered shares (can dilute owners)", "warn"), "3.03": ("Changed the rights of shareholders", "info"),
    "4.01": ("Changed its auditor", "warn"),
    "4.02": ("Said past financial statements should not be relied on (restatement)", "bad"),
    "5.01": ("Change in who controls the company", "warn"),
    "5.02": ("Executive or director left, or was appointed", "warn"), "5.03": ("Changed its bylaws", "info"),
    "5.07": ("Shareholder vote results", "info"), "7.01": ("Shared a presentation or update (Regulation FD)", "info"),
    "8.01": ("Shared other news it chose to disclose", "info"),
}
_TONE_RANK = {"info": 0, "warn": 1, "bad": 2}


def developments(rows, cik, now=None, days=180, limit=12):
    now = now or time.time()
    out = []
    for r in rows:
        form = r["form"]
        periodic = form in ("10-K", "10-Q", "20-F", "40-F")
        if form not in ("8-K", "8-K/A", "6-K") and not periodic:
            continue
        ts = _epoch(r["filingDate"])
        if not ts or now - ts > days * 86400:
            continue
        items = []
        if periodic:
            kind = {"10-K": "annual report", "20-F": "annual report", "40-F": "annual report", "10-Q": "quarterly report"}[form]
            items = [{"code": "", "label": f"Filed its {kind}", "tone": "info"}]
        else:
            for code in (c.strip() for c in (r["items"] or "").split(",")):
                if not code or code == "9.01":
                    continue
                label, tone = ITEMS.get(code, (f"Other event (item {code})", "info"))
                items.append({"code": code, "label": label, "tone": tone})
            if not items:
                items = [{"code": "", "label": "Company announcement" if form != "6-K" else "Update from a foreign company", "tone": "info"}]
        out.append({"date": r["filingDate"], "ts": ts, "form": form, "items": items,
                    "tone": max((i["tone"] for i in items), key=_TONE_RANK.get), "url": _index_url(cik, r)})
    return out[:limit]


# ---------------------------------------------------------------- the numbers (SEC structured data)
FLOW = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "eps": ["EarningsPerShareDiluted", "DilutedEarningsLossPerShare", "EarningsPerShareBasic"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
}
STOCK = {
    "assets": ["Assets"], "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
}


def _span(start, end):
    try:
        return (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
    except ValueError:
        return 0


def _series(facts, names, flow):
    """The best yearly series among the names a company might have used: freshest, then longest."""
    best = None
    for tax in ("us-gaap", "ifrs-full"):
        for name in names:
            node = facts.get(tax, {}).get(name)
            for unit, entries in ((node or {}).get("units") or {}).items():
                pts = {}
                for e in entries:
                    end = e.get("end")
                    if e.get("form") not in ANNUAL_FORMS or not end or "val" not in e:
                        continue
                    if flow and not 340 <= _span(e.get("start") or end, end) <= 380:
                        continue
                    cur = pts.get(end)
                    if cur is None or (e.get("filed") or "") >= cur[1]:
                        pts[end] = (e["val"], e.get("filed") or "")
                if pts:
                    cand = (max(pts), len(pts), unit, {k: v[0] for k, v in pts.items()})
                    if best is None or cand[:2] > best[:2]:
                        best = cand
    return best


def _near(day, table, tol=12):
    if day in table:
        return table[day]
    d = _epoch(day)
    for k, v in table.items():
        if abs(_epoch(k) - d) <= tol * 86400:
            return v
    return None


def financials(facts, years=5):
    series = {k: _series(facts, n, True) for k, n in FLOW.items()}
    series.update({k: _series(facts, n, False) for k, n in STOCK.items()})
    anchor = series.get("revenue") or series.get("net_income")
    if not anchor:
        return None
    ends = sorted(anchor[3])[-years:]
    rows = {k: [_near(e, s[3]) for e in ends] for k, s in series.items() if s}
    cur = (anchor[2] or "USD").split("/")[0]

    def per(a, b):
        return [round(x / y, 4) if x is not None and y not in (None, 0) else None for x, y in zip(rows.get(a, [None] * len(ends)), rows.get(b, [None] * len(ends)))]
    rows["gross_margin"] = per("gross_profit", "revenue")
    rows["operating_margin"] = per("operating_income", "revenue")
    rows["net_margin"] = per("net_income", "revenue")
    if "cfo" in rows:
        rows["fcf"] = [None if c is None else c - (x or 0) for c, x in zip(rows["cfo"], rows.get("capex", [None] * len(ends)))]
    rows["debt_to_equity"] = per("debt", "equity")
    out = {"currency": cur, "years": ends, "rows": rows}
    out["read"] = read(out)
    return out


_SYMS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "CAD": "C$", "AUD": "A$", "CHF": "CHF ", "HKD": "HK$", "SGD": "S$", "INR": "₹"}


def money(v, cur="USD"):
    s = _SYMS.get(cur, cur + " ")
    a = abs(v)
    t = f"{a / 1e12:.1f}T" if a >= 1e12 else f"{a / 1e9:.1f}B" if a >= 1e9 else f"{a / 1e6:.0f}M" if a >= 1e6 else f"{a:,.0f}"
    return ("-" if v < 0 else "") + s + t


def read(f):
    """A short, rule-based read of the numbers. Every line states its own cause; none of it is advice."""
    R, n, cur = f["rows"], len(f["years"]), f["currency"]
    out = []

    def g(k, back=0):
        v = R.get(k)
        return v[n - 1 - back] if v and n - 1 - back >= 0 else None
    rev, prev = g("revenue"), g("revenue", 1)
    if rev is not None and prev:
        growth = rev / prev - 1
        first = R["revenue"][0]
        cagr = f" (about {((rev / first) ** (1 / (n - 1)) - 1) * 100:.0f}% a year over {n - 1} years)" if n >= 4 and first and first > 0 and rev > 0 else ""
        tone = "good" if growth > 0.05 else "warn" if growth < 0 else "info"
        out.append({"tone": tone, "text": f"Revenue {'grew' if growth >= 0 else 'fell'} {abs(growth) * 100:.1f}% to {money(rev, cur)}{cagr}."})
    ni, nm, pnm = g("net_income"), g("net_margin"), g("net_margin", 1)
    if ni is not None and ni < 0:
        out.append({"tone": "bad", "text": f"The company lost money last year: a net loss of {money(-ni, cur)}."})
    elif nm is not None and pnm is not None:
        d = (nm - pnm) * 100
        tone = "good" if d > 1 else "warn" if d < -2 else "info"
        out.append({"tone": tone, "text": f"Net margin (profit per dollar of sales) was {nm * 100:.1f}%, {'up' if d >= 0 else 'down'} from {pnm * 100:.1f}%."})
    cfo = g("cfo")
    if cfo is not None and ni and ni > 0:
        r = cfo / ni
        if r < 0.7:
            out.append({"tone": "warn", "text": f"Only about {r * 100:.0f} cents of each dollar of reported profit arrived as cash from operations, so the profit may not be as solid as it looks."})
        elif r >= 1:
            out.append({"tone": "good", "text": f"Profit is backed by cash: operating cash flow was {r:.1f} times net income."})
    fcf = g("fcf")
    if fcf is not None and fcf < 0:
        out.append({"tone": "bad" if (ni or 0) <= 0 else "warn", "text": f"Free cash flow was negative ({money(fcf, cur)}): it spent more than its operations brought in."})
    eq, debt, cash = g("equity"), g("debt"), g("cash")
    if eq is not None and eq < 0:
        out.append({"tone": "warn", "text": "Shareholders' equity is negative: on paper the company owes more than it owns. That is common after big buybacks, but it leaves little cushion."})
    elif debt is not None and eq:
        de = debt / eq
        if de > 2:
            out.append({"tone": "warn", "text": f"Long-term debt is {de:.1f} times shareholders' equity, which is heavily borrowed."})
    if cash is not None and debt is not None and debt > 0 and cash > debt:
        out.append({"tone": "good", "text": f"It holds more cash ({money(cash, cur)}) than long-term debt ({money(debt, cur)})."})
    pdebt = g("debt", 1)
    if debt and pdebt and rev and prev and debt / pdebt - 1 > 0.3 and debt / pdebt > rev / prev:
        out.append({"tone": "warn", "text": f"Long-term debt rose {(debt / pdebt - 1) * 100:.0f}%, much faster than sales."})
    return out


def _financials_for(cik):
    def run():
        with _HEAVY:
            raw = engine._sec_get(f"{DATA}/api/xbrl/companyfacts/CIK{cik:010d}.json", max_bytes=40_000_000, timeout=45)
            return financials(json.loads(raw).get("facts", {}))
    return engine.cached(f"sec:fin:{cik}", 43200, run)


# ---------------------------------------------------------------- the quick brief
def _filing_ref(cik, row):
    return None if not row else {"form": row["form"], "filed": row["filingDate"], "period": row["reportDate"], "url": _doc_url(cik, row)}


def get_company(symbol):
    if not engine.sec_agent():
        return {"configured": False}
    s = (symbol or "").strip().upper()
    try:
        hit = lookup(s)
        if not hit:
            return {"configured": True, "supported": False, "symbol": s}
        cik, name = hit
        sub = _submissions(cik)
        rows = _recent(sub)
        out = {"configured": True, "supported": True, "symbol": s, "name": sub.get("name") or name, "cik": cik,
               "edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=40",
               "developments": developments(rows, cik),
               "annual": _filing_ref(cik, next((r for r in rows if r["form"] in ORIGINAL_ANNUAL), None)),
               "quarterly": _filing_ref(cik, next((r for r in rows if r["form"] == "10-Q"), None))}
        try:
            out["financials"] = _financials_for(cik)
        except Exception as e:
            out["financials_error"] = type(_sec_error(e)).__name__
        return out
    except urllib.error.HTTPError as e:
        raise _sec_error(e)


# ---------------------------------------------------------------- reading the annual report itself
class _Lines(HTMLParser):
    """HTML to lines of text. Skips scripts and the hidden XBRL header every modern filing starts with."""
    BLOCK = {"p", "div", "br", "tr", "li", "table", "section", "center", "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "head", "title", "ix:header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.buf, self.skip = [], [], 0

    def _flush(self):
        t = " ".join("".join(self.buf).split())
        self.buf = []
        if t:
            self.lines.append(t)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self._flush()
        elif tag in ("td", "th"):
            self.buf.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


_ITEM_ONLY = re.compile(r"^item\s*\d+[a-c]?[.:]?$", re.I)


def doc_lines(html_text):
    p = _Lines()
    p.feed(html_text)
    p._flush()
    out, i = [], 0
    while i < len(p.lines):   # some filings put "Item 1A." and "Risk Factors" on separate lines
        if _ITEM_ONLY.match(p.lines[i]) and i + 1 < len(p.lines):
            out.append(p.lines[i] + " " + p.lines[i + 1])
            i += 2
        else:
            out.append(p.lines[i])
            i += 1
    return out


_SECTIONS = {
    "10-K": {"risk": (r"^item\s*1a\b[\s.:\-–—]*risk\s+factors", r"^item\s*(1b|1c|2)\b"),
             "mdna": (r"^item\s*7\b[\s.:\-–—]*management", r"^item\s*(7a|8)\b")},
    "20-F": {"risk": (r"^(item\s*3\.?\s*)?(d\.?\s*)?risk\s+factors\s*$", r"^item\s*4\b"),
             "mdna": (r"^item\s*5\b[\s.:\-–—]*operating", r"^item\s*6\b")},
}


def section(lines, kind, form="10-K"):
    """The longest stretch between a matching heading and the next item: the table of contents also matches,
    but it is short, so the real section wins. Empty when nothing plausible is found."""
    cfg = _SECTIONS["20-F" if form.startswith(("20-F", "40-F")) else "10-K"][kind]
    srx, erx = re.compile(cfg[0], re.I), re.compile(cfg[1], re.I)
    best = ""
    for i, ln in enumerate(lines):
        if not srx.search(ln[:200]):
            continue
        j = next((k for k in range(i + 1, len(lines)) if erx.search(lines[k][:80])), None)
        if j is not None:
            body = "\n".join(lines[i + 1:j])
            if len(body) > len(best):
                best = body
    return best if len(best) >= 2000 else ""


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")


def sentences(text):
    return [s.strip() for line in text.split("\n") for s in _SENT.split(line) if s.strip()]


_HEDGE = re.compile(r"\b(could|may|might|would|if|potential|possible|risk that|from time to time|no assurance|cannot assure|unable to predict)\b", re.I)
FLAGS = [
    ("going", "Doubt it can keep going (going concern)", "bad", r"substantial doubt[^.]{0,100}going concern|going concern"),
    ("weak", "Weakness in its financial controls", "bad", r"material weakness"),
    ("restate", "Restated past results", "bad", r"restate(d|ment)[^.]{0,80}(previously issued|prior period|financial statements)|non-reliance"),
    ("delist", "Exchange listing at risk", "bad", r"\bdelist|minimum bid price|continued listing (standard|requirement)"),
    ("auditor", "Changed or lost its auditor", "warn", r"(dismiss|resign|terminat)\w*[^.]{0,60}(independent registered public accounting firm|auditor)|(auditor|accounting firm)[^.]{0,50}(dismissed|resigned)"),
    ("probe", "Government or regulator investigation", "warn", r"subpoena|wells notice|formal investigation|civil investigative demand|sec (investigation|inquiry)"),
    ("covenant", "Trouble with its loan terms (covenants)", "warn", r"(violat|breach|not in compliance|waiver)\w*[^.]{0,80}covenant|covenant[^.]{0,80}(violat|breach|waiver)"),
    ("impair", "Wrote down the value of assets", "warn", r"(goodwill|long-lived assets?)[^.]{0,80}impairment|impairment (charge|of goodwill)"),
    ("cyber", "Cybersecurity incident", "warn", r"(cybersecurity|cyber) (incident|attack)|data breach|ransomware"),
    ("suit", "Class action or major lawsuit", "info", r"class action|securities litigation"),
    ("cuts", "Job cuts or restructuring", "info", r"reduction in (force|workforce)|restructuring (plan|charge)|layoffs"),
]
_FLAG_RX = [(i, lab, tone, re.compile(rx, re.I)) for i, lab, tone, rx in FLAGS]
_CONC = re.compile(r"(\d{2})% of (?:our |the company'?s |its )?(?:total |net |consolidated )?(?:net )?(?:revenues?|sales)", re.I)


def scan_flags(text):
    """Red-flag phrases, split into what the report states and what it only mentions as a possible risk. Nearly
    every report mentions going concern or a breach *hypothetically*; those are shown, but toned down."""
    found = {}
    for s in sentences(text):
        if not 40 <= len(s) <= 700:
            continue
        for fid, label, tone, rx in _FLAG_RX:
            if rx.search(s):
                hedged = bool(_HEDGE.search(s))
                cur = found.get(fid)
                if cur is None or (cur["hedged"] and not hedged):
                    found[fid] = {"id": fid, "label": label, "tone": "info" if hedged and tone != "info" else tone,
                                  "hedged": hedged, "text": s[:320] + ("…" if len(s) > 320 else "")}
        m = _CONC.search(s)
        if m and int(m.group(1)) >= 10 and "customer" in s.lower() and "conc" not in found:
            found["conc"] = {"id": "conc", "label": f"Depends on a few big customers ({m.group(1)}% of sales from one)",
                             "tone": "warn", "hedged": False, "text": s[:320] + ("…" if len(s) > 320 else "")}
    order = {"bad": 0, "warn": 1, "info": 2}
    return sorted(found.values(), key=lambda f: (order[f["tone"]], f["hedged"]))


_DRIVER = re.compile(r"(increase|decrease|decline|grew|growth|higher|lower|rose|fell)", re.I)
_CAUSE = re.compile(r"(due to|driven by|primarily|attributable|as a result of|resulted from|mainly)", re.I)
_BIG = re.compile(r"(revenue|net sales|gross margin|operating income|operating expenses|net income|cost of)", re.I)


def drivers(mdna, limit=5):
    """Sentences where management itself says what moved a number, and why."""
    scored = []
    for s in sentences(mdna):
        if 70 <= len(s) <= 420 and re.search(r"\d+(\.\d+)?%", s) and _DRIVER.search(s) and _CAUSE.search(s):
            scored.append((0 if _BIG.search(s) else 1, len(scored), s))
    scored.sort()
    return [s for _, _, s in scored[:limit]]


def _shingles(text, n=4):
    w = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def new_risks(cur, prior, limit=6):
    """Risk sentences whose wording barely appears in last year's report. It is a rewording detector, so it
    over-reports a little; it points at where to look, it does not prove a new risk."""
    if not cur or not prior:
        return None
    seen = _shingles(prior)
    out = []
    for s in sentences(cur):
        words = len(s.split())
        if not 14 <= words <= 90 or not re.search(r"\b(adverse|harm|loss|could|may|risk)\b", s, re.I):
            continue
        sh = _shingles(s)
        if sh and len(sh & seen) / len(sh) < 0.15:
            out.append((len(sh & seen) / len(sh), s))
    out.sort(key=lambda t: t[0])
    return [s[:300] + ("…" if len(s) > 300 else "") for _, s in out[:limit]]


def analyze(cik, cur, prior):
    html_text = engine._sec_get(_doc_url(cik, cur), max_bytes=15_000_000, timeout=50).decode("utf-8", "replace")
    lines = doc_lines(html_text)
    del html_text
    risk, mdna = section(lines, "risk", cur["form"]), section(lines, "mdna", cur["form"])
    out = {"available": True, "form": cur["form"], "filed": cur["filingDate"], "period": cur["reportDate"],
           "url": _doc_url(cik, cur), "flags": scan_flags("\n".join(lines)), "drivers": drivers(mdna),
           "sections": {"risk": bool(risk), "mdna": bool(mdna)}, "words": sum(len(x.split()) for x in lines),
           "prior": None, "new_risks": None}
    del lines
    if prior and risk:
        try:
            plines = doc_lines(engine._sec_get(_doc_url(cik, prior), max_bytes=15_000_000, timeout=50).decode("utf-8", "replace"))
            out["prior"] = {"form": prior["form"], "filed": prior["filingDate"], "period": prior["reportDate"]}
            out["new_risks"] = new_risks(risk, section(plines, "risk", prior["form"]))
        except Exception:
            pass   # last year's report is a bonus: failing to read it must not hide this year's
    return out


def get_annual_report(symbol):
    if not engine.sec_agent():
        return {"configured": False}
    s = (symbol or "").strip().upper()
    try:
        hit = lookup(s)
        if not hit:
            return {"configured": True, "supported": False, "symbol": s}
        cik, _ = hit
        annual = [r for r in _recent(_submissions(cik)) if r["form"] in ORIGINAL_ANNUAL and r["primaryDocument"]]
        if not annual:
            return {"configured": True, "supported": True, "available": False,
                    "reason": "No annual report in the SEC's recent filings for this company."}
        cur = annual[0]
        prior = next((r for r in annual[1:] if r["reportDate"] != cur["reportDate"]), None)

        def run():
            with _HEAVY:
                return analyze(cik, cur, prior)
        res = engine.cached(f"annual:{cik}:{cur['accessionNumber']}", 7 * 86400, run)
        return {"configured": True, "supported": True, "symbol": s, **res}
    except urllib.error.HTTPError as e:
        raise _sec_error(e)
