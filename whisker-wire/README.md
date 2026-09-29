# Whisker Wire

Fast, unfiltered market information for newer traders, with **Tick**, a tabby who reads articles with you and highlights what matters.

```
python whisker-wire/server.py        # then open http://127.0.0.1:8787
```

Python 3.10+, standard library only. No accounts, no analytics, no request logging. Binds to localhost.

**Want to host this for other people, with free accounts and a mailing list?** See [DEPLOY.md](DEPLOY.md).
That mode is opt-in (nothing changes unless you set it up). The wire, Value Radar and filings stay open
to any visitor; a free account is only asked for at the two personal features, Ask Tick and Tick
remembers, each kept separately per person, plus a newsletter checkbox at signup — the "no accounts"
line above describes local mode only.

## What it does

- **Ten markets**, chosen from the pills under the logo: United States, China, Hong Kong, Singapore, United Kingdom, Japan, India, Australia, Canada and Europe. Each has its own news feeds (81 in total: 42 outlets plus 39 targeted searches), index strip, tickers in the local format (`0700.HK`, `D05.SI`, `VOD.L`), prices in the local currency, and Value Radar. Your choice is remembered and can be shared as a link (`?market=hk`). China's state media outlets are labelled so you can weigh them or switch them off.
- **The Wire**: mainstream, analyst, wire, independent, government, community and state-media feeds, plus targeted searches for insider buys, short reports, activists, guidance changes and FDA news. Duplicates merge into one story that keeps every publisher. Each story is scored, labelled *Corroborated* or *Single source*, and tagged *Not in big headlines* when it has a strong signal that the big outlets are not carrying yet. Searches must mention something local in the headline, so a London trust's buyback notice cannot leak into the Hong Kong wire.
  - **Short pages**: the wire, Value Radar, filings and the reader all use numbered pages instead of one long scroll. In the reader, Tick's clues carry across pages (Next clue turns the page for you); arrow keys turn pages too.
  - **What it is, at a glance**: a plain-English intro sits at the top of the first page (collapsible; the headline always stays).
- **Value Radar**: for the US, Yahoo's undervalued and crowded-short screens; for every other market, the largest companies on the local exchanges (via Yahoo's screener). All are re-scored 0 to 100 with plain-English "why it looks cheap" and "how it could be a trap" for every pick, in the local currency.
- **Filings**: for the US, insider open-market purchases (Form 4) and Schedule 13D stakes straight from the SEC (one in-app step to switch on, see below). For other markets, links to the official announcement portals (HKEXnews, SGX, London RNS, CNINFO, TDnet, NSE/BSE, ASX, SEDAR+ and more), since only the US filings are read automatically.
- **Tick pops out of the bottom-right corner of every page.** Click him and a panel opens with everything he can do: **Ask** (the chat), **Remembers** (what he knows about you, with one-tap thesis-drift checks) and **Read** (paste an article or link and he reads it with you). Esc closes him. The reader has its own Tick, so the pop-out steps aside while you read.
- **Ask Tick** (the bar under the intro, and the Ask tab in the pop-out): ask about a stock, a money term, an index, a coin, or how markets work. Tick looks it up live from Yahoo Finance (prices, valuation, analyst view), Google News, Bing News and Wikipedia, plus this app's own scored stories, and answers in plain English with sources. Questions that are not about money get a friendly nudge to Google instead. Every story also has an **Ask Tick** button that explains what its headline signals. Tick never tells you to buy or sell; for "should I buy X" she gives the numbers and the questions to ask yourself.
- **Tick**: open any story (or paste text or a link). Google News links are decoded so the publisher's page opens; paywalled pages fall back to the headline plus paste. She highlights bullish clues, red flags, key numbers, catalysts and fine print, follows you as you scroll, explains each in beginner language, and underlines jargon. Keys: `n` next, `p` back, `Esc` close. Tap Tick to fold her note. **Serious mode** (in Sources) hides the mascot artwork but keeps the notes.
- **Tick remembers** (the tab of that name): a small memory you can see and edit yourself. It holds your experience level, the markets you follow, a watchlist, and **thesis notes**: why you own or watch a stock, what would change your mind, and optional price lines to review at. When you save a note Tick records that day's price, forward P/E, analyst view and value read. Later, **Check drift** compares the note with today: price move, P/E, analyst view, value read, headlines published since you wrote it, and whether your price lines were crossed. It is a transparent points system (every point has a stated cause; 4+ is "under pressure", 2 to 3 is "worth a look") and a prompt to re-read your reasons, not a sell signal. Ask Tick "How are my stocks doing?", or about a stock you wrote a note on, and she uses it.
- **Track record** (US stories only, since it is measured against the S&P 500): every Urgent or Watch story that names a stock is logged with its price and the S&P 500's, then measured 1 and 5 trading days later. It shows results only after 20 measured stories, and says so plainly until then. Stored in `data/track.db` on your machine.

