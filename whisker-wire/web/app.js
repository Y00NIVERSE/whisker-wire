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
// A small mark on every link that leaves the app, so "Read here" reads as the one option that keeps you on Whisker Wire.
const extIcon = () => h("span", { class: "ext-ic", "aria-hidden": "true", text: "↗" });

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
  mem: null, drift: {}, editing: null,
  signals: null, showSells: false, openCalc: new Set(),
  revealed: new Set(),   // keys of cards that have already played their reveal + count-up once this session
};
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
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
  if (v === "memory") loadMemory();
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
  refreshStarters();
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
    const want = new URLSearchParams(location.search).get("market") || store.get("market", null) || state.mem?.markets?.[0] || "us";
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

/* ------------------------------------------------------------ Tick remembers */
// The watchlist lives on the server (so Tick can use it) with a spare copy in the browser.
function commitWatch() {
  store.set("watch", [...state.watch]);
  postJson("/api/memory", { op: "watch_set", symbols: [...state.watch] })
    .then((m) => { state.mem = m; if (state.view === "memory") renderMemory(); })
    .catch(() => { /* the local copy still works */ });
}

async function memOp(body) {
  const m = await postJson("/api/memory", body);
  state.mem = m;
  state.watch = new Set(m.watchlist);
  store.set("watch", m.watchlist);
  refreshStarters();   // "How are my stocks doing?" appears once there is something to ask about
  renderTickMine();
  return m;
}

async function loadMemory() {
  try {
    const m = await api("/api/memory");
    state.mem = m;
    const local = store.get("watch", []);
    if (!m.watchlist.length && local.length) await memOp({ op: "watch_set", symbols: local });   // one-time move from this browser
    else { state.watch = new Set(m.watchlist); store.set("watch", m.watchlist); }
    if (state.feed) renderWire();
    if (state.view === "memory") renderMemory();
  } catch { /* the app works without memory */ }
}

const dateOf = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
const EXPERIENCE = [["beginner", "New to this"], ["some", "Some experience"], ["experienced", "Experienced"]];

function memAbout(m) {
  const save = async (experience, markets) => { try { await memOp({ op: "profile", experience, markets }); renderMemory(); renderMarkets(); } catch (e) { flash(e.message); } };
  return h("section", { class: "mem-sec" },
    h("h2", { class: "subhead", text: "About you" }),
    h("p", { class: "small", text: "New to this adds plain-English explanations to Tick's answers. The markets you follow are preferred when Tick works out which listing you mean, and set your starting market." }),
    h("p", { class: "eyebrow gap", text: "Experience" }),
    h("div", { class: "chips" }, EXPERIENCE.map(([v, label]) => h("button", { class: "chip" + (m.experience === v ? " is-on" : ""), "aria-pressed": String(m.experience === v), onclick: () => save(m.experience === v ? "" : v, m.markets) }, label))),
    h("p", { class: "eyebrow gap", text: "Markets I follow" }),
    h("div", { class: "chips" }, state.markets.map((k) => { const on = m.markets.includes(k.id); return h("button", { class: "chip" + (on ? " is-on" : ""), "aria-pressed": String(on), onclick: () => save(m.experience || "", on ? m.markets.filter((x) => x !== k.id) : [...m.markets, k.id]) }, k.name); })));
}

