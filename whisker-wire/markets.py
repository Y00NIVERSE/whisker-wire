"""Per-market configuration: news sources, index strip, screener spec and official filing portals.

The United States is the default market and keeps its sources in engine.py. Every other market is
described here. Adding a market means adding one entry to MARKETS; nothing else needs to change.
"""
import re
import urllib.parse

# (hl, gl, ceid) locale triples for Google News. Japan has no English edition, so it borrows the US one.
_US = ("en-US", "US", "US:en")


def gn_url(query, loc):
    hl, gl, ceid = loc
    return f"https://news.google.com/rss/search?hl={hl}&gl={gl}&ceid={ceid}&q=" + urllib.parse.quote(query)


def _feed(id_, name, kind, url):
    return {"id": id_, "name": name, "kind": kind, "tier": "niche", "url": url}


def _queries(prefix, loc, rows):
    return [{"id": f"{prefix}-gn{i}", "name": f"Search: {label}", "kind": "Search", "tier": "niche", "gn": True,
             "url": gn_url(q, loc)} for i, (label, q) in enumerate(rows)]


def _market(mid, name, short, loc, feeds, queries, strip, screen, filings, note=""):
    return {"id": mid, "name": name, "short": short, "loc": loc, "note": note,
            "sources": feeds + _queries(mid, loc, queries), "strip": strip, "screen": screen, "filings": filings}


_HK, _SG, _GB, _IN, _AU, _CA, _IE = ("en-HK", "HK", "HK:en"), ("en-SG", "SG", "SG:en"), ("en-GB", "GB", "GB:en"), \
    ("en-IN", "IN", "IN:en"), ("en-AU", "AU", "AU:en"), ("en-CA", "CA", "CA:en"), ("en-IE", "IE", "IE:en")

