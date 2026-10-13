"""Tick's profit lens: what a text says has already happened, what it says is coming, and which of it matters
for where profit goes next.

A beginner reading an earnings story mixes two very different kinds of sentence. "Revenue rose 12%" is a fact
that can be checked. "We expect margins to improve" is a promise that can miss. This separates them, strips out
the legal disclaimer that sounds like an outlook but is not, picks out the few things that actually drive
profit (leading indicators such as orders, the guidance itself, input costs, pricing, one-offs that will not
repeat), and says which way the signals lean and why.

It is rules over words, not understanding: it shows where to look and what to check next, never a forecast.
Pure functions, standard library only.
"""
import datetime
import re

from textutil import sentences

MAX_CHARS = 400_000

# ---------------------------------------------------------------- vocabulary
_UP = re.compile(r"\b(increas\w+|grew|grow\w*|rose|rise|rising|risen|higher|expan\w+|improv\w+|accelerat\w+|strong\w*|record|"
                 r"surg\w+|jump\w*|climb\w*|gain\w*|up|benefit\w*|tailwinds?|upside|favou?rable|exceed\w*|beat\w*|outperform\w*|"
                 r"robust|healthy|solid|recover\w*|rebound\w*|ahead of|soar\w*|lifted|swell\w*|stronger)\b", re.I)
_DOWN = re.compile(r"\b(decreas\w+|declin\w+|fell|fall\w*|drop\w*|lower\w*|reduc\w+|contract\w*|weak\w*|soft\w*|pressure\w*|compress\w+|"
                   r"erod\w+|headwinds?|downside|unfavou?rable|shortfall|delay\w*|challeng\w+|slow\w*|deteriorat\w+|loss(?:es)?|"
                   r"miss\w*|cut\w*|trim\w*|below|disrupt\w*|subdued|muted|dilution|dilutive|down|shrank|shrunk|shrink\w*|worse\w*|dipped|"
                   r"slipped|slid|eased|tumbl\w*|plung\w*|plummet\w*|sank|fewer|lagg\w+|weighed|weighing)\b", re.I)
# words that state what something did TO profit, whatever the thing was
_HURT = re.compile(r"\b(weigh\w*|pressur\w+|hurt\w*|hit|hits|squeez\w+|erod\w+|dent\w*|drag\w*|burden\w*|weaken\w*|undermin\w+)\b", re.I)
_HELP = re.compile(r"\b(boost\w*|lift\w*|support\w*|help\w*|fuel\w*|underpin\w*|bolster\w*)\b", re.I)
_RELIEF = re.compile(r"\b(eas\w+|remov\w+|roll\w* back|exempt\w*|waiver|suspen\w+|reduc\w+|lower\w*|lift\w*|cut)\b", re.I)
_OUTCOME = re.compile(r"\b(margins?|profit\w*|earnings|income|eps|cash flow|results)\b", re.I)
# (?![a-z]) rather than \b: tables stick footnote digits onto words ("currency tailwind1")
_TAIL = re.compile(r"\btailwinds?(?![a-z])|\bfavou?rable(?![a-z])", re.I)
_HEAD = re.compile(r"\bheadwinds?(?![a-z])|\bunfavou?rable(?![a-z])", re.I)

# (id, label, polarity, leading indicator?, pattern). Polarity: does MORE of this help profit (+1) or hurt it (-1)?
BUCKETS = [
    ("demand", "Orders and demand", +1, True,
     r"\b(orders?|bookings?|backlog|pipeline|demand|volumes?|shipments?|traffic|subscribers?|remaining performance obligations?|rpo|"
     r"same[- ]store sales|comparable sales|utili[sz]ation|customer (?:additions?|growth)|design wins?)\b"),
    ("pricing", "Pricing and mix", +1, True,
     r"\b(pricing|price (?:increases?|hikes?|cuts?|realization)|average selling prices?|asp|product mix|mix|discounting|promotional)\b"),
    ("costs", "Costs", -1, False,
     r"\b(costs?|expenses?|opex|cost of (?:sales|goods|revenue)|raw materials?|commodit\w+|freight|logistics|labou?r|wages?|"
     r"inflation|energy|input costs?|supply chain|headcount|compensation)\b"),
    ("trade", "Tariffs and trade", -1, False, r"\b(tariffs?|duties|trade (?:war|restrictions?|policy)|export (?:controls?|restrictions?)|sanctions?)\b"),
    ("fx", "Currency", 0, False, r"\b(currency|foreign exchange|fx|exchange rates?|strengthening dollar|weaker dollar|stronger dollar)\b"),
    ("margin", "Margins", +1, False,
     r"\b(gross margins?|operating margins?|net margins?|ebitda margins?|margins?|gross profit|operating income|operating profit|ebit|profitability)\b"),
    ("sales", "Sales", +1, False, r"\b(revenues?|net sales|sales|top[- ]line)\b"),
    ("result", "Profit and cash", +1, False, r"\b(net income|net profit|earnings|eps|profit|free cash flow|cash flow)\b"),
    ("invest", "Investment and capacity", -1, False,
     r"\b(capex|capital expenditures?|new (?:plant|factory|facility|facilities|stores?)|capacity|r&d|research and development|hiring)\b"),
    ("capital", "Interest, tax and share count", 0, False,
     r"\b(interest expense|interest rates?|refinanc\w+|tax rate|effective tax|share count|buybacks?|repurchases?|dilution)\b"),
]
_BUCKETS = [(i, lab, pol, lead, re.compile(rx, re.I)) for i, lab, pol, lead, rx in BUCKETS]

