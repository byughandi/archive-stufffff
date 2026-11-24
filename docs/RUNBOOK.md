# Runbook

Sections for scrapers only; other components add their own below.

## Sources and test ladders

Every source has a ladder: the first healthy rung is used, a blocked rung is parked for 6 hours
(kv `rung_blocked:<source>:<rung>`), and three consecutive blocked runs open the circuit breaker
for 6 hours (`source_health.breaker_until`, status `paused`; `GET /api/health` shows it). We never
try to defeat Cloudflare, CAPTCHAs or IP blocks: a block is recorded and the next rung takes over.
Tested from the build machine on 2026-11-24 (one sandbox IP, behind an HTTPS allowlist proxy).

| Source | Tested | Result | Rung in use |
|---|---|---|---|
| `mercari_jp` | live, 2026-11-24 | Search on-sale and sold-out, item detail, Mercari Shops products: all work through `mercapi` (signed requests). | `library` |
| `yahoo_jp` | live, 2026-11-24 | Open search, ending-soonest, closed search and item page all return a `__NEXT_DATA__` blob. | `direct` |
| `webshops` (`shop:<slug>`) | live, 2026-11-24 | `driewgarments.com` (CAD, ~2,000 products) and `marais.com.au` (AUD) serve `/products.json`. | `direct` |
| `grailed` | **not reachable** | `www.grailed.com` answers 403 "Sorry, you have been blocked" (Cloudflare). Algolia host reachable but needs the public key. Not retried. | `direct` (Algolia) is untested; fallback `apify` |
| `mercari_us` | **not reachable** | `www.mercari.com` answers 403 (Cloudflare managed challenge). Not retried. | `direct` single attempt, fallback `apify` |
| `instagram` | not reachable | `api.apify.com` and instagram.com blocked from the build machine. Mock-tested. | `apify` |

### Mercari JP (`library`)
- Search is `POST api.mercari.jp/v2/entities:search` through `mercapi`; sort `created_time desc`, up to 120 items per page. We page until a page holds only ids already in the DB (cap 3 pages, 8 with `--deep`).
- Sold comps use the sold-out filter (`ITEM_STATUS_TRADING` and `SOLD_OUT` both count as sold); `sold_at` is the item's `updated` time.
- Results include **Mercari Shops** products (ids that do not look like `m123...`, `item_type BEYOND`). They have their own endpoint and URL (`jp.mercari.com/shops/product/<id>`). The Buyee deep link for them (`buyee.jp/mercari/shops/product/<id>`) is from memory, unverified.
- Buyee deep links `buyee.jp/mercari/item/<id>` and `buyee.jp/item/yahoo/auction/<id>` answer (the Yahoo one redirects to `/item/jdirectitems/auction/<id>`); the pages themselves are JS/WAF interstitials from the build machine, so we only build the links, never fetch them.
- `condition_raw` is Mercari's numeric `item_condition_id` as a string (1 new ... 6 poor), same as `scripts/dev_seed.py`.
- **When it goes quiet:** `mercapi` signs requests like the web app; if Mercari changes signing, searches return 4xx. Check `mercapi` for a release (`uv pip install -U mercapi`). 403/429 trips the breaker like any source.

### Yahoo! Auctions JP (`direct`)
- `GET /search/search?p=<kw>&s1=new&o1=d&n=50` (301 to a path-style URL; we follow it). Newest first; `s1=end&o1=a` is ending-soonest (used to refresh bids and end times); closed auctions are `GET /closedsearch/closedsearch?p=<kw>&n=50&s1=end&o1=d`. All are JSON inside `__NEXT_DATA__` at `props.pageProps.initialState.search.items.listing.items`; item page at `...initialState.item.detail.item`.
- Closed search includes unsold auctions; we keep only `bidCount > 0` as sold comps.
- Yahoo pads results with loosely matching items, so scraped items and comps must mention the query's brand (JA or EN name) in the title or category path (`queries.anchor_terms`). This is a volume guard, not scoring.
- Closed-search pages are ~1.2 MB of HTML; keep comps to a few queries per run.
- **When it goes quiet:** a `FetchError: __NEXT_DATA__ search listing not found` means the page layout changed: re-inspect `__NEXT_DATA__` and fix `search_items` / `listing_from_search`. Datacenter-IP blocking would show as 403/429.

