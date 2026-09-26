// Whisker Wire front end. Feed text is untrusted: everything is built with DOM nodes and
// textContent, never innerHTML, and links are restricted to http(s).
import { analyze, glossSegments, CATS, LEAN_TEXT } from "./cat.js";

const BASE_TITLE = document.title;   // the full page title from the HTML, restored after alerts
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style") Object.assign(e.style, v);
    else if (k === "href") { if (/^https?:\/\//i.test(v)) { e.href = v; e.target = "_blank"; e.rel = "noopener noreferrer"; } }
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}

// replaceChildren stringifies undefined/false/0 into visible text, so filter first.
const fill = (node, ...kids) => node.replaceChildren(...kids.flat(Infinity).filter((c) => c != null && c !== false && c !== 0));

const store = {
  get(k, d) { try { const v = localStorage.getItem("ww:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ww:" + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

async function api(path) {
  const r = await fetch(path, { cache: "no-store" });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "Request failed");
  return j;
}

const CUR_SYM = { USD: "$", HKD: "HK$", SGD: "S$", GBP: "£", CNY: "¥", JPY: "¥", INR: "₹", AUD: "A$", CAD: "C$", EUR: "€", CHF: "CHF ", SEK: "kr ", DKK: "kr ", NOK: "kr " };
const fmt = {
  price: (n) => (n == null ? "n/a" : n >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 }) : n.toFixed(2)),
  pct: (n, d = 2) => (n == null ? "n/a" : (n > 0 ? "+" : "") + n.toFixed(d) + "%"),
  usd: (n) => (n >= 1e9 ? "$" + (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? "$" + (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? "$" + Math.round(n / 1e3) + "K" : "$" + Math.round(n)),
  x: (n, d = 1) => (n == null ? "n/a" : n.toFixed(d)),
  // Prices come in each market's own currency. London quotes in pence.
  px: (n, cur = "USD") => (n == null ? "n/a" : cur === "GBp" ? n.toLocaleString("en-GB", { maximumFractionDigits: 1 }) + "p" : (CUR_SYM[cur] ?? cur + " ") + fmt.price(n)),
  cap: (n, cur = "USD") => {
    if (!n) return "n/a";
    const sym = cur === "GBp" ? "£" : (CUR_SYM[cur] ?? cur + " ");
    return sym + (n >= 1e12 ? (n / 1e12).toFixed(1) + "T" : n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? (n / 1e6).toFixed(0) + "M" : Math.round(n).toLocaleString("en-US"));
  },
};
const ago = (ts) => {
  const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  return m < 1 ? "just now" : m < 60 ? m + "m ago" : m < 1440 ? Math.round(m / 60) + "h ago" : Math.round(m / 1440) + "d ago";
};
const dirClass = (n, invert) => (n == null || Math.abs(n) < 0.005 ? "flat" : (n > 0) !== !!invert ? "up" : "down");
async function postJson(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "Request failed");
  return j;
}

// Jargon gets a dotted underline and a plain-English tooltip everywhere, not only in the reader.
function glossNodes(text, seen = new Set()) {
  return glossSegments(text, seen).map((g) => (g.def
    ? h("span", { class: "gl", tabindex: 0, "data-def": g.def, "aria-label": g.t + ": " + g.def }, g.t) : g.t));
}
const tip = (cls, text, def) => h("span", { class: "tagx tip " + cls, tabindex: 0, "data-def": def, "aria-label": text + ": " + def }, text);

// Send people to the primary source: the company's own filings on SEC.gov.
const SEC_FORM = { "insider-buy": ["4", "Form 4 insider trades"], "insider-sell": ["4", "Form 4 insider trades"], activist: ["SCHEDULE 13D", "13D stake filings"] };
const SEC_8K = new Set(["guidance-up", "guidance-down", "beat", "miss", "distress", "exec-exit", "probe", "takeover", "buyback", "fda", "contract", "dividend", "dilution", "layoffs", "recall", "halt"]);
function secLink(s) {
  const tk = s.tickers[0];
  if (state.market !== "us" || !tk || !/^[A-Z]{1,5}$/.test(tk)) return null;
  const ids = s.signals.map((g) => g.id);
  const hit = ids.find((i) => SEC_FORM[i]);
  const [form, label] = hit ? SEC_FORM[hit] : ids.some((i) => SEC_8K.has(i)) ? ["8-K", "8-K company announcements"] : [null];
  if (!form) return null;
  return { label: "SEC.gov: " + label, url: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${encodeURIComponent(tk)}&type=${encodeURIComponent(form)}&dateb=&owner=include&count=20` };
}

const isGoogle = (u) => { try { return new URL(u).hostname === "news.google.com"; } catch { return false; } };

/* ------------------------------------------------------------ state */
const PER = { wire: 10, radar: 5, buys: 10, stakes: 10 };   // items per page: short pages instead of one long scroll
const state = {
  view: "wire", filter: "all", ticker: null,
  market: "us", markets: [], page: { wire: 1, radar: 1, buys: 1, stakes: 1 },
  watch: new Set(store.get("watch", [])),
  off: new Set(store.get("kindsOff", [])), allKinds: new Set(),   // source types switched off; new types default to on
  feed: null, picks: null, radarList: "all", seen: null, openSrcs: new Set(), filings: null,
  signals: null, showSells: false, openCalc: new Set(),
};
const kindOn = (k) => !state.off.has(k);
const marketInfo = () => state.markets.find((m) => m.id === state.market) || { id: "us", name: "United States", filings: [], note: "" };

/* ------------------------------------------------------------ Tick drawings */
function mountTicks() {
  const tpl = $("#tick-tpl");
  $$("[data-tick]").forEach((n) => { if (!n.firstChild) n.append(tpl.content.cloneNode(true)); });
}

/* ------------------------------------------------------------ theme */
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
applyTheme(store.get("theme", null));
$("#theme").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next); store.set("theme", next);
});

/* ------------------------------------------------------------ tabs */
function setView(v) {
  state.view = v;
  $$(".tab[data-view]").forEach((t) => { const on = t.dataset.view === v; t.classList.toggle("is-on", on); t.setAttribute("aria-pressed", on); });
  $$(".view").forEach((s) => s.classList.toggle("is-on", s.id === "view-" + v));
  if (v === "radar" && !state.picks) loadRadar();
  if (v === "filings") loadFilings();
  window.scrollTo({ top: 0 });
}
$$(".tab[data-view]").forEach((t) => t.addEventListener("click", () => setView(t.dataset.view)));
$("#open-reader").addEventListener("click", () => openReader({ paste: true }));

/* ------------------------------------------------------------ markets and the index strip */
function renderMarkets() {
  fill($("#markets"), ...state.markets.map((m) => h("button", {
    class: "mkt" + (m.id === state.market ? " is-on" : ""), "aria-pressed": String(m.id === state.market), title: m.name,
    onclick: () => setMarket(m.id),
  }, h("span", { class: "mk-short", text: m.short }), h("span", { class: "mk-name", text: m.name }))));
  $("#mkt-name").textContent = marketInfo().name;
  // On a phone the row scrolls sideways: keep the selected market in view so people can see where they are.
  const row = $("#markets"), on = $("#markets .mkt.is-on");
  if (on) row.scrollTo({ left: Math.max(0, on.offsetLeft - (row.clientWidth - on.offsetWidth) / 2) });
  const note = $("#mkt-note");
  note.textContent = marketInfo().note || "";
  note.hidden = !marketInfo().note;
}

function setMarket(id) {
  if (id === state.market) return;
  state.market = id;
  store.set("market", id);
  try { history.replaceState(null, "", id === "us" ? location.pathname : "?market=" + id); } catch { /* file or sandbox */ }
  Object.assign(state, { feed: null, seen: null, newIds: new Set(), picks: null, filings: null, filter: "all", ticker: null, radarList: "all", allKinds: new Set() });
  state.page = { wire: 1, radar: 1, buys: 1, stakes: 1 };
  renderMarkets();
  fill($("#wire-list"), h("li", { class: "empty", text: `Loading ${marketInfo().name} stories…` }));
  $("#wire-pager").hidden = true; $("#wire-empty").hidden = true;
  fill($("#strip"));
  fill($("#top3")); fill($("#start-list"));
  loadFeed(); loadQuotes();
  if (state.view === "radar") loadRadar();
  if (state.view === "filings") loadFilings();
}

async function initMarket() {
  try {
    state.markets = (await api("/api/markets")).markets;
    const want = new URLSearchParams(location.search).get("market") || store.get("market", "us");
    state.market = state.markets.some((m) => m.id === want) ? want : "us";
  } catch { state.markets = []; }
  renderMarkets();
}

async function loadQuotes() {
  const mk = state.market;
  try {
    const { quotes } = await api("/api/quotes?market=" + mk);
    if (mk !== state.market) return;   // the user switched markets while this was loading
    fill($("#strip"), ...quotes.filter((q) => q.price != null).map((q) =>
      h("div", { class: "q" }, h("b", { text: q.label }), h("span", { text: fmt.price(q.price) }),
        h("span", { class: q.symbol.endsWith("=X") ? "flat" : dirClass(q.chg, q.symbol === "^VIX"), text: fmt.pct(q.chg) }))));
  } catch { /* strip is optional */ }
}

// The headline always says what the site is; the detail can be tucked away by people who already know.
const heroMore = $("#hero-more"), heroBtn = $("#hero-toggle");
function setHero(open) {
  heroMore.hidden = !open;
  heroBtn.setAttribute("aria-expanded", String(open));
  heroBtn.textContent = open ? "Hide details" : "What is this?";
  store.set("heroOpen", open);
}
setHero(store.get("heroOpen", true));
heroBtn.addEventListener("click", () => setHero(heroMore.hidden));

/* ------------------------------------------------------------ pagination */
function pageNumbers(cur, pages) {
  const keep = new Set([1, pages, cur - 1, cur, cur + 1]);
  const out = [];
  for (let n = 1; n <= pages; n++) {
    if (keep.has(n)) out.push(n);
    else if (out[out.length - 1] !== "…") out.push("…");
  }
  return out;
}

// Short numbered pages instead of one endless scroll. onGo re-renders the list.
function renderPager(box, total, key, per, onGo) {
  const pages = Math.max(1, Math.ceil(total / per));
  if (pages <= 1) { fill(box); box.hidden = true; return; }
  box.hidden = false;
  const cur = state.page[key];
  const go = (n) => { state.page[key] = Math.min(pages, Math.max(1, n)); onGo(); };
  fill(box,
    h("span", { class: "pg-range", text: `Showing ${(cur - 1) * per + 1} to ${Math.min(total, cur * per)} of ${total}` }),
    h("div", { class: "pg-btns" },
      h("button", { class: "pg", disabled: cur === 1, "aria-label": "Previous page", onclick: () => go(cur - 1) }, "Previous"),
      pageNumbers(cur, pages).map((n) => (n === "…" ? h("span", { class: "pg-gap", text: "…" })
        : h("button", { class: "pg" + (n === cur ? " is-on" : ""), "aria-current": n === cur ? "page" : null, "aria-label": "Page " + n, onclick: () => go(n) }, String(n)))),
      h("button", { class: "pg", disabled: cur === pages, "aria-label": "Next page", onclick: () => go(cur + 1) }, "Next")));
}
const toTopOf = (el) => el.scrollIntoView({ block: "start", behavior: "smooth" });

/* ------------------------------------------------------------ the wire */
const FILTERS = [
  ["all", "All", () => true],
  ["urgent", "Urgent", (s) => s.level === "urgent"],
  ["ovr", "Not in big headlines", (s) => s.overlooked],
  ["bull", "Bullish", (s) => s.dir === "bull" || s.dir === "mixed"],
  ["bear", "Bearish", (s) => s.dir === "bear" || s.dir === "mixed"],
  ["corro", "Corroborated", (s) => s.corroborated],
  ["mine", "My tickers", (s) => s.tickers.some((t) => state.watch.has(t))],
];

function visibleStories() {
  if (!state.feed) return [];
  const f = FILTERS.find((x) => x[0] === state.filter)[2];
  return state.feed.stories.filter((s) =>
    s.kinds.some(kindOn) && f(s) && (!state.ticker || s.tickers.includes(state.ticker)));
}

function renderFilters() {
  const base = state.feed ? state.feed.stories.filter((s) => s.kinds.some(kindOn)) : [];
  fill($("#filters"), ...FILTERS.map(([id, label, fn]) =>
    h("button", { class: "chip" + (state.filter === id ? " is-on" : ""), "aria-pressed": state.filter === id,
      onclick: () => { state.filter = id; state.page.wire = 1; renderWire(); } },
    label, h("span", { class: "n", text: base.filter(fn).length }))));
}

function renderWatching() {
  const tags = [...state.watch].map((t) => h("button", { class: "wtag", title: "Remove " + t, onclick: () => { state.watch.delete(t); store.set("watch", [...state.watch]); renderWire(); } }, t));
  if (state.ticker) tags.unshift(h("button", { class: "wtag", title: "Clear ticker filter", onclick: () => { state.ticker = null; state.page.wire = 1; renderWire(); } }, "Showing " + state.ticker));
  if (state.watch.size) tags.unshift(h("span", { class: "wlabel", text: "Watching" }));
  fill($("#watching"), ...tags);
}

const LEVEL_NOTE = {
  urgent: "Urgent: 8 or more points and confirmed by two or more outlets, or by a major or official source.",
  watch: "Watch: 5 to 7 points.",
  normal: "Under 5 points, so it stays in the background.",
};

function calcEl(s, open) {
  const p = s.parts;
  const row = (label, pts) => h("li", {}, h("span", { text: label }), h("b", { class: "cn", text: (pts > 0 ? "+" : "") + pts }));
  return h("div", { class: "calc" + (open ? " is-on" : "") },
    h("p", { class: "calc-h", text: `How ${s.score} points were built` }),
    h("ul", {},
      p.signals.map((g) => row(g.label, g.pts)),
      !p.signals.length && row("No trading signal found", 0),
      row("Fresh news (under 1 hour is 3, under 3 hours is 2, under 8 hours is 1)", p.fresh),
      row("Other outlets reporting it", p.outlets),
      row("A stock ticker is named", p.ticker),
      p.question !== 0 && row("Question headline (often clickbait)", p.question)),
    h("p", { class: "calc-sum" }, `Total: ${s.score} points`),
    p.no_signal_cap && h("p", { class: "calc-n", text: "Stories with no trading signal are held at 3 points." }),
    p.capped
      ? h("p", { class: "calc-n warn", text: "Held at Watch: only one lesser-known outlet reports this so far. It becomes Urgent once a second outlet, or a major or official source, confirms it." })
      : h("p", { class: "calc-n", text: LEVEL_NOTE[s.level] }));
}

function storyEl(s, isNew) {
  const mine = s.tickers.some((t) => state.watch.has(t));
  const open = state.openSrcs.has(s.id);
  const calcOpen = state.openCalc.has(s.id);
  const seen = new Set();
  const calc = calcEl(s, calcOpen);
  const scoreBtn = h("button", { class: "scorebtn", "aria-expanded": String(calcOpen), title: "Click to see how this score was built",
    "aria-label": `${s.score} points. Show how it was built.`,
    onclick: () => { const on = calc.classList.toggle("is-on"); on ? state.openCalc.add(s.id) : state.openCalc.delete(s.id); scoreBtn.setAttribute("aria-expanded", String(on)); } },
  h("span", { class: "n", text: s.score }), h("span", { class: "pts", text: "pts" }));
  const srcList = h("ul", { class: "srcs" + (open ? " is-on" : "") },
    s.links.map((l) => h("li", {}, h("a", { href: l.url }, l.publisher), isGoogle(l.url) ? " (via Google News)" : "", " · " + l.title)));
  const sec = secLink(s);
  return h("li", { class: `story lvl-${s.level}` + (isNew ? " is-new" : ""), "data-id": s.id },
    h("div", { class: "score" }, scoreBtn, h("span", { class: "lbl", text: s.level })),
    h("div", { class: "body" },
      h("div", { class: "meta" },
        h("span", { "data-ts": s.ts, text: ago(s.ts) }),
        h("span", { text: s.n_pub + (s.n_pub === 1 ? " source" : " sources") }),
        s.corroborated
          ? tip("tag-corr", "Corroborated", "Two or more different outlets reported this.")
          : tip("tag-single", "Single source", "Only one outlet reported this so far. Unconfirmed: wait for a second outlet or the filing."),
        s.overlooked && tip("tag-ovr", "Not in big headlines", "A strong signal that the big outlets (CNBC, Reuters, SCMP, BBC and similar) are not carrying yet. Early, but unconfirmed: check before acting."),
        mine && h("span", { class: "tagx tag-mine", text: "Your ticker" })),
      h("h3", {}, h("a", { href: s.link }, s.title)),
      calc,
      s.summary && h("p", { class: "sum" }, glossNodes(s.summary.length > 260 ? s.summary.slice(0, 257) + "…" : s.summary, seen)),
      s.why && h("p", { class: "why" }, h("b", { text: "Why it matters" }), glossNodes(s.why, seen)),
      h("div", { class: "tags" },
        s.tickers.map((t) => h("button", { class: "tk", title: "Show only " + t, onclick: () => { state.ticker = t; state.page.wire = 1; setView("wire"); renderWire(); } }, t)),
        s.signals.map((g) => h("span", { class: "sg sg-" + g.dir, text: g.label }))),
      h("div", { class: "acts" },
        h("button", { class: "read", onclick: () => openReader({ story: s }) }, "Read with Tick"),
        h("button", { class: "more-btn", "aria-label": "Show more about this story", onclick: (e) => { const on = e.target.closest(".story").classList.toggle("is-open"); e.target.textContent = on ? "Less" : "More"; } }, "More"),
        sec && h("a", { href: sec.url, title: "The company's own filings, straight from the SEC" }, sec.label),
        h("a", { href: s.link, title: isGoogle(s.link) ? "Opens through Google News, which then forwards you to the publisher" : "" }, isGoogle(s.link) ? "Original (via Google News)" : "Original"),
        h("a", { href: "https://web.archive.org/web/2/" + s.link }, "Archive copy"),
        h("button", { onclick: (e) => { const on = srcList.classList.toggle("is-on"); on ? state.openSrcs.add(s.id) : state.openSrcs.delete(s.id); e.target.setAttribute("aria-expanded", String(on)); }, "aria-expanded": String(open) },
          "Who reported it (" + s.n_pub + ")")),
      srcList));
}

function renderWire() {
  renderFilters(); renderWatching();
  const list = visibleStories();
  const pages = Math.max(1, Math.ceil(list.length / PER.wire));
  state.page.wire = Math.min(state.page.wire, pages);
  const newIds = state.newIds || new Set();
  const from = (state.page.wire - 1) * PER.wire;
  fill($("#wire-list"), ...list.slice(from, from + PER.wire).map((s) => storyEl(s, newIds.has(s.id))));
  renderPager($("#wire-pager"), list.length, "wire", PER.wire, () => { renderWire(); toTopOf($("#wire-top")); });
  $("#wire-empty").hidden = list.length > 0;
  $("#wire-empty").textContent = emptyText();
  renderTop3();
}

function emptyText() {
  if (state.filter === "mine") {
    const n = state.watch.size;
    return n
      ? `None of your watched ${n === 1 ? "ticker is" : "tickers are"} in the news right now (${[...state.watch].join(", ")}). New mentions will appear here.`
      : "Add a ticker above (like NVDA) and any story that mentions it will show up here.";
  }
  if (state.ticker) return `No stories mention ${state.ticker} right now.`;
  return "Nothing matches those filters right now. Tick is napping.";
}

const topStories = () => state.feed.stories.filter((s) => s.kinds.some(kindOn)).slice(0, 3);

function renderTop3() {
  if (!state.feed) return;
  fill($("#top3"), ...topStories().map((s) => h("li", {},
    h("div", {}, h("button", { onclick: () => openReader({ story: s }), text: s.title }),
      h("span", { class: "m", text: `${s.score} pts · ${s.n_pub} ${s.n_pub === 1 ? "source" : "sources"} · ${ago(s.ts)}` })))));
  const PLAIN = { bull: ["Good news", "sg-bull"], bear: ["Bad news", "sg-bear"], mixed: ["Mixed news", "sg-flag"], flag: ["Worth a look", "sg-flag"], none: ["Background", "sg-flag"] };
  fill($("#start-list"), ...topStories().map((s) => h("li", {},
    h("div", { class: "st-head" }, h("span", { class: "sg " + PLAIN[s.dir][1], text: PLAIN[s.dir][0] }),
      h("span", { class: "st-meta", text: `${s.n_pub} ${s.n_pub === 1 ? "source" : "sources"} · ${ago(s.ts)}` })),
    h("button", { class: "st-title", onclick: () => openReader({ story: s }), text: s.title }),
    s.why && h("p", { class: "st-why" }, glossNodes(s.why)))));
}

function renderKinds() {
  const kinds = [...state.allKinds].sort();
  $("#src-count").textContent = `${kinds.filter(kindOn).length}/${kinds.length}`;
  fill($("#kinds"), ...kinds.map((k) => h("button", {
    class: "chip" + (kindOn(k) ? " is-on" : ""), "aria-pressed": String(kindOn(k)),
    onclick: () => { kindOn(k) ? state.off.add(k) : state.off.delete(k); store.set("kindsOff", [...state.off]); state.page.wire = 1; renderKinds(); renderWire(); },
  }, k)));
}

function renderHealth(feed) {
  const rows = feed.health.map((x) => h("li", { class: x.ok ? "" : "off", title: x.ok ? `${x.count} items in ${x.ms}ms` : "Failed: " + x.error }, h("i"), x.name));
  fill($("#health"), ...rows);
}

async function loadFeed() {
  const live = $("#live"), mk = state.market;
  try {
    const feed = await api("/api/feed?market=" + mk);
    if (mk !== state.market) return;   // the user switched markets while this was loading
    const first = !state.seen;
    const ids = new Set(feed.stories.map((s) => s.id));
    if (first) { state.seen = ids; state.newIds = new Set(); }
    else {
      state.newIds = new Set([...ids].filter((i) => !state.seen.has(i)));
      const fresh = feed.stories.filter((s) => state.newIds.has(s.id) && s.level !== "normal");
      ids.forEach((i) => state.seen.add(i));
      if (fresh.length) announce(fresh);
    }
    state.feed = feed;
    feed.stories.forEach((s) => s.kinds.forEach((k) => state.allKinds.add(k)));
    renderKinds(); renderWire(); renderHealth(feed);
    live.className = "live ok";
    $("#updated").textContent = "Live · " + feed.stories.length + " stories · " + ago(feed.generated);
    $("#updated").dataset.ts = feed.generated;
  } catch (e) {
    if (mk !== state.market) return;
    live.className = "live bad";
    $("#updated").textContent = "Offline: " + e.message;
  }
}

function announce(fresh) {
  const top = fresh[0];
  const text = fresh.length === 1 ? top.title : `${fresh.length} new stories, top: ${top.title}`;
  const t = $("#toast");
  t.textContent = "New: " + text;
  t.hidden = false;
  t.onclick = () => { t.hidden = true; openReader({ story: top }); };
  clearTimeout(announce.t);
  announce.t = setTimeout(() => { t.hidden = true; }, 9000);
  document.title = `(${fresh.length}) ${BASE_TITLE}`;
  if (store.get("alerts", false) && "Notification" in window && Notification.permission === "granted" && fresh.some((s) => s.level === "urgent")) {
    try { new Notification("Whisker Wire: urgent", { body: fresh.find((s) => s.level === "urgent").title }); } catch { /* ignore */ }
  }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) { document.title = BASE_TITLE; loadFeed(); loadQuotes(); } });

$("#watch-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#watch-in").value.trim().toUpperCase().replace(/[^A-Z0-9.&-]/g, "");
  if (!v) return flash("Type a ticker symbol first, like NVDA.");
  $("#watch-in").value = "";
  if (state.watch.has(v)) return flash(`${v} is already on your watchlist.`);
  state.watch.add(v); store.set("watch", [...state.watch]);
  const n = state.feed ? state.feed.stories.filter((s) => s.tickers.includes(v)).length : 0;
  renderWire();
  flash(n ? `${v} added. ${n} ${n === 1 ? "story mentions" : "stories mention"} it right now: see "My tickers".`
    : `${v} added. No stories mention it right now; new mentions will show up under "My tickers".`);
});

$("#alerts").addEventListener("click", async () => {
  if (!("Notification" in window)) return flash("This browser cannot show desktop alerts.");
  const on = !store.get("alerts", false);
  if (on && Notification.permission !== "granted") {
    const p = await Notification.requestPermission();
    if (p !== "granted") return flash("Alerts were blocked in the browser settings.");
  }
  store.set("alerts", on);
  syncAlerts();
  flash(on ? "Alerts on. Urgent stories will pop up here." : "Alerts off.");
});
function syncAlerts() { $("#alerts").textContent = store.get("alerts", false) ? "Alerts on" : "Alerts"; }
function flash(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false; t.onclick = () => { t.hidden = true; };
  clearTimeout(announce.t); announce.t = setTimeout(() => { t.hidden = true; }, 4000);
}

/* ------------------------------------------------------------ sources, scoring, track record */
const panel = $("#panel");
function openPanel(which) {
  const same = !panel.hidden && panel.dataset.focus === which;
  panel.hidden = same;
  panel.dataset.focus = same ? "" : which;
  $("#btn-sources").setAttribute("aria-expanded", String(!panel.hidden && which === "sources"));
  $("#btn-how").setAttribute("aria-expanded", String(!panel.hidden && which === "how"));
  if (same) return;
  loadTrack();
  const sec = $("#sec-" + which);
  sec.scrollIntoView({ block: "nearest", behavior: "smooth" });
  $$(".panel-col", panel).forEach((c) => c.classList.toggle("hot", c === sec));
}
// One tap from any tab: go to the wire and open the panel.
$("#tab-how").addEventListener("click", () => {
  setView("wire");
  if (panel.hidden) openPanel("how");
  requestAnimationFrame(() => $(".toolbar").scrollIntoView({ behavior: "smooth", block: "start" }));
});
$("#btn-sources").addEventListener("click", () => openPanel("sources"));
$("#btn-how").addEventListener("click", () => openPanel("how"));

const serious = $("#serious");
serious.checked = store.get("serious", false);
document.body.classList.toggle("serious", serious.checked);
serious.addEventListener("change", () => { document.body.classList.toggle("serious", serious.checked); store.set("serious", serious.checked); });

async function loadTrack() {
  const box = $("#track-body");
  try { renderTrack(box, await api("/api/track")); }
  catch { fill(box, h("p", { class: "small", text: "Track record is unavailable right now." })); }
}

function renderTrack(box, t) {
  const intro = h("p", { class: "small", text: "Each Urgent or Watch story that names a stock is logged with its price and the S&P 500's at that moment, then checked 1 and 5 trading days later. Results only show once there are enough to mean something." });
  if (!t.logged) return fill(box, intro, h("p", { class: "small strong", text: "Collecting: nothing measured yet. Leave the app running and check back in a week." }));
  const prog = h("p", { class: "small strong", text: `${t.logged} logged over ${t.days_running} days. ${t.measured_5d} of the ${t.min_sample} needed have a 5-day result.` });
  if (!t.enough) return fill(box, intro, prog);
  const label = (g) => `${g.level === "urgent" ? "Urgent" : "Watch"} · ${g.dir === "bull" ? "bullish" : "bearish"}`;
  const rows = t.groups.filter((g) => g.n5 > 0).map((g) => h("li", {},
    h("span", { text: label(g) }),
    h("span", { class: "mono", text: `${Math.round(g.hit5 * 100)}% right after 5 days` }),
    h("span", { class: "mono " + (g.avg5 >= 0 ? "up" : "down"), text: `${fmt.pct(g.avg5 * 100)} vs S&P 500` }),
    h("span", { class: "mono small", text: `n=${g.n5}${g.n5 < 10 ? " (small)" : ""}` })));
  fill(box, prog, h("ul", { class: "trk" }, rows), h("p", { class: "small", text: "Right means a bullish story's stock beat the S&P 500 (or a bearish one's lagged it). Small samples swing wildly." }));
}

/* ------------------------------------------------------------ value radar */
const radarLists = () => (state.market === "us"
  ? [["all", "All"], ["undervalued_large_caps", "Large caps"], ["undervalued_growth_stocks", "Growth"], ["most_shorted_stocks", "Crowded shorts"]]
  : [["all", "All"], ["large", "Large caps"], ["mid", "Mid and small caps"]]);

async function loadRadar() {
  const box = $("#radar-list"), mk = state.market;
  fill(box, h("p", { class: "empty", text: "Tick is checking the numbers…" }));
  try {
    const d = await api("/api/undervalued?market=" + mk);
    if (mk !== state.market) return;
    state.picks = d.picks;
    renderRadar();
  } catch (e) { if (mk === state.market) fill(box, h("p", { class: "empty", text: "Could not load the screener: " + e.message })); }
}

function sparkline(closes) {
  const W = 300, H = 90, min = Math.min(...closes), max = Math.max(...closes);
  const pts = closes.map((c, i) => [(i / (closes.length - 1)) * W, H - 6 - ((c - min) / (max - min || 1)) * (H - 12)]);
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Six month price line: from ${closes[0]} to ${closes[closes.length - 1]}`);
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", pts.map((q, i) => (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1)).join(" "));
  p.setAttribute("fill", "none"); p.setAttribute("stroke", closes.at(-1) >= closes[0] ? "var(--bull)" : "var(--bear)");
  p.setAttribute("stroke-width", "2"); p.setAttribute("vector-effect", "non-scaling-stroke");
  svg.append(p);
  return svg;
}

function pickEl(p) {
  const pos = Math.min(100, Math.max(0, ((p.price - p.lo) / (p.hi - p.lo)) * 100));
  const tier = p.score >= 70 ? "hi" : p.score >= 50 ? "mid" : "lo";
  const detail = h("div", { class: "detail" });
  const metric = (label, val) => h("span", {}, h("b", {}, glossNodes(label)), val);
  const seen = new Set();
  const bullet = (t) => h("li", {}, glossNodes(t, seen));
  return h("article", { class: "pick" },
    h("div", { class: "pk-head" },
      h("span", { class: "pk-sym", text: p.symbol }), h("span", { class: "pk-name", text: p.name }),
      h("span", { class: "pk-px" }, fmt.px(p.price, p.currency) + " ", h("span", { class: dirClass(p.chg), text: fmt.pct(p.chg) })),
      h("span", { class: "pk-list", text: p.list_label })),
    h("div", { class: "scoreblock" },
      h("div", { class: "n" }, String(p.score), h("small", { text: "/100" })),
      h("div", { class: "meter", role: "img", "aria-label": "Value score " + p.score + " out of 100" }, h("i", { style: { transform: `scaleX(${p.score / 100})`, background: tier === "hi" ? "var(--bull)" : tier === "mid" ? "var(--alert)" : "var(--ink-2)" } })),
      h("div", { class: "cap", text: tier === "hi" ? "Strong value case" : tier === "mid" ? "Worth a look" : "Weak case" })),
    h("div", {}, h("div", { class: "metrics" },
      metric("Fwd P/E", fmt.x(p.fpe)), metric("P/B", p.pb != null && p.pb < 0 ? "negative" : fmt.x(p.pb)), metric("Off 52-week high", fmt.pct(p.off_high, 0)),
      metric("Mkt cap", fmt.cap(p.mcap, p.currency)), metric("Analysts", p.rating ? p.rating.split(" - ")[1] || p.rating : "n/a")),
    h("div", { class: "range", role: "img", "aria-label": `Price sits ${pos.toFixed(0)} percent of the way up its 52 week range` },
      h("i", { style: { left: pos + "%" } }),
      h("span", { style: { left: "0" }, text: fmt.px(p.lo, p.currency) }),
      h("span", { style: { right: "0" }, text: fmt.px(p.hi, p.currency) }))),
    h("div", { class: "two" },
      h("div", { class: "g" }, h("h4", { text: "Why it looks cheap" }), h("ul", {}, p.good.length ? p.good.map(bullet) : h("li", { text: "Few classic value signals. Its score comes from small pieces." }))),
      h("div", { class: "w" }, h("h4", { text: "How it could be a trap" }), h("ul", {}, p.warn.map(bullet)))),
    h("div", { class: "pk-acts" },
      h("button", { onclick: async (e) => {
        const on = detail.classList.toggle("is-on"); e.target.textContent = on ? "Hide chart and news" : "Chart and news";
        if (on && !detail.firstChild) {
          detail.append(h("p", { class: "small", text: "Loading…" }));
          try {
            const t = await api("/api/ticker?symbol=" + encodeURIComponent(p.symbol));
            fill(detail, 
              h("div", {}, h("h4", { class: "eyebrow", text: "Six months" }), t.spark.length > 3 ? sparkline(t.spark) : h("p", { class: "small", text: "No chart data." })),
              h("div", {}, h("h4", { class: "eyebrow", text: "Latest headlines" }), h("ul", { class: "lnk" },
                t.news.length ? t.news.slice(0, 5).map((n) => h("li", {}, h("a", { href: n.url }, n.title), n.publisher ? " · " + n.publisher : "")) : h("li", { text: "Nothing recent found." }))));
          } catch (err) { fill(detail, h("p", { class: "small", text: "Could not load: " + err.message })); }
        }
      } }, "Chart and news"),
      h("button", { onclick: () => { state.ticker = p.symbol; state.filter = "all"; state.page.wire = 1; setView("wire"); renderWire(); } }, "Filter the wire"),
      h("button", { onclick: () => { state.watch.add(p.symbol); store.set("watch", [...state.watch]); flash(p.symbol + " added to your watchlist."); renderWire(); } }, "Watch")),
    detail);
}

function renderRadar() {
  fill($("#radar-filters"), ...radarLists().map(([id, label]) =>
    h("button", { class: "chip" + (state.radarList === id ? " is-on" : ""), "aria-pressed": String(state.radarList === id), onclick: () => { state.radarList = id; state.page.radar = 1; renderRadar(); } }, label)));
  const rows = state.picks.filter((p) => state.radarList === "all" || p.list === state.radarList);
  const pages = Math.max(1, Math.ceil(rows.length / PER.radar));
  state.page.radar = Math.min(state.page.radar, pages);
  const from = (state.page.radar - 1) * PER.radar;
  fill($("#radar-list"), ...(rows.length ? rows.slice(from, from + PER.radar).map(pickEl) : [h("p", { class: "empty", text: "Nothing in this list right now." })]));
  renderPager($("#radar-pager"), rows.length, "radar", PER.radar, () => { renderRadar(); toTopOf($("#view-radar")); });
}

/* ------------------------------------------------------------ filings */
function secSetup() {
  const name = h("input", { type: "text", placeholder: "Your name", autocomplete: "name", maxlength: "60", required: true, "aria-label": "Your name" });
  const email = h("input", { type: "email", placeholder: "you@example.com", autocomplete: "email", required: true, "aria-label": "Your email" });
  const msg = h("p", { class: "small", role: "status" });
  const form = h("form", { class: "sec-form", onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = "Saving…";
    try { await postJson("/api/sec-contact", { name: name.value, email: email.value }); loadFilings(); }
    catch (err) { msg.textContent = err.message; }
  } }, name, email, h("button", { class: "primary", type: "submit" }, "Turn on filings"));
  return h("div", { class: "setup" },
    h("h3", { text: "Turn on insider trades in one step" }),
    h("p", { class: "small", text: "The SEC asks anyone who fetches filings automatically to say who they are. This is saved only on this computer, in a file called sec_contact.txt, and sent only to sec.gov with each request. Never anywhere else." }),
    form, msg,
    h("p", { class: "small", text: "Prefer to do it by hand? Create whisker-wire/sec_contact.txt containing one line: Your Name you@example.com" }));
}

function renderPortals(box) {
  const m = marketInfo();
  fill(box, h("div", { class: "portals" },
    h("h2", { class: "subhead", text: `Where ${m.name} companies file` }),
    h("p", { class: "small", text: "Whisker Wire reads US filings from the SEC automatically. For this market, the official announcements, including director and insider dealings, live at these sites. Open them to check any story at its source." }),
    m.note && h("p", { class: "small", text: m.note }),
    h("ul", { class: "portal-list" }, m.filings.map((f) => h("li", {}, h("a", { href: f.url }, f.name), h("span", { text: f.what })))),
    h("button", { class: "ghost", onclick: () => setMarket("us") }, "Switch to US insider filings")));
}

async function loadFilings() {
  const box = $("#filings-body");
  if (state.market !== "us") return renderPortals(box);
  fill(box, h("p", { class: "empty", text: "Asking the SEC…" }));
  try { state.filings = await api("/api/filings"); } catch (e) { return fill(box, h("p", { class: "empty", text: "Could not load filings: " + e.message })); }
  renderFilings();
}

function renderFilings() {
  const box = $("#filings-body"), d = state.filings;
  if (!d) return;
  if (!d.configured) return fill(box, secSetup());
  const buys = d.insider.filter((r) => r.buy_usd > 0);
  const sells = d.insider.filter((r) => r.sell_usd > 0 && !r.buy_usd);
  const cluster = {};
  buys.forEach((r) => { (cluster[r.symbol] ||= new Set()).add(r.insider); });
  const row = (r, buy) => h("div", { class: "frow" },
    h("button", { class: "tk", onclick: () => { state.ticker = r.symbol; state.page.wire = 1; setView("wire"); renderWire(); } }, r.symbol || "?"),
    h("div", {}, h("div", { class: "who", text: r.insider }),
      h("div", { class: "sub" }, `${r.role} at ${r.company} · ${ago(r.ts)} · `, h("a", { href: r.link }, "filing"),
        buy && cluster[r.symbol] && cluster[r.symbol].size > 1 ? "  " : "", buy && cluster[r.symbol] && cluster[r.symbol].size > 1 && h("span", { class: "tagx tag-corr", text: cluster[r.symbol].size + " insiders buying" }))),
    h("div", { class: "amt " + (buy ? "buy" : "sell"), text: fmt.usd(buy ? r.buy_usd : r.sell_usd) }));
  const slice = (arr, key) => arr.slice((Math.min(state.page[key], Math.max(1, Math.ceil(arr.length / PER[key]))) - 1) * PER[key]).slice(0, PER[key]);
  const buyPager = h("nav", { class: "pager", "aria-label": "Insider buy pages", hidden: true });
  const stakePager = h("nav", { class: "pager", "aria-label": "Stake filing pages", hidden: true });
  state.page.buys = Math.min(state.page.buys, Math.max(1, Math.ceil(buys.length / PER.buys)));
  state.page.stakes = Math.min(state.page.stakes, Math.max(1, Math.ceil(d.stakes.length / PER.stakes)));
  fill(box,
    h("h2", { class: "subhead", text: "Insiders buying with their own cash" }),
    h("p", { class: "small" }, glossNodes("Open-market purchases (code P) from the latest Form 4 filings. Several insiders at one company is the strongest version.")),
    ...(buys.length ? slice(buys, "buys").map((r) => row(r, true)) : [h("p", { class: "empty", text: d.insider_error ? "The SEC did not answer (" + d.insider_error + "). Try again shortly." : "No open-market insider buys in the latest batch." })]),
    buyPager,
    h("h2", { class: "subhead", text: "Big holders and activists (Schedule 13D)" }),
    ...(d.stakes.length ? slice(d.stakes, "stakes").map((r) => h("div", { class: "frow" }, h("span", {}), h("div", {}, h("a", { class: "who", href: r.link }, r.title), h("div", { class: "sub", text: ago(r.ts) })), h("span"))) : [h("p", { class: "empty", text: "None in the latest batch." })]),
    stakePager,
    h("div", { class: "chips" }, h("button", { class: "chip" + (state.showSells ? " is-on" : ""), onclick: () => { state.showSells = !state.showSells; renderFilings(); } }, "Show insider sales (noisy)")),
    ...(state.showSells ? sells.map((r) => row(r, false)) : []));
  renderPager(buyPager, buys.length, "buys", PER.buys, () => { renderFilings(); toTopOf($("#view-filings")); });
  renderPager(stakePager, d.stakes.length, "stakes", PER.stakes, () => { renderFilings(); toTopOf($("#view-filings")); });
}

/* ------------------------------------------------------------ reader + Tick */
const reader = { open: false, marks: [], idx: -1, lockUntil: 0, sleepT: 0, result: null, page: 0, pageCount: 1 };
const PAGE_CHARS = 2000;   // about one screen of reading per page
const scroller = $("#reader-scroll");
const catEl = $("#cat");

function setCatState(s) { catEl.dataset.state = s; }
function wake() {
  clearTimeout(reader.sleepT);
  if (catEl.dataset.state === "sleep") setCatState("idle");
  reader.sleepT = setTimeout(() => setCatState("sleep"), 25000);
}

function openReader(opts = {}) {
  reader.open = true;
  const d = $("#reader");
  d.classList.add("is-open"); d.setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
  document.body.style.overflow = "hidden";
  $("#reader-close").focus();
  if (opts.story) loadStory(opts.story);
  else if (opts.paste) showPaste(true);
  wake();
}
function closeReader() {
  reader.open = false;
  const d = $("#reader");
  d.classList.remove("is-open"); d.setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true; catEl.hidden = true;
  document.body.style.overflow = "";
  clearTimeout(reader.sleepT);
}
$("#reader-close").addEventListener("click", closeReader);
$("#scrim").addEventListener("click", closeReader);
function showPaste(on) {
  $("#paste").hidden = !on;
  $("#mode-paste").classList.toggle("is-on", on);
  $("#mode-article").classList.toggle("is-on", !on);
  if (on) $("#paste-in").focus();
}
$("#mode-paste").addEventListener("click", () => showPaste(true));
$("#mode-article").addEventListener("click", () => showPaste(false));

$("#paste-go").addEventListener("click", async () => {
  const v = $("#paste-in").value.trim();
  if (!v) return;
  if (/^https?:\/\/\S+$/i.test(v)) return loadUrl(v, "");
  const paras = v.split(/\n+/).map((x) => x.trim()).filter(Boolean);
  await render({ title: paras[0].length < 140 ? paras[0] : "Pasted text", url: "", paragraphs: paras.length > 1 ? paras.slice(paras[0].length < 140 ? 1 : 0) : paras });
});

// Tapping Tick folds her note away (handy on a phone) and brings it back.
const catFig = $("#cat-fig");
catFig.setAttribute("role", "button"); catFig.tabIndex = 0;
catFig.setAttribute("aria-label", "Hide or show Tick's note");
const toggleNote = () => { const mini = catEl.classList.toggle("mini"); catFig.setAttribute("aria-pressed", mini); wake(); };
catFig.addEventListener("click", toggleNote);
catFig.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleNote(); } });

