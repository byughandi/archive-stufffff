# YAML output schemas (the filter and scoring engine parse these — follow them exactly)

Conventions for every file
- Valid YAML, UTF-8, 2-space indent, lists of mappings. Quote strings containing `:` `#` `(` `)`.
- ids are lowercase snake_case. Brand ids: `dior_homme`, `saint_laurent`, `celine`, `balmain`,
  `rick_owens`, `undercover`, `beauty_beast`, `20471120`, `chanel`, `erd`, `number_nine`,
  `raf_simons`, `helmut_lang`, `margiela`, `hysteric_glamour`, `chrome_hearts`, … (same pattern).
- Era ids: `<brand>__<designer_or_period>` e.g. `dior_homme__hedi`, `dior_homme__kva`,
  `saint_laurent__hedi`, `celine__hedi`, `balmain__decarnin`, `rick_owens__early`,
  `undercover__early`, `chanel__vintage`, `erd__early`, `margiela__martin`, `helmut_lang__helmut`.
- Season ids: `<brand>__<ss|aw><yy>` e.g. `number_nine__aw05`. Use `aw` (not `fw`) in ids; put
  FW spellings in aliases.
- Archetype ids: `leather_jacket`, `biker_jacket`, `varsity_jacket`, `blazer`, `coat`, `denim`,
  `pants`, `hoodie`, `knit`, `shirt`, `graphic_tee`, `boots`, `sneakers`, `jewelry`, `bag`,
  `belt`, `accessory` (add more only if needed, and define them in `archetypes.yaml`).
- Every entity: `sources: [url, ...]` (≥1) and `confidence: high|med|low`. Unverified:
  `confidence: low` and `verify: true`. Use the string `UNKNOWN` for a field you could not fill.
- All alias strings lowercase, as they would appear in a listing title.

## data/taxonomy/brands.yaml  (R2)
```yaml
brands:
  - id: dior_homme
    name: Dior Homme
    group: core            # core | jp_archive | eu_archive | rapper_staple
    base_weight: 9         # 1-10 desirability of the brand to this buyer, before era
    aliases: ["dior homme", "dior hommes", "hedi dior"]   # EN + misspellings
    ambiguous_aliases: ["dh", "dior"]   # match only with supporting context
    negative_context: ["sauvage", "perfume", "eau de toilette"]  # means NOT a wanted item
    lines: [{id: dior_homme__mainline, name: "Dior Homme", aliases: []}]
    price_floor_usd: {leather_jacket: 250, denim: 60}   # below this = suspicious, per archetype
    sources: []
    confidence: high
```

## data/taxonomy/eras.yaml  (R2)
```yaml
eras:
  - id: dior_homme__hedi
    brand: dior_homme
    designer: Hedi Slimane
    years: [2000, 2007]
    weight: 10             # 1-10; the multiplier that makes era the moat
    aliases: ["hedi", "hedi slimane", "hedi era", "slimane"]
    cues:                  # how to resolve this era FROM A LISTING
      season_code_regex: ""      # documented regex for tag/season codes, or UNKNOWN
      season_code_notes: ""      # plain-language explanation with examples
      label: []                  # tag wording / design descriptions
      made_in: []                # e.g. ["japan", "italy"]
      model_names: []            # e.g. ["l01", "19cm"]
      keywords: []               # other strong textual cues
    anti_cues: []          # text that means a DIFFERENT era of the same brand
    sources: []
    confidence: high
```

## data/taxonomy/seasons.yaml  (R2)
```yaml
seasons:
  - id: dior_homme__ss04
    brand: dior_homme
    era: dior_homme__hedi
    code: SS04
    year: 2004
    name: "Strip"
    aliases: ["ss04", "s/s 2004", "spring 2004", "strip"]
    weight: 9              # 1-10 grail status of the season
    reason: ""
    grail_pieces:
      - {name: "", aliases: [], archetype: denim, weight: 9, reason: ""}
    sources: []
    confidence: high
```

## data/taxonomy/archetypes.yaml  (R2)
```yaml
archetypes:
  - {id: leather_jacket, name: "Leather jacket", aliases: ["leather jacket", "lambskin jacket"], ship_weight_class: heavy, base_desirability: 8}
    # ship_weight_class: light | medium | heavy | shoes | small (jewelry/belts)
brand_archetypes:          # per brand+era overrides
  - {brand: saint_laurent, era: saint_laurent__hedi, archetype: biker_jacket, desirability: 9, model_names: ["l01"], reason: "", sources: [], confidence: high}
```

## data/taxonomy/exemplars.yaml  (R2)
```yaml
grail:
  - id: slp_l01_biker
    brand: saint_laurent
    era: saint_laurent__hedi
    season: UNKNOWN
    archetype: biker_jacket
    tier: S                # S | A
    texts: []              # 5-15 short descriptions written the way real sellers title/describe it
    image_urls: []         # 0-3 public reference image URLs
    sources: []
junk:
  - id: fast_fashion_grunge_denim
    category: fast_fashion_lookalike   # fast_fashion_lookalike | brand_misuse | word_collision | fake_language | mall_brand
    texts: []              # 5-15 realistic junk titles
```