function memWatch(m) {
  const input = h("input", { type: "text", placeholder: "Add a ticker, e.g. NVDA or 0700.HK", maxlength: "14", "aria-label": "Add a ticker to your watchlist", spellcheck: "false" });
  const msg = h("p", { class: "small", role: "status" });
  const set = async (symbols) => { try { await memOp({ op: "watch_set", symbols }); if (state.feed) renderWire(); renderMemory(); } catch (e) { msg.textContent = e.message; } };
  return h("section", { class: "mem-sec" },
    h("h2", { class: "subhead", text: "My watchlist" }),
    h("p", { class: "small", text: "The same list as on the wire. Ask Tick \"How are my stocks doing?\" and she will use it." }),
    m.watchlist.length ? h("div", { class: "chips" }, m.watchlist.map((s) => h("button", { class: "wtag", title: "Remove " + s, onclick: () => set(m.watchlist.filter((x) => x !== s)) }, s))) : h("p", { class: "small", text: "Nothing on your watchlist yet." }),
    h("form", { class: "mem-form row", onsubmit: (e) => { e.preventDefault(); const v = input.value.trim().toUpperCase(); if (v) set([...m.watchlist, v]); } }, input, h("button", { class: "ghost", type: "submit" }, "Add")),
    msg);
}

function driftEl(d) {
  return h("div", { class: "drift st-" + d.status },
    h("div", { class: "drift-head" }, h("span", { class: "drift-badge", text: d.label }), h("span", { class: "small mono", text: `${d.points} point${d.points === 1 ? "" : "s"} · checked ${ago(d.checked)}` })),
    d.breakdown.length ? h("ul", { class: "calc-list" }, d.breakdown.map((b) => h("li", {}, h("span", { text: b.label }), h("b", { class: "cn", text: "+" + b.pts })))) : h("p", { class: "small", text: "Nothing has moved against your reasons." }),
    h("ul", { class: "facts-list" }, d.facts.map((f) => h("li", { text: f }))),
    d.news.length > 0 && [h("p", { class: "blk-t", text: "Negative headlines since you wrote it" }), h("ul", { class: "news" }, d.news.map((n) => h("li", {}, h("a", { href: n.url }, n.title), h("span", { class: "nm", text: n.publisher || "" }))))],
    h("p", { class: "small", text: "4 or more points is under pressure, 2 to 3 is worth a look. Every point has a stated cause. This is a prompt to re-read your note, not a sell signal." }));
}

async function runDrift(t, btn) {
  btn.disabled = true; btn.textContent = "Checking…";
  try { const r = await memOp({ op: "check", id: t.id }); state.drift[t.id] = r.drift; } catch (err) { flash(err.message); }
  renderMemory(); renderTickMine();
}

const snapLine = (t) => {
  const s = t.snap;
  if (!s) return "No numbers were saved with this note.";
  const bits = [`price ${fmt.px(s.price, s.currency)}`];
  if (s.fpe) bits.push(`forward P/E ${s.fpe.toFixed(1)}`);
  if (s.rating) bits.push(`analysts ${s.rating.split(" - ").pop()}`);
  if (s.score != null) bits.push(`value read ${s.score}/100`);
  return "When you wrote it: " + bits.join(", ") + ".";
};