$("#cat-on").addEventListener("change", (e) => {
  document.body.classList.toggle("no-cat", !e.target.checked);
  catEl.hidden = !e.target.checked || !reader.marks.length;
});

async function ensureSignals() {
  if (!state.signals) state.signals = (await api("/api/signals")).signals;
  return state.signals;
}

async function loadStory(s) {
  showPaste(false);
  await loadUrl(s.link, s.title, s.summary);
}

async function loadUrl(url, fallbackTitle, summary = "") {
  showPaste(false);
  head({ title: fallbackTitle || url, url });
  $("#take").hidden = true; fill($("#article"), h("p", { class: "small", text: "Tick is reading the page…" }));
  catEl.hidden = false; setCatState("think"); placeCat(null); fill($("#cat-note"), h("div", { text: "Reading… one moment." }));
  try {
    const a = await api("/api/article?url=" + encodeURIComponent(url));
    await render({ title: a.title || fallbackTitle || url, url, paragraphs: a.paragraphs });
  } catch (e) {
    head({ title: fallbackTitle || url, url, err: e.message + (/paste/i.test(e.message) ? "" : " Paste the article text below and Tick will read that instead.") });
    showPaste(true);
    // Never leave a dead end: read what we do have (summary or headline) so Tick still has something to say.
    const basic = summary || (fallbackTitle ? fallbackTitle + (/[.!?]$/.test(fallbackTitle) ? "" : ".") : "");
    if (basic) await render({ title: fallbackTitle, url, paragraphs: [basic], keepErr: true }, true);
    else { fill($("#article")); catEl.hidden = true; }
  }
}

