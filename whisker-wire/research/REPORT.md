# Whisker Wire: market survey report (simulated pilot, n = 3)

Three Haiku-model participants ran the same protocol (`PROTOCOL.md`) independently: a 5-second test, 7 tasks,
a comprehension check, SUS, NPS, trust, Van Westendorp price and Kano. Raw reports: `persona-1-maya.md`,
`persona-2-dev.md`, `persona-3-gloria.md`.

## Headline numbers (corrected)

| | Maya, 26, beginner (phone) | Dev, 34, active novice (desktop) | Gloria, 51, value investor (laptop) |
|---|---|---|---|
| SUS (68 = average) | **57.5** | **90** (agent reported 55, arithmetic error) | **72.5** |
| NPS answer | 6 | 8 | 6 |
| Trust (1 to 5) | 3 | 3.5 | 3 |
| Would use | weekly | **daily** | weekly |
| Price: bargain / getting expensive / too expensive | $4.99 / $9.99 / $19.99 | $15 / $25 / $40 | $12 / $22 / $30 |
| Most-liked feature | Tick, Value Radar | Tick, source labels | Value Radar "trap" reasons, Tick |

Read: the product fits **experienced novices best** (Dev) and is weakest for true beginners (Maya) because of
unexplained jargon. Nobody is a promoter yet (no 9 or 10). Trust is middling for everyone, and the reasons
are fixable. Stated price appetite is roughly **free core plus a $10 to $15 tier**; beginners stop near $10.
With three simulated people these are directions, not measurements.

## What is working (keep it)

- **Tick** was liked by all three (Kano "Like" x3). Nobody found her childish except Gloria's mild doubt.
- **"How it could be a trap"** on Value Radar was called the standout by Gloria and Dev, and Maya used it to decide "wait".
- **Single source / Corroborated labels**: all three would be upset if removed. They made people cautious in the right way.
- The honest, skeptical tone ("Cheap is a question, not an answer") raised trust rather than lowering it.

## Ranked actions: highest value for the least effort first

Effort: S = under a day, M = a few days, L = weeks.

1. **Put "how scores work" and "choose your sources" where people can see them (S).**
   Two of three failed the task "find the source setting"; both said the same. Both controls sit in the side
   rail, which drops ~13,000px down the page below 1080px wide (phones, tablets, small windows).
   These two controls are the transparency and anti-censorship promise, so hiding them undercuts the pitch.
   Do: a "Sources" button and a "How scoring works" link in the toolbar above the wire, on every screen size.
2. **Show each score's working, and label its unit (S to M).**
   Two of three read the story score "8" as "out of 100" (it is an open-ended points total; 8+ is Urgent).
   All three asked how a story earned its rank. Dev's and Gloria's #1 and #3 requests.
   Do: click the score to show "insider buying +5, fresh +3, other outlets +0 = 8". The numbers already exist server-side.
3. **Confirm watchlist actions and explain "My tickers 0" (S).**
   Verified: adding a ticker shows a chip but no message, and the count stays 0 when no stories match, which
   Maya read as broken. Do: a toast ("AAPL added"), and empty-state text ("No stories mention AAPL right now").
4. **Stop unconfirmed stories headlining as URGENT, and reword "Under the radar" (S).**
   The top story for all three was a single, little-known source marked URGENT. Dev and Gloria both asked why
   something unverified is urgent; Dev and Maya read "Under the radar" as an opportunity rather than a caution.
   Do: cap single-source stories at Watch unless the source is official; rename the tag "Not in big headlines yet".
5. **Explain jargon everywhere, not only in the reader (S to M).**
   Tooltips exist only inside Tick's reader. Wire cards, Value Radar (forward P/E, P/B, book value) and
   Filings (Form 4) use terms unexplained. Maya: without them "I'd stop using the site". This is your core
   beginner audience. Do: reuse the glossary on all text and metric labels.
6. **Link to primary sources (S to M).**
   Gloria: "Original" goes through Google News, so she cannot see who reported it. Dev: link to the actual Form 4.
   Do: label those links "via Google News"; on insider stories add "Find the Form 4 on SEC.gov" (built from the ticker).
7. **Make SEC filings work without editing a file (M).**
   All three flagged the `sec_contact.txt` step; Maya: "feels like gatekeeping". Insider buying is your core
   "overlooked info" feature and it is off by default. Do: a one-time in-app form that saves the contact locally.
8. **Remove the Tick dead end on Google News stories (M).**
   All three hit "cannot fetch" on the very first story they tried, then had to paste text. Do: prefer readable
   stories in the top slots, flag "paste needed" on the card before clicking, or investigate decoding.
9. **A beginner-friendly mobile view (M to L).**
   Maya: "dense", "designed for desktop". Dev would not recommend it to beginners. Do: on phones show headline,
   score and one line, with details on tap; add a "Start here: top 3 in plain English" strip.
10. **Prove the scores work (L, but start logging now).**
    Dev's top request: "how often does an 8 actually move a stock?" It is what separates "nice" from "essential"
    and what a paid tier needs. Start now by recording each Urgent story's price at publish time and after 1 and 5 days.
11. **Later:** custom alert rules (Dev, Gloria), sentiment gauge (Dev), peer comparison and price targets (Gloria).

Small extra: an optional "serious mode" that hides the cat, since Gloria's only reservation was tone.

## Reliability notes (read before acting)

- Participants are simulated. They tend to be agreeable and they made slips: an invented `sec_contact1.txt` in a
  "subscribers-only folder", a "BEAR FLAG - BREAK OUT" label that does not exist, a wrong SUS total, two skipped
  tasks. Findings above are limited to what two or more reported independently, or what I verified on the live site.
- The three shared one browser, so a stray "NV" ticker leaked between sessions. Links that "closed the tab" were
  the test browser blocking new tabs, not a site bug.
- Next step for real evidence: 5 people per segment, especially true beginners on phones, using the same protocol.