function memTheses(m) {
  const editing = m.theses.find((t) => t.id === state.editing);
  const f = {
    symbol: h("input", { type: "text", placeholder: "Ticker, e.g. TSLA or 0700.HK", maxlength: "12", "aria-label": "Ticker", spellcheck: "false", disabled: !!editing, value: editing?.symbol || "" }),
    note: h("textarea", { rows: "3", maxlength: String(m.limits.note), placeholder: "Why do you own or watch it? One or two sentences, in your own words.", "aria-label": "Your reason" }, editing?.note || ""),
    inv: h("input", { type: "text", maxlength: String(m.limits.invalidate_if), placeholder: "I would rethink if… (optional, e.g. sales fall two quarters in a row)", "aria-label": "What would change your mind", value: editing?.invalidate_if || "" }),
    below: h("input", { type: "number", step: "any", min: "0", placeholder: "Review if below (price)", "aria-label": "Review below price", value: editing?.review_below ?? "" }),
    above: h("input", { type: "number", step: "any", min: "0", placeholder: "Review if above (price)", "aria-label": "Review above price", value: editing?.review_above ?? "" }),
  };
  const msg = h("p", { class: "small", role: "status" });
  const submit = async (e) => {
    e.preventDefault();
    msg.textContent = editing ? "Saving…" : "Saving, and noting today's price…";
    try {
      await memOp({ op: "thesis_save", id: editing?.id, symbol: f.symbol.value, note: f.note.value, invalidate_if: f.inv.value, review_below: f.below.value, review_above: f.above.value });
      state.editing = null; flash("Note saved."); renderMemory();
    } catch (err) { msg.textContent = err.message; }
  };
  const card = (t) => {
    const cur = t.snap?.currency || "USD";
    const lines = [t.invalidate_if && ["I would rethink if: ", t.invalidate_if], t.review_below && ["Review if the price falls to ", fmt.px(t.review_below, cur)], t.review_above && ["Review if the price rises to ", fmt.px(t.review_above, cur)]].filter(Boolean);
    const check = h("button", { onclick: () => runDrift(t, check) }, state.drift[t.id] ? "Check again" : "Check drift");
    return h("article", { class: "tcard" },
      h("div", { class: "pk-head" }, h("span", { class: "pk-sym", text: t.symbol }), h("span", { class: "pk-name", text: t.name || "" }), h("span", { class: "small mono", text: `written ${dateOf(t.created)}` })),
      h("p", { class: "tc-note", text: t.note }),
      lines.map(([a, b]) => h("p", { class: "small" }, h("b", { text: a }), b)),
      h("p", { class: "small mono", text: snapLine(t) }),
      h("div", { class: "pk-acts" }, check,
        h("button", { onclick: () => { state.editing = t.id; renderMemory(); $("#memory-body .mem-form.thesis")?.scrollIntoView({ behavior: "smooth", block: "center" }); } }, "Edit"),
        h("button", { onclick: async () => { if (!confirm(`Delete your note on ${t.symbol}?`)) return; try { await memOp({ op: "thesis_delete", id: t.id }); delete state.drift[t.id]; renderMemory(); } catch (err) { flash(err.message); } } }, "Delete")),
      state.drift[t.id] && driftEl(state.drift[t.id]));
  };
  return h("section", { class: "mem-sec" },
    h("h2", { class: "subhead", text: "My thesis notes" }),
    h("p", { class: "small", text: "Write down why you own or watch something, and what would change your mind. Tick saves today's price and numbers with it, so later she can check whether your reasons still hold. Notes are never shared." }),
    h("form", { class: "mem-form thesis", onsubmit: submit },
      h("div", { class: "row" }, f.symbol), f.note, f.inv, h("div", { class: "row two" }, f.below, f.above),
      h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, editing ? "Update note" : "Save note"), editing && h("button", { class: "ghost", type: "button", onclick: () => { state.editing = null; renderMemory(); } }, "Cancel")),
      msg),
    m.theses.length ? h("div", { class: "tlist" }, m.theses.map(card)) : h("p", { class: "small", text: "No notes yet." }));
}

function memData(m) {
  return h("section", { class: "mem-sec" },
    h("h2", { class: "subhead", text: "Your data" }),
    h("p", { class: "small" }, "Stored in ", h("span", { class: "mono", text: m.location }), ". It is on this computer only, and outside the project folder so a cloud-synced folder does not copy it."),
    h("div", { class: "chips" },
      h("button", { class: "ghost", onclick: () => {
        const a = h("a", { download: "tick-memory.json" });
        a.href = URL.createObjectURL(new Blob([JSON.stringify(m, null, 2)], { type: "application/json" }));
        a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      } }, "Export everything"),
      h("button", { class: "ghost danger", onclick: async () => {
        if (!confirm("Forget everything Tick remembers about you: your profile, watchlist and all notes? This cannot be undone.")) return;
        try { await memOp({ op: "forget", confirm: "forget" }); state.drift = {}; state.editing = null; if (state.feed) renderWire(); renderMemory(); flash("Done. Tick has forgotten everything."); } catch (e) { flash(e.message); }
      } }, "Forget everything")));
}