## data/taxonomy/blocklist.yaml  (R2)
```yaml
reject_phrases:            # hard reject when present
  - {phrase: "inspired", scope: any, reason: ""}     # scope: title | any
conditional_phrases:       # reject unless an allow-context matches
  - {phrase: "bootleg", allow_when: ["vintage tee", "90s"], reason: ""}
mall_brands: []            # brand names that mean fast fashion / mall
category_exclusions: []    # e.g. "phone case", "poster", "perfume"
brand_collisions:          # unrelated things sharing brand words
  - {brand: undercover, phrases: ["undercover police", "undercover boss"], reason: ""}
fake_red_flags:            # for RISK SCORING only, not a buying guide
  - {id: "", description: "", listing_signals: [], brands: [], severity: 2, sources: []}   # severity 1-3
```

## data/taxonomy/aliases_ja.yaml  (R2)
```yaml
brands: {dior_homme: ["ディオールオム"]}
eras: {dior_homme__hedi: ["エディ期", "エディスリマン"]}
archetypes: {leather_jacket: ["レザージャケット", "ライダース"]}
terms:
  - {ja: "美品", romaji: "bihin", meaning: "excellent condition", signal: positive}   # positive | negative | neutral
search_queries:            # ready-to-run JP marketplace queries
  - {brand: dior_homme, era: dior_homme__hedi, query: "ディオールオム エディ期"}
sources: []
```

## data/taxonomy/sellers.yaml  (R1)
```yaml
accounts:
  - handle: glam_archive   # no @
    platform: instagram
    type: seller           # seller | curator | collector | store | stylist | artist
    sub_scene: chanel_glam # hedi | jp_archive | chanel_glam | rick_avant | ballhog | y2k_designer | general_archive
    brands_focus: []       # brand ids
    region: TH
    has_webshop: false
    webshop_url: UNKNOWN
    webshop_platform: UNKNOWN   # shopify | bigcartel | other | UNKNOWN
    grailed_username: UNKNOWN
    follower_band: UNKNOWN      # <5k | 5-20k | 20-100k | 100k+
    signal_weight: 0.8          # 0-1 for trend scoring
    sources: []
    confidence: high
hashtags:
  - {tag: "archivefashion", note: "", sources: []}
weekly_scrape_list: []     # top 40-60 handles by signal_weight
webshops:
  - {name: "", url: "", platform: shopify, products_json: unknown, brands_focus: [], owner_handle: "", sources: []}   # products_json: true | false | unknown
```

## data/taxonomy/trend_priors.yaml  (R3)
```yaml
heat_list:
  - {rank: 1, brand: number_nine, era: UNKNOWN, season: UNKNOWN, piece: "", archetype: hoodie, trend_prior: 0.9, direction: rising, evidence: [{text: "", url: "", date: ""}], confidence: med}
    # direction: rising | steady | cooling
people:
  - name: fakemink
    handles: {instagram: UNKNOWN, other: []}
    role: rapper           # rapper | stylist | influencer
    documented_fits: [{brand: "", piece: "", season: UNKNOWN, source: "", date: ""}]
    grailed_tag_page: UNKNOWN
    confidence: med
```

## data/taxonomy/price_bands.yaml  (R4)
```yaml
bands:
  - {brand: saint_laurent, era: saint_laurent__hedi, season: UNKNOWN, piece: "L01 biker jacket", archetype: biker_jacket, low: 0, median: 0, high: 0, currency: USD, basis: sold, n_observed: 0, source: "", date_observed: "", confidence: med}
    # basis: sold | asking (prefer sold; mark asking honestly)
```

## config/sources.yaml  (R4)
```yaml
sources:
  - id: grailed
    priority: core         # core | high | medium | low
    interval_minutes: 10
    method: ""             # e.g. algolia_api | graphql | html | json_endpoint | library | apify
    endpoint: ""
    auth: ""               # how tokens/keys are obtained
    pagination: ""
    sort_newest: ""
    anti_bot: ""
    sold_data: ""          # available? how?
    fields: []
    polite_rate: ""
    libraries: [{name: "", url: ""}]
    apify_actors: [{id: "", price_per_1k_usd: 0}]
    live_test: {status: not_tested, detail: "", date: ""}   # works | blocked | needs_proxy | not_tested
    sources: []
    confidence: med
```

## config/japan_costs.yaml  (R4)
```yaml
proxies:
  - {id: buyee, fee_fixed_jpy: 0, fee_pct: 0, charged_on: "", notes: "", sources: [], date_verified: ""}
shipping_usd_by_weight_class: {small: 0, light: 0, medium: 0, heavy: 0, shoes: 0}   # JP -> US, cheapest tracked method
domestic_shipping_jpy_default: 0
duties: {us_de_minimis_usd: 0, notes: "", typical_rate_apparel_pct: 0, sources: [], date_verified: ""}
fx: {api: "", url: "", notes: ""}
```