function head({ title, url, err }) {
  fill($("#reader-head"), 
    h("h2", { text: title || "Untitled" }),
    url && h("div", { class: "links" }, h("a", { href: url }, "Open original"), h("a", { href: "https://web.archive.org/web/2/" + url }, "Archive copy")),
    err && h("p", { class: "err", text: err }));
}

async function render({ title, url, paragraphs, keepErr }, partial = false) {
  const sigs = await ensureSignals();
  const res = analyze(paragraphs, sigs);
  reader.result = res;
  if (!keepErr) head({ title, url });
  // Tick's take
  const take = $("#take");
  take.hidden = false;
  fill(take, 
    h("h3", {}, "Tick's take", h("span", { class: "lean lean-" + res.lean, text: LEAN_TEXT[res.lean] })),
    res.take.length ? h("ol", {}, res.take.map((t) => h("li", { class: "k-" + t.cat, style: { borderLeftColor: "currentColor" }, tabindex: 0, role: "button",
      onclick: () => focusMark(t.n, true), onkeydown: (e) => { if (e.key === "Enter") focusMark(t.n, true); } },
      h("span", { style: { color: "var(--ink)" }, text: t.text })))) : h("p", { class: "small", text: "No strong signals in this text. That is information too: nothing here should change a trade." }),
    res.facts.length > 0 && h("div", { class: "facts" }, res.facts.map((f) => h("span", { class: "fact", title: f.context }, h("b", { text: f.value })))),
    h("p", { class: "fine", text: `Tick reads ${res.sentences} sentences by keywords and numbers. She spots patterns, not truth: verify anything you might act on.${partial ? " (Headline only.)" : ""}` }));

  // article, split into short pages so nobody has to scroll a wall of text
  const seenTerms = new Set();
  const art = $("#article");
  const pages = splitPages(res.paras);
  fill(art, ...pages.map((paras, pi) => h("div", { class: "rpage", "data-page": String(pi), hidden: pi > 0 },
    paras.map((sents) => h("p", {}, sents.map((s, i) => {
      const sp = i ? " " : "";
      if (s.hl) {
        return [sp, h("mark", { class: "hl hl-" + s.cat, "data-n": s.n, tabindex: 0, role: "button",
          "aria-label": `${CATS[s.cat].label}: ${s.label}. Press Enter for Tick's note.`,
          onclick: () => focusMark(s.n, false), onkeydown: (e) => { if (e.key === "Enter") focusMark(s.n, false); } }, s.text)];
      }
      return [sp, glossSegments(s.text, seenTerms).map((g) => g.def ? h("span", { class: "gl", tabindex: 0, "data-def": g.def, "aria-label": g.t + ": " + g.def }, g.t) : g.t)];
    }))))));
  reader.marks = $$("mark.hl", art);
  reader.hls = res.hls;
  reader.idx = -1;
  reader.pageCount = pages.length;
  showReaderPage(0);
  scroller.scrollTop = 0;
  catEl.hidden = !$("#cat-on").checked;
  if (reader.marks.length) { focusMark(0, false, true); }
  else { setCatState("sleep"); fill($("#cat-note"), h("div", { text: "Nothing here should change a trade. I checked twice." })); placeCat(null); }
  wake();
}

