# Grail Radar — design direction

Subject: a private tool one person opens on their phone many times a day to decide, in
seconds, whether a second-hand designer listing is worth a tap. The page's job is ranking
made visible: what it is, which era, how far under fair value, how sure we are.

Two directions were drawn against the same real listings. **Direction A is chosen.**

| | A — Selvedge (chosen) | B — Contact sheet |
|---|---|---|
| Idea | The garment's own paperwork: sewn labels, swing tags, the price captions of a Japanese catalogue page | A photographer's contact sheet, picks circled in grease pencil |
| Ground / ink | White `#FFFFFF` / true black `#000000` | Film black `#000000` / base white `#F3F3F3` |
| Accent | Selvedge red `#D8232A`, used only for "under fair value" | Wax yellow `#FFD60A`, the grease-pencil circle |
| Photos | Full colour, untouched (they are evidence) | Greyscale until opened |
| Layout | One listing per row: photo left, caption right, feedback strip below | Two-up grid of frames with edge numbers |
| Mockup | `mockups/direction-a.html` | `mockups/direction-b.html` |

Why A: listing photos are amateur and colour carries real information (fades, wax, leather
grain), so desaturating them costs the buyer something. White reads outdoors on a phone.
And A's two devices both encode data: the red edge is the deal, the tier glyph is signal
strength. B's two-up grid survives inside A as the optional "Grid" density.

## Tokens
`web/src/styles/tokens.css` is the source of truth. Summary:

- **Color:** `--paper`, `--ink`, `--thread` (secondary text), `--rule` (hairlines), `--label`
  (quiet surface), `--selvedge` (accent). Dark scheme inverts paper/ink and brightens the
  accent. **Red has one meaning: this is under fair value.** Errors, risk and "suspicious" are
  drawn in black hazard hatch, never red.
- **Type:** one family, Archivo Variable, self-hosted via `@fontsource-variable/archivo`
  (import `standard.css`, which carries the weight and width axes). The width axis is the
  voice: figures, tabs and stamps at `font-stretch: 62%` weight 900 or 700; reading text at
  100%. Japanese falls through to the system face (Hiragino on iOS, Yu Gothic on Windows).
  Sentence case everywhere. Tabular numerals for prices.
- **Shape:** corners are square. Only stamped things are round (tier discs, deal stamps).
  Structure comes from 1 px rules: black between listings, grey inside one.
- **Motion:** two moments. A deal stamp presses in once when its card first enters view
  (scale 1.12 → 1, 240 ms). A feedback button fills with ink on tap. Sheets slide. Nothing
  else moves, and `prefers-reduced-motion` turns all of it off.

## Art (`web/public/art/`, built by `design/build_art.py`)
All original, drawn from primitives; lettering is Archivo converted to outlines.

| File | Use |
|---|---|
| `logo-wordmark.svg`, `logo-mark.svg`, `favicon.svg` | The scope: black disc, two rings, hatched sweep, one red contact |
| `tier-s/a/b/c/x.svg` | Tier as signal strength: S solid with halo, A solid, B ring, C dashed ring, X struck out |
| `stamp-steal/great/good/fair/overpriced/suspicious/unknown.svg` | Deal labels as rubber stamps with ink wear. Steal is a full red plate; Great a red double rule; Good black; Fair and No comps thin grey; Overpriced struck through; Suspicious in hazard hatch |
| `empty-rack.svg`, `empty-watchlist.svg`, `empty-quiet.svg` | Empty feed, empty watchlist, quiet source |
| `loading-sweep.svg` | Loading (inline it; stop the animation under reduced motion) |
| `icon-alert.svg`, `halftone.svg` | Alerts; photo placeholder ground |

In dark scheme the black-ink art needs to invert: inline the SVGs as components and swap
`#000000` / `#FFFFFF` for `var(--ink)` / `var(--paper)`, keeping `#D8232A` as
`var(--selvedge)`. Brand names are always plain text. No brand logo or monogram appears
anywhere, including in filter menus.

## The listing card (the one component that matters)
```
┌──┬──────────────┬────────────────────────────┐
│▌ │              │ (S) [STEAL]                │  tier glyph 30 px, stamp 24 px tall, −3°
│▌ │   photo      │ Rick Owens                 │  brand, 18 px bold
│▌ │   4:5        │ Early mainline, leather    │  era + season/piece, 13 px grey
│▌ │        日本  │ ▨ Ask for tag photos       │  flags, hazard-hatch square + text
│▌ │              │ −41%  under fair value     │  the figure: 48 px condensed black, red if a deal
│▌ │              │ $1,612 landed  $1,790      │  landed price bold; previous price struck
│▌ │              │ Fair $2,740 from 11 sold.  │  fair value, comp count, size
├──┴──────────────┴────────────────────────────┤
│ Mercari Japan, 12 min ago. 極美品 リックオウ… │  source, age, original title on one line
├──────┬──────┬───────┬──────┬────────┬────────┤
│ Yes  │ No   │ Would │ Fake │ Wrong  │ Wrong  │  six one-tap cells, 44 px tall
│      │      │ cop   │      │ era    │ brand  │
└──────┴──────┴───────┴──────┴────────┴────────┘
 ▌ = 4 px selvedge-red edge, present only when the label is Steal
```
- Photo column 42% on phones. Tapping the photo or caption opens the drawer; the photo is not
  a link out (the drawer has the "Open listing" and "Buy via Buyee" buttons).