_AHEAD = re.compile(r"\b(expects?|expected to|expecting|anticipat\w+|forecast\w*|projects?|projected|projecting|guid(?:ance|ing)|outlook|"
                    r"targets?|targeting|plans? to|aims? to|intends?|on track|poised|set to|will|going forward|looking ahead|"
                    r"(?:next|coming|upcoming) (?:quarter|year|fiscal year|twelve months|12 months|few quarters)|"
                    r"remainder of|should (?:be|see|benefit|improve))\b", re.I)
# "second half" and "third quarter of 2025" are not listed above on purpose: they are as often past as future, and a
# year later than the document's own date already marks the future ("fourth quarter of 2026" in a 2025 report).
_BACK = re.compile(r"\b(increased|decreased|grew|rose|fell|declined|dropped|improved|reported|recorded|delivered|achieved|generated|totale?d|"
                   r"reached|posted|compared (?:with|to)|year[- ]over[- ]year|prior[- ]year|last (?:year|quarter)|"
                   r"(?:quarter|year|period|months?) ended|during (?:the )?(?:quarter|year|fiscal|period)|came in|amounted to|"
                   r"(?:was|were) (?:up|down|\$?\d[\d.,]*|flat)|resulted in|reflecting|reflected|due to|driven by|ended (?:the )?(?:quarter|year))\b", re.I)
_YEARS = re.compile(r"\b(20\d\d)\b")
# Cues that mean the writer is looking ahead. A bare "will" is not one of them: it shows up in "will depend on many
# factors" and "which will be effective", so it can list a sentence under Looking ahead but cannot move the read.
_STRONG = re.compile(r"\b(?:expects?|expected to|expecting|anticipates?|anticipating|forecast\w*|projects?|projected|projecting|guid(?:ance|ing)|"
                     r"outlook|targets?|targeting|aims? to|intends? to|on track|poised|set to|going forward|looking ahead|"
                     r"(?:next|coming|upcoming) (?:quarter|year|fiscal year|twelve months|12 months)|should (?:be|see|benefit|improve))\b", re.I)

# The legal paragraph that sounds like an outlook ("we expect...", "will...") but is a safe-harbour notice.
_DISCLAIMER = re.compile(r"forward[- ]looking statements?|safe[- ]harbou?r|reform act|actual results (?:may|could|might) differ materially|"
                         r"undertakes? no (?:obligation|duty)|assumes? no (?:obligation|duty)|no obligation to update|"
                         r"not (?:a )?(?:guarantee|guarantees) of future|unreasonabl[ey] (?:efforts|burdensome)|without unreasonable|"
                         r"we do not provide (?:a )?(?:reconciliation|forward)|(?:the )?use of non-gaap|"
                         r"non-gaap financial measures? (?:are|is) not (?:a )?(?:substitute|measure)", re.I)
# Accounting-rule notes ("will be effective for fiscal years beginning...") are future tense but not a profit outlook,
# and "outlook" next to an impairment is a valuation input, not guidance.
_ACCOUNTING = re.compile(r"\bFASB\b|\bASU\b|accounting standards? (?:update|codification)|recently (?:issued|adopted) accounting|"
                         r"effective for (?:fiscal|annual|interim)|early adoption|adopt\w* (?:this|the) (?:standard|guidance|ASU|amendments?)", re.I)
_VALUATION = re.compile(r"\b(?:impairment|goodwill|trademark|fair value|valuation|discount rate|indefinite[- ]lived|long[- ]lived)\b", re.I)
_URL = re.compile(r"https?://\S+|www\.\S+")