MARKETS = {
    "us": {"id": "us", "name": "United States", "short": "US", "loc": _US, "sources": None, "strip": None, "screen": None,
           "note": "", "filings": []},

    "cn": _market(
        "cn", "China", "CN", _US,
        [_feed("cn-scmp", "South China Morning Post", "Mainstream", "https://www.scmp.com/rss/4/feed"),
         _feed("cn-cgtn", "CGTN Business", "State media", "https://www.cgtn.com/subscribe/rss/section/business.xml")],
        [("A-shares and indexes", '("A-shares" OR "Shanghai Composite" OR "CSI 300" OR "China stocks") when:2d'),
         ("regulator actions", '(CSRC OR "China securities regulator") (investigation OR probe OR fraud OR delisting OR fine) when:3d'),
         ("movers and ratings", '("Chinese stocks" OR "China stocks") (upgrade OR downgrade OR rally OR plunge OR surge) when:2d'),
         ("STAR Market and ChiNext", '("STAR Market" OR ChiNext OR Shenzhen) shares when:2d')],
        [("000001.SS", "Shanghai Comp"), ("399001.SZ", "Shenzhen"), ("000300.SS", "CSI 300"), ("^HSCE", "HK China Ent."),
         ("KWEB", "China internet ETF"), ("CNY=X", "USD/CNY")],
        {"exchanges": ["SHH", "SHZ"], "currencies": ["CNY"]},
        [{"name": "CNINFO (official disclosures)", "url": "http://www.cninfo.com.cn/new/index", "what": "Announcements from Shanghai and Shenzhen listed companies"},
         {"name": "Shanghai Stock Exchange", "url": "https://english.sse.com.cn/", "what": "Listing notices and company announcements"},
         {"name": "Shenzhen Stock Exchange", "url": "https://www.szse.cn/English/", "what": "Listing notices and company announcements"}],
        note="China's state media outlets are labelled so you can weigh them. Toggle them off under Sources."),

    "hk": _market(
        "hk", "Hong Kong", "HK", _HK,
        [_feed("hk-scmp", "South China Morning Post", "Mainstream", "https://www.scmp.com/rss/92/feed"),
         _feed("hk-scmpc", "SCMP China economy", "Mainstream", "https://www.scmp.com/rss/4/feed")],
        [("Hang Seng and HKEX", '("Hang Seng" OR "Hong Kong stocks" OR HKEX) when:2d'),
         ("profit alerts and buybacks", '("profit warning" OR "positive profit alert" OR "share buyback" OR "director bought") Hong Kong shares when:3d'),
         ("tech and property names", '(Tencent OR Alibaba OR Meituan OR "Hang Seng Tech" OR "Hong Kong property") shares when:2d'),
         ("deals and placements", '("Hong Kong-listed" OR "H-shares") (takeover OR placement OR privatisation OR "share sale") when:3d')],
        [("^HSI", "Hang Seng"), ("^HSCE", "China Enterprises"), ("0700.HK", "Tencent"), ("9988.HK", "Alibaba"),
         ("0005.HK", "HSBC"), ("HKD=X", "USD/HKD")],
        {"exchanges": ["HKG"], "currencies": ["HKD"]},
        [{"name": "HKEXnews", "url": "https://www.hkexnews.hk/", "what": "Every listed company's announcements"},
         {"name": "Disclosure of Interests", "url": "https://www.hkexnews.hk/di/", "what": "Director and substantial shareholder dealings"}]),

    "sg": _market(
        "sg", "Singapore", "SG", _SG,
        [_feed("sg-st", "The Straits Times", "Mainstream", "https://www.straitstimes.com/news/business/rss.xml"),
         _feed("sg-bt", "The Business Times", "Mainstream", "https://www.businesstimes.com.sg/rss/companies-markets"),
         _feed("sg-cna", "Channel NewsAsia", "Mainstream", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936"),
         _feed("sg-edge", "The Edge Singapore", "Analyst", "https://www.theedgesingapore.com/rss.xml")],
        [("STI and SGX", '("Straits Times Index" OR SGX OR "Singapore stocks") when:2d'),
         ("banks and telcos", '(DBS OR OCBC OR UOB OR Singtel OR "Singapore Exchange") shares when:2d'),
         ("S-REITs", '("Singapore REIT" OR S-REIT OR "Singapore REITs") when:3d'),
         ("deals and shareholders", '(SGX OR Singapore-listed) (takeover OR "profit warning" OR buyback OR "substantial shareholder") when:3d')],
        [("^STI", "Straits Times"), ("D05.SI", "DBS"), ("O39.SI", "OCBC"), ("U11.SI", "UOB"), ("Z74.SI", "Singtel"),
         ("SGD=X", "USD/SGD")],
        {"exchanges": ["SES"], "currencies": ["SGD"]},
        [{"name": "SGX company announcements", "url": "https://www.sgx.com/securities/company-announcements", "what": "Filings and notices from every SGX issuer"},
         {"name": "MAS Financial Institutions Directory", "url": "https://eservices.mas.gov.sg/fid", "what": "Check whether a firm is licensed"}]),

    "uk": _market(
        "uk", "United Kingdom", "UK", _GB,
        [_feed("uk-bbc", "BBC News Business", "Mainstream", "https://feeds.bbci.co.uk/news/business/rss.xml"),
         _feed("uk-guardian", "The Guardian Business", "Mainstream", "https://www.theguardian.com/uk/business/rss"),
         _feed("uk-sky", "Sky News Business", "Mainstream", "https://feeds.skynews.com/feeds/rss/business.xml"),
         _feed("uk-tim", "This is Money", "Analyst", "https://www.thisismoney.co.uk/money/index.rss"),
         _feed("uk-proactive", "Proactive Investors UK", "Analyst", "https://www.proactiveinvestors.co.uk/rss/news.xml")],
        [("FTSE indexes", '("FTSE 100" OR "FTSE 250" OR "London stocks" OR "London Stock Exchange") when:2d'),
         ("RNS alerts", '(RNS OR "regulatory news") ("profit warning" OR takeover OR buyback OR "director dealing") when:3d'),
         ("director dealings", '("director buys" OR "director bought" OR "director dealings" OR "insider buying") shares FTSE when:3d'),
         ("bids and offers", '("takeover bid" OR "possible offer" OR "recommended offer" OR "Rule 2.7") UK when:3d')],
        [("^FTSE", "FTSE 100"), ("^FTMC", "FTSE 250"), ("HSBA.L", "HSBC"), ("SHEL.L", "Shell"), ("AZN.L", "AstraZeneca"),
         ("GBPUSD=X", "GBP/USD")],
        {"exchanges": ["LSE"], "currencies": ["GBp", "GBP"]},
        [{"name": "London Stock Exchange news (RNS)", "url": "https://www.londonstockexchange.com/news?tab=news-explorer", "what": "Regulatory news from every listed company"},
         {"name": "FCA National Storage Mechanism", "url": "https://data.fca.org.uk/#/nsm/nationalstoragemechanism", "what": "Official filings, including director share dealings"}],
        note="London prices are quoted in pence (p)."),

    "jp": _market(
        "jp", "Japan", "JP", _US,
        [_feed("jp-jt", "The Japan Times", "Mainstream", "https://www.japantimes.co.jp/feed/")],
        [("Nikkei and TOPIX", '("Nikkei 225" OR "Tokyo stocks" OR TOPIX OR "Japanese stocks") when:2d'),
         ("deals and activists", '(Japan OR Japanese) (buyback OR "tender offer" OR takeover OR activist) shares when:3d'),
         ("big names", '(Toyota OR SoftBank OR Sony OR "Bank of Japan" OR Nintendo) shares when:2d')],
        [("^N225", "Nikkei 225"), ("7203.T", "Toyota"), ("9984.T", "SoftBank Group"), ("8306.T", "MUFG"),
         ("JPY=X", "USD/JPY")],
        {"exchanges": ["JPX"], "currencies": ["JPY"]},
        [{"name": "TDnet (timely disclosure)", "url": "https://www.release.tdnet.info/inbs/I_main_00.html", "what": "Company disclosures as they are released"},
         {"name": "EDINET", "url": "https://disclosure2.edinet-fsa.go.jp/", "what": "Official securities reports and large-holding filings"}]),

    "in": _market(
        "in", "India", "IN", _IN,
        [_feed("in-et", "The Economic Times", "Mainstream", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
         _feed("in-mint", "Mint", "Mainstream", "https://www.livemint.com/rss/markets"),
         _feed("in-bs", "Business Standard", "Mainstream", "https://www.business-standard.com/rss/markets-106.rss"),
         _feed("in-bl", "The Hindu BusinessLine", "Mainstream", "https://www.thehindubusinessline.com/markets/feeder/default.rss")],
        [("Sensex and Nifty", '("Sensex" OR "Nifty" OR "Indian stocks") when:2d'),
         ("SEBI actions", '(SEBI) (order OR probe OR penalty OR "insider trading") when:3d'),
         ("bulk deals and promoters", '("bulk deal" OR "block deal" OR promoter OR "open offer") (Sensex OR Nifty OR NSE) when:3d'),
         ("stocks to watch", '("stocks to watch" OR "stock recommendations" OR "buy or sell") India when:2d')],
        [("^BSESN", "Sensex"), ("^NSEI", "Nifty 50"), ("RELIANCE.NS", "Reliance"), ("HDFCBANK.NS", "HDFC Bank"),
         ("INR=X", "USD/INR")],
        {"exchanges": ["NSI"], "currencies": ["INR"]},
        [{"name": "NSE corporate announcements", "url": "https://www.nseindia.com/companies-listing/corporate-filings-announcements", "what": "Company filings on the National Stock Exchange"},
         {"name": "BSE corporate announcements", "url": "https://www.bseindia.com/corporates/ann.html", "what": "Company filings on the Bombay Stock Exchange"},
         {"name": "SEBI", "url": "https://www.sebi.gov.in/", "what": "Regulator orders and insider-trading disclosures"}]),

    "au": _market(
        "au", "Australia", "AU", _AU,
        [_feed("au-smh", "The Sydney Morning Herald", "Mainstream", "https://www.smh.com.au/rss/business.xml"),
         _feed("au-fool", "The Motley Fool Australia", "Analyst", "https://www.fool.com.au/feed/")],
        [("ASX 200", '("ASX 200" OR "Australian shares" OR "ASX") stocks when:2d'),
         ("halts and deals", '(ASX) (takeover OR "trading halt" OR "profit warning" OR buyback OR "director buys") when:3d'),
         ("big names", '(BHP OR CBA OR "Rio Tinto" OR CSL OR Woolworths) shares when:2d')],
        [("^AXJO", "ASX 200"), ("BHP.AX", "BHP"), ("CBA.AX", "CommBank"), ("CSL.AX", "CSL"), ("AUDUSD=X", "AUD/USD")],
        {"exchanges": ["ASX"], "currencies": ["AUD"]},
        [{"name": "ASX announcements", "url": "https://www.asx.com.au/markets/trade-our-cash-market/announcements", "what": "Company announcements, including director interest notices"}]),

    "ca": _market(
        "ca", "Canada", "CA", _CA,
        [_feed("ca-fp", "Financial Post", "Mainstream", "https://financialpost.com/feed"),
         _feed("ca-cbc", "CBC Business", "Mainstream", "https://www.cbc.ca/webfeed/rss/rss-business"),
         _feed("ca-gm", "The Globe and Mail", "Mainstream", "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/business/")],
        [("TSX", '("TSX" OR "S&P/TSX" OR "Canadian stocks") when:2d'),
         ("deals and insiders", '(TSX) (takeover OR "insider buying" OR buyback OR guidance) when:3d'),
         ("big names", '(Shopify OR "Royal Bank" OR Suncor OR "Canadian Natural" OR Enbridge) shares when:2d')],
        [("^GSPTSE", "S&P/TSX"), ("SHOP.TO", "Shopify"), ("RY.TO", "Royal Bank"), ("CAD=X", "USD/CAD")],
        {"exchanges": ["TOR"], "currencies": ["CAD"]},
        [{"name": "SEDAR+", "url": "https://www.sedarplus.ca/", "what": "Canada's official filing system, including insider reports"}]),

    "eu": _market(
        "eu", "Europe", "EU", _IE,
        [_feed("eu-euronews", "Euronews Business", "Mainstream", "https://www.euronews.com/rss?level=theme&name=business"),
         _feed("eu-f24", "France 24 Business", "Mainstream", "https://www.france24.com/en/business/rss"),
         _feed("eu-dw", "DW Business", "Mainstream", "https://rss.dw.com/xml/rss-en-bus")],
        [("European indexes", '("STOXX 600" OR DAX OR "CAC 40" OR "European stocks") when:2d'),
         ("warnings and deals", '(Europe OR German OR French) ("profit warning" OR takeover OR buyback OR "guidance cut") shares when:3d'),
         ("ECB", '(ECB OR "European Central Bank") (rate OR decision OR inflation) when:2d'),
         ("big names", '(ASML OR SAP OR LVMH OR Siemens OR Nestle) shares when:2d')],
        [("^STOXX50E", "Euro Stoxx 50"), ("^GDAXI", "DAX"), ("^FCHI", "CAC 40"), ("ASML.AS", "ASML"), ("EURUSD=X", "EUR/USD")],
        {"exchanges": ["GER", "PAR", "AMS", "MIL", "MCE", "HEL", "STO", "EBS"], "currencies": ["EUR", "CHF", "SEK", "DKK", "NOK"]},
        [{"name": "ESMA", "url": "https://www.esma.europa.eu/", "what": "EU regulator; links to each country's official filings"},
         {"name": "Euronext announcements", "url": "https://live.euronext.com/en/products/equities/company-news", "what": "Company news from Amsterdam, Paris, Brussels, Milan and more"},
         {"name": "Deutsche Boerse", "url": "https://www.boerse-frankfurt.de/en/news", "what": "German exchange news and company announcements"}],
        note="Europe combines several exchanges, and some US names also trade there."),
}

# Google News searches are loose: "Hong Kong shares" also returns a London trust's buyback notice. Stories that come
# from a search (not from a regional outlet) must mention something local in the headline to be kept.
_KEYWORDS = {
    "cn": r"china|chinese|beijing|shanghai|shenzhen|hong kong|hang seng|yuan|renminbi|pboc|csrc|a-shares?|star market|chinext"
          r"|alibaba|tencent|baidu|byd|pdd|jd\.com|xiaomi|catl|moutai|weibo|kweb",
    "hk": r"hong kong|hkex|hang seng|hk\$|h-shares?|\d{4}\.hk|tencent|alibaba|meituan|xiaomi|jd\.com|byd|\baia\b|hsbc|hkma",
    "sg": r"singapore|sgx|straits times|\bsti\b|\bdbs\b|ocbc|\buob\b|singtel|reits?\b|s\$|temasek|capitaland|keppel|sembcorp|\.si\b",
    "uk": r"\buk\b|britain|british|london|ftse|\blse\b|sterling|bank of england|\brns\b|\bplc\b|£|\.l\b|barclays|lloyds|natwest"
          r"|hsbc|shell|\bbp\b|astrazeneca|unilever|glencore|rio tinto|vodafone|tesco|\bpence\b",
    "jp": r"japan|japanese|tokyo|nikkei|topix|\byen\b|\bboj\b|bank of japan|toyota|sony|softbank|nintendo|mitsubishi|mitsui"
          r"|sumitomo|honda|nissan|fast retailing|tdnet",
    "in": r"india|indian|sensex|nifty|\bnse\b|\bbse\b|sebi|\brbi\b|rupee|mumbai|reliance|\btata\b|infosys|hdfc|icici|adani|wipro|₹|crore|lakh",
    "au": r"australia|australian|\basx\b|sydney|melbourne|\brba\b|\baud\b|a\$|\bbhp\b|\bcba\b|commonwealth bank|\bcsl\b|woolworths"
          r"|wesfarmers|rio tinto|fortescue|telstra|\banz\b|\bnab\b|westpac",
    "ca": r"canada|canadian|\btsx\b|toronto|bank of canada|\bcad\b|c\$|shopify|royal bank|suncor|enbridge|cenovus|td bank"
          r"|scotiabank|\bbmo\b|cibc|manulife|nutrien",
    "eu": r"europe|european|eurozone|euro area|\becb\b|stoxx|\bdax\b|\bcac\b|ftse mib|ibex|germany|german|france|french|ital(y|ian)"
          r"|spain|spanish|netherlands|dutch|switzerland|swiss|sweden|swedish|asml|\bsap\b|lvmh|siemens|nestl|novo nordisk|airbus|volkswagen|€",
}
for _mid, _m in MARKETS.items():
    _m["kw"] = re.compile(_KEYWORDS[_mid], re.I) if _mid in _KEYWORDS else None

DEFAULT_MARKET = "us"


def market_list():
    """What the browser needs to draw the selector and the filings panel."""
    return [{"id": m["id"], "name": m["name"], "short": m["short"], "filings": m["filings"], "note": m["note"],
             "has_screen": m["id"] == "us" or bool(m["screen"])} for m in MARKETS.values()]


def valid_market(mid):
    return mid if mid in MARKETS else DEFAULT_MARKET
