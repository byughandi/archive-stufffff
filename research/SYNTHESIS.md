# Research synthesis (Orchestrator)

## What we have
| File | Contents | State |
|---|---|---|
| `brands.yaml` | 54 brands (10 core, 19 JP archive, 18 EU archive, 7 rapper staples), aliases, ambiguous aliases, negative context, price floors | Good. Structure verified, no dangling ids |
| `eras.yaml` | 55 eras including the unwanted ones (Kim Jones Dior, Vaccarello SLP, Rousteing Balmain, N(N) relaunch) with cues and anti-cues | Good. Every `season_code_regex` is `UNKNOWN` on purpose |
| `seasons.yaml` | 114 seasons: 47 from research, 67 added at synthesis | Mixed, see below |
| `archetypes.yaml` | 17 archetypes, 40 brand-specific overrides | Good |
| `exemplars.yaml` | 59 grail groups (300 texts), 14 junk groups (97 texts) | Synthetic texts; replaced by real listings as feedback arrives |
| `blocklist.yaml` | 45 reject phrases, 26 conditional, 38 mall brands, 77 category exclusions, 30 collision groups, 22 fake red flags | Good |
| `aliases_ja.yaml` | Katakana for all 54 brands, 40 eras, 64 listing terms, 53 ready queries | Most spellings from memory; confirmed in practice by live Mercari JP hits |
| `sellers.yaml` | 54 Instagram accounts (7 high, 28 med, 19 low), 2 webshops, 0 Grailed usernames | Thin |
| `trend_priors.yaml` | 51 heat rows, 14 people | Evidence mostly one source family |
| `price_bands.yaml` | 19 bands (17 sold, 2 asking), nearly all single observations | Fallback only |
| `sources.yaml`, `japan_costs.yaml` | Mechanics per source; proxy fees, shipping, duties, FX | Usable; fees need a re-check |

## Why the research is thinner than planned
Page fetching failed for every agent (the session could search but not open grailed.com,
Wikipedia, Hypebeast, Dazed, Sabukaru, Truss Archive or Apify). Everything rests on search
snippets plus background knowledge, and the agents marked it that way instead of padding.

## Corrections to the taste profile (kept, because they change matching)
- **Rick Owens:** "Gethsemane" is AW21 and "Strobe" is AW22. Both are recent, not old Rick.
  "Dust" is a colour; the old season is most likely **AW06 "Dustulator"**. "Moog" is **AW05**.
  Old-Rick weight now sits on AW02–AW11 season names.
- **Number (N)ine:** "Give Peace a Chance" is AW04, not SS04. "Touch Me I'm Sick" filed as SS03
  (sources disagree with AW03; both spellings resolve to the Miyashita era either way).
  The 2025 relaunch is its own era so it is never mistaken for archive.
- **Dior Homme:** "Luster" is AW03; sellers also write "AW05 Luster". The word is treated as a
  Hedi cue, not a season proof.
- **Balmain "Coin" bikers**, Undercover "Last Scream of Zamiang" and the Beauty:Beast ×
  Undercover/20471120 collabs could not be confirmed. Kept as low-weight keywords only.

## Orchestrator decisions
1. **Season names are era evidence first, grail evidence second.** A matched season name pins
   the year, which pins the era. The 67 synthesis additions (Rick AW02–AW23, N(N), Undercover,
   early Raf, Dior AW02, Helmut AW99/AW03) carry `confidence: low`, `verify: true` and a
   plain "background knowledge" source. Their weights only matter once the weekly refresh or
   the user confirms them.
2. **Common-word season names are `ambiguous_aliases`** ("release", "island", "dirt", "queen",
   "waves", "purple"). They count only next to the brand plus a season code.
3. **No season-code regexes.** Research could document one Dior Homme tag example. The engine
   uses stated seasons and years in listing text, and treats tag digits as a consistency check.
4. **Trend priors are capped at 0.85** and default to 0.4 where nothing matched. Rapper fit
   documentation exists only for fakemink; the other names are recorded with empty fit lists.
5. **Price bands are a last-resort prior**, weighted as `value_conf: low`. Real fair values
   come from sold comps collected at runtime.
6. **Japan cost model:** Buyee ¥500 per item, ZenMarket ¥800, domestic ¥800, shipping by
   weight class, duty 12.5% (Japan origin) or 15% (other origin) on item value, with no
   de minimis exemption. White Rabbit / Japan Rabbit is not modelled (quote-based).

## Known gaps, in priority order
1. Grailed usernames for archive sellers: none found. The seller-trust feature starts from
   marketplace ratings only.
2. Price evidence for most S/A pieces: none. First `comps-daily` run fills this.
3. Which KVA seasons are respected, Celine standout seasons, ERD early graphics: unverified.
   These eras resolve correctly but their internal ranking is flat until feedback arrives.
4. Ballhog and Chanel/glam seller accounts are under-covered in `sellers.yaml`.
5. Medium-priority JP chains (Rakuma, 2nd Street, RagTag, Kindal, Treasure Factory): search
   mechanics not researched; not built in the first pass.