def _clean(s):
    """Page furniture out of the way: links, a leading page number, runs of spaces."""
    s = _URL.sub(" ", s)
    s = re.sub(r"^\s*\d{1,3}\s+(?=[A-Z“\"])", "", s)
    return " ".join(s.split())


def _is_prose(s):
    """A sentence, not a table row: a row is mostly numbers and has few real words."""
    words = re.findall(r"[A-Za-z']{2,}", s)
    nums = re.findall(r"\d[\d.,]*", s)
    return len(words) >= 8 and len(nums) <= len(words)
_BOILER = re.compile(r"\b(subscribe|sign up|newsletter|click here|follow us|read more|all rights reserved|copyright|advertisement|"
                     r"privacy policy|not investment advice|conference call|webcast|dial[- ]in|replay)\b", re.I)

_SOFT = re.compile(r"\b(may|might|could|hope\w*|aim\w*|aspir\w+|ambition|subject to|uncertain\w*|if|potentially|possibly|"
                   r"cannot (?:assure|guarantee|predict)|no assurance|seek\w* to|endeavou?r\w*|believes?)\b", re.I)

# "above"/"below" alone are not enough: "the outlook information provided below" is a label, not a cut
_RAISE = re.compile(r"(?:rais\w+|lift\w*|boost\w*|hik\w+|upgrad\w+|upward)[^.]{0,50}(?:outlook|guidance|forecasts?|targets?|expectations)|"
                    r"(?:outlook|guidance|forecasts?)[^.]{0,50}(?:rais\w+|upgrad\w+|upward|higher than (?:previous|prior|expected)|above (?:previous|prior|the high end|expectations|consensus))", re.I)
_CUT = re.compile(r"(?:lower\w*|cut\w*|reduc\w+|trim\w*|slash\w*|withdr\w+|suspend\w*|downgrad\w+|downward)[^.]{0,50}(?:outlook|guidance|forecasts?|targets?|expectations)|"
                  r"(?:outlook|guidance|forecasts?)[^.]{0,50}(?:lower\w*|cut|reduc\w+|withdr\w+|suspend\w*|downgrad\w+|downward|below (?:previous|prior|expectations|consensus))|"
                  r"profit warning|warned (?:that )?profits?", re.I)
_HOLD = re.compile(r"(?:reaffirm\w*|reiterat\w*|maintain\w*|affirm\w*|confirm\w*|unchanged)[^.]{0,50}(?:outlook|guidance|forecasts?|targets?)|"
                   r"(?:outlook|guidance|forecasts?)[^.]{0,30}(?:unchanged|reaffirmed|maintained)", re.I)

_ONEOFF = re.compile(r"\b(one[- ]time|non[- ]?recurring|one[- ]off|restructuring (?:charges?|costs?)|impairments?|gains? on (?:the )?sale|"
                     r"loss(?:es)? on (?:the )?sale|(?:legal )?settlements?|special items?|acquisition[- ]related|discrete (?:tax )?items?|"
                     r"write[- ]?(?:down|off)s?|severance|unusual items?|exceptional)\b", re.I)

_MONEY = re.compile(r"(?:US|A|S|HK|C|NZ)?[$£€¥]\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|t|bn|mm|million|billion|trillion|thousand)?\b", re.I)
_PCT = re.compile(r"\d+(?:\.\d+)?\s?(?:%|percent(?!age))", re.I)
_RANGE_WORDS = re.compile(r"\b(?:low|mid|high)[- ](?:single|double)[- ]digits?\b", re.I)
_HORIZON = re.compile(r"\b(next (?:quarter|year|fiscal year)|(?:first|second|third|fourth) quarter(?: of (?:fiscal )?20\d\d)?|"
                      r"full[- ]year(?: 20\d\d)?|fiscal (?:year )?20\d\d|(?:the )?(?:second|first) half(?: of (?:fiscal )?20\d\d)?|"
                      r"20\d\d|coming (?:quarters?|year)|remainder of (?:the )?(?:year|fiscal year))\b", re.I)
_METRIC_NAMES = re.compile(r"\b(revenues?|net sales|sales|gross margin|operating margin|net margin|ebitda|operating income|net income|"
                           r"earnings per share|eps|earnings|free cash flow|capex|capital expenditures?|tax rate|margins?|profit)\b", re.I)


