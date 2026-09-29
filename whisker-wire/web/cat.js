// Tick's brain: reads an article and decides what a newer trader must not miss.
// Pure functions, no DOM. Signal patterns come from the server so the wire and the reader agree.

export const CATS = {
  bull:  { label: "Bullish clue", short: "Bullish" },
  bear:  { label: "Red flag",     short: "Red flag" },
  key:   { label: "Key number",   short: "Number" },
  catch: { label: "Catalyst",     short: "Next" },
  fine:  { label: "Fine print",   short: "Fine print" },
};

const GLOSSARY = {
  "P/E": "Price divided by yearly profit per share. Lower can mean cheaper, but only compared with similar companies.",
  "forward P/E": "P/E using next year's expected profit instead of last year's actual profit.",
  "EPS": "Earnings per share: the company's profit divided by its number of shares.",
  "guidance": "The company's own forecast for coming quarters. Markets react to it more than to past results.",
  "market cap": "Share price times number of shares: what the whole company is worth on the stock market.",
  "short interest": "How many shares are borrowed and sold by traders betting the price will fall.",
  "short squeeze": "Short sellers are forced to buy back shares as the price rises, which pushes it up even faster.",
  "buyback": "The company buys its own shares, so fewer remain and each one owns a bigger slice.",
  "dilution": "Issuing new shares, which shrinks every existing shareholder's slice.",
  "dividend yield": "Yearly dividend divided by share price. 3% means $3 a year per $100 invested.",
  "13F": "A quarterly report where big funds list what they own. It is up to 45 days old when published.",
  "Form 4": "The filing where insiders report their own trades, due within two business days.",
  "13D": "A filing when someone crosses 5% ownership and may want to influence the company.",
  "insider buying": "Executives or directors buying stock with their own money, reported publicly.",
  "price target": "An analyst's guess for where the stock will trade in about a year.",
  "basis points": "One hundredth of a percent. 25 basis points is 0.25%.",
  "yield curve": "Interest rates for short versus long loans. An inverted curve has often come before recessions.",
  "float": "Shares actually available to trade. A small float means big price swings.",
  "volatility": "How wildly the price swings. High volatility means more risk in both directions.",
  "VIX": "The market's fear gauge. Above 30 means investors are nervous.",
  "ETF": "A basket of stocks that trades like a single stock.",
  "book value": "What the company would own minus what it owes, on paper. Price below book can signal a bargain or a problem.",
  "free cash flow": "Cash left after running the business and investing in it. Hard to fake, so traders trust it.",
  "EBITDA": "Profit before interest, taxes and some accounting charges. A rough measure of operating strength.",
  "operating margin": "Share of each sales dollar left as profit from operations.",
  "catalyst": "An event that could move the price: earnings, a decision, a launch, a deal.",
  "going concern": "An auditor's warning that the company may not survive the next 12 months.",
  "lock-up": "A period after an IPO when insiders cannot sell. Selling pressure often follows when it ends.",
  "bear market": "A drop of 20% or more from a recent high.",
  "rally": "A sustained rise in prices.",
  "headwinds": "Conditions that make the business harder.",
  "tailwinds": "Conditions that help the business.",
  "consensus": "The average of what analysts expect. Beating consensus is what moves the price.",
  "activist investor": "A shareholder who buys a big stake to push the company to change.",
  "Fwd P/E": "Forward P/E: price divided by next year's expected profit per share. Lower can mean cheaper.",
  "P/B": "Price divided by book value (what the company owns minus what it owes). Under about 1.5 can mean a bargain or a problem.",
  "Mkt cap": "Market cap: share price times number of shares, the stock market's price tag for the whole company.",
  "trailing P/E": "P/E using the last 12 months of actual profit.",
  "52-week high": "The highest price in the past year. Being far below it means the stock has fallen a lot.",
  "200-day average": "The average price over about 10 months. A stock far below it is in a downtrend.",
  "Schedule 13D": "A filing when someone crosses 5% ownership and may want to influence the company.",
  "short seller": "Someone who bets the price will fall by selling borrowed shares and buying them back cheaper.",
  "premarket": "Trading before the regular 9:30am Eastern open. Thin, so prices jump around.",
  "restatement": "A company correcting its past financial results. A serious red flag about the numbers.",
  "share repurchase": "The company buying its own shares (a buyback), so each remaining share owns more.",
  "upgrade": "An analyst raising their rating on a stock.",
  "downgrade": "An analyst lowering their rating on a stock.",
  "open-market": "Bought or sold on the regular exchange at the going price, not through a company grant.",
  "analysts": "Professionals at banks and research firms who rate stocks. Ratings run from 1 (strong buy) to 5 (sell).",
};
export const GLOSSARY_TERMS = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);
export const glossaryDef = (t) => GLOSSARY[Object.keys(GLOSSARY).find((k) => k.toLowerCase() === t.toLowerCase())] || "";
const GLOSS_RX = new RegExp("(?<![\\w/])(" + GLOSSARY_TERMS.map((t) => t.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")).join("|") + ")(?![\\w/])", "gi");

const ABBR = /\b(?:U\.S|U\.K|Inc|Corp|Co|Ltd|Mr|Mrs|Ms|Dr|St|No|vs|approx|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|a\.m|p\.m)\./g;

export function splitSentences(p) {
  const guarded = p.replace(ABBR, (m) => m.slice(0, -1) + "\u0001");
  const out = guarded.split(/(?<=[.!?]["')\]]?)\s+(?=["“(]?[A-Z0-9$])/);
  return out.map((s) => s.replace(/\u0001/g, ".").trim()).filter(Boolean);
}

const MONEY = /\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|t|bn|mm|million|billion|trillion|thousand)?\b|\bUS\$\s?\d[\d,.]*\s?(?:k|m|b|million|billion)?/gi;
const PCT = /\d+(?:\.\d+)?\s?(?:%|percent(?!age))/gi;
const FINWORD = /\b(?:revenue|sales|profit|earnings|eps|guidance|margin|cash|debt|forecast|target|expects?|estimates?|shares|stake|income|loss|backlog|orders|dividend|buyback|valuation)\b/i;
const FORWARD = /\b(?:expects?|plans? to|will|outlook|guidance|next (?:quarter|year)|by (?:the )?end of|later this|scheduled|upcoming|launch(?:es|ing)?|approval (?:decision|date)|target date|announce)\b/i;
const HEDGE = /\b(?:may|might|could|subject to|uncertain\w*|no assurance|if approved|pending|risks?|cannot guarantee|forward-looking)\b/i;
const IMPORTANT = /\b(?:record|first time|lowest since|highest since|unexpected|surprise|despite|however|warned|abrupt\w*|sharply|plunge\w*|soar\w*|jump\w*|tumbl\w*|surg\w*)\b/i;
const BOILER = /\b(?:subscribe|sign up|newsletter|click here|follow us|read more|all rights reserved|copyright|advertisement|privacy policy|not investment advice)\b/i;

const count = (rx, s) => (s.match(rx) || []).length;

const KEY_NOTES = [
  "Numbers are the facts; the rest is opinion. Compare this one with last year and with what analysts expected.",
  "A percentage only means something next to its baseline. Percent of what, and compared with when?",
  "Ask if this figure is big for this company. $50 million is huge for a small firm and a rounding error for a giant.",
];
const CATCH_NOTE = "This is about what happens next. Note the date: prices move on scheduled events, and the gap between expectation and result is what pays.";
const FINE_NOTE = "Hedging language. The company is protecting itself. Ask what happens to the stock if this goes the wrong way.";

export function compileSignals(list) {
  return list.map((s) => ({ ...s, rx: new RegExp(s.pattern, "i") }));
}

function scoreSentence(text, idx, isFirstPara, sigs) {
  if (BOILER.test(text) || text.length < 30) return { score: -9, cat: null };
  let score = 0, cat = null, note = "", sigLabel = "", sigId = "", dir = "";
  let best = 0;
  for (const s of sigs) {
    if (s.rx.test(text)) {
      score += s.weight;
      if (s.weight > best) { best = s.weight; cat = s.cat; note = s.note; sigLabel = s.label; sigId = s.id; dir = s.dir; }
    }
  }
  const money = count(MONEY, text), pct = count(PCT, text);
  const nums = Math.min(3, money + pct);
  if (nums) {
    score += nums;
    if (FINWORD.test(text)) score += 2;
    if (!cat && !FORWARD.test(text)) { cat = "key"; note = KEY_NOTES[pct && !money ? 1 : money >= 2 ? 2 : 0]; }
  }
  if (FORWARD.test(text)) { score += 1; if (!cat) { cat = "catch"; note = CATCH_NOTE; } }
  if (IMPORTANT.test(text)) score += 1;
  if (HEDGE.test(text)) { score += 0.5; if (!cat && score >= 3) { cat = "fine"; note = FINE_NOTE; } }
  if (isFirstPara && idx === 0) score += 1;
  if (text.length > 320) score -= 1;
  return { score, cat, note, label: sigLabel || (cat ? CATS[cat].label : ""), sigId, dir };
}

export function findFacts(text) {
  const seen = new Set(), out = [];
  const rx = new RegExp(MONEY.source + "|" + PCT.source, "gi");
  for (const m of text.matchAll(rx)) {
    const v = m[0].replace(/\s+/g, " ").trim();
    if (seen.has(v.toLowerCase())) continue;
    seen.add(v.toLowerCase());
    const a = Math.max(0, m.index - 46), b = Math.min(text.length, m.index + v.length + 34);
    out.push({ value: v, context: (a ? "…" : "") + text.slice(a, b).trim() + (b < text.length ? "…" : "") });
    if (out.length >= 6) break;
  }
  return out;
}

/** paragraphs: string[]; signals: server signal list (compiled here). */
export function analyze(paragraphs, rawSignals, opts = {}) {
  const sigs = compileSignals(rawSignals);
  const paras = paragraphs.map((p, pi) => splitSentences(p).map((text, si) => {
    const r = scoreSentence(text, si, pi === 0, sigs);
    return { text, ...r, hl: null };
  }));
  const flat = paras.flat();
  const total = flat.length;
  const want = Math.max(5, Math.min(12, Math.round(total * 0.25)));
  const ranked = flat.filter((s) => s.cat && s.score >= 3).sort((a, b) => b.score - a.score).slice(0, want);
  ranked.forEach((s) => { s.hl = true; });
  let n = 0;
  flat.forEach((s) => { if (s.hl) s.n = n++; });

  const hls = flat.filter((s) => s.hl);
  const bull = hls.filter((s) => s.dir === "bull" || s.cat === "bull").length;
  const bear = hls.filter((s) => s.dir === "bear" || s.cat === "bear").length;
  const lean = !hls.length ? "none" : bull && bear ? "mixed" : bull > bear ? "bull" : bear > bull ? "bear" : "neutral";

  const takeCount = Math.min(3, hls.length);
  const take = [...hls].sort((a, b) => b.score - a.score).slice(0, takeCount).sort((a, b) => a.n - b.n)
    .map((s) => ({ text: s.text.length > 220 ? s.text.slice(0, 217) + "…" : s.text, cat: s.cat, n: s.n }));

  const fullText = paragraphs.join(" ");
  const glossary = [];
  const seenG = new Set();
  for (const m of fullText.matchAll(GLOSS_RX)) {
    const k = m[1].toLowerCase();
    if (!seenG.has(k)) { seenG.add(k); glossary.push(m[1]); }
  }
  return { paras, hls, lean, bull, bear, take, facts: findFacts(fullText), glossary, sentences: total };
}

/** Splits plain text into glossary-term segments so the UI can wrap them without innerHTML. */
export function glossSegments(text, seen) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(GLOSS_RX)) {
    const k = m[1].toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    if (m.index > last) out.push({ t: text.slice(last, m.index) });
    out.push({ t: m[1], def: glossaryDef(m[1]) });
    last = m.index + m[1].length;
  }
  if (last < text.length) out.push({ t: text.slice(last) });
  return out;
}

export const LEAN_TEXT = {
  bull: "Leans bullish", bear: "Leans bearish", mixed: "Mixed: good and bad news together",
  neutral: "No clear lean", none: "Nothing stood out",
};