// Group paragraphs into pages of roughly PAGE_CHARS; never leave a tiny last page on its own.
function splitPages(paras) {
  const pages = [];
  let cur = [], n = 0;
  for (const sents of paras) {
    cur.push(sents);
    n += sents.reduce((a, s) => a + s.text.length, 0);
    if (n >= PAGE_CHARS) { pages.push(cur); cur = []; n = 0; }
  }
  if (cur.length) {
    if (pages.length && n < PAGE_CHARS * 0.35) pages[pages.length - 1].push(...cur); else pages.push(cur);
  }
  return pages.length ? pages : [[]];
}

function renderReaderPager() {
  const box = $("#rpager"), n = reader.pageCount, cur = reader.page;
  $("#rpage-tag").textContent = n > 1 ? `Page ${cur + 1} of ${n}` : "";
  if (n <= 1) { fill(box); box.hidden = true; return; }
  box.hidden = false;
  fill(box,
    h("button", { class: "pg", disabled: cur === 0, onclick: () => goReaderPage(cur - 1) }, "Previous page"),
    h("span", { class: "pg-of", text: `Page ${cur + 1} of ${n}` }),
    h("button", { class: "pg", disabled: cur === n - 1, onclick: () => goReaderPage(cur + 1) }, "Next page"));
}