# ---------------------------------------------------------------- what the guidance implies
_MAG = {"trillion": 1e12, "tn": 1e12, "t": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_MONEY_VAL = re.compile(r"(?:US|A|S|HK|C|NZ)?[$£€¥]\s?(\d[\d,]*(?:\.\d+)?)\s?(trillion|billion|million|thousand|bn|mm|tn|[tbmk])?\b", re.I)
_PCT_VAL = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent(?!age))", re.I)
_METRIC_KEYS = [
    ("gross margin", re.compile(r"\bgross margins?\b", re.I)), ("operating margin", re.compile(r"\boperating margins?\b|\bebit margin\b", re.I)),
    ("net margin", re.compile(r"\bnet margins?\b", re.I)), ("eps", re.compile(r"\beps\b|earnings per (?:diluted )?share|per diluted share", re.I)),
    ("operating income", re.compile(r"\boperating (?:income|profit)\b|\bebit(?:da)?\b", re.I)),
    ("net income", re.compile(r"\bnet (?:income|profit|earnings)\b", re.I)),
    ("revenue", re.compile(r"\b(?:revenues?|net sales|sales)\b", re.I)),
    ("free cash flow", re.compile(r"\bfree cash flow\b", re.I)),
]
_MARGINS = ("gross margin", "operating margin", "net margin")


def _metric_key(s):
    best = None
    for key, rx in _METRIC_KEYS:
        m = rx.search(s)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), key)
    return best[1] if best else None


def _money_values(s):
    return [float(m.group(1).replace(",", "")) * _MAG.get((m.group(2) or "").lower(), 1) for m in _MONEY_VAL.finditer(s)]


def _pct_values(s):
    return [float(m.group(1)) for m in _PCT_VAL.finditer(s)]


def _headline_value(s, key):
    """The one number a guidance or results sentence is about: a range collapses to its middle."""
    if key in _MARGINS:
        v = _pct_values(s)
        return v[0] if v else None
    v = _money_values(s)
    if not v:
        return None
    if len(v) >= 2 and re.search(r"\b(?:to|between|and|-|–)\b", s) and 0.5 <= v[0] / v[1] <= 2:
        return (v[0] + v[1]) / 2
    return v[0]


_YEAR_KIND = re.compile(r"\b(?:full[- ]year|fiscal year|fiscal 20\d\d|for the year|annual|year ended|12 months|twelve months)\b", re.I)
_QUARTER_KIND = re.compile(r"\b(?:quarter|q[1-4]|three months)\b", re.I)


def _period_kind(s):
    """A year or a quarter: guidance for the year must be set against the year's figure, never a quarter's.
    'Quarter' wins when both appear: "the first quarter of fiscal year 2027" is a quarter, dated by its year."""
    if _QUARTER_KIND.search(s):
        return "quarter"
    return "year" if _YEAR_KIND.search(s) else None


def _implied(fwd, back_items):
    """Guidance against the last reported figure for the same thing: 'revenue guided to $108B vs $89B reported'.
    The reported figure is the largest one found for that metric, so a segment is not mistaken for the total.
    Rough by nature: the periods may differ (a quarter against a year), so the page says to check."""
    key = _metric_key(fwd["text"])
    # profit lines can be losses, and a loss written without its sign pairs a loss with a profit: stay with the
    # stable ones (sales and margins), and never pair a sentence that talks about a loss
    if not key or key not in ("revenue",) + _MARGINS or re.search(r"\bloss(?:es)?\b", fwd["text"], re.I):
        return None
    f = _headline_value(fwd["text"], key)
    kind = _period_kind(fwd["text"])
    cands = [(v, b) for b in back_items if _metric_key(b["text"]) == key and not re.search(r"\bloss(?:es)?\b", b["text"], re.I)
             and not (kind and _period_kind(b["text"]) and _period_kind(b["text"]) != kind)
             and (v := _headline_value(b["text"], key)) is not None]
    if f is None or not cands:
        return None
    if key in _MARGINS:
        v, b = max(cands, key=lambda c: c[1]["score"])
        return {"metric": key, "now": f, "then": v, "delta": round(f - v, 1), "unit": "pp", "from": b["text"][:90]}
    v, b = max(cands, key=lambda c: c[0])
    if v <= 0 or not 0.3 <= f / v <= 3 or abs(f / v - 1) < 0.001:
        return None
    return {"metric": key, "now": f, "then": v, "delta": round((f / v - 1) * 100, 1), "unit": "%", "from": b["text"][:90]}


# ---------------------------------------------------------------- guidance tables
# Earnings releases often give the outlook as a table: "Organic revenues   Approx. 5% growth   4% to 5% growth"
# under "Full Year 2026 Guidance" with Current and Prior columns. That is not prose, but it is the most useful
# forecasting information in the release, so lines in a guidance section are read as forward statements.
_GUID_HEAD = re.compile(r"^(?:(?:full[- ]year|first[- ]quarter|second[- ]quarter|third[- ]quarter|fourth[- ]quarter|q[1-4]|fiscal|annual|"
                        r"next[- ]year|20\d\d)\s*){0,5}(?:guidance|outlook|considerations|expectations|targets)\b[^.]{0,40}$", re.I)