function renderMemory() {
  const m = state.mem, box = $("#memory-body");
  if (!m) return fill(box, h("p", { class: "empty", text: "Tick's memory is not available right now." }));
  fill(box, h("p", { class: "small mem-warn", text: "Please do not enter holdings amounts, account numbers or passwords. Tick does not need them." }), memAbout(m), memWatch(m), memTheses(m), memData(m));
}

/* ------------------------------------------------------------ Ask Tick (chat) */
const ask = { history: [], busy: false, asked: false };
const askLog = $("#ask-log"), askIn = $("#ask-in");
const EXAMPLE_CO = { us: "Tesla", cn: "Alibaba", hk: "Tencent", sg: "DBS", uk: "Shell", jp: "Toyota", in: "Reliance", au: "BHP", ca: "Shopify", eu: "ASML" };
const starterChips = () => [`What's moving in ${marketInfo().name} today?`, `Is ${EXAMPLE_CO[state.market] || "Tesla"} undervalued?`,
  state.watch.size || state.mem?.theses?.length ? "How are my stocks doing?" : "What is a P/E ratio?", "How should a beginner start investing?"];

function avatar() {
  const a = h("span", { class: "msg-cat", "aria-hidden": "true" });
  a.append($("#tick-tpl").content.cloneNode(true));
  return a;
}
const bubble = (role, ...kids) => h("div", { class: "msg msg-" + role }, role === "tick" && avatar(), h("div", { class: "bubble" }, kids));

function renderAskChips(list) {
  fill($("#ask-chips"), ...list.map((q) => h("button", { class: "chip", type: "button", onclick: () => askTick(q) }, q)));
}
function renderHomeChips() {
  fill($("#home-chips"), ...starterChips().map((q) => h("button", { class: "chip", type: "button", onclick: () => askTick(q) }, q)));
}
// The homepage bar always shows starter questions; the pop-out swaps to follow-ups once a conversation begins.
function refreshStarters() { renderHomeChips(); if (!ask.asked) renderAskChips(starterChips()); }

// Answers may quote web text, so they are built from DOM nodes only. [1] style citations become links to the sources.
function richText(text, sources) {
  const url = (n) => sources.find((s) => s.n === n)?.url;
  const inline = (line) => line.split(/(\[\d+\])/).map((part) => {
    const m = /^\[(\d+)\]$/.exec(part);
    return m && url(+m[1]) ? h("a", { class: "cite", href: url(+m[1]), title: sources.find((s) => s.n === +m[1]).title }, part) : part;
  });
  const out = [];
  let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) { list = null; continue; }
    if (/^[-•]\s+/.test(line)) {
      if (!list) { list = h("ul", {}); out.push(list); }
      list.append(h("li", {}, inline(line.replace(/^[-•]\s+/, ""))));
    } else { list = null; out.push(h("p", {}, inline(line))); }
  }
  return out;
}

function blockEl(b, sources) {
  if (b.type === "p") return h("p", { text: b.text });
  if (b.type === "note") return h("p", { class: "note", text: b.text });
  if (b.type === "text") return richText(b.text, sources);
  if (b.type === "stats") return h("dl", { class: "stats" }, b.items.map(([k, v]) => [h("dt", { text: k }), h("dd", { text: v })]));
  if (b.type === "ul") return [b.title && h("p", { class: "blk-t", text: b.title }), h("ul", {}, b.items.map((t) => h("li", { text: t })))];
  if (b.type === "news") {
    return [h("p", { class: "blk-t", text: b.title }), h("ul", { class: "news" }, b.items.map((n) => h("li", {},
      h("a", { href: n.url }, n.title),
      h("span", { class: "nm" }, (n.wire ? "Whisker Wire · " : "") + (n.publisher || ""),
        (n.tags || []).map((t) => h("span", { class: "sg sg-" + (n.dir === "none" ? "flag" : n.dir), text: t }))))))];
  }
  return null;
}