### Webshops (`direct`)
- Shopify `GET <shop>/products.json?limit=100&page=N` (default order is newest-published first, verified). Currency and country come from `<shop>/meta.json` (cached in kv `shop_meta:<slug>`): driewgarments is CAD/CA, marais is AUD/AU, so `region` is `CA` / `AU`.
- Only `available` variants count; the price is the cheapest available variant, `size_raw` lists available sizes. Products that are already sold out and were never stored are skipped.
- Incremental: stop at the first page whose newest `published_at` is not newer than the previous run's (kv `shop_pub:<slug>`); known products are re-emitted only if `updated_at` moved past `shop_wm:<slug>`. DRIEW touches every product's `updated_at` continuously, so its watermark skips little, but unchanged rows cost no writes.
- Sold detection for tracked products is in `recheck` via `/products/<handle>.js` (the only public endpoint with per-variant `available`).
- `marais.com.au/collections/rick-owens-archive` (named in `sellers.yaml`) now 404s. The scraper falls back to the whole store filtered to `brands_focus` (vendor, title, tags). Marais is mostly new-season retail, not archive: expect Rick Owens current-season items; the pipeline's era logic decides. Marais returned a 429 once after ~40 requests in a few minutes during testing, which is why shops are paced 1.5 to 3 s apart.
- BigCartel support (`/products.json`) is written from memory and untested: no BigCartel shop is in `sellers.yaml` yet.

### Grailed (`direct` Algolia, fallback `apify`) — FIRST LIVE RUN MUST HAPPEN IN CI
`www.grailed.com` is hard-blocked for the build machine, so credential discovery, index names and hit field names could not be checked. The code is written to be tolerant, and its tests use synthetic pages and hits (clearly marked in `tests/test_scrapers_grailed.py`). The real block page is saved as `tests/fixtures/grailed_blocked.html` and is detected as `Blocked`.
- Credentials, in order: env `GRAILED_ALGOLIA_APP_ID` + `GRAILED_ALGOLIA_KEY`; kv `grailed_algolia` (app id, key, index names, `saved_at`); a fetch of `https://www.grailed.com/` (then up to 6 same-site script bundles) with tolerant regexes (`window.PUBLIC_CONFIG`, `ALGOLIA_*` keys, `x-algolia-*` params, `*-dsn.algolia.net` hosts).
- Index names are discovered from the page, then each is probed with a 0-hit query; the reported names (`Listing_production`, `Listing_by_date_production`, `Listing_sold_production`) are last-resort defaults (`DEFAULT_INDICES`). Newest-first uses the by-date replica when it exists.
- A 403 from Algolia triggers one re-discovery and retry (the key rotates).
- **First live run checklist (CI):** `python -m scrapers.run fast --source grailed --dry-run --max-queries 1`, then open `raw/grailed/*.jsonl.gz`: confirm the homepage yielded app id and key, that the printed index names exist, and that one raw hit has the fields `listing_from_hit` reads (`objectID`, `title`, `designers`, `price`, `size`, `category_path`, `condition`, `cover_photo`, `created_at_i`, `user`/`seller` with `seller_score`; sold index: `sold_price`, `sold_at_i`). Fix the field names in `scrapers/grailed.py` (`listing_from_hit`, `seller_from_hit`) if they differ.
- If CI's IP is also blocked: the first request is recorded as `blocked`, the direct rung is parked for 6 h, the Apify actor takes over (needs `APIFY_TOKEN`), and after three blocked runs the source pauses. Set `GRAILED_ALGOLIA_APP_ID` / `GRAILED_ALGOLIA_KEY` from a browser session on a different network to bypass discovery only (it does not bypass Cloudflare on the homepage).
- **When it goes quiet:** `GET /api/health` shows `last_status`; `paused` with `last_error` containing 403 means blocked. A `CredsError` means the page layout changed: re-capture the key from the browser's network tab and set the two env vars.

### Mercari US (`direct` one attempt, fallback `apify`)
Mock-tested only. Rung 1 makes one honest GET of the public search page per run. A 403 or a challenge page raises `Blocked` (parked for 6 h); a 200 page is parsed through `__NEXT_DATA__` (tolerant walker for `{id, name, price}` objects) and an unrecognised page is a plain error, not a block. Rung 3 runs an Apify actor on at most 2 narrow saved searches, 25 items each, at most once every 6 h, inside the per-source monthly cap. The sold actor runs at most once a day (1 query, 40 items) and also flips known active listings to `sold`.

