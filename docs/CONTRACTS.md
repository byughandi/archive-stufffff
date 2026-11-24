# Contracts between components

Three builders work in parallel (scrapers, scoring, site). These shapes are what they agree on.
Change them only by editing this file first.

## 1. Scrapers → database
Scrapers produce `core.models.Listing` / `SoldComp` and call `upsert_listings` / `upsert_comps`.
They set no scores. `needs_score = 1` and `comps_sold.classified = 0` are the work queues.

## 2. Pipeline → database
For every queued listing the pipeline writes `listing_entities`, `scores`, `feed` and sets
`listings.needs_score = 0`, plus `listings.size_norm`, `condition_norm`, `landed_usd`.

Enumerations
- `tier`: `S | A | B | C | X`; `tier_rank`: S=0, A=1, B=2, C=3, X=9.
- `deal_label`: `steal | great | good | fair | overpriced | suspicious | unknown`
  (`steal` = 40%+ under and `great` = 25–40% under, both only on high or medium value
  confidence; `good` = 15–25% under, or any larger discount on low-confidence value;
  `unknown` = no usable fair value).
- `value_conf`: `high | med | low | none`.
- `comp_level`: `season | era_archetype | brand_archetype | brand | price_band | none`.
- `feed.suspicious` = 1 exactly when `deal_label = 'suspicious'`.
- `feed.base_key` = `deal_score` plus the freshness and price-drop boosts. `feed.sort_key` =
  `base_key` minus a small, capped diversity penalty for each further row of the same tier,
  brand and piece type. Default feed order is `tier_rank ASC, sort_key DESC`.
- `feed.listed_at` = `listings.listed_at` or `first_seen_at`.

`scores.explain` (JSON, what the "why this score" drawer renders)
```json
{
  "entities": {
    "brand":     {"id": "dior_homme", "name": "Dior Homme", "conf": 0.98, "matched": ["ディオールオム"]},
    "era":       {"id": "dior_homme__hedi", "name": "Hedi Slimane", "years": [2000, 2007], "conf": 0.9,
                  "cues": ["エディ期", "07AW"], "anti_cues": []},
    "season":    {"id": "dior_homme__aw07", "name": "AW07 Navigate", "conf": 0.8, "matched": ["07AW"]},
    "archetype": {"id": "denim", "name": "Denim", "matched": ["デニム"]}
  },
  "desirability": {
    "score": 78, "tier": "A", "ceiling": null, "ceiling_reason": null,
    "factors": [{"k": "brand_era", "label": "Brand and era", "v": 0.95, "w": 0.35}]
  },
  "value": {
    "fair_value_usd": 620, "conf": "med", "level": "era_archetype", "market": "JP",
    "comp_count": 14, "range_usd": [480, 790],
    "comps": [{"id": "mercari_jp:m123", "title": "…", "price_usd": 590, "sold_at": 1795000000,
               "url": "https://…", "source": "mercari_jp"}]
  },
  "cost": {"price_usd": 415, "proxy_fee_usd": 3.1, "domestic_shipping_usd": 5.0,
           "intl_shipping_usd": 48, "duty_usd": 52, "landed_usd": 523, "fx_fallback": false},
  "deal": {"discount": 0.16, "score": 0.11, "label": "good", "risk": 0.05,
           "factors": [{"k": "value_conf", "label": "Value confidence", "v": 0.8}]},
  "flags": [{"id": "needs_tag_pics", "label": "Era unconfirmed. Ask for tag photos.", "severity": 1}],
  "similarity": {"taste": 0.71, "junk": 0.22, "visual": null},
  "ranker": {"prob": 0.88, "model": "formula-v1"}
}
```
Any block may be `null` when it does not apply (a rejected listing has `entities` and `flags`
at most). `comps` holds at most 8 rows. `flags[].severity`: 1 info, 2 caution, 3 serious.
`feed.flags` is the JSON array of flag ids only.

`feedback.kind`: `up | down | cop | fake | wrong_era | wrong_brand | bought`.
Ranker labels: positive = `up, cop, bought`; negative = `down, fake, wrong_brand`;
`wrong_era` is a negative for era resolution and neutral for relevance.

`saved_searches.rule` (JSON; every key optional, all present keys must match)
```json
{"q": "l01", "brand": "saint_laurent", "era": "saint_laurent__hedi", "archetype": "biker_jacket",
 "sizes": ["46", "48"], "max_landed_usd": 1500, "min_tier": "A", "labels": ["steal", "great"],
 "sources": [], "region": null}
```
The built-in global rule (`is_global = 1`) is: tier S, or label `steal`; never `suspicious`.

`kv` keys in use: `fx_rates`, `ranker_model`, `size_profile`, `grailed_algolia`,
`run_stats:<job>`, `taxonomy_version`, `alert_delivery` (written by pipeline/alerts.py).

`taxonomy_entities.data` (JSON): eras carry `{"years": [2000, 2007], "designer": "…"}`; seasons
carry `{"code": "AW07", "year": 2007}`. Era `name` is the designer or period name; season `name`
is code plus name ("AW07 Navigate").

## 3. Worker API (same origin as the site, all under `/api`, JSON)
| Method + path | Returns |
|---|---|
| `GET /api/feed?tab=&brand=&era=&archetype=&size=&min_price=&max_price=&source=&region=&min_conf=&hide_suspicious=&sort=&cursor=&limit=` | `{items: FeedItem[], next_cursor}` |
| `GET /api/listing/:id` | `{item: FeedItem, explain, snapshots: [{at, price_usd, status}], feedback: [kind], watched: bool, description}` |
| `POST /api/feedback` `{listing_id, kind, undo?}` | `{ok: true}`. `undo: true` removes that kind. `up` and `down` are exclusive: recording one clears the other |
| `PUT /api/watchlist/:id`, `DELETE /api/watchlist/:id` | `{ok: true}` |
| `GET /api/trends` | `{heat: HeatRow[], series: [{kind, id, name, points: [{week, score, mentions}]}], rising: [...]}` |
| `GET /api/comps?brand=&era=&archetype=&season=` | `{stats: {count, median, p25, p75}, comps: Comp[], by_month: [{month, median, count}]}` |
| `GET /api/searches`, `POST /api/searches`, `PUT /api/searches/:id`, `DELETE /api/searches/:id` | saved searches; GET also returns `delivery` from kv `alert_delivery` (`{channel, configured, last_sent_at}`), or null |
| `GET /api/health` | `{sources: SourceHealth[], spend: {apify_month_usd, apify_cap_usd, llm_month_usd}, counts: {active, today}}` |
| `GET /api/taxonomy` | `{brands, eras, seasons, archetypes}`: `id, kind, name, parent, weight, trend_prior, years, code, label`. Era `label` adds the years ("Hedi Slimane, 2000–2007") because designer names repeat within a brand |
| `GET /api/profile`, `PUT /api/profile` | saved size profile |

`tab`: `feed | steals | grails | heat | new | japan | ending | watchlist | rejected`.
With `count=1` the feed endpoint returns `{count, capped}` (capped at 1,000) instead of rows.
`sort`: `best` (default) `| newest | price_asc | price_desc | discount | ending`.
`FeedItem` = one `feed` row, with `flags` parsed to an array and two extras:
`watched: bool`, `my_feedback: string[]`.
