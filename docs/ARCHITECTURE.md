# Grail Radar — architecture

Always on, never local, ~$0/month. Everything that costs CPU happens in scheduled CI jobs;
the site only reads precomputed rows.

```
 GitHub Actions (cron)                         Turso (libSQL)              Cloudflare
 ┌──────────────────────────┐   batched HTTP   ┌──────────────┐  indexed   ┌───────────────────────┐
 │ scrapers  → core.upsert  │ ───────────────► │ listings     │  reads     │ Worker                │
 │ pipeline  → filter/score │ ───────────────► │ scores, feed │ ◄───────── │  /api/*  (read + tap) │
 │ alerts    → ntfy         │                  │ comps_sold…  │  feedback  │  static site assets   │
 └──────────────────────────┘                  └──────────────┘ ─────────► └───────────┬───────────┘
        ▲ taxonomy YAML in repo                                              Cloudflare Access
        └── weekly "brain refresh" PR (Claude Code scheduled task)           (one email allowed)
```

## Stack decisions

| Layer | Choice | Why / limit that matters |
|---|---|---|
| Scheduler + compute | GitHub Actions cron, **public** repo recommended | 5-minute minimum interval, runs can be delayed tens of minutes, schedules auto-disable after 60 days without repo activity (keepalive workflow handles it). Private repo works with a slower schedule (see RUNBOOK). |
| Database | **Turso** (libSQL) | Free: 5 GB, 500M row reads/month, 10M row writes/month; it blocks when a metric is exceeded, it does not pause for inactivity. The write budget drives the "write only on change" rule below. |
| API + site | **One Cloudflare Worker with static assets** | Same origin for site and API, so one Access application protects both and there is no CORS. Static asset requests are free; API calls count against 100k requests/day and 10 ms CPU each. |
| Privacy | **Cloudflare Access** in front of the Worker, plus JWT verification inside the Worker | The Worker refuses any `/api` request without a valid Access token for the configured audience. |
| Alerts | **ntfy.sh** topic | 250 messages/day per sending IP. GitHub runners share IPs, so alerts are capped per run and deduplicated in `alerts_sent`. |
| Paid fallback | Apify, free $5/month credit, no overage | Every call is logged to `spend_ledger`; the client refuses to start a run once the month reaches 90% ($4.50). |
| LLM | none at runtime | There is no LLM client anywhere in the runtime code. The optional Haiku fallback described in the brief is **not built**; `MAX_LLM_ITEMS_PER_DAY` and `llm:` in `config/settings.yaml` are reserved names that nothing reads. |

**Deviation from the brief:** the brief names "Cloudflare Pages + Worker". Cloudflare now serves
static assets directly from a Worker, which removes a second project, the Pages build quota
(500 builds/month) and cross-origin auth. Same free tier, fewer moving parts. The site is still
a static app that fetches data at runtime; nothing rebuilds per scrape.

## Repo layout

```
core/            db.py (sqlite + Turso HTTP backends)  models.py (Listing contract, upsert)
                 fx.py  taxonomy.py (YAML loader)  health.py (source_health + circuit breaker)
scrapers/        grailed.py  mercari_us.py  mercari_jp.py  yahoo_jp.py  webshops.py
                 instagram_trends.py  apify.py  run.py (CLI)  common/ (http client, query builder)
pipeline/        normalize.py  filter.py  classify.py  embed.py  ranker.py  desirability.py
                 comps.py  score.py  alerts.py  trends.py  run.py (CLI)
data/taxonomy/   brands, eras, seasons, archetypes, aliases_ja, blocklist, sellers, exemplars,
                 trend_priors, price_bands (.yaml)
data/eval/       labeled_listings.jsonl (gold set; CI gate)
config/          sources.yaml  japan_costs.yaml  settings.yaml
db/schema.sql    single source of truth for tables and indexes
worker/          Cloudflare Worker (API + static assets), wrangler.jsonc
web/             static site (built into worker/public by CI)
tests/           pytest: unit tests + eval gate
.github/workflows/  scrape-fast  scrape-slow  comps-daily  retrain-nightly  trends-weekly
                    keepalive  tests  deploy
docs/            ARCHITECTURE  RUNBOOK  VERIFICATION
```

## Data flow

1. **Scrape** (`python -m scrapers.run <group>`). Each source builds saved searches from the
   taxonomy (brand × era terms × archetype, Japanese aliases for JP sources), rotates through
   them (`search_cursor`), pages newest-first and stops at the first page with only known ids.
   Output is `core.models.Listing` objects handed to `upsert_listings`, which inserts new rows
   with `needs_score = 1`, writes a `listing_snapshots` row only when price or status changes,
   and otherwise writes nothing (one `last_seen_at` touch per day at most).