### Grailed through Apify: `piotrv1001/grailed-listings-scraper` (verified with real runs)
The fallback rung for Grailed, for both live listings and sold comps. Verified on 2026-11-24 with two
real runs (15 live "dior homme hedi slimane", 15 sold "saint laurent paris l01", about 4 seconds each).
- **Input** (`apify.grailed_input`): `searchQuery` (one per run), `soldOnly`, `department`, `scrapeDetails:
  false`, `maxItems`, `proxyConfiguration`. `startUrls`, `minPrice` and `maxPrice` exist and are unused.
- **Output fields read** (`grailed._apify_listing`, `_apify_comp`): `id`, `url`, `title`, `designer`
  ("Dior × Hedi Slimane"), `categoryPath`, `size`, `condition`, `price`, `sold`, `soldPrice`, `soldAt`,
  `createdAt`, `coverPhoto`, `shipping.us.amount`, `seller.{id, username, ratingAverage, ratingCount,
  totalBoughtAndSold}`. Results come back in Grailed's default order, not newest first.
- **Price:** $0.003 per listing returned ($3 per 1,000). `scrapeDetails` would add $0.012 per listing
  and stays off.
- **Volumes inside the $2.75 monthly Grailed budget:** sold comps, 2 searches x 12 listings about once a
  day (about $2.20 a month); live listings, 1 search x 6 listings once a day (about $0.55 a month), used
  only while the direct route is blocked. Tune with `APIFY_GRAILED_COMP_QUERIES`,
  `APIFY_GRAILED_COMP_ITEMS`, `APIFY_GRAILED_QUERIES`, `APIFY_GRAILED_ITEMS` and
  `APIFY_BUDGET_GRAILED_USD` (set them as workflow env).
- **What that means:** the free $5 credit buys roughly 900 Grailed listings a month. That is enough to
  keep sold prices fresh across the taxonomy over a few weeks, not enough to watch Grailed's live
  listings. Live Grailed coverage needs either the direct route to work from GitHub's runners or a paid
  Apify plan.

### Apify (budget guard)
`scrapers/apify.py`. Before a run: this month's `spend_ledger` total (vendor `apify`) plus the run's worst-case estimate must stay at or under 90% of the $5 credit ($4.50), and under a per-source monthly cap (`grailed` $2.75, `mercari_us` $0.50, `instagram` $1.25; override with `APIFY_BUDGET_<SOURCE>_USD`). After a run the estimated cost (items x per-1k price) is written to `spend_ledger` with `note = source:<name>`. Actor ids and per-1k prices come from `config/sources.yaml`, overridable with `APIFY_ACTOR_<KEY>` / `APIFY_PRICE_<KEY>`. **The Grailed mapping is verified (see above). `mercari_us_input` and `instagram_input` are still unverified: confirm against each actor's input schema before first use**, and check `maxItems` / `maxTotalChargeUsd` are honoured.

### Instagram trends (`apify`)
Weekly. `weekly_scrape_list` from `sellers.yaml`, 12 posts per account, 25 accounts per actor run, written to `ig_posts` (handle, time, caption, hashtags, likes, comments, hotlinked `image_url`; no images stored). Output field names (`ownerUsername`, `displayUrl`, `likesCount`...) are from memory: check one real dataset item on the first run.

## Running scrapers locally

```bash
. .venv/bin/activate
export GR_DB_PATH=data/dev/scrape.db          # never data/dev/dev.db (pipeline work uses that)
python -m scrapers.run slow --max-queries 6   # mercari_jp, yahoo_jp, every webshop
python -m scrapers.run fast                   # grailed (+ mercari_us every second run)
python -m scrapers.run comps --source yahoo_jp --max-queries 3
python -m scrapers.run recheck --ids m123,m456 --source mercari_jp   # default: feed rows with tier S/A/B, oldest-checked first
python -m scrapers.run trends                 # needs APIFY_TOKEN
python -m scrapers.run slow --dry-run         # fetch and parse, write nothing (no health, no rows)
python -m scrapers.run slow --deep            # first fill: more pages per query
python -m scrapers.run slow --force           # ignore an open breaker
python -m pytest tests -q                     # no network
```

