# Research index — who owns what

Agents stay in their own lane. Nobody searches outside it. Findings go to files, not chat.
Budget per agent: ≤25 searches, ≤15 page fetches. Every entity needs a source URL and
`confidence: high|med|low`. Unverified → `confidence: low` + `verify: true`. Never invent
handles, season names or prices.

| Agent | Lane | Owns (writes) | Must NOT research |
|---|---|---|---|
| R1 | Instagram accounts, archive sellers, their webshops and Grailed usernames, scene hashtags | `research/R1_instagram.md`, `data/taxonomy/sellers.yaml` | brand history, prices, rapper fits, scraping mechanics |
| R2 | Brand / era / season / piece taxonomy, aliases (EN + JA), era-resolution cues, fake red flags, exemplars, junk blocklist | `research/R2_taxonomy.md`, `data/taxonomy/{brands,eras,seasons,archetypes,exemplars,blocklist,aliases_ja}.yaml` | IG accounts, current trends, prices, scraping mechanics |
| R3 | What is hot now: rapper/influencer fits, last-90-day archive-IG pushes, Grailed demand signals | `research/R3_trends.md`, `data/taxonomy/trend_priors.yaml` | seller discovery, era boundaries, scraping mechanics, price bands |
| R4 | Marketplace mechanics, anti-bot posture, libraries/actors, sold-price bands, Japan landed-cost model | `research/R4_markets.md`, `config/sources.yaml`, `config/japan_costs.yaml`, `data/taxonomy/price_bands.yaml` | IG accounts, brand history, trends |

Notes
- R3 writes `trend_priors.yaml` (keyed by the brand/era/season ids R2 uses) instead of editing
  R2's files, so the two never write the same file. The Orchestrator merges `trend_prior`
  into `brands.yaml` / `seasons.yaml` at synthesis.
- Shared id convention (all agents): lowercase snake_case. Brand ids like `dior_homme`,
  `saint_laurent`, `number_nine`, `rick_owens`, `undercover`, `beauty_beast`, `20471120`,
  `erd`. Era ids `<brand>__<designer>` e.g. `dior_homme__hedi`, `dior_homme__kva`,
  `saint_laurent__hedi`, `celine__hedi`, `balmain__decarnin`. Season ids
  `<brand>__<ss|aw><yy>` e.g. `number_nine__aw05`, `undercover__ss03`.
- After all four finish: Orchestrator writes `research/SYNTHESIS.md` and reviews every YAML.