2. **Pipeline** (`python -m pipeline.run`). Reads the `needs_score = 1` queue and runs the
   cascade: normalize + landed cost → dedupe → hard rejects → taxonomy match and era
   resolution → embeddings similarity → ranker → desirability tier → fair value from comps →
   deal score. Writes `listing_entities`, `scores` (full breakdown + `explain` JSON) and the
   denormalized `feed` row, then clears the queue flag.
3. **Alerts.** After scoring, rows that match the global rule (S tier or Steal, never
   Suspicious) or a user saved search are pushed to ntfy once per listing per rule.
4. **Read path.** The Worker runs single-table indexed queries on `feed` (default order
   `tier_rank, sort_key DESC`) and returns JSON. The drawer fetches `scores.explain` for one id.
5. **Feedback.** A tap POSTs to `/api/feedback`; the Worker inserts one `feedback` row. The
   nightly job retrains the ranker from those rows and stores coefficients in `kv`.

## Schedules (UTC, odd minutes to dodge the top-of-hour queue)

| Workflow | Cron | Does |
|---|---|---|
| `scrape-fast` | `7,17,27,37,47,57 * * * *` | Grailed every run; Mercari US every second run; pipeline; alerts |
| `scrape-slow` | `13 * * * *` | Mercari JP, Yahoo! Auctions JP, webshops hourly; JP chains every 6 h; recheck of tracked listings; pipeline; alerts |
| `comps-daily` | `41 9 * * *` | Grailed sold index, Mercari JP sold-out, Yahoo closed auctions → `comps_sold`; rescore all active rows; prune |
| `retrain-nightly` | `23 8 * * *` | Fit ranker on feedback; run eval gate; store model in `kv` |
| `trends-weekly` | `31 7 * * 1` | Apify Instagram scrape of the curated account list → `ig_posts`, `trend_scores` |
| `keepalive` | `19 6 * * 3` | Re-enables scheduled workflows through the API so the 60-day rule never trips |
| `tests` | push / PR | Unit tests + eval gate (precision@50 must not regress) |
| `deploy` | push to `main` touching `worker/`, `web/`, `db/` | Apply schema, build site, `wrangler deploy` |

Every job has a `concurrency` group so a delayed run never overlaps the next, and a
`timeout-minutes` between 3 (keepalive) and 20 (daily comps). Target wall time is under
5 minutes; measured locally: slow scrape about 2 minutes, scoring under 10 seconds.

## Budgets

**Turso writes (10M/month).** A new listing costs 5 row writes (listing, snapshot, entities,
score, feed). At ~4,000 new listings/day that is ~600k/month. The daily full rescore writes a
row only when a visible field changed (tier, label, fair value by more than 2%), which keeps it
well under 1M/month. Rejected rows (tier X) are kept 7 days for the audit tab, then deleted.
Sold or removed rows are deleted after 30 days; sold ones are first copied to `comps_sold`.

**Image hashes** are computed for at most 120 top candidates per run, so duplicate-photo flags
on a newly scraped batch can appear one or two runs after the listing does.

**Turso reads (500M/month).** Feed requests read about one index range of 30–60 rows. The
pipeline reads comps per run through an in-memory index loaded once (≤ ~100k rows).

**Worker (100k requests/day, 10 ms CPU).** One user. No scoring in the Worker; the only CPU is
JSON serialization of ≤ 60 rows and one JWT signature check (cached key).

**Apify ($5/month).** The weekly Instagram pull is the only planned spend. It is sized to its
own $3.50/month cap: with 42 accounts at the configured $2.30 per 1,000 results it takes 8
posts per account (about $3.40/month). The actor price is an unverified default; check it on
the first run. Mercari US and Grailed fall back to Apify only if their direct
rungs fail, and only inside what the ledger says is left.

**CI time.** Dependencies and the embedding model are restored from `actions/cache`. Image
embeddings and perceptual hashes run only on rows that already passed the text stages, capped
per run, and are skipped when the run is near its time budget.

## Era resolution (the moat), in one paragraph

`pipeline/classify.py` scores every era of the matched brand from independent cues: explicit
designer names, season codes and years in the title or description, model names, label/tag
wording, made-in country, and anti-cues that point to another era. The winning era carries an
`era_conf` in 0..1. Below 0.5 the listing keeps the brand match but its desirability ceiling
drops to tier B, it gets a `needs_tag_pics` flag, and its deal score is multiplied by the
`era_confidence_weight`. Nothing is silently assumed to be the good era.

## Security

- No secrets in the repo. CI reads `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `NTFY_TOPIC`,
  `APIFY_TOKEN`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` from GitHub Secrets; the Worker
  reads its Turso token from a Worker secret.
- The Worker's Turso token should be a database-scoped token. Its write surface is three
  tables: `feedback`, `watchlist`, `saved_searches`.
- Read-only towards marketplaces: no login, no buying, no offers, no messages.