function showReaderPage(n, { top = true } = {}) {
  n = Math.min(reader.pageCount - 1, Math.max(0, n));
  $$(".rpage", $("#article")).forEach((p, i) => { p.hidden = i !== n; });
  reader.page = n;
  $("#take").hidden = n > 0;   // the summary belongs to the first page
  renderReaderPager();
  if (top) scroller.scrollTo({ top: 0, behavior: "instant" });
}

function goReaderPage(n) {
  n = Math.min(reader.pageCount - 1, Math.max(0, n));
  if (n === reader.page) return;
  showReaderPage(n);
  if (!reader.marks.length) return;
  const i = reader.marks.findIndex((m) => +m.closest(".rpage").dataset.page === n);
  if (i >= 0) focusMark(i, false, true);
  else {
    reader.marks[reader.idx]?.classList.remove("is-focus");
    reader.idx = -1;
    fill($("#cat-note"), h("div", { text: "No clues on this page. Turn the page when you are ready." }));
    setCatState("idle"); placeCat(null);
  }
  wake();
}

function placeCat(mark) {
  if (docked()) return;
  const dr = $("#reader").getBoundingClientRect();
  const top0 = 62;
  let y = top0 + 36;
  if (mark) y = mark.getBoundingClientRect().top - dr.top - 10;
  const max = dr.height - catEl.offsetHeight - 12;
  catEl.style.top = Math.max(top0, Math.min(y, max)) + "px";
}