_REGION_END = re.compile(r"^(?:condensed|consolidated|reconciliation|selected|schedule|about |safe harbor|non-gaap (?:reconciliation|financial)|supplemental|"
                         r"for more information|contact)", re.I)
_PRIOR_COLS = re.compile(r"\b(?:current|updated|new)\b.*\b(?:prior|previous|old)\b|\b(?:prior|previous)\b.*\b(?:current|updated|new)\b", re.I)
_VALUE_TOKEN = re.compile(r"(\d+(?:\.\d+)?)\s?%?\s+to\s+(\d+(?:\.\d+)?)\s?%|(\d+(?:\.\d+)?)\s?%")


def _current_vs_prior(line):
    """'Approx. 5% growth  4% to 5% growth' -> the current guidance (5) against the prior (4 to 5, middle 4.5): raised."""
    vals = [(float(m.group(1)) + float(m.group(2))) / 2 if m.group(1) else float(m.group(3)) for m in _VALUE_TOKEN.finditer(line)]
    if len(vals) != 2:
        return None
    return "raise" if vals[0] > vals[1] + 0.05 else "cut" if vals[0] < vals[1] - 0.05 else "hold"


def _guidance_rows(lines):
    rows, i = [], 0
    n = len(lines)
    while i < n:
        if len(lines[i]) <= 90 and _GUID_HEAD.match(lines[i].strip()):
            j, region, prior_cols = i + 1, [], False
            while j < n and j < i + 55 and not _REGION_END.match(lines[j].strip()):
                region.append(lines[j]); prior_cols = prior_cols or bool(_PRIOR_COLS.search(lines[j])) ; j += 1
            for ln in region:
                ln = _clean(ln).lstrip("•· ")
                # a table row has no full stop at the end; a sentence does, and sentences are read as sentences
                if len(ln) < 12 or ln.rstrip().endswith((".", "!", "?", "”", '"')) or not _figures(ln):
                    continue
                b = _bucket(ln)
                key = _metric_key(ln)
                if not b and not key:
                    continue
                rows.append((ln, key, b, _current_vs_prior(ln) if prior_cols else None))
            i = j
        else:
            i += 1
    return rows


# ---------------------------------------------------------------- reading one sentence
def _direction(s):
    if _TAIL.search(s) and not _HEAD.search(s):
        return 1
    if _HEAD.search(s) and not _TAIL.search(s):
        return -1
    ups, downs = list(_UP.finditer(s)), list(_DOWN.finditer(s))
    if len(ups) != len(downs):
        return 1 if len(ups) > len(downs) else -1
    last = max([(m.start(), 1) for m in ups] + [(m.start(), -1) for m in downs], default=None)
    return last[1] if last else 0     # a tie: the later word is usually the verb about the outcome


def _bucket(s):
    """What a sentence is about: the theme it names first, because the first thing named is what changed
    ("Gross margin was down as costs rose" is about margin; the costs are the reason)."""
    best = None
    for n, (i, label, pol, lead, rx) in enumerate(_BUCKETS):
        m = rx.search(s)
        if m and (best is None or (m.start(), n) < best[0]):
            best = ((m.start(), n), (i, label, pol, lead))
    return best[1] if best else None


# "revenue rose 12% AS demand stayed strong": the part after the connector is the reason, a driver in its own right
_CAUSE = re.compile(r",?\s+\b(?:as|because|due to|driven by|amid|after|reflecting|thanks to|owing to|on the back of|helped by|weighed (?:down )?by)\s+", re.I)


def _split_cause(s):
    m = _CAUSE.search(s)
    return (s[:m.start()], s[m.end():]) if m else (s, "")


def _impact(direction, polarity, s, bucket=None):
    """Good (+1) or bad (-1) for profit. Order matters: an explicit headwind/tailwind, then tariffs (bad unless
    eased), then words that state an effect on profit ("weighed on", "boosted"), then direction times polarity
    (costs rising hurts, so polarity flips the sign) - except that a sentence about margins or profit reports the
    outcome itself, so its direction is taken as it reads."""
    if _HEAD.search(s) and not _TAIL.search(s):
        return -1
    if _TAIL.search(s) and not _HEAD.search(s):
        return 1
    hurt, help_ = _HURT.search(s), _HELP.search(s)
    if bucket == "trade":
        return 1 if _RELIEF.search(s) and not hurt else -1
    if hurt and not help_:
        return -1
    if help_ and not hurt:
        return 1
    pol = 1 if _OUTCOME.search(s) else polarity
    return direction * pol if pol else 0