function replyEl(r) {
  const body = [r.blocks.map((b) => blockEl(b, r.sources || []))];
  if (r.google) body.push(h("p", {}, h("a", { class: "ghost gbtn", href: r.google }, "Search Google for this")));
  if (r.sources?.length) {
    body.push(h("p", { class: "srcline" }, "Sources: ", r.sources.slice(0, 6).map((s) => h("a", { href: s.url, title: s.engine + ": " + s.title }, `[${s.n}] ${s.title.length > 32 ? s.title.slice(0, 30) + "…" : s.title}`))));
  }
  return bubble("tick", body);
}

const plain = (r) => r.blocks.map((b) => b.text || (b.items || []).map((i) => (typeof i === "string" ? i : i.title || i.join?.(" "))).join(" ")).join(" ").slice(0, 600);

async function askTick(q) {
  q = (q || "").trim();
  if (!q || ask.busy) return;
  openTick("ask");   // the conversation happens in Tick's pop-out, wherever the question came from
  ask.busy = true; ask.asked = true;
  $("#ask-go").disabled = true;
  askIn.value = "";
  askLog.append(bubble("user", h("p", { text: q })));
  const wait = bubble("tick", h("span", { class: "typing", "aria-hidden": "true" }, h("i"), h("i"), h("i")), h("span", { class: "small", text: " Checking Yahoo Finance, Google News, Bing and Wikipedia…" }));
  askLog.append(wait);
  askLog.scrollTop = askLog.scrollHeight;
  try {
    const r = await postJson("/api/chat", { q, market: state.market, history: ask.history.slice(-6) });
    ask.history.push({ role: "user", text: q }, { role: "tick", text: plain(r) });
    const reply = replyEl(r);
    wait.replaceWith(reply);
    renderAskChips(r.followups || []);
    // Show the start of the new answer, not its tail: people read from the top.
    askLog.scrollTop += reply.getBoundingClientRect().top - askLog.getBoundingClientRect().top - 6;
    return;
  } catch (e) {
    wait.replaceWith(bubble("tick", h("p", { text: e.message || "Something went wrong. Try again in a moment." })));
    askLog.scrollTop = askLog.scrollHeight;
  } finally {
    ask.busy = false;
    $("#ask-go").disabled = false;
  }
}

function askAbout(q) {
  askTick(q);
}

$("#home-ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#home-ask-in").value;
  if (v.trim()) { $("#home-ask-in").value = ""; askTick(v); }
});

$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); askTick(askIn.value); });

async function initAsk() {
  askLog.append(bubble("tick", h("p", { text: "Hi, I'm Tick. Ask me about a stock, a money term, or how markets work, and I'll look it up. If it isn't about money, I'll point you to Google." })));
  refreshStarters();
  let mode = "";
  try {
    const s = await api("/api/chat-status");
    mode = s.smart
      ? "Smart answers on: Claude reads live results from Yahoo Finance, Google News, Bing News and Wikipedia."
      : "Basic mode: I search Yahoo Finance, Google News, Bing News and Wikipedia and sum up what I find. Add an Anthropic key for fuller answers (see the README).";
  } catch { /* leave it blank */ }
  $$(".ask-mode").forEach((n) => { n.textContent = mode; });
}

/* ------------------------------------------------------------ entrance motion (once per card, ever) */
function countUp(el, target, ms = 650) {
  if (!el) return;
  if (reduceMotion.matches || !Number.isFinite(target)) { el.textContent = String(target); return; }
  const t0 = performance.now();
  const tick = (now) => {
    const p = Math.min(1, (now - t0) / ms);
    el.textContent = String(Math.round(target * (1 - (1 - p) ** 3)));   // ease-out cubic
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// Wraps a freshly built card: plays a rise-in the first time a key is seen, and skips straight to
// the settled state on every later render (poll refreshes, page changes) so nothing keeps re-animating.
function revealed(key, el, { countTo, countEl } = {}) {
  if (state.revealed.has(key) || reduceMotion.matches) {
    el.classList.add("reveal-done");
    return el;
  }
  el.classList.add("reveal");
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      state.revealed.add(key);
      requestAnimationFrame(() => el.classList.add("reveal-in"));
      if (countEl && Number.isFinite(countTo)) { countEl.textContent = "0"; countUp(countEl, countTo); }
      io.disconnect();
    }
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.15 });
  io.observe(el);
  return el;
}