const docked = () => matchMedia("(max-width: 1040px)").matches;
// Docked Tick sits over the bottom of the page, so keep the sentence she is explaining in the upper part.
const readLine = () => (docked() ? 0.24 : 0.4);
function scrollToMark(m) {
  const r = scroller.getBoundingClientRect();
  scroller.scrollTo({ top: scroller.scrollTop + m.getBoundingClientRect().top - (r.top + r.height * readLine()) });
}

function focusMark(i, scroll, instant) {
  const marks = reader.marks;
  if (!marks.length) return;
  i = (i + marks.length) % marks.length;
  const changed = i !== reader.idx;
  marks[reader.idx]?.classList.remove("is-focus");
  reader.idx = i;
  const m = marks[i];
  const pg = +m.closest(".rpage").dataset.page;
  if (pg !== reader.page) showReaderPage(pg, { top: false });   // the clue lives on another page: turn to it
  m.classList.add("is-focus");
  const hl = reader.hls[i];
  const kind = hl.cat;
  fill($("#cat-note"), 
    h("div", { class: "k k-" + kind, text: CATS[kind].label + (hl.label && hl.label !== CATS[kind].label ? " · " + hl.label : "") }),
    h("div", { text: hl.note || "Worth a second look." }),
    h("div", { class: "nav" },
      h("button", { onclick: () => focusMark(reader.idx - 1, true), "aria-label": "Previous clue" }, "Back"),
      h("span", { text: (i + 1) + " of " + marks.length }),
      h("button", { onclick: () => focusMark(reader.idx + 1, true), "aria-label": "Next clue" }, "Next")));
  if (scroll) { reader.lockUntil = Date.now() + 900; scrollToMark(m); }
  if (changed && !instant) { setCatState("walk"); setTimeout(() => { if (catEl.dataset.state === "walk") setCatState("alert"); }, 620); setTimeout(() => { if (catEl.dataset.state === "alert") setCatState("idle"); }, 2600); }
  else if (instant) setCatState("alert");
  placeCat(m);
  wake();
}