## Ask Tick: two modes

- **Basic mode (default, no account or key):** Tick assembles the answer herself. Live numbers, this app's value read (with the ways it could go wrong), headlines tagged by what they mean, a plain-English definition, and general education for beginner questions. It is grounded and fast, but it cannot reason about anything it did not find.
- **Smart mode (optional):** with an Anthropic API key, Claude writes the answer from the same retrieved sources, cites them like [1], and decides for itself whether a question is about money. To turn it on, either set `ANTHROPIC_API_KEY`, or put the key on one line in `whisker-wire/anthropic_key.txt` (git-ignored), then restart. `TICK_MODEL` overrides the model (default `claude-sonnet-5`). The key stays on the server and is never sent to the browser. If Claude is unavailable, Tick falls back to basic mode and says so.

Privacy: there is no account. Your question goes to the search sources above to find an answer, and, only in smart mode, to Anthropic along with the headlines Tick found. Rate-limited to 30 questions per 10 minutes.

What Tick will not do: scrape Google's results page (it is blocked and against Google's terms; she uses Google News RSS, Bing News RSS, Yahoo and Wikipedia, and links to a Google search when a question is not about money), give personalised buy or sell orders, or invent a price she did not find.

## Tick remembers: what is stored, and where

- **Only what you type:** experience level, followed markets, watchlist tickers, and thesis notes (your words, your price lines, and a snapshot of the numbers on the day). No holdings amounts, no account details, no AI-generated "memories". Please do not type any.
- **Where:** one SQLite file, `tick_memory.db`, in your per-user app-data folder (`%LOCALAPPDATA%\WhiskerWire` on Windows, `~/Library/Application Support/WhiskerWire` on macOS, `~/.local/share/WhiskerWire` on Linux; override with `WHISKER_WIRE_DATA`). It is deliberately **not** in the project folder, because that folder is often synced to OneDrive or Dropbox. It is not encrypted; anyone with access to your user account can read it.
- **Who sees it:** nobody. Notes, price lines and the watchlist are never sent to a search engine or an AI service. In smart mode Claude receives only your self-described experience level and followed markets, and your note is added to the answer on your screen afterwards, by this app. There is a test for exactly this.
- **Control:** every item is editable on the page, **Export everything** downloads it as JSON, and **Forget everything** deletes it and compacts the file so deleted text is not left inside it.
- The wire's watchlist and this one are the same list; existing browser watchlists move over automatically the first time.
- Limits: 50 tickers, 30 notes, 600 characters per note.

## Turn on SEC filings

The SEC requires automated requests to identify who is asking. Open the **Filings** tab, enter your name and email, and press *Turn on filings*. It is saved only in `whisker-wire/sec_contact.txt` (git-ignored) and sent only to sec.gov. You can also create that file by hand with one line: `Your Name you@example.com`.

## How scoring works (no hidden ranking)

`points = top 3 signal weights + fresh (0-3) + other publishers (0-3) + ticker found (1) - 2 if the headline is a question`.
Urgent is 8 or more points and confirmed; Watch is 5 to 7 (or 8 or more but unconfirmed). Signal definitions live in `signals.py`, and the browser uses the same file, so the wire and Tick agree. You can turn source types on or off in the UI; nothing is ranked down for its politics.

## Limits, stated plainly

- **Public information is priced in fast.** This finds things earlier than a headline scan, not before professionals with faster feeds. It is not a promise of returns. Never trade on non-public information: that is illegal.
- **Tick reads keywords and numbers, not meaning.** She will miss subtle things and can highlight a sentence that is not important. Verify before acting.
- **Some pages cannot be read in the app**: paywalled, script-rendered, or publishers that block automated readers. In a test of 54 stories across the non-US markets 43 opened; Japan is the weakest (The Japan Times refuses automated readers), so Japanese stories often fall back to the headline plus paste. Tick then analyses the headline and asks you to paste the text. Google News links are decoded through an unofficial route that Google could change.
- Non-US screens need a short-lived Yahoo session that is fetched automatically; it and every Yahoo endpoint here are unofficial and may change. Europe combines several exchanges and includes some US names that also trade there; London prices are in pence.
- Yahoo endpoints are unofficial and may change. Feeds can be delayed. Any single source can be down (see Source health in the Sources panel).
- **Basic-mode Tick is not an analyst.** She matches your question to a company by name, so unusual names can pick the wrong stock (she shows what she matched; a ticker such as `D05.SI` is safest). Smart mode has been tested only against a mocked Claude, not a live key.
- Education, not financial advice.

## Development

```
python -m unittest discover -s whisker-wire/tests -v     # offline tests (157)
```

Design rules are in `DESIGN.md` (awesome-design-md format, with taste-skill dials).
