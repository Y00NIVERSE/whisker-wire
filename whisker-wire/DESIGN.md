# Whisker Wire: DESIGN.md

Format follows the awesome-design-md nine-section convention. Dials follow the taste-skill
model: DESIGN_VARIANCE 7 (asymmetric, editorial), MOTION_INTENSITY 4 (purposeful, never
decorative), VISUAL_DENSITY 7 (a working desk, not a landing page).

## 1. Visual Theme & Atmosphere

A trading desk crossed with a broadsheet. Warm newsprint paper, ink-dark text, and three signal
colors that always mean the same thing. Information is dense but never cramped: hierarchy comes
from type scale and rules (hairlines), not from boxes and shadows. The cat, Tick, is the only
illustrated element, so she carries all the personality and everything else stays serious.

Not allowed: neon-on-navy "crypto" glow, purple gradients, glassmorphism, emoji as icons,
centered hero with three feature cards, lorem-style filler, em dashes in copy.

## 2. Color Palette & Roles

| Token | Light | Dark | Role |
|---|---|---|---|
| `--paper` | `#F3EEE2` | `#0F1412` | page |
| `--surface` | `#FBF8F0` | `#161D1A` | cards, drawer |
| `--ink` | `#14221C` | `#ECE7DA` | text |
| `--ink-2` | `#4B5A52` | `#A5B1AA` | secondary text |
| `--rule` | `#D9D1BE` | `#26302B` | hairlines |
| `--bull` | `#12804A` | `#4FD18B` | positive, bullish clue |
| `--bear` | `#C13A2B` | `#FF7A6B` | negative, red flag |
| `--alert` | `#E39B0B` | `#F4B740` | urgent, key number |
| `--catch` | `#2F5DD3` | `#7FA2FF` | catalyst, what happens next |
| `--fine` | `#7A4FB5` | `#B79BEB` | fine print, hedging |

Rule: green/red only ever mean direction of the news, never brand. Amber only means urgency.

## 3. Typography Rules

- Display: **Bricolage Grotesque** 600/800, tight tracking (-0.02em), headlines and section titles.
- Reading: **Newsreader** 400/500, 1.65 line height, 62ch measure, used in the reader and summaries.
- Data: **JetBrains Mono** 500, tabular numerals, for tickers, prices, scores, timestamps.
- Scale: 12 / 14 / 16 / 20 / 28 / 44 (clamp on hero numerals). Eyebrows are 11px caps, +0.14em.

## 4. Component Stylings

- **Wire row**: hairline-separated, no card chrome. Left gutter holds a score numeral in mono; the
  headline is display 20px; meta line is mono 12px.
- **Chips**: 999px radius, 1px border in the signal color, tinted fill at 10%. Ticker chips are square (4px).
- **Meters**: 6px tall, flat, no gradients. 52-week range bar has a tick marker for the current price.
- **Highlights** (reader): marker-pen background at 28% signal color plus a 2px underline whose style
  differs by category (solid, dashed, dotted, wavy) so meaning never rests on color alone.
- **Drawer**: slides from the right, 880px max, sits on `--surface` with a hairline edge.

## 5. Layout Principles

12-column grid, 1280px max. Wire takes 8 columns and reads top to bottom; the right rail (4 columns,
sticky) holds Value Radar, Filings and How-to-read. Asymmetry is deliberate: the rail is narrower and
denser than the wire. Section rhythm is 48px; inside sections 16px. Mobile collapses to one column
with a sticky segmented switch (Wire / Radar / Filings).

### Markets, first-glance intro and pages (added later)

- **Market row**: a second header row of pill buttons (short code in mono plus name). The selected pill is filled ink and is
  scrolled into view on phones. Everything below re-renders for that market: feeds, index strip, currency, Value Radar.
- **Intro**: the H1 states what the product is ("A stock-news radar for newer traders.") and never collapses. The lede, the
  three one-line feature descriptions and the disclaimer sit below it and can be tucked away with "Hide details".
- **Pages, not scroll**: lists paginate (wire 10, radar 5, filings 10) with a mono "Showing 1 to 10 of 160" range and
  numbered buttons. The reader splits at about 2,000 characters, roughly one screen. Motion stays limited: no page transitions.
- Currency is always shown with its symbol; London prices are in pence and say so. FX pairs in the strip are neutral (no
  green or red), since a rising USD/CNY is not good or bad news.

## 6. Depth & Elevation

Flat. Depth comes from paper vs surface tone and hairlines. One shadow exists, on the drawer and
toasts: `0 24px 60px -24px rgb(0 0 0 / .35)`.

## 7. Do's and Don'ts

- Do show the source count and a "Corroborated / Single source" label on every item.
- Do pair every bullish idea with the way it could be a trap.
- Do keep every claim traceable: original link plus archive link.
- Don't animate numbers for show; motion is for new items, the cat, and the drawer only.
- Don't use color alone: every signal also has a text label.
- Don't put untrusted feed text through innerHTML. Ever.

## 8. Responsive Behavior

Breakpoints: 1080 (rail drops below wire), 720 (drawer becomes full screen, cat docks bottom-right,
margin notes become inline chips under the paragraph). Touch targets 44px. Respects
`prefers-reduced-motion` (cat stops walking and teleports; no slide animation) and `prefers-color-scheme`.

## 9. Agent Prompt Guide

"Build with the Whisker Wire tokens. Paper background, hairline rules, mono numerals. Signal colors
mean direction, amber means urgency. No shadows except drawer. Every list item shows source count.
Inject feed text with textContent only. Tick the tabby is the sole illustration."