let ticking = false;
scroller.addEventListener("scroll", () => {
  if (ticking || Date.now() < reader.lockUntil || !reader.marks.length) return;
  ticking = true;
  requestAnimationFrame(() => {
    ticking = false;
    const r = scroller.getBoundingClientRect(), line = r.top + r.height * readLine();
    let best = -1, bd = Infinity;
    reader.marks.forEach((m, i) => { if (m.closest(".rpage").hidden) return; const b = m.getBoundingClientRect(); const d = Math.abs((b.top + b.bottom) / 2 - line); if (d < bd) { bd = d; best = i; } });
    if (best !== reader.idx) focusMark(best, false);
    else placeCat(reader.marks[best]);
    wake();
  });
}, { passive: true });

document.addEventListener("keydown", (e) => {
  if (!reader.open) return;
  if (e.key === "Escape") return closeReader();
  if (/^(INPUT|TEXTAREA)$/.test(e.target.tagName) || e.metaKey || e.ctrlKey) return;
  if (e.key === "n" || e.key === "j") focusMark(reader.idx + 1, true);
  if (e.key === "p" || e.key === "k") focusMark(reader.idx - 1, true);
  if (e.key === "ArrowRight") goReaderPage(reader.page + 1);
  if (e.key === "ArrowLeft") goReaderPage(reader.page - 1);
});
addEventListener("resize", () => { if (reader.open && reader.marks[reader.idx]) placeCat(reader.marks[reader.idx]); });

/* ------------------------------------------------------------ boot */
mountTicks();
syncAlerts();
initMarket().then(() => { loadQuotes(); loadFeed(); });
setInterval(loadFeed, 60000);
setInterval(loadQuotes, 45000);
setInterval(() => {
  $$("[data-ts]").forEach((n) => { if (n.id !== "updated") n.textContent = ago(+n.dataset.ts); });
  const u = $("#updated"); if (u.dataset.ts && state.feed) u.textContent = "Live · " + state.feed.stories.length + " stories · " + ago(+u.dataset.ts);
}, 30000);