/* ------------------------------------------------------------ the ticker tape (header) */
function tapeItem(s) {
  const dirCls = s.dir === "bull" ? "up" : s.dir === "bear" ? "down" : "flat";
  return h("span", { class: "tape-item" },
    h("b", { class: "mono", text: String(s.score) }),
    s.tickers[0] && h("span", { class: "tape-tk mono", text: s.tickers[0] }),
    h("span", { class: "tape-dir " + dirCls, "aria-hidden": "true", text: s.dir === "bull" ? "▲" : s.dir === "bear" ? "▼" : "•" }),
    h("span", { class: "tape-t", text: s.title }));
}

function renderTape() {
  const track = $("#tape-track");
  if (!state.feed || !track) return;
  const items = state.feed.stories.filter((s) => s.kinds.some(kindOn)).slice(0, 16);
  if (!items.length) { $("#tape").hidden = true; return; }
  $("#tape").hidden = false;
  // two copies back to back so translateX(-50%) loops seamlessly; duration scales with content so speed stays steady
  fill(track, items.map(tapeItem), items.map(tapeItem));
  track.style.animationDuration = Math.max(26, items.length * 3.4) + "s";
}

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
  const tags = [...state.watch].map((t) => h("button", { class: "wtag", title: "Remove " + t, onclick: () => { state.watch.delete(t); commitWatch(); renderWire(); } }, t));
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
  h("span", { class: "n", text: String(s.score) }), h("span", { class: "pts", text: "pts" }));
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
        h("button", { class: "read", title: "Open the full article right here, with Tick's highlights", onclick: () => openReader({ story: s }) },
          h("span", { class: "read-t", text: "Read here" }), h("span", { class: "read-ic", "aria-hidden": "true", text: "→" })),
        h("button", { class: "ext", onclick: () => askAbout(`What does this mean for the stock: ${s.title}`) }, "Ask Tick"),
        h("button", { class: "more-btn", "aria-label": "Show more about this story", onclick: (e) => { const on = e.target.closest(".story").classList.toggle("is-open"); e.target.textContent = on ? "Less" : "More"; } }, "More"),
        sec && h("a", { class: "ext", href: sec.url, title: "The company's own filings, straight from the SEC" }, sec.label, extIcon()),
        h("a", { class: "ext", href: s.link, title: isGoogle(s.link) ? "Opens through Google News, which then forwards you to the publisher" : "Leaves Whisker Wire and opens the publisher's own site" }, isGoogle(s.link) ? "Original (via Google News)" : "Original", extIcon()),
        h("a", { class: "ext", href: "https://web.archive.org/web/2/" + s.link, title: "Leaves Whisker Wire and opens an archived copy" }, "Archive copy", extIcon()),
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
  fill($("#wire-list"), ...list.slice(from, from + PER.wire).map((s) => {
    const card = storyEl(s, newIds.has(s.id));
    return revealed("wire:" + s.id, card, { countTo: s.score, countEl: card.querySelector(".scorebtn .n") });
  }));
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
    onclick: () => { kindOn(k) ? state.off.add(k) : state.off.delete(k); store.set("kindsOff", [...state.off]); state.page.wire = 1; renderKinds(); renderWire(); renderTape(); },
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
    renderKinds(); renderWire(); renderHealth(feed); renderTape();
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
document.addEventListener("visibilitychange", () => { const t = $("#tape-track"); if (t) t.style.animationPlayState = document.hidden ? "paused" : "running"; });   // do not spend battery animating a tab nobody is looking at