def _figures(s):
    figs = [m.group(0).strip() for m in _MONEY.finditer(s)] + [m.group(0).strip() for m in _PCT.finditer(s)] + [m.group(0) for m in _RANGE_WORDS.finditer(s)]
    seen, out = set(), []
    for f in figs:
        k = f.lower()
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out[:4]


_PERIOD_END = re.compile(r"\b(?:year|quarter|period|months?|fiscal year)s? ended (?:on )?(?:[A-Z][a-z]+\.? ?\d{0,2},? ?)?(20\d\d)\b", re.I)


def _reference_year(sents):
    """The year the text is 'about'. Years later than this are the future. It comes from explicit period ends
    ("the year ended December 31, 2025"), so an old report is judged against its own date, not today's, and a
    debt maturity in 2030 cannot make the whole report look like it was written in 2030."""
    limit = datetime.date.today().year + 1
    ends = [int(m.group(1)) for s in sents for m in _PERIOD_END.finditer(s) if int(m.group(1)) <= limit]
    if ends:
        return max(ends)
    ys = [int(y) for s in sents if re.search(r"\b(?:fiscal|reported|full[- ]year)\b", s, re.I) and not _AHEAD.search(s) for y in _YEARS.findall(s) if int(y) <= limit]
    return max(ys) if ys else datetime.date.today().year


# "notes due 2030" and "expires in 2028" name a later year without forecasting anything
_DATE_ONLY = re.compile(r"(?:due|mature\w*|maturity|expir\w+|through|until|ending|ends|terminat\w+)\W+(?:\w+\W+){0,3}$", re.I)


def _future_years(s, ref):
    out = []
    for m in _YEARS.finditer(s):
        if int(m.group(1)) > ref and not _DATE_ONLY.search(s[max(0, m.start() - 40):m.start()]):
            out.append(int(m.group(1)))
    return out


def _tense(s, ref):
    ahead = bool(_AHEAD.search(s)) or bool(_future_years(s, ref))
    back = bool(_BACK.search(s))
    return "both" if ahead and back else "ahead" if ahead else "back" if back else None


