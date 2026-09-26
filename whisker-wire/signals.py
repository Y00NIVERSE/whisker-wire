"""Signal definitions shared by the server (wire tagging) and the browser (Tick's highlights).

Patterns are written to be valid in both Python `re` and JavaScript RegExp (case-insensitive).
`dir` is the direction of the news for the stock: bull, bear, or flag (needs a human look).
`cat` is the category Tick uses for the highlight: bull, bear, key, catch, fine.
`note` is the plain-English explanation shown to beginners.
"""

SIGNALS = [
    # ---- bullish clues
    {"id": "insider-buy", "label": "Insider buying", "dir": "bull", "cat": "bull", "weight": 5,
     "pattern": r"insider (?:buy|purchas)|(?:ceo|cfo|director|chairman|president|founder)s? (?:buys?|bought|purchas\w+|snaps? up|scoops? up)|(?:buys?|bought|purchased) \$?[\d.,]+ ?(?:k|m|million|thousand)? (?:of|worth of) (?:\w+ )?(?:shares|stock)",
     "note": "Insiders spending their own cash is one of the few signals with a track record. Check the size, and whether several insiders bought together."},
    {"id": "guidance-up", "label": "Guidance raised", "dir": "bull", "cat": "bull", "weight": 4,
     "pattern": r"rais(?:es|ed|ing) (?:its |their |full[- ]year |annual |fy ?\d* )*(?:guidance|outlook|forecast)|(?:guidance|outlook|forecast) (?:raised|boosted|lifted)|lifts? (?:its )?(?:guidance|outlook|forecast)",
     "note": "Management knows the business best. Raising the forecast usually means orders or margins are better than they planned."},
    {"id": "beat", "label": "Earnings beat", "dir": "bull", "cat": "bull", "weight": 3,
     "pattern": r"(?:beats?|tops?|topped|exceeds?|surpass\w*) (?:analyst |wall street |consensus )?(?:estimates|expectations|forecasts|views)|earnings beat|better[- ]than[- ]expected",
     "note": "Beating estimates matters, but the stock moves on the next quarter's outlook more than on this quarter's beat."},
    {"id": "upgrade", "label": "Analyst upgrade", "dir": "bull", "cat": "bull", "weight": 3,
     "pattern": r"upgrad(?:es|ed|ing)|(?:raises?|lifts?|boosts?|hikes?) (?:its )?(?:price )?target|price target (?:raised|lifted|boosted)",
     "note": "Analysts often move after the stock has moved. Useful as confirmation, weak as a first signal."},
    {"id": "buyback", "label": "Buyback", "dir": "bull", "cat": "bull", "weight": 3,
     "pattern": r"buy ?backs?|repurchase (?:program|plan|authori\w+)|(?:share|stock) repurchase|repurchases? (?:up to )?\$",
     "note": "A buyback shrinks the share count, which lifts earnings per share. Watch whether they actually buy or just announce."},
    {"id": "fda", "label": "Regulatory win", "dir": "bull", "cat": "catch", "weight": 4,
     "pattern": r"fda approv|approval (?:from|by) (?:the )?fda|phase (?:2|3|ii|iii) (?:trial )?(?:success|met|positive)|clearance from (?:the )?fda|breakthrough (?:therapy )?designation",
     "note": "Approvals are binary events. Small biotechs can jump or fall 50 percent on one, so size positions small."},
    {"id": "activist", "label": "Activist / big stake", "dir": "bull", "cat": "catch", "weight": 4,
     "pattern": r"activist|schedule 13d|13d filing|takes? (?:a )?(?:\d+(?:\.\d+)?% )?stake|(?:discloses?|reveals?|builds?) (?:a )?(?:new |\d+(?:\.\d+)?% )?stake|stake in",
     "note": "A large investor pushing for change can unlock value. Ask what they want (sale, breakup, buyback, new board)."},
    {"id": "takeover", "label": "Takeover / merger", "dir": "bull", "cat": "catch", "weight": 4,
     "pattern": r"to (?:be )?acquire[ds]?|takeover|buyout|tender offer|merger|agrees? to (?:buy|sell)|(?:receives?|rejects?) (?:an? )?(?:unsolicited )?(?:offer|bid)|go(?:es|ing)? private",
     "note": "Targets usually trade just under the offer price. The upside is capped; the risk is the deal collapsing."},
    {"id": "dividend", "label": "Dividend up", "dir": "bull", "cat": "bull", "weight": 2,
     "pattern": r"(?:raises?|hikes?|boosts?|increases?) (?:its |the |quarterly )*dividend|dividend (?:hike|increase|raise)|special dividend|initiates? (?:a )?dividend",
     "note": "Boards rarely raise dividends unless they trust future cash flow."},
    {"id": "contract", "label": "Big contract", "dir": "bull", "cat": "catch", "weight": 2,
     "pattern": r"(?:awarded|wins?|won|secures?|lands?) (?:an? )?(?:\$[\d.,]+ ?(?:million|billion|m|b) )?(?:multi-?year )?(?:contract|order|deal)",
     "note": "Compare the contract size to the company's yearly revenue. A big number on a small company is the interesting case."},
    {"id": "cheap", "label": "Valuation call", "dir": "bull", "cat": "key", "weight": 2,
     "pattern": r"undervalued|deeply discounted|discount to (?:fair|intrinsic|book|nav)|trading below (?:book|intrinsic|cash)|bargain|(?:cheap|cheapest) (?:stocks?|valuation)",
     "note": "Cheap can stay cheap. Ask what the market fears, and whether that fear is temporary."},

    # ---- bearish clues
    {"id": "guidance-down", "label": "Guidance cut", "dir": "bear", "cat": "bear", "weight": 4,
     "pattern": r"(?:cuts?|lowers?|slash(?:es)?|trims?|withdraws?|suspends?|warns? on) (?:its |their |full[- ]year |annual )*(?:guidance|outlook|forecast)|(?:guidance|outlook|forecast) (?:cut|lowered|slashed|withdrawn)|profit warning",
     "note": "Cuts are rarely one-offs. Companies tend to release bad news in stages."},
    {"id": "miss", "label": "Earnings miss", "dir": "bear", "cat": "bear", "weight": 3,
     "pattern": r"(?:miss(?:es|ed)?|falls? short of|lags?|trails?|disappoints?) (?:analyst |wall street |consensus )?(?:estimates|expectations|forecasts|views)|earnings miss|worse[- ]than[- ]expected",
     "note": "A miss combined with weak guidance is the dangerous pair."},
    {"id": "downgrade", "label": "Analyst downgrade", "dir": "bear", "cat": "bear", "weight": 3,
     "pattern": r"downgrad(?:es|ed|ing)|(?:cuts?|lowers?|slash(?:es)?) (?:its )?(?:price )?target|price target (?:cut|lowered|slashed)",
     "note": "Downgrades follow news, and can also trigger forced selling by funds with rating rules."},
    {"id": "probe", "label": "Investigation / lawsuit", "dir": "bear", "cat": "bear", "weight": 4,
     "pattern": r"sec (?:probe|investigation|subpoena|charges?|inquiry)|doj (?:probe|investigation)|class[- ]action|securities fraud|accounting (?:fraud|irregularit\w+)|whistleblower|subpoena|indict\w+|criminal (?:probe|charges)",
     "note": "Legal risk is hard to price. Look for words like 'restatement' or 'audit committee' which signal the numbers themselves may be wrong."},
    {"id": "short-report", "label": "Short-seller report", "dir": "bear", "cat": "bear", "weight": 4,
     "pattern": r"short[- ]seller|short report|hindenburg|muddy waters|citron|scorpion capital|spruce point|fuzzy panda|culper|bet(?:s|ting)? against",
     "note": "Short sellers profit if the stock falls, so read for evidence, not tone. Some reports are right, some are attacks."},
    {"id": "distress", "label": "Distress", "dir": "bear", "cat": "bear", "weight": 5,
     "pattern": r"bankrupt\w*|chapter (?:7|11)|going[- ]concern|(?:receives?|gets?|faces?|risks?|threat of|notice of|warning of|deficiency) (?:\w+ )?delist\w*|(?:to be|will be|been) delisted|default(?:s|ed)? on|covenant (?:breach|violation)|liquidity (?:crunch|concerns?)|debt restructuring|missed (?:an? )?(?:interest )?payment",
     "note": "Equity holders are last in line in a bankruptcy and often get nothing. This is the highest-risk category."},
    {"id": "halt", "label": "Trading halt", "dir": "flag", "cat": "bear", "weight": 4,
     "pattern": r"trading (?:halt|halted|suspended|suspension)|halted (?:for|pending)|circuit breaker",
     "note": "A halt means news is pending or something is wrong. Wait for the news before touching it."},
    {"id": "dilution", "label": "Dilution risk", "dir": "bear", "cat": "fine", "weight": 2,
     "pattern": r"public offering|secondary offering|dilut\w+|shelf registration|at-the-market|convertible notes?|prices? (?:an? )?(?:\$[\d.,]+ ?(?:million|billion|m|b) )?offering|raises? \$[\d.,]+ ?(?:million|billion|m|b)? (?:in|through) (?:an? )?(?:offering|placement)",
     "note": "New shares split the pie into more slices. Small companies that keep issuing stock rarely reward holders."},
    {"id": "exec-exit", "label": "Leadership exit", "dir": "flag", "cat": "fine", "weight": 3,
     "pattern": r"(?:ceo|cfo|coo|chief executive|chief financial officer|president)(?: [\w.'-]+){0,3} (?:abruptly )?(?:resign\w*|steps? down|stepped down|depart\w*|leaves|left the company|exits?|fired|ousted)|abrupt(?:ly)? (?:departure|resign\w+)",
     "note": "An abrupt CFO exit before earnings is a classic warning sign. A planned succession is usually fine."},
    {"id": "layoffs", "label": "Layoffs / restructuring", "dir": "flag", "cat": "fine", "weight": 2,
     "pattern": r"layoffs?|job cuts|(?:cuts?|eliminates?) \d[\d,]* (?:jobs|positions|roles)|restructur\w+|plant closure|store closures",
     "note": "Can be good (costs fall) or bad (demand fell). The guidance number tells you which."},
    {"id": "recall", "label": "Recall / outage", "dir": "bear", "cat": "bear", "weight": 2,
     "pattern": r"recall(?:s|ed)?|data breach|cyber ?attack|ransomware|outage|safety (?:probe|investigation)",
     "note": "One-off costs are usually priced quickly; look for repeat problems."},
    {"id": "insider-sell", "label": "Insider selling", "dir": "bear", "cat": "fine", "weight": 1,
     "pattern": r"insider sell|(?:ceo|cfo|director|chairman)s? (?:sells?|sold|dumps?|unloads?)",
     "note": "Insiders sell for many reasons (taxes, houses). Buying is far more informative than selling."},

    # ---- context (not directional)
    {"id": "macro", "label": "Macro", "dir": "flag", "cat": "catch", "weight": 2,
     "pattern": r"\bfed(?:eral reserve)?\b|rate (?:cut|hike|decision)|\bcpi\b|inflation|jobs report|nonfarm|tariffs?|treasury yields?|powell|fomc|recession",
     "note": "Macro news moves whole sectors at once. Rate-sensitive stocks (banks, homebuilders, small caps) react most."},
    {"id": "ipo", "label": "IPO / listing", "dir": "flag", "cat": "catch", "weight": 2,
     "pattern": r"\bipo\b|initial public offering|direct listing|spac (?:merger|deal)|lock-?up (?:expir\w+|ends?)",
     "note": "Lock-up expiries often bring selling pressure. Fresh IPOs are volatile, so wait for a few quarters of reports."},
]

# Publishers that make up the "top headlines". An item only they cover is not overlooked.
MAINSTREAM = {
    "cnbc", "marketwatch", "yahoofinance", "yahoo", "nasdaq", "reuters", "bloomberg", "wsj",
    "thewallstreetjournal", "financialtimes", "ft", "apnews", "associatedpress", "cnn",
    "cnnbusiness", "forbes", "barrons", "investorsbusinessdaily", "foxbusiness", "businessinsider",
}

# Words that look like tickers in parentheses but are not.
TICKER_STOP = {
    "CEO", "CFO", "COO", "CTO", "AI", "EPS", "FDA", "SEC", "IPO", "ETF", "USA", "GDP", "CPI", "FED",
    "US", "UK", "EU", "ESG", "LLC", "INC", "LTD", "PE", "PPI", "PCE", "OPEC", "NYSE", "DOJ", "FTC",
    "IMF", "ECB", "BOE", "BOJ", "FOMC", "AP", "UPDATE", "VIDEO", "WATCH", "LIVE", "NEW", "TOP",
    "BEST", "USD", "EUR", "GBP", "YTD", "QOQ", "YOY", "ETFS", "IRS", "NFL", "NBA", "TV", "IT", "ALL",
}