$("#watch-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#watch-in").value.trim().toUpperCase().replace(/[^A-Z0-9.&-]/g, "");
  if (!v) return flash("Type a ticker symbol first, like NVDA.");
  $("#watch-in").value = "";
  if (state.watch.has(v)) return flash(`${v} is already on your watchlist.`);
  state.watch.add(v); commitWatch();
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
      h("div", { class: "n" }, h("span", { text: String(p.score) }), h("small", { text: "/100" })),
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
      h("button", { onclick: () => { state.watch.add(p.symbol); commitWatch(); flash(p.symbol + " added to your watchlist."); renderWire(); } }, "Watch")),
    detail);
}

function renderRadar() {
  fill($("#radar-filters"), ...radarLists().map(([id, label]) =>
    h("button", { class: "chip" + (state.radarList === id ? " is-on" : ""), "aria-pressed": String(state.radarList === id), onclick: () => { state.radarList = id; state.page.radar = 1; renderRadar(); } }, label)));
  const rows = state.picks.filter((p) => state.radarList === "all" || p.list === state.radarList);
  const pages = Math.max(1, Math.ceil(rows.length / PER.radar));
  state.page.radar = Math.min(state.page.radar, pages);
  const from = (state.page.radar - 1) * PER.radar;
  fill($("#radar-list"), ...(rows.length ? rows.slice(from, from + PER.radar).map((p) => {
    const card = pickEl(p);
    return revealed("radar:" + p.symbol + ":" + p.list, card, { countTo: p.score, countEl: card.querySelector(".scoreblock .n > span") });
  }) : [h("p", { class: "empty", text: "Nothing in this list right now." })]));
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
  document.body.classList.add("reader-open");
  if (typeof closeTick === "function") closeTick(false);
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
  document.body.classList.remove("reader-open");
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

async function readInput(v) {
  if (/^https?:\/\/\S+$/i.test(v)) return loadUrl(v, "");
  const paras = v.split(/\n+/).map((x) => x.trim()).filter(Boolean);
  await render({ title: paras[0].length < 140 ? paras[0] : "Pasted text", url: "", paragraphs: paras.length > 1 ? paras.slice(paras[0].length < 140 ? 1 : 0) : paras });
}
$("#paste-go").addEventListener("click", async () => {
  const v = $("#paste-in").value.trim();
  if (v) await readInput(v);
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

/* ------------------------------------------------------------ Tick pops out (bottom right) */
const fab = $("#tick-fab"), tickPop = $("#tick-pop");
const tp = { open: false, tab: "ask" };
const TP_TABS = ["ask", "mine", "read"];

function showTickTab(name) {
  if (!TP_TABS.includes(name)) return;
  tp.tab = name;
  for (const t of TP_TABS) {
    const on = t === name;
    const tab = $("#tp-tab-" + t);
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    $("#tp-" + t).hidden = !on;
  }
  if (name === "mine") renderTickMine();
}

function openTick(tab) {
  if (reader.open) return;
  if (tab) showTickTab(tab);
  if (tp.open) return;
  tp.open = true;
  tickPop.hidden = false;
  fab.setAttribute("aria-expanded", "true");
  fab.classList.add("is-open");
  fab.classList.remove("hint");
  requestAnimationFrame(() => { if (tp.tab === "ask") $("#ask-in").focus({ preventScroll: true }); });
}

function closeTick(refocus = true) {
  if (!tp.open) return;
  tp.open = false;
  tickPop.hidden = true;
  fab.setAttribute("aria-expanded", "false");
  fab.classList.remove("is-open");
  if (refocus) fab.focus({ preventScroll: true });
}

fab.addEventListener("click", () => {
  fab.classList.remove("pop"); void fab.offsetWidth; fab.classList.add("pop");   // a little bounce: he is happy to see you
  tp.open ? closeTick(false) : openTick();
});
$("#tp-close").addEventListener("click", () => closeTick());
$$(".tp-tabs [role=tab]").forEach((b) => b.addEventListener("click", () => showTickTab(b.dataset.tp)));
$(".tp-tabs").addEventListener("keydown", (e) => {
  const i = TP_TABS.indexOf(tp.tab);
  const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? TP_TABS.length - 1 : null;
  if (next == null) return;
  e.preventDefault();
  showTickTab(TP_TABS[(next + TP_TABS.length) % TP_TABS.length]);
  $("#tp-tab-" + tp.tab).focus();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && tp.open && !reader.open) closeTick(); });

// Remembers: a compact view of what he knows, with quick drift checks. Editing happens on the full page.
function renderTickMine() {
  const box = $("#tp-mine-body"), m = state.mem;
  if (!box) return;
  if (!m) return fill(box, h("p", { class: "small", text: "Tick's memory is not available right now." }));
  const you = [EXPERIENCE.find(([v]) => v === m.experience)?.[1], m.markets.length ? "follows " + m.markets.map((id) => state.markets.find((x) => x.id === id)?.name || id).join(", ") : null].filter(Boolean);
  const noteRow = (t) => {
    const btn = h("button", { class: "ghost", onclick: () => runDrift(t, btn) }, state.drift[t.id] ? "Check again" : "Check drift");
    return h("div", { class: "tp-note" },
      h("div", { class: "pk-head" }, h("span", { class: "pk-sym", text: t.symbol }), h("span", { class: "small mono", text: `written ${dateOf(t.created)}` })),
      h("p", { class: "small", text: t.note.length > 130 ? t.note.slice(0, 127) + "…" : t.note }),
      btn, state.drift[t.id] && driftEl(state.drift[t.id]));
  };
  fill(box,
    h("p", { class: "small", text: you.length ? "You told Tick: " + you.join(" · ") : "You have not told Tick about yourself yet." }),
    m.watchlist.length > 0 && [h("p", { class: "blk-t", text: "Your watchlist" }),
      h("div", { class: "chips" }, m.watchlist.map((s) => h("span", { class: "tk", text: s }))),
      h("p", {}, h("button", { class: "chip", onclick: () => { showTickTab("ask"); askTick("How are my stocks doing?"); } }, "How are my stocks doing?"))],
    m.theses.length
      ? [h("p", { class: "blk-t", text: "Thesis notes" }), h("div", { class: "tp-notes" }, m.theses.map(noteRow))]
      : h("p", { class: "small", text: "No thesis notes yet. Write why you own or watch a stock, and Tick can tell you later whether your reasons still hold." }),
    h("p", {}, h("button", { class: "ghost", onclick: () => { closeTick(false); setView("memory"); } }, "See and edit everything")));
}

$("#tp-read-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const v = $("#tp-read-in").value.trim();
  if (!v) return;
  $("#tp-read-in").value = "";
  openReader({});          // the reader has its own Tick, so the pop-out closes
  showPaste(false);
  await readInput(v);
});

// First visit: a little speech bubble says who he is, then tucks away.
if (!store.get("fabSeen", false)) {
  fab.classList.add("hint");
  setTimeout(() => { fab.classList.remove("hint"); store.set("fabSeen", true); }, 9000);
}

/* ------------------------------------------------------------ boot */
mountTicks();
syncAlerts();
initAsk();
// Tick's memory is a fast local call, so load it first: it can set the starting market and the watchlist.
loadMemory().finally(() => initMarket().then(() => { loadQuotes(); loadFeed(); }));
setInterval(loadFeed, 60000);
setInterval(loadQuotes, 45000);
setInterval(() => {
  $$("[data-ts]").forEach((n) => { if (n.id !== "updated") n.textContent = ago(+n.dataset.ts); });
  const u = $("#updated"); if (u.dataset.ts && state.feed) u.textContent = "Live · " + state.feed.stories.length + " stories · " + ago(+u.dataset.ts);
}, 30000);
