# Whisker Wire

Fast, unfiltered market information for newer traders, with **Tick**, a tabby who reads articles with you and highlights what matters.

```
python whisker-wire/server.py        # then open http://127.0.0.1:8787
```

Python 3.10+, standard library only. No accounts, no analytics, no request logging. Binds to localhost.

## What it does

- **The Wire**: about 22 independent sources (mainstream, analyst, wire, independent, government, community, plus targeted searches for insider buys, short reports, activists, guidance changes, FDA news). Duplicates merge into one story that keeps every publisher. Each story is scored, labelled *Corroborated* or *Single source*, and flagged *Under the radar* when it has a strong signal that none of the big headline sites carry yet.
- **Value Radar**: Yahoo's undervalued and crowded-short screens re-scored 0 to 100, with plain-English "why it looks cheap" and "how it could be a trap" for every pick.
- **Filings**: insider open-market purchases (Form 4) and Schedule 13D stakes straight from the SEC. Needs your contact, see below.
- **Tick**: open any story (or paste text or a link). She highlights bullish clues, red flags, key numbers, catalysts and fine print, follows you as you scroll, explains each in beginner language, and underlines jargon with definitions. Keys: `n` next, `p` back, `Esc` close. Tap Tick to fold her note away.

## Turn on SEC filings

The SEC requires automated requests to identify who is asking. Create `whisker-wire/sec_contact.txt` (git-ignored) with one line:

```
Your Name your.email@example.com
```

Restart the server. The details are sent only to sec.gov.

## How scoring works (no hidden ranking)

`score = top 3 signal weights + recency (0-3) + other publishers (0-3) + ticker found (1) - 2 if the headline is a question`.
Urgent is 8 or more, Watch is 5 to 7. Signal definitions live in `signals.py`, and the browser uses the same file, so the wire and Tick agree. You can turn source types on or off in the UI; nothing is ranked down for its politics.

## Limits, stated plainly

- **Public information is priced in fast.** This finds things earlier than a headline scan, not before professionals with faster feeds. It is not a promise of returns. Never trade on non-public information: that is illegal.
- **Tick reads keywords and numbers, not meaning.** She will miss subtle things and can highlight a sentence that is not important. Verify before acting.
- **Google News results cannot be opened inside the reader**, because Google hides the publisher URL behind a script redirect. Tick analyses the headline and asks you to paste the article. Paywalled and script-rendered pages fall back to paste as well.
- Yahoo endpoints are unofficial and may change. Feeds can be delayed. Any single source can be down (see Source health in the rail).
- Education, not financial advice.

## Development

```
python -m unittest discover -s whisker-wire/tests -v     # offline tests
```

Design rules are in `DESIGN.md` (awesome-design-md format, with taste-skill dials).