- Each run prints one JSON line per source: `status` is `ok`, `empty` (ran, nothing new), `blocked`, `error`, `paused` (breaker open, nothing requested) or `skipped`. Exit code is 0 unless every attempted source failed.
- Rotation: each run takes the N least-recently-run saved searches (`search_cursor`), core brands more often. Two back-to-back runs therefore use *different* queries; to re-run the same ones (e.g. to see the incremental stop), `DELETE FROM search_cursor WHERE source = '<source>'`.
- Raw responses: `raw/<source>/<utc-timestamp>.jsonl.gz` (gitignored; CI uploads them as a 7-day artifact). Disable with `GR_RAW=0`.
- Secrets come from env only: `APIFY_TOKEN`, `GRAILED_ALGOLIA_APP_ID`, `GRAILED_ALGOLIA_KEY`. `MERCARI_JP_ENRICH` (default 12) caps detail calls per run for new Mercari listings.
- Politeness: 1 to 3 s jittered delay between requests to one host, desktop-browser User-Agent, exponential backoff on 429/5xx, no retry on 403. Live budget when testing from one IP: about 150 requests per source in total.

## Running the whole thing locally (no accounts needed)

```bash
. .venv/bin/activate
export GR_DB_PATH=data/dev/local.db
python -m scrapers.run slow --max-queries 6      # Mercari JP, Yahoo JP, webshops (live)
python -m scrapers.run comps --max-queries 3     # sold listings
python -m pipeline.run all                       # classify comps, score, trends priors, alerts (printed)
python scripts/dev_turso.py data/dev/local.db 8080 &                 # stand-in for Turso
(cd web && npm ci && npm run build)                                   # site -> worker/public
(cd worker && npm ci && NO_PROXY=127.0.0.1,localhost npx wrangler dev --port 8787)   # site + API
```
`worker/.dev.vars` (not committed) needs `TURSO_DATABASE_URL=http://127.0.0.1:8080` and
`DEV_NO_AUTH=1`. Never set `DEV_NO_AUTH` in production: it switches the login check off.

## Scoring: what to check when the feed looks wrong

| Symptom | Where to look |
|---|---|
| A wanted piece is in Rejected | Its `reject_reason` on the card. `no_brand` = the brand is not in `data/taxonomy/brands.yaml`; `category:` / `blocklist:` = a phrase in `blocklist.yaml` fired |
| Wrong era on a card | Tap "Wrong era". The drawer's "What it is" section lists the evidence that fired; fix the cue in `eras.yaml` |
| Everything looks "overpriced" | Few sold comps yet. Run **Comps daily**; check `comps_sold` count on the Sources page |
| A plain piece shows a huge discount | Its comps are pooled with named-season pieces (`explain.value.stratum = mixed_seasons`, confidence drops a notch). More comps fix it |
| Auctions never show as steals | By design: a bid or start price is not a final price. They are scored normally in the last 2 hours |
| Fair value for Japan looks low next to Grailed | Japanese listings are valued on Japanese sold prices (landed-equivalent). `scoring.jp_to_us_uplift` in `config/settings.yaml` scales it; default 1.0 |

Tuning knobs live in `pipeline/__init__.py` (`DEFAULTS`) and can be overridden under `scoring:`
in `config/settings.yaml` or with `GR_<KEY>` environment variables. After any change:
`python -m pytest tests -q && python -m pipeline.run eval`.

## Embedding model

The semantic stage has two backends behind one interface, and every score records which one
produced it (`explain.similarity.backend`).

- **Character n-gram TF-IDF + taxonomy concepts (the default, and the only one measured).**
  Needs no download. The eval gate numbers and everything in `docs/VERIFICATION.md` were
  produced with it.
- **Small multilingual sentence-embedding model via `fastembed` (opt-in, not yet measured).**
  It is used only when its weights are already in `models/`, or when `GR_EMBED=fastembed` is
  set (which allows the download). The build machine could not download the weights, so this
  backend has never been run against the eval set.

To try the neural backend: set `GR_EMBED: fastembed` in the `tests` workflow's env, let it run
the eval gate, and compare `precision_at_50`, `junk_rejection` and `era_ok` with
`data/eval/baseline.json`. Switch the scrape workflows over only if it is at least as good;
the similarity thresholds were tuned on the TF-IDF backend.