def _short(s, n=300):
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# ---------------------------------------------------------------- the lens
def analyze(paragraphs):
    paras = [p for p in (paragraphs or []) if isinstance(p, str) and p.strip()]
    sents, disclaimer = [], False
    for p in paras:
        ss = sentences(p)
        if any(_DISCLAIMER.search(s) for s in ss):
            disclaimer = True          # the whole notice goes: its risk list reads like an outlook but promises nothing
            continue
        sents.extend(c for c in (_clean(s) for s in ss)
                     if 40 <= len(c) <= 600 and _is_prose(c) and not _BOILER.search(c) and not _ACCOUNTING.search(c))
    ref = _reference_year(sents)

    items = []
    for s in sents:
        guid = "raise" if _RAISE.search(s) else "cut" if _CUT.search(s) else "hold" if _HOLD.search(s) else None
        if guid and (_VALUATION.search(s) or not _METRIC_NAMES.search(s)):
            guid = None                 # guidance is about revenue, profit or margin: not an asset's valuation inputs
        main, cause = _split_cause(s)
        b = _bucket(main) or _bucket(s)
        if not b and not guid:
            continue
        tense = _tense(s, ref)
        if not tense and not guid:
            continue
        figs = _figures(s)
        bid, label, pol, lead = b if b else ("guidance", "Guidance", +1, True)
        # direction comes from the main clause; the reason after "as ..." must not cancel it out
        d_main = _direction(main)
        impact = _impact(d_main or _direction(s), pol, main if d_main else s, bid)
        if guid:
            impact = {"raise": 1, "cut": -1, "hold": 0}[guid]
        base = (3 if guid else 0) + (2 if figs else 0) + (1 if _METRIC_NAMES.search(s) else 0) + (1 if _HORIZON.search(s) else 0) - (1 if len(s) > 380 else 0)
        hz = _HORIZON.search(s)
        future_year = bool(_future_years(s, ref))
        common = {"text": s, "tense": tense or "ahead", "guidance": guid, "firm": not _SOFT.search(s), "figures": figs,
                  "horizon": hz.group(0) if hz else None, "oneoff": bool(_ONEOFF.search(s)),
                  "strong": bool(_STRONG.search(s)) or future_year or bool(guid)}
        items.append({**common, "bucket": bid, "label": label, "impact": impact, "leading": lead,
                      "score": base + (2 if lead else 0) + (1 if impact else 0)})
        cb = _bucket(cause) if cause else None
        if cb and cb[0] != bid and _direction(cause):
            c_impact = _impact(_direction(cause), cb[2], cause, cb[0])
            items.append({**common, "bucket": cb[0], "label": cb[1], "impact": c_impact, "leading": cb[3], "cause": True,
                          "score": base - 1 + (2 if cb[3] else 0) + (1 if c_impact else 0)})
    for ln, key, b, cvp in _guidance_rows(paras):
        bid, label, pol, lead = b if b else ("guidance", "Guidance", +1, True)
        impact = {"raise": 1, "cut": -1, "hold": 0}[cvp] if cvp else _impact(_direction(ln), pol, ln, bid)
        items.append({"text": ln, "tense": "ahead", "guidance": cvp, "firm": True, "figures": _figures(ln), "horizon": None, "oneoff": False,
                      "bucket": bid, "label": label, "impact": impact, "leading": lead, "table": True, "strong": True,
                      "score": 5 + (3 if cvp else 0) + (1 if impact else 0)})
    # a sentence with no figure and no direction says nothing a person can act on
    items = [i for i in items if i["figures"] or i["impact"] or i["guidance"]]
    if len(items) < 2:
        return {"available": False, "disclaimer": disclaimer,
                "reason": "Tick found no profit-related statements in this text, so there is nothing to split into past and future."}

    def top(rows, n):
        out, seen = [], set()
        for r in sorted(rows, key=lambda r: -r["score"]):
            k = r["text"][:60]
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out[:n]

    def tone(i):
        return "good" if i["impact"] > 0 else "bad" if i["impact"] < 0 else "info"

    # a "because of ..." clause is a driver in its own right but the sentence is listed once, under what changed
    main_items = [i for i in items if not i.get("cause")]
    back = top([i for i in main_items if i["tense"] in ("back", "both") and not i["guidance"]], 5)   # guidance is forward by definition
    ahead = top([i for i in main_items if i["tense"] in ("ahead", "both")], 6)
    back_pool = [i for i in main_items if i["tense"] in ("back", "both") and not i["guidance"]]
    for i in ahead:
        i["implied"] = _implied(i, back_pool)

    # what actually drives profit: one line per theme, leading indicators and the outlook ahead first
    drivers, used = [], set()
    for i in sorted(items, key=lambda r: (-(r["tense"] in ("ahead", "both")), -r["leading"], -r["score"])):
        if i["bucket"] in used or i["bucket"] == "guidance" or not (i["impact"] or i["figures"]):
            continue
        used.add(i["bucket"])
        drivers.append({"theme": i["label"], "leading": i["leading"], "tone": tone(i), "when": "ahead" if i["tense"] != "back" else "back", "text": _short(i["text"])})
        if len(drivers) >= 6:
            break

    one_offs = top([i for i in items if i["oneoff"] and i["figures"]], 3)

    # ---- the read: every point states its own cause
    points, score = [], 0.0
    guid = next((i for i in sorted(items, key=lambda r: -r["score"]) if i["guidance"]), None)
    if guid:
        word = {"raise": "raised", "cut": "cut or withdrawn", "hold": "kept unchanged"}[guid["guidance"]]
        score += {"raise": 3, "cut": -3, "hold": 0}[guid["guidance"]]
        points.append({"tone": {"raise": "good", "cut": "bad", "hold": "info"}[guid["guidance"]], "text": f"The outlook itself was {word}: that is the strongest single signal in the text."})
    implied_pts = 0
    for i in [i for i in ahead if i.get("implied")][:2]:       # the numbers behind the outlook: the most useful forecasting fact
        m = i["implied"]
        sym = next((c for c in i["text"] if c in "$£€¥"), "$")
        good = m["delta"] > 0
        if m["unit"] == "pp":
            txt = f"Guidance puts {m['metric']} at about {m['now']}%, {'up' if good else 'down'} {abs(m['delta'])} points on the reported figure."
        else:
            txt = f"Guidance implies {m['metric']} of about {_fmt_money(m['now'], sym)}, {'up' if good else 'down'} {abs(m['delta'])}% from the last reported {_fmt_money(m['then'], sym)}."
        if abs(m["delta"]) >= (0.3 if m["unit"] == "pp" else 1):
            points.append({"tone": "good" if good else "bad", "text": txt + " Rough: check both numbers cover the periods you think."})
            score += 1 if good else -1
            implied_pts += 1
    fwd = [i for i in items if i["tense"] in ("ahead", "both") and i["impact"] and not i["guidance"] and i["strong"]]
    tail = [i for i in fwd if i["impact"] > 0]
    head = [i for i in fwd if i["impact"] < 0]
    w = lambda rows: sum(2 if r["leading"] else 1 for r in rows)
    score += w(tail) - w(head)
    if tail or head:
        lead_t = [r["label"].lower() for r in tail if r["leading"]]
        points.append({"tone": "good" if w(tail) > w(head) else "bad" if w(head) > w(tail) else "info",
                       "text": f"Looking ahead it names {len(tail)} thing{'s' if len(tail) != 1 else ''} that should help profit and {len(head)} that should hurt it"
                               + (f" (leading indicators on the plus side: {', '.join(sorted(set(lead_t)))})." if lead_t else ".")})
    bk = [i for i in items if i["tense"] == "back" and i["impact"]]
    back_net = sum(i["impact"] for i in bk)
    if bk:
        net = back_net
        score += 0.5 * net
        points.append({"tone": "good" if net > 0 else "bad" if net < 0 else "info",
                       "text": f"Looking back, {sum(1 for i in bk if i['impact'] > 0)} reported results moved the right way for profit and {sum(1 for i in bk if i['impact'] < 0)} the wrong way."})
    soft_fwd = [i for i in items if i["tense"] in ("ahead", "both") and i["strong"] and not i["firm"]]
    firm_fwd = [i for i in items if i["tense"] in ("ahead", "both") and i["strong"] and i["firm"]]
    if soft_fwd and len(soft_fwd) >= len(firm_fwd):
        points.append({"tone": "warn", "text": "Most of the outlook is hedged (may, could, aims): that is hope, not guidance."})
    if one_offs:
        points.append({"tone": "warn", "text": f"{len(one_offs)} one-off item{'s' if len(one_offs) != 1 else ''} will not repeat, so the trend looks different once they are stripped out."})

    lean = "unclear"
    if guid or tail or head or implied_pts:
        both = len(tail) >= 2 and len(head) >= 2
        lean = "mixed" if both and abs(score) < 3 else "up" if score >= 2 else "down" if score <= -2 else "mixed" if tail and head else "unclear"
        # A direction needs an explicit outlook to stand on: counting hopeful words is not a forecast. And it must not
        # contradict what already happened: a company whose results are falling does not get called "up" on adjectives.
        if lean in ("up", "down") and not (guid or implied_pts):
            lean = "mixed" if tail and head else "unclear"
        if (lean == "up" and back_net < 0) or (lean == "down" and back_net > 0):
            lean = "mixed"

    check = []
    if guid and guid["guidance"] != "hold" or any(i["guidance"] is None and i["figures"] and i["tense"] != "back" for i in items):
        check.append("Compare any guidance with what analysts expected. A raise that is smaller than hoped can still sink the stock.")
    if not guid:
        check.append("No change to the company's own outlook was found. Look for its guidance in the earnings release or call.")
    if head and any(r["bucket"] in ("costs", "trade") for r in head):
        check.append("Costs or tariffs are a headwind: check whether gross margin held up, which shows if the company can pass them on in prices.")
    if one_offs:
        check.append("Strip the one-offs out before judging the trend: ask what profit looks like without them.")
    if soft_fwd:
        check.append("Treat hedged statements as hopes. Firm numbers with a date are worth far more.")

    return {"available": True, "disclaimer": disclaimer, "reference_year": ref,
            "counts": {"sentences": len(sents), "ahead": sum(1 for i in items if i["tense"] in ("ahead", "both")), "back": sum(1 for i in items if i["tense"] in ("back", "both"))},
            "looking_back": [_out(i, tone(i)) for i in back], "looking_ahead": [_out(i, tone(i)) for i in ahead],
            "drivers": drivers, "one_offs": [{"text": _short(i["text"]), "figures": i["figures"]} for i in one_offs],
            "read": {"lean": lean, "points": points, "check": check[:4]}}


def _fmt_money(v, sym="$"):
    a = abs(v)
    t = f"{a / 1e12:.1f}T" if a >= 1e12 else f"{a / 1e9:.1f}B" if a >= 1e9 else f"{a / 1e6:.0f}M" if a >= 1e6 else f"{a:,.2f}" if a < 100 else f"{a:,.0f}"
    return sym + t


def _out(i, tone):
    return {"text": _short(i["text"]), "tone": tone, "theme": i["label"], "figures": i["figures"], "guidance": i["guidance"],
            "firm": i["firm"], "strong": i["strong"], "horizon": i["horizon"], "leading": i["leading"], "implied": i.get("implied")}


def analyze_text(text):
    text = (text or "").strip()[:MAX_CHARS]
    if len(text) < 200:
        raise ValueError("Give Tick a few paragraphs to read first.")
    return analyze([p for p in re.split(r"\n+", text) if p.strip()])
