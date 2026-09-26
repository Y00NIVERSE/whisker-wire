# Whisker Wire

Fast, unfiltered market information for newer traders, with **Tick**, a tabby who reads articles with you and highlights what matters.

```
python whisker-wire/server.py        # then open http://127.0.0.1:8787
```

Python 3.10+, standard library only. No accounts, no analytics, no request logging. Binds to localhost.

## What it does

- **The Wire**: about 22 independent sources (mainstream, analyst, wire, independent, government, community, plus targeted searches for insider buys, short reports, activists, guidance changes, FDA news). Duplicates merge into one story that keeps every publisher. Each story is scored, labelled *Corroborated* or *Single source*, and tagged *Not in big headlines* when it has a strong signal that CNBC, MarketWatch, Yahoo Finance and Nasdaq are not carrying yet.
  - **Click any score** to see exactly how its points were built.
  - **Urgent has to be confirmed**: 8 or more points and two or more outlets (or one major or official source). A single lesser-known outlet stays at Watch until confirmed.
  - **Sources and How scoring works** are buttons above the wire (and a nav tab), so they are one tap away on any screen size.
  - Jargon (P/E, Form 4, guidance...) has a dotted underline and a plain-English tooltip everywhere.
  - Insider and filing stories link straight to the company's filings on SEC.gov.
  - On phones: a "Start here" strip with the top three in plain English, and compact cards (tap More for the rest).
- **Value Radar**: Yahoo's undervalued and crowded-short screens re-scored 0 to 100, with plain-English "why it looks cheap" and "how it could be a trap" for every pick.
- **Filings**: insider open-market purchases (Form 4) and Schedule 13D stakes straight from the SEC. One in-app step to switch on, see below.
- **Tick**: open any story (or paste text or a link). Google News links are decoded so the publisher's page opens; paywalled pages fall back to the headline plus paste. She highlights bullish clues, red flags, key numbers, catalysts and fine print, follows you as you scroll, explains each in beginner language, and underlines jargon. Keys: `n` next, `p` back, `Esc` close. Tap Tick to fold her note. **Serious mode** (in Sources) hides the mascot artwork but keeps the notes.
- **Track record**: every Urgent or Watch story that names a stock is logged with its price and the S&P 500's, then measured 1 and 5 trading days later. It shows results only after 20 measured stories, and says so plainly until then. Stored in `data/track.db` on your machine.

## Turn on SEC filings

The SEC requires automated requests to identify who is asking. Open the **Filings** tab, enter your name and email, and press *Turn on filings*. It is saved only in `whisker-wire/sec_contact.txt` (git-ignored) and sent only to sec.gov. You can also create that file by hand with one line: `Your Name you@example.com`.

## How scoring works (no hidden ranking)

`points = top 3 signal weights + fresh (0-3) + other publishers (0-3) + ticker found (1) - 2 if the headline is a question`.
Urgent is 8 or more points and confirmed; Watch is 5 to 7 (or 8 or more but unconfirmed). Signal definitions live in `signals.py`, and the browser uses the same file, so the wire and Tick agree. You can turn source types on or off in the UI; nothing is ranked down for its politics.

## Limits, stated plainly

- **Public information is priced in fast.** This finds things earlier than a headline scan, not before professionals with faster feeds. It is not a promise of returns. Never trade on non-public information: that is illegal.
- **Tick reads keywords and numbers, not meaning.** She will miss subtle things and can highlight a sentence that is not important. Verify before acting.
- **Some pages cannot be read in the app**: paywalled, script-rendered, or publishers that block automated readers. Tick then analyses the headline and asks you to paste the text. Google News links are decoded through an unofficial route that Google could change.
- Yahoo endpoints are unofficial and may change. Feeds can be delayed. Any single source can be down (see Source health in the Sources panel).
- Education, not financial advice.

## Development

```
python -m unittest discover -s whisker-wire/tests -v     # offline tests (32)
```

Design rules are in `DESIGN.md` (awesome-design-md format, with taste-skill dials).