- The figure shows the discount when a fair value exists: `−41%` in red for steal/great,
  black for good/fair, grey `+12%` when over. With no fair value it shows the landed price
  and the line "no fair value yet".
- Japan listings carry a vertical `日本` tab on the photo's top-right corner.
- Auctions replace the age with "ends in 3 h 12 min, 4 bids".
- A price drop shows the old price struck through next to the landed price.
- Suspicious listings: hazard-hatch stamp, no red anywhere on the card, and the flag line
  says why.
- Pressed feedback cells are solid ink. Tapping again undoes. `Yes`/`No` are exclusive.
- Density toggle: **List** (above, default) and **Grid** (two-up on phones: photo, tier and
  stamp over the photo's lower edge, brand, figure, landed price; feedback lives in the
  drawer). Desktop: List becomes two columns at ≥ 900 px and three at ≥ 1400 px; Grid goes to
  4–6 columns.

## Screens
1. **Feed.** Sticky header: wordmark, Search, Filter. Tab strip in condensed bold, scrolls
   sideways: Best, Steals, Grails, Heat, New, Japan, Ending soon, Watchlist, Rejected. One
   status sentence under it ("214 live listings. Last scan 4 minutes ago."). Infinite scroll.
2. **Why this score** (bottom sheet on phones, right-hand panel ≥ 900 px). Top to bottom:
   photo strip; brand, era, title; the figure at 72 px with landed and fair value; buttons
   "Open listing" and, for Japan, "Buy via Buyee"; then four plain sections:
   **What it is** (brand, era with the cues that fired, season, piece, each with a
   confidence bar), **What it's worth** (a range bar: the comps' 25–75% band, the median
   tick, and this listing's landed price as a marker; then the comps as a list with price,
   date and link), **What it costs** (price, proxy fee, shipping, duty, landed, as a ledger),
   **Why this rank** (desirability factors and deal factors as labelled bars; flags).
   Feedback strip and "Watch" pinned at the bottom.
3. **Filter sheet.** Brand, era (narrows to the chosen brand), piece type, size (with "Use my
   sizes"), price range, source, region, minimum value confidence, hide suspicious. Sort.
   "Show 48 listings" as the confirm button.
4. **Trends.** "Rising this week" first, then the heat list: one row per brand/era with a
   sparkline of weekly scores and the prior from research. Before any Instagram data exists,
   the page says so and shows research priors only.
5. **Comps.** Pick brand, then era and piece type. Shows count, median, 25–75% range, a
   month-by-month median chart and the sold listings.
6. **Alerts.** The built-in rule (S tier or Steal) with an on/off switch, the user's saved
   searches, and a form to add one. Shows where alerts are delivered.
7. **Sources.** One row per source: last successful scan, state (ok, quiet, paused, blocked),
   listings today, which access path is in use; Apify spend against the $5 cap; job run log.
8. **Sizes** (inside Filter or Alerts): the saved size profile.

Navigation between Feed, Trends, Comps, Alerts and Sources: a bottom bar on phones (five
text items, condensed bold, current one underlined), a left-aligned row beside the wordmark
on desktop.

## Copy
- Plain verbs, sentence case, no exclamation marks. Name things as the buyer would:
  "landed" (price plus fees, shipping and duty), "fair value", "sold comps".
- Buttons say what happens: "Open listing", "Buy via Buyee", "Watch", "Save search",
  "Show 48 listings".
- Empty states direct: "Nothing matches these filters. Clear filters." /
  "Nothing watched yet. Tap Watch on a listing to keep it here." /
  "No scan has succeeded for Grailed since Tuesday 14:10. See Sources."
- Errors say what happened and what to do: "Could not reach the database. Try again."
- Never show internal ids (`dior_homme__hedi`); show "Dior Homme, Hedi Slimane".

## Not doing
No all-caps tracked labels, no middle-dot meta strings, no monospace data labels, no arrows
on links, no gradients, no shadows, no card radius, no emoji. The brief's 👍/👎 become the
words "Yes" and "No": faster to read at 44 px and unambiguous beside four other verdicts.
