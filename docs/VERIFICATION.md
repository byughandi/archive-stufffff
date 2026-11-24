# Verification

**Current status (third verifier, blind sample, 2026-11-24).**
Blind filter check (n=120): 20 of 20 irrelevant items are tier X or C (target 90%: met, but 4 of them are tier C and still in the default feed). Only 78% of relevant items (61 of 78) reach S/A/B, and 1 wanted piece (03SS Undercover scab) is rejected as `no_brand`.
Top 50 of the feed: 50 of 50 relevant by title, but 29 are Dior Homme, 30 of 50 have low value confidence, and 21 are labelled overpriced.
Label honesty holds on the numbers (38 steals and 42 greats: none low confidence, no auction under 2 h, all have comps) but 2 steals are lookalikes ("Rick Owens似", "JOSEPH HOMME ... Dior homme") and 17 of 38 steals price against pooled brand-archetype comps (all eras mixed).
Site: drawer makes 1 listing request in 10 s (loop fixed), no internal ids in the drawer text, feedback row written, filter sheet makes 1 `count=1` request. 171 tests pass; eval gate passes.
Changes made after this check (lookalike steals, unknown-era pricing, the rejected Undercover piece, unknown-era boots) are listed at the end under "After the third check". They are covered by tests but have not had a fresh blind sample.
Not verifiable until deployed: Grailed, Mercari US and Apify live behaviour, CI runs, Turso, Cloudflare Access and real token signatures, delivery to the user's phone, the weekly refresh task.

Independent verification run on 2026-11-24 by a verifier who did not build the system. Own
database `data/dev/verify.db` (started empty), live sources reached through the sandbox proxy.
Nothing is deployed: Grailed, Mercari US, Apify, GitHub, Turso, Cloudflare and the user's phone
were not reachable, so those checks are BLOCKED, not passed. No code, taxonomy, test or other
doc was edited. Labelling for checks 2 and 3 was done before `tests/` and `data/eval/` were read.

Evidence classes used below: **LIVE** (real network from this machine), **MOCK** (mocked
transport or unit tests), **LOCAL** (local stand-ins: sqlite behind `dev_turso.py`, `wrangler dev`),
**BLOCKED** (needs deployment or an account).

## Summary

| # | Check | Result | One-line evidence |
|---|---|---|---|
| 1a | Scrapers ingest real listings (Mercari JP, Yahoo JP, driewgarments, marais) | PASS (LIVE) | Run 1: 588 + 217 + 228 + 66 inserted; comps 239 + 94 |
| 1b | Incremental stop | PASS (LIVE) | Same searches re-run after resetting `search_cursor`: 0 inserted for Mercari JP and Yahoo JP; webshops 0 on a plain second run |
| 1c | Backoff + breaker on simulated 429 | PASS (MOCK) | 3 attempts with 3.6 s and 3.8 s waits, `Blocked`; 3 blocked runs set `breaker_until` = +21600 s; next CLI run printed `paused`, requested nothing |
| 1d | Grailed, Mercari US, Instagram on this machine | BLOCKED, no crash | Grailed 403 in 1 s, Mercari US 403, Instagram "APIFY_TOKEN is not set". All recorded in `source_health`. Exit code is 1, not 0 (see defect 12) |
| 1e | Runs in CI | BLOCKED; static check PASS with notes | 8 workflows parse; every command exists; secrets are only `${{ secrets.* }}`; cron matches ARCHITECTURE; timeouts do not |
| 2a | Irrelevant items rejected or tier C or below, target >= 90% | **FAIL** | 23 of 30 = 76.7% (n = 100 random, 30 labelled irrelevant) |
| 2b | Top 50 of feed >= 85% relevant | PASS | 50 of 50 by title (all Dior Homme or Undercover, all tier S, all Japan) |
| 2c | Known junk patterns | PASS | 15 of 16 probes behaved as expected (the 16th, Gyakusou shorts, was tier C, acceptable) |
| 3 | Era resolution >= 85% correct or honestly unresolved | PASS | 31 to 33 of 33 (94% to 100%) depending on how two judgement calls are scored; no clear confidently wrong era |
| 4a | Fair value within researched price band >= 80% | **FAIL, sample tiny** | About 40 S/A items have an applicable band; 0 inside it |
| 4b | Every non-`unknown` label has comps in explain | **FAIL (2 rows)** | 788 of 790 rows list comps; 2 `price_band` rows have `comps: []` and no `source` |
| 4c | Spot-check 10 fair values by hand | PASS | 10 of 10 reproduce within 3% (0.0% diff) |
| 5a | Zero paid LLM calls | PASS | No LLM client anywhere in runtime code; `spend_ledger` empty after all runs |
| 5b | Apify spend guard | PASS (MOCK), projection FAIL | Guard tests pass (12); weekly Instagram job projects to $5.04 a month, over the $5 credit and the $3.50 source cap |
| 5c | Runtime under 5 minutes | PASS | slow 1m50 and 1m12; score 4.4 s; comps 0.2 s; rescore 5.4 s |
| 6a | Site locally (feed, feedback write, drawer with comps, filters, 4 pages, console) | PASS (LOCAL) | feedback wrote 2 rows; drawer lists 8 sold comps; filters change URL; 0 uncaught errors |
| 6b | Auth path without dev bypass | PASS (LOCAL) | `DEV_NO_AUTH:0`: every route 503; dummy Access values: no token 401, forged/garbage/alg-none 401. Real signature verification not exercised |
| 6c | ntfy delivery | **FAIL** | ASCII title delivered and read back; any non-ASCII (Japanese) title crashes `pipeline.run alerts` |
| 6d | Deployed behind Cloudflare Access; alerts to the user's phone | BLOCKED | Nothing deployed; user's topic not set up |
| 7a | Keepalive workflow | PASS (static) | Does what its comment says; BLOCKED for live run |
| 7b | Brain-refresh data step | PASS | `refresh-report` printed valid JSON with all 5 promised sections |
| 7c | Weekly scheduled task | BLOCKED | Needs the GitHub repository |
| 8 | Test suite, types, no Depop/Vinted, secrets, SQL injection | PASS | 158 pytest pass; `tsc` 0 errors; `svelte-check` 0 errors; no Depop/Vinted outside prohibitions; no secrets; parameterised SQL |

Verified live here: scrapers for Mercari JP, Yahoo JP and two webshops, FX, ntfy publish.
Verified by mock only: breaker and backoff, Apify guard, Grailed, Mercari US, Instagram.
Blocked until deployed: CI runs, Cloudflare Access, Turso, scheduled task, phone delivery,
Grailed and Mercari US live behaviour, Algolia field names, Apify actor field names.

## Check 1. Scrapers

### 1.1 Live ingest (slow group, `GR_DB_PATH=data/dev/verify.db`)

`python -m scrapers.run slow --max-queries 6`, wall 1m50.6s:

| Source | queries | requests | seen | inserted | seconds |
|---|---|---|---|---|---|
| mercari_jp | 6 | 20 | 664 | 588 | 58.3 |
| yahoo_jp | 6 | 14 | 231 | 217 | 25.3 |
| shop:driewgarments | 1 | 6 | 228 | 228 | 13.2 |
| shop:marais | 1 | 13 | 66 | 66 | 13.2 |

Second run, same command, wall 1m12.4s (rotates to different searches by design):

| Source | queries | requests | seen | inserted | status |
|---|---|---|---|---|---|
| mercari_jp | 6 | 18 | 181 | 180 | ok |
| yahoo_jp | 6 | 16 | 348 | 299 | ok |
| shop:driewgarments | 1 | 1 | 78 | 0 | empty |
| shop:marais | 1 | 3 | 9 | 0 | empty |

True same-search rerun: the RUNBOOK documents `DELETE FROM search_cursor WHERE source = ...`. I did
that for mercari_jp and yahoo_jp, then re-ran each with `--max-queries 6`:
mercari_jp 6 requests, seen 431, **inserted 0**, 16 s; yahoo_jp 12 requests, seen 187,
**inserted 0**, 23 s. Incremental stop works. Webshops inserted 0 on the plain second run.

Result in db: listings mercari_jp 768, yahoo_jp 516, driewgarments 228, marais 66 (total 1,578).
`python -m scrapers.run comps --max-queries 3`: mercari_jp 239 comps (3 requests),
yahoo_jp 94 comps (3 requests); grailed blocked (403), mercari_us error (no token).
Request budget respected: roughly 50 requests per live source in total.

Marais note: the `rick-owens-archive` collection 404s, so the scraper crawls the whole store;
what comes back is current-season retail (see check 2).

### 1.2 Backoff and breaker (MOCK; script at `.../scratchpad/verify/breaker.py`)

Project `PoliteClient` with `httpx.MockTransport` returning 429 with `Retry-After: 3`:
3 attempts, sleeps `[3.56, 3.77]` (honours Retry-After plus jitter), then `Blocked`. A 403 raises
`Blocked` after 1 attempt (no retry). A 200 "Just a moment..." page raises `Blocked`.
`core.health.record_failure(blocked=True)` three times: tripped on the 3rd, `breaker_until` =
now + 21600 s (6.0 h), `allowed()` False, `allowed(at=+6h+5s)` True (half-open).
End-to-end with the real CLI in a scratch db (`verify_breaker.db`): grailed hit a real 403,
the next run parked the rung, the third run printed `status: paused, breaker: open 6h`, the
fourth printed `{"status": "paused", "breaker_s": 21600}` and made no request. Exit code 0 once
paused. `pytest tests/test_scrapers_health.py tests/test_scrapers_http.py -q`, run after check 3:
13 passed.

### 1.3 Blocked sources on this machine

| Source | What happened | Recorded | Exit |
|---|---|---|---|
| grailed | `Blocked('403 https://www.grailed.com/')` in 1.0 s | `source_health` blocked, failures 2 after 2 runs | 1 |
| mercari_us (fast, dry run) | `Blocked('403 https://www.mercari.com/search/...')` | not written (dry run) | 1 |
| mercari_us (comps) | `ApifyUnavailable: APIFY_TOKEN is not set`, reported as `error` not `blocked` | error, failures 1 | n/a |
| instagram (trends) | `ApifyUnavailable` | error | 1 |

No crash, no traceback. The exit code is 1 when every attempted source failed, which is the
documented rule but not the 0 the brief expected. In CI that turns the scrape-fast job red
every 10 minutes until the breaker opens (30 minutes) if Grailed is also blocked there.
All three are **BLOCKED for live verification**.

### 1.4 Workflows (static)

All 8 files in `.github/workflows` parse as YAML; the composite action `.github/actions/setup`
exists. Every command they call exists: `scrapers.run {fast,slow,comps,recheck,trends}`,
`pipeline.run {score,comps,rescore,prune,retrain,eval,trends,alerts,taxonomy}`. Secrets appear
only as `${{ secrets.X }}`; a regex scan for hardcoded tokens found nothing. Crons match
ARCHITECTURE: fast `7,17,27,37,47,57 * * * *`, slow `13 * * * *`, comps `41 9 * * *`,
retrain `23 8 * * *`, trends `31 7 * * 1`, keepalive `19 6 * * 3`. Mismatch: ARCHITECTURE says every
job has `timeout-minutes` of 9; actual values are fast 9, slow 12, comps 20, retrain 10,
trends 15, deploy 12, keepalive 3. **Not run in CI: BLOCKED.**

## Check 2. Filter quality (blind)

Sample: all 1,578 ingested rows in `listings`, `random.seed(20261124)`, `random.sample(ids, 100)`.
Shown to me: id, source, title, price, brand field, description snippet. Labels written to
`.../scratchpad/verify/labels_sample100.json` before any score was looked at. Labels:
62 relevant (R), 30 irrelevant (I), 8 borderline (B: recent but real Rick Owens, CDG Homme
AW19, BBS SS22, a Dior Homme key cover, plain KVA tee, an unknown-era Dior Homme jacket, a
1994-95 reissue Undercover knit). The sample is nearly all targeted brands because the scrapers
search by brand, so the junk share is low (30 irrelevant) and the denominator is small.

**Irrelevant share rejected (X) or tier C: 23 of 30 = 76.7%. Target 90%. FAIL.**
(Counting the 8 borderlines as irrelevant: 23 of 38 = 60.5%.) Of the 30: 14 X, 9 C, 7 B.

Disagreements (my label versus the system):

| id | title | mine | system | who is right |
|---|---|---|---|---|
| yahoo_jp:t1239256431 | アンダーカバー UNDERCOVER Tシャツ 1 白 ロゴ 半袖 | I (generic modern logo tee, 4,800 yen) | B | Arguable. The builders' eval set labels plain Undercover tees such as "Tシャツ MAD バックプリント" as relevant. I still hold they are low interest for this buyer |
| yahoo_jp:z705121656 | アンダーカバー Tシャツ サイズ3 | I | B | Same |
| mercari_jp:m45405998739 | UNDERCOVER Tシャツ ホワイト ロゴプリント | I | B | Same |
| yahoo_jp:r1246407172 | UNDERCOVER NON MUSIC TEE | I | B | Same |
| mercari_jp:m71699842236 | UNDERCOVER Uロゴ 半袖Tシャツ L | I | B | Same |
| mercari_jp:m41634109647 | UNDERCOVER Tシャツ XL ブラック | I | B | Same |
| yahoo_jp:o1229192852 | アンダーカバー Undercover GU Tシャツ XL 白 | I (GU mall collab) | B | **Verifier right.** `GU` is not in `mall_brands`, only the katakana. Uniqlo collabs were all rejected, the GU one was not |
| shop:driewgarments:8212935213134 | Number (N)ine SS04 "DREAM BABY DREAM" Wool Spider Knit | R | X `conditional:baby` | **Verifier right.** A real wanted piece was rejected because of the word "baby". "Number Nine baby tee Dream Baby Dream sweater" is only tier C |

If the six plain tees are counted as relevant the share is 23 of 24 (96%), but the GU miss and the
Number (N)ine false reject stand. After `rescore` one borderline row moved B to C; nothing else.

**Top 50 of the default feed** (`tier_rank ASC, sort_key DESC`, active, tier not X): titles
exported alone, labelled blind: **50 of 50 relevant (100%, target 85%)**. Composition: 30 Dior
Homme, 20 Undercover; 50 tier S; 32 Mercari JP, 18 Yahoo JP. Caveats: title-only judgement cannot
detect fakes or lookalike condition; the top 50 has no diversity; after `rescore` 5 of the 50
changed (the 5 newcomers are also relevant). Tier inflation: S 90 and A 617 of 1,384 live rows
(51%) is S or A, so "S or A" does not discriminate much.

**Known junk patterns through the real scoring code** (`score_items`, source grailed):

| Title | Tier | Reject reason |
|---|---|---|
| Chanel No.5 perfume 100ml | X | category:perfume |
| Disney Beauty and the Beast plush toy | X | conditional:toy |
| Undercover police toy car diecast | X | conditional:toy |
| Celine Dion World Tour 2008 tee | X | collision:celine:celine dion |
| Dior-style inspired skinny jeans black | X | blocklist:-style |
| Rick and Morty hoodie | X | collision:rick_owens:rick and morty |
| Balmain x H&M 2015 jacket | X | mall_brand:h&m |
| Saint Laurent perfume Y eau de parfum | X | category:perfume |
| Celine Dion Taking Chances concert t-shirt | X | collision:celine:celine dion |
| Zara dior homme style slim jeans | X | mall_brand:zara |
| Chrome Hearts replica ring 925 | X | conditional:replica |
| Burberry Prorsum 2009 trench (out of scope brand) | X | no_brand |
| Saint Laurent Paris SS25 Vaccarello leather jacket | C | none (unwanted era, ceiling works) |
| Dior Homme Kim Jones 2020 sweater | C | none (unwanted era) |
| Undercover x Nike Gyakusou running shorts | C | none |
| Dior Homme AW05 Hedi Slimane leather jacket 48 | S | none (control, wanted) |

## Check 3. Era resolution

Sample (33, not 30): my db has 777 Dior Homme, 31 Saint Laurent, 5 Celine and **0 Balmain**
(six queries did not reach Balmain). I took all 5 Celine, 10 Saint Laurent, 10 Dior Homme (4
unresolved, 6 confident) from `verify.db`, plus 8 Balmain rows read-only from `data/dev/full.db`.
Seed 20261124. I decided the era by hand from title and description, then compared.

Result by row (mine versus system `era` / `era_conf` / flag):
- Dior Homme (10): 6 confident and all agree (Hedi x3 incl. one with a stuffing flag, KVA x4 incl. 08AW and 09AW); 4 unresolved (no cue) all honestly `era_conf` 0 with `needs_tag_pics`.
- Balmain (8, full.db): 4 Decarnin confident and correct (10SS, FW09, cords with "デカルナン期", pigment-coated); 4 unresolved or 0.18 to 0.47 with `needs_tag_pics` or `era_conflict` (one is "2011AW Oil Spill Biker Jeans", which I believe is Decarnin; the system hedged at 0.47 with `era_conflict`).
- Saint Laurent (10): Hedi resolved at 0.7 for 6 (L-01 15AW jacket, last-season "watch it" tee, 5-zip denim, rust skinny, crush denim cases), unresolved (conf 0) for 3 where only a bare "エディ" appears (no "期") plus a studded backpack.
- Celine (5): 3 Hedi at 0.8 correct (21AW shirt and bomber); a spike belt (cannot tell) and a "19ss ... エディ" jacket unresolved at 0.33.

Score: honest or correct in 31 of 33 (94%) strictly, 33 of 33 if the two judgement calls below
are accepted. Target 85%. **PASS.**

Possible confidently-wrong rows (for the user, none definite):
1. `yahoo_jp:o1247043968` (keyword-stuffed "Saint Laurent ... エディスリマン ... セリーヌ Dior homme ディオールオム" tweed blouson): system says Saint Laurent Hedi at 0.91. I cannot tell which brand it is. Mitigated: `keyword_stuffing` flag, tier C.
2. `mercari_jp:m51686056966` ("サンローランジーンズ 90s ストレートデニム [エディ期]"): the title contradicts itself (a 90s Yves piece versus the Hedi era). System: Hedi at 0.7, tier A. I would call it "cannot tell". Mitigated by nothing; the contradiction raises no flag.
I first labelled `mercari_jp:m26933262895` ("07AW エディ期 JAKE") as KVA, then corrected myself: AW07 is Hedi's last
collection and KVA's first is SS08, so the system's Hedi at 0.91 is right.
Also: a scan of all 665 resolved (conf >= 0.5) Dior Homme, Saint Laurent and Celine rows found 3
with no era wording in the title; one has "エディスリマン" in the description (fine), one is
"06FW SUPER SLENDER" (fine), one is "FW17 HarDior" (fine).
Resolution rates in the full db: Dior Homme 636 of 777 resolved (82%); Saint Laurent 26 of 31;
Celine 3 of 5. Undercover is unresolved for 135 of 395 rows.
Sample size 33 is small; 6 of the 33 are the same Hedi/KVA decision on a single brand.

## Check 4. Pricing sanity

Bands: `data/taxonomy/price_bands.yaml` (19 rows, 17 with `n_observed` 1 or unknown, US market,
Grailed, StockX, 1stdibs). In my db no S/A row used the `price_band` level (all 711 S/A rows used
season 142, era_archetype 255, brand 95, or none 219).

S/A rows with an applicable band (brand, era, archetype, season match) and a fair value:

| Band | S/A rows | Band range (USD) | System fair value | Inside band? |
|---|---|---|---|---|
| Dior Homme Hedi SS04 Strip denim | 12 | 800 to 911 | 2,107 | 0 of 12 (2.6x) |
| Dior Homme Hedi coat ('04E' shirt-jacket) | 26 | 435 | 585 to 665 | 0 of 26 strictly; within +/-50% for those at 585 |
| Saint Laurent Hedi varsity | 1 | 950 to 1,520 | 327 | 0 of 1 |
| Saint Laurent Hedi biker | 1 | 1,650 | 327 | 0 of 1 |
| Number (N)ine hoodie, Rick Owens, Chrome Hearts | 0 | n/a | n/a | no S/A rows |

About 40 applicable rows, **0 inside the band: FAIL against the 80% target**, but the sample is
far too small to mean much: every band is a single observation, US-market, undated, and the
comps here are Japanese sold prices converted to a landed equivalent. The failure that does
matter: SS04 fair value 2,107 is built from 6 season-level comps ranging 226 to 1,886 yen-converted
USD (a belt/pants combo, a black skinny at 786, ice-blue denim at 566, 1,823 and 1,886, and an
"sample" waxed military jacket at 1,886), pooled across piece types because
`era_archetype` found too few comps. Medium confidence, "72% under", Tier S alert. See defect 3.

Label versus comps: of 790 feed rows with a deal label other than `unknown`, 788 list comps
(1 to 8). The other 2 (`shop:marais:15293890888043` and `...855275`, the Adidas x Rick Owens
Springblade) are level `price_band`, `comps: []`, no `source` field, label `fair`, a band value
of 650 taken from a different shoe (Geobasket). The contract allows `price_band` "with its
source"; the source is missing. Observed discount range per label: overpriced below -15%, fair -15% to +15%, good from 15%,
great from 25%, steal from 43% (minimums seen in the data, not read from code); auctions with a live bid are capped at `good`
(`good` rows therefore reach 91% discount).

Hand check of 10 fair values (random seed 11, all rows with every comp listed, so the median is
recomputable): recency-weighted median (half-life 90 days) of the cited comps, 3.5x outlier trim,
then the documented JP landed-equivalent (proxy fee, domestic and international shipping, 12.5%
duty, 159.07 JPY per USD, uplift 1.0). **10 of 10 match the system to the cent** (e.g. 7 comps
median 1,131.6 gives 1,329.2; 4 comps weighted median 213.7 gives 278.6). Caveat: I reused the
project's own `landed_cost` and `wquantile`, so this checks arithmetic and cited-comp consistency,
not the cost model. Over the whole feed, fair value is 1.22 to 1.53 times the median sticker price
of the comps, which is the landed conversion, and it makes fair value land above every comp's
sticker price, so a listing priced at the median sticker looks like a 20% to 30% discount.

## Check 5. Cost

- LLM: no `anthropic`, `openai`, `claude` or `haiku` import or HTTP call in `scrapers/`, `pipeline/`, `core/`, `worker/src`. The only hits are a label in `worker/src/index.ts` (`usd("anthropic")` for the health page) and the setting itself. `spend_ledger` has 0 rows after all my runs. `config/settings.yaml` has `llm.max_items_per_day: 0` and every workflow sets `MAX_LLM_ITEMS_PER_DAY: "0"`. **PASS.** Note: no Python code reads that setting, and ARCHITECTURE's "optional Haiku fallback is a stub" does not exist; there is no stub (defect 10).
- Apify guard (`scrapers/apify.py`): checks month total + worst-case estimate against 90% of $5 and a per-source cap (grailed 0.75, mercari_us 1.00, instagram 3.50), passes `maxTotalChargeUsd` to the actor, logs cost after the run. `pytest -k apify`: 12 passed (MOCK). Real spend could not be tested.
- Projection: `weekly_scrape_list` has 42 accounts, 12 posts each, 504 items per run, actor `apify/instagram-scraper` at $2.30 per 1k = **$1.16 per run, $5.04 per month** at 4.35 runs. That is over the whole $5 credit and over the $3.50 Instagram cap. The guard stops the 4th run of a month (3 x 1.16 = 3.48; a 4th would pass 3.50), so trend data would have gaps in weeks 4 and 5. ARCHITECTURE claims "$3 to $4 a month for 40 to 60 accounts"; 60 accounts is $7.20. The price is a config default (`UNKNOWN` in sources.yaml), not a verified price. Cost accounting uses estimated items x price, not Apify's billing.
- Runtime (this machine, small db): `scrapers.run slow --max-queries 6` 110 s and 72 s; `scrapers.run comps --max-queries 3` 12.5 s; `pipeline.run score` 0.7 s on an empty queue, 4.4 s for 1,578 rows (362 rows a second); `comps` 0.2 s; `rescore` 5.4 s; `pipeline.run all` 5.5 s. All well under 5 minutes. The embedding model weights were not available, so the TF-IDF fallback produced these numbers (`embed_backend: tfidf-char+concepts`); weights loading in CI will be slower.

## Check 6. Site

Local stand-ins: `scripts/dev_turso.py data/dev/verify.db 8080`, `wrangler dev --port 8787`
(`.dev.vars` has `DEV_NO_AUTH=1`), site built with `npm ci && npm run build` (0 vulnerabilities).
Playwright Chromium at 390x844.

- Feed: loads in about 3 s with "1,386 live listings", 30 cards, thumbnails from `static.mercdn.net`, banner "No scan has succeeded for Grailed yet". PASS.
- Feedback: tapping "Wrong era" then "Would cop" sent `POST /api/feedback` and the `feedback` table in `verify.db` gained 2 rows (`wrong_era`, `cop`, with a snapshot JSON of the scores). PASS.
- Drawer: opens from the card and via deep link `/?l=<id>`. It shows What it is (brand, era with evidence and confidence, season, piece), What it's worth ($657, median, range, **8 sold comps with price, date, title, link**), What it costs (itemised landed), Why this rank (desirability factors, deal factors), taste similarity, Open listing and Buy via Buyee. PASS.
- Filters: panel (brand, era, piece, min and max price, sort, hide suspicious) with a "Show N listings" button. Selecting brand Undercover then Show changed the URL to `/?brand=undercover` and the first card; adding sort and max price gave `/?brand=undercover&max_price=200&sort=price_asc`. Tabs change the URL (`?tab=steals`, `?tab=japan`). PASS. Observation: opening the filter panel fires about 7 feed requests of 60 rows (offsets to 300) just to count results; against the 100k Worker requests a day that is cheap for one user.
- Trends (research priors only, no Instagram data), Comps (brand picker), Alerts ("No ntfy topic is set yet"), Sources (Grailed blocked, failures 2, error text): all load with meaningful content. PASS.
- Console: 0 uncaught page errors, 0 console errors apart from the image-host tunnel refusal.
- Auth, no dev bypass: Worker with `--var DEV_NO_AUTH:0`: `/api/health`, `feed`, `taxonomy`, `trends`, `comps`, `searches`, `profile`, `listing/<id>` and POST `feedback` all return **503 "Cloudflare Access is not configured"**; static `/` still serves (200). Worker with `DEV_NO_AUTH:0`, `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD` dummy: no token **401 "Not signed in"**; a forged RS256-shaped token with matching aud and iss in the header or in the cookie, a garbage token, and an `alg: none` token all **401 "Invalid session"**. Caveat: the dummy team domain is unreachable, so the 401 for the forged token comes from the failed certificate fetch, not from a signature mismatch. Code review of `authenticate()`: pins RS256, verifies signature, aud, iss, exp, optional `ALLOWED_EMAIL`, fails closed. `DEV_NO_AUTH` is honoured only when exactly `"1"`, with no hostname or environment guard, so one stray variable in production disables auth (documented as never to set).
- SQL injection: probes in brand, q, sort, size, min_price, limit and cursor returned empty or normal results and `feed` still had 1,578 rows. All user input is bound as `?` parameters; `sort` is looked up in a fixed map; column names are fixed. A cross-origin POST (`Origin: https://evil.example`, `text/plain`) is refused 403 "Cross-origin writes are not allowed". PASS.
- Alerts: `NTFY_TOPIC=grailradar-verify-<24 hex>`. `python -m pipeline.run alerts` **crashed** with `UnicodeEncodeError: 'ascii' codec can't encode characters` in `httpx` header handling: `pipeline/alerts.py::send` puts the title in the `Title` header via `.encode("utf-8").decode("latin-1","ignore")`, which httpx then encodes as ASCII. Calling `send()` directly: an ASCII title returned True and `curl https://ntfy.sh/<topic>/json?poll=1` returned the message (title, body, priority 4, tag, click). A title with Japanese characters raised. Almost every listing here has a Japanese title. **FAIL.** Only `httpx.HTTPError` is caught, so the exception also stops the CI step.
- Deployed behaviour and the user's phone: BLOCKED.

## Check 7. Scheduling

- `keepalive.yml`: weekly Wednesday 06:19 UTC, `actions: write`, loops `gh api -X PUT .../actions/workflows/<wf>.yml/enable` over scrape-fast, scrape-slow, comps-daily, retrain-nightly, trends-weekly, keepalive. This does what its comment says (statically). Not run (no repository). Note that enabling through the API resets GitHub's 60-day clock only if the API call counts as activity, which GitHub does not guarantee; not verifiable here.
- `python -m pipeline.run refresh-report` against `verify.db`: exit 0, valid JSON, keys `trend_scores` (0, no Instagram data), `unmatched_terms` (60), `feedback` (`wrong_era` 1 with the listing, `cop` 1), `rejected_but_liked` (0), `top_unresolved_eras` (7 brands; dior_homme 138, undercover 135, rick_owens 49). All five promised sections present. Quality note: the top unmatched terms are generic English or Japanese words ("leather", "cotton", "即決") so the weekly agent gets little signal until stop-words are filtered.
- The weekly scheduled task itself: BLOCKED.

## Check 8. Other findings

- Depop and Vinted: only the prohibitions (`config/sources.yaml` comment, `PLAN.md`, `research/R1_instagram.md`, `.claude/agents/scraper-engineer.md`). No source code, taxonomy or UI uses them.
- Secrets: none in tracked files; `.dev.vars` and `*.db` are ignored; `git status` clean. The dev token file contains no Turso token.
- `python -m pytest tests -q`: 158 passed in 3.6 s. `cd worker && npx tsc --noEmit`: 0 errors. `cd web && npm run check`: 194 files, 0 errors, 0 warnings. `python -m pipeline.run eval`: gate pass (junk rejection 0.972, precision@50 1.0 on the builders' 287-row set). That set agrees with the builders' own labels, so it did not catch the issues above.
- Scoring is not idempotent: `pipeline.run all` then `pipeline.run rescore` changed 40 rows with no new data (tiers S 94 to 90, C 138 to 151) and 5 of the top 50. A second `rescore` changed nothing.
- The first listing in the live feed (a 10-month-old Mercari listing, "Jan 7") ranks first, and a Yahoo auction at 330 yen with 3 bids and 127 hours left is rank 14 of the top 50 with "good, 91% under" (risk flag `too_good`, risk 0.59). Auctions with live bids are capped at `good` as documented, but it still sorts as tier S.
- `mercari_jp:m666233852` is a sold-out placeholder at 999,999 yen titled "売り切れ" and is active tier A in the feed.

## Defects, most serious first

1. **ntfy alerts crash on any non-ASCII title.** Repro: `GR_DB_PATH=data/dev/verify.db NTFY_TOPIC=<topic> python -m pipeline.run alerts`, or `from pipeline.alerts import send; send({"title":"Dior Homme エディ期","body":"x","click":"https://example.com","tags":"fire"},"<topic>","https://ntfy.sh")` raises `UnicodeEncodeError`. Almost every JP listing has Japanese text. The alerts step in `scrape-fast` and `scrape-slow` would fail and no JP alert would ever be delivered. The `except httpx.HTTPError` does not catch it.
2. **Undelivered alerts are recorded as sent.** With no `NTFY_TOPIC` set, `run_alerts` prints to stdout, sets `ok = True` and inserts `alerts_sent` rows (8 in `verify.db`); after the topic is configured those listings are never alerted (only a 10% price drop re-triggers). Also `alerts_last_run` advances. Repro: `pipeline.run all` then `SELECT count(*) FROM alerts_sent`.
3. **Season-level fair value pools unlike pieces.** SS04 Strip ice-blue denim gets fair value $2,107 (6 comps from 226 to 1,886 yen-converted USD, including a belt/pants combo and a sample jacket), "med" confidence, "72% under" labels and S-tier alerts. The only price evidence in the repo (`price_bands.yaml`) is $800 to $911. 12 S/A rows affected. Query: `SELECT listing_id, fair_value_usd FROM feed WHERE season='dior_homme__ss04' AND tier IN ('S','A')`. Inflated fair values also hit the Dior Homme coat band (585 to 665 versus 435) and SL varsity/biker (327 versus 950 to 1,650).
4. **Filter quality target missed.** 76.7% of hand-labelled irrelevant items were rejected or tier C or below (target 90%). Concrete misses: `GU` is not in `mall_brands` so Undercover x GU tees pass at tier B (`yahoo_jp:o1229192852`); six plain modern Undercover logo tees sit at tier B (a judgement call, but the buyer profile says "old Jun Takahashi 1990s to 2010"). One wanted piece is wrongly rejected: Number (N)ine SS04 "DREAM BABY DREAM" knit (`conditional:baby`). Repro: `score_items([{"title":"Number (N)ine SS04 \"DREAM BABY DREAM\" Wool Spider Knit Long-sleeves","source":"shop:driewgarments","price_usd":700}])`.
5. **Apify projection exceeds the budget.** 42 accounts x 12 posts x $2.30 per 1k = $1.16 a run, $5.04 a month. The guard (cap $3.50 for Instagram) will refuse the 4th run, leaving gaps in trend data. ARCHITECTURE's "$3 to $4" claim is wrong for 42 or more accounts; the actor price is a config default, unverified.
6. **`price_band` values carry no provenance and mis-apply.** Two Marais rows: `explain.value.comps = []`, no `source`, fair value 650 from a Geobasket band applied to a Springblade runner, label `fair`. The contract and the drawer expect a source.
7. **Scoring changes between `all` and `rescore`** (40 rows, 5 of the top 50). Non-deterministic or order-dependent dedupe; the CI jobs call `score` and `rescore` on different cadences, so a listing's tier can flip with no new data.
8. **Era gaps that are honest but costly.** A bare "エディ" (without 期) on Saint Laurent Paris titles leaves era unresolved (3 of 10 sampled), and Undercover era is unresolved for 135 of 395 rows. Two rows resolve confidently on contradictory or spam text (`yahoo_jp:o1247043968` stuffed 0.91; `mercari_jp:m51686056966` "90s ... エディ期" 0.7, tier A).
9. **Tier inflation.** S plus A is 51% of live rows; the top 50 is 100% Dior Homme and Undercover, all Japan, all tier S, so the feed does not rank within the good pile and shows no other brand.
10. **Docs say more than the code does.** ARCHITECTURE: "optional Haiku fallback is a stub that is off and budget-gated" (no such code; `MAX_LLM_ITEMS_PER_DAY` is read by nothing); "every job has `timeout-minutes` of 9" (actual 3 to 20); README links `docs/VERIFICATION.md` (this file now exists).
11. **Sold-out placeholder and stale-auction rows in the feed**: `mercari_jp:m666233852` (999,999 yen, "売り切れ") is active tier A; a 330 yen auction ranks 14th of the top 50.
12. **Scrapers exit 1 when the only attempted source is blocked** (documented, but brief expected 0). In CI a Grailed block makes `scrape-fast` red until the breaker opens.
13. **Filter panel prefetches about 7 pages (60 rows each) of the feed** to count results; wasteful but harmless at one user.
14. **`DEV_NO_AUTH=1` has no environment guard** in `authenticate()`; a leaked variable opens every route.
15. **Refresh report signal quality**: the unmatched-terms list is dominated by generic words.

## Not verified (needs deployment or accounts)

Grailed (Algolia credentials, index names, hit fields), Mercari US, Apify actors and real spend,
Instagram output field names, GitHub Actions runs and caching, the embedding model weights path,
Turso (HTTP backend, write budget), Cloudflare Access and real JWT signature verification, the
Worker's behaviour at the Cloudflare edge, delivery to the user's own ntfy topic and phone, the
weekly brain-refresh scheduled task, keepalive against the GitHub API.


## Re-verification (second verifier)

Run on 2026-11-24 by a second verifier who did not build the system or write the first report. Database
`data/dev/verify2.db` (the first verifier's 1,578 listings and 333 comps, scoring tables empty). Two scratch
copies were used for checks that need a cold start or a fresh breaker: `data/dev/verify2_g.db` (check G) and
`data/dev/verify2_s.db` (scraper exit codes). No code, taxonomy, test or other doc was edited. The blind labels
for D were written to disk before any tier was read, and `tests/` and `data/eval/` were not opened until D was
finished. Live requests: one to grailed.com, one each to ntfy.sh publish/read; the thumbnail fetches of the
image-hash stage went through the proxy (many refused hosts, harmless).

### Summary

| # | Check | Result | One-line evidence |
|---|---|---|---|
| A | Defect 1, alerts with Japanese titles | **FIXED** (LIVE) | `alerts` exit 0, 8 alerts sent, 8 read back from ntfy.sh with intact Japanese titles, priority 4, click URLs |
| B | Defect 2, undelivered recorded as sent | **FIXED** | No topic: `alerts_sent` = 0. Topic set later: the same 8 delivered. Second run: 0 candidates, 8 rows on the topic, unchanged |
| C | Defect 3, season-level fair value | **PARTLY** | Shrinkage and low confidence work when the piece type is known (SS04 denim 2,107 to 1,156, `low`). A listing with no piece type still pools the whole season: neck warmer valued 1,320, `steal`, `med`. 13 of 40 such S/A/B rows are `steal`/`great` |
| D | Defect 4, filter quality | **PARTLY** | Irrelevant rejected or tier C: 14 of 17 = 82.4% (target 90%). Top 50: 50 of 50 relevant by title. All six named retests behave. Brand mix of the top 50 still 34 Dior Homme + 16 Undercover |
| E | Defect 5, Apify projection | **FIXED** (code, MOCK) | 42 accounts x 8 posts x $2.30 per 1k = $0.77 a run, $3.09 (4 runs) to $3.40 (4.4 runs) a month, under $3.50; a 5-Monday month hits the cap on the 5th run ($3.86) and is refused. Price still unverified |
| F | Defect 6, price bands | **FIXED** | 0 feed rows at `price_band`; both Marais Springblade rows are `unknown`, comp level `none`. Code now requires a matching season |
| G | Defect 7, `all` vs `rescore` | **PARTLY** | `--no-phash`: 0 rows change. With the hash stage: 23 of 1,578 rows change `sort_key` only on the first rescore (2 of the top 50 swap), 0 after. Builders' explanation holds |
| H | Defects 8 to 14 | **MIXED** | エディ: FIXED. Docs: FIXED. Grailed exit 0: FIXED. Unexpected error exits 1 (test passes). Filter count: FIXED. `DEV_NO_AUTH`: FIXED. Tier inflation (S+A about half): NOT FIXED. Top 50 brand mix: NOT FIXED |
| I | Regression sweep | **PASS, 1 new defect** | 162 pytest pass; eval gate pass; `tsc` 0; `svelte-check` 0 errors; build ok; feed, feedback, drawer, 4 pages, 0 console errors. Drawer polls the API in a loop (J1). `base_key` present |
| J | New problems | **6 found** | Drawer request loop; JPY 999,999 or more auto-rejected (10 plausible grails); stuffed titles and an accessory at tier A; `womens` false positive; alerts omit value confidence; top-50 auctions at start price |

### A and B. Alerts (LIVE)

`python -m pipeline.run all` on the cold database, no topic: exit 0, 1,578 scored, 8 alerts printed as
`would_send` (`delivered_via: stdout`), `SELECT COUNT(*) FROM alerts_sent` = 0 (the first verifier saw 8).
Then `NTFY_TOPIC=<random long topic> python -m pipeline.run alerts`: exit 0, `candidates 1374, sent 8,
delivered_via ntfy`, `alerts_sent` = 8. `curl https://ntfy.sh/<topic>/json?poll=1` returned 8 `message` events with
the Japanese titles byte-for-byte as stored (for example "Dior Homme 06SS ブリーチデニム エディ期 アーカイブ　状態良好",
and one with ◇ and ■ symbols), priority 4, correct `click` URLs. The same 8 listings that were
printed earlier were the ones delivered. A second `alerts` run: `candidates 0, sent 0`, exit 0, still 8 messages on
the topic (no re-send). Not tested: ntfy being down (only the `HTTPError` branch is read, not exercised), and the
user's real topic and phone (BLOCKED).

### C. Season-level fair value

`SELECT ... FROM feed WHERE season='dior_homme__ss04' AND tier IN ('S','A')` gives 33 rows. Fair values now:
denim 1,156 (13 rows, `low`, level `season`, 3 comps), pants 504.67 (6 rows, `high`, `era_archetype`, 15 comps),
coat 664.66, belt 472.74, shirt 295.47, and six rows with **no piece type** at 1,840.13 (`low`, 6 comps). The
first verifier's 2,107 is gone.

Explain for `mercari_jp:m85604883631` (Strip ice-blue denim, 465 USD, tier S): level `season`, 3 comps (565.79,
1,823.10, 1,885.96), confidence `low`, `shrunk: {weight_on_season 0.33, parent_median 562.31, parent_count 62}`.
Hand recomputation without the project's quantile function: weights `0.5^(age_days/90)` at the stored `scored_at`
= 0.9929, 0.9707, 0.9906; sorted midpoint positions 0.168, 0.500, 0.832; interpolated median at 0.5 = 1,821.66;
effective count 2.954, shrink weight 2.954/(2.954+6) = 0.330; 0.330 x 1,821.66 + 0.670 x 562.31 = **977.80**; the
cited `sticker_median_usd` is 977.8. The landed-equivalent step (x1.1824 to 1,156.19) I did not derive; it uses the
project's cost model. Label is `great`, "50% under", on a `low` confidence value. The price-band research
evidence for Strip denim is 800 to 911, so 1,156 is still about 27% above it, but it is now flagged low and
shrunk. Second row, `m76722795914` (04SS cut pants, `high`, 15 comps, median 504.67, `fair`): comps are pants
and trousers of several Hedi seasons (a 04SS pants listing priced from 05AW cords and 06AW tuxedo trousers),
plausible and honest as era+piece-type evidence. Confidence is honest on both.

`steal` on low-confidence value: none (all 10 `steal` rows are `med` or `high`). `great` on `low`: 80 rows in the
feed, 58 of them S or A. Alerts do not show confidence (see J5).

**Still open.** Listings whose piece type is unresolved (`archetype` NULL) skip both the archetype filter and the
shrinkage (the shrink block requires `era and archetype`). `mercari_jp:m72620950940` (a 03AW Dior Homme beaded
neck warmer, 126 USD) is valued at **1,320** from 10 AW03 season comps that are mostly clawmark denim (1,131,
1,236, 2,584), plus gloves (415) and boots (635); conf `med`, label `steal`, with a `too_good` severity-2 flag.
Across S/A/B rows at level `season` with no piece type: 40 rows, 2 `steal`, 11 `great`.
Dior Homme coat band (435) and Saint Laurent varsity/biker bands (950 to 1,650): bands no longer apply (their
season is `UNKNOWN`); those rows use `era_archetype` or `brand` comps, e.g. coats 555 to 665, `low`, SL varsity
327 (`brand`, `low`, "overpriced"). So they are no longer silently contradicting the band, but still sit well
below it for SL (JP comps versus US prices).

### D. Filter quality (blind, new sample)

Sample: all 1,578 `listings` rows, `random.seed(20261125)`, `random.sample(ids, 100)`, exported as id, source,
title, price, brand field, 100-character description. Labels in
`/tmp/claude-0/-home-user/3ffcb37d-a3c2-56f0-b3af-af2c5ff03255/scratchpad/verify2/labels_sample100.json`
(written before any tier was read): 52 relevant, 31 borderline, 17 irrelevant. Irrelevant were: Uniqlo x
Undercover (3), Rick Owens current retail and SS23 (4), plain modern Undercover tees (4), Gareth Pugh, a DH
replacement button, DH sunglasses, two keyword-stuffed Dior Homme listings, one keyword-stuffed Saint Laurent
listing.

**Irrelevant that are X or C: 14 of 17 = 82.4% (5 X, 9 C), target 90%. Still below target** (first round 76.7%).
Counting the 31 borderlines as irrelevant: 26 of 48 = 54%. The sample is brand-targeted, so n = 17 is small and
one more miss moves the share 6 points; this is a weak estimate. Of the 52 relevant: 36 A, 3 S, 9 B, 4 C, 0 X.

Disagreements (mine versus system tier) and who is right:

| id | title (shortened) | mine | system | who is right |
|---|---|---|---|---|
| yahoo_jp:z532425638 | ディオールオム 07AW JAKE デニムパンツジャケットコートTシャツニットブルゾン... | I (stuffed list) | A, no flag | Verifier right. Keyword stuffing not detected |
| yahoo_jp:c1246727357 | ディオールオム マフラー デニム パンツ コート チェスター ジャケット ブーツ サンローラン... | I (stuffed list) | A, no flag | Verifier right |
| mercari_jp:m21215773440 | 希少 エディ期 Dior homme の替えボタン 2個 | I (spare button) | A, `too_good` | Verifier right. 33 USD accessory at A |
| yahoo_jp:q428404829 | Dior Homme 比翼 ドレスシャツ ... 最小 36P XXS メンズ エディ期 | R | C, `womens` | Verifier right. Title says メンズ; flag is a false positive |
| yahoo_jp:l1253207684 | Undercover 蜘蛛巣城 長袖Tシャツ | R | C (auction, no era) | Arguable. Known Undercover piece; system conservative |
| mercari_jp:m88503890895 | アンダーカバー Tシャツ L WE MAKE NOISE | R | C | Arguable. Could be a reissue; I would call it borderline |
| yahoo_jp:f1250502150 | アンダーカバー ニット ... 初期 ... レディース | R | C, `womens` | System defensible. I mislabelled; women's piece, borderline |
| yahoo_jp:f1252802053 | UNDERCOVER 4/3 SLEEVES BORDER T LESS BUT BETTER | B | A | Arguable |
| shop:driewgarments Gareth Pugh skirt, Uniqlo x Undercover (3), Rick Owens SS23, plain Undercover tees (4) | I | X or C | Agree |

Top 50 of the default feed (`status='active' AND tier_rank < 9 ORDER BY tier_rank, sort_key DESC`), titles only,
blind: **50 of 50 relevant (100%, target 85%)**. Composition: **34 Dior Homme, 16 Undercover, 0 others; 50 tier S;
31 Mercari JP, 19 Yahoo JP; 15 are auctions**. The top 100 is
83 Dior Homme, 16 Undercover, 1 Saint Laurent. The feed ranks by tier first and only 86 rows are S, so the
diversity penalty cannot reach other brands or A-tier pieces. Rank 30 is a Yahoo auction at 2.07 USD with 3 bids
labelled `good`, tier S; 15 top-50 rows are auctions priced at the opening bid with 0 bids. First-verifier concern
about brand mix: **NOT FIXED**.

Named retests, through `score_items` and the stored feed:

| Case | Result now |
|---|---|
| Undercover x GU tee ("アンダーカバー Undercover GU Tシャツ XL 白") | X `mall_brand:gu`. FIXED |
| Number (N)ine SS04 "DREAM BABY DREAM" Wool Spider Knit | tier A, era `number_nine__miyashita` 0.91. FIXED |
| Plain Undercover logo tee, no era (6 variants in the data; two constructed) | tier C with `needs_tag_pics` (was B). FIXED, and consistent with the buyer profile |
| Unknown-era Dior Homme leather jacket ("Dior Homme レザージャケット 46", also English) | tier B, `needs_tag_pics`, not C. FIXED |
| 999,999 yen listing (`mercari_jp:m666233852` and `m58669864082`) | X `placeholder_price`. FIXED, but see J2 |
| Title containing 売り切れ | X `marked_sold`, also with a wanted brand and era. FIXED |

### E. Apify projection

From the code and config as they stand: `weekly_scrape_list` = 42 handles; `apify/instagram-scraper` at 2.30 per
1k (default, unverified); source cap 3.50; total stop `credit_limit()` = 4.50. `posts_per_account(42, 2.30, 3.50)`
= int(3.50 / 4.4 / 2.30 x 1000 / 42) = **8 posts per account** (was 12), 336 items per run, 2 batches of at most 25
accounts, **$0.773 a run: $3.09 for 4 runs, $3.40 at 4.4 runs, $3.86 for 5 runs**. Four Mondays fit under the $3.50
cap; in a month with five Mondays the 5th run is refused by the guard (gap in trend data, no overspend). Total stop
$4.50 leaves $1.10 for Grailed (0.75) and Mercari US (1.00) caps, whose sum exceeds that headroom, but the total
guard still wins. ARCHITECTURE now says "42 accounts ... 8 posts ... about $3.40/month", matching. `pytest -k "apify or
instagram or trends"`: 15 passed. The $2.30 price and all actor field names remain unverified (BLOCKED).

### F. Price bands

`scores.comp_level = 'price_band'`: 0 rows in the whole table. The two Marais rows (`shop:marais:15293890888043`,
`...855275`, Springblade runners) are tier C, `comp_level none`, `deal_label unknown`, no fair value. In
`CompsIndex._band` a band applies only when its season equals the listing's season, and the result carries `band`
and `band_source`. Nothing in this database exercises that branch, so the output shape is code-read, not run.

### G. Scoring changes between `all` and `rescore`

Cold start made from `verify2.db` (scoring tables emptied, `needs_score = 1`, `phash` and `canonical_id` cleared,
comps unclassified).
- `all --no-phash` then `rescore --no-phash`: snapshot of `feed` (tier, deal_label, fair_value_usd, sort_key,
  status, canonical_id): **0 of 1,578 rows changed**.
- `all` (with hashes): `listings.phash` set on 103 rows, duplicates 23. First `rescore`: phash on 114 rows,
  duplicates 20, diversity moved 23, 16 rows written. Diff: **23 rows changed, all in `sort_key` only** (tier, label,
  fair value, status unchanged; largest `sort_key` move 0.20); top 50 membership 48 of 50 the same, order
  different; top 100 membership identical. Second and third `rescore`: **0 rows changed**.
The builders' explanation (hash stage working through a capped number of thumbnails, then duplicate groups settle)
holds for what changed: only the diversity-penalised ordering moves, never tier, label or value. It still
means the order of the top of the feed shifts once after the first rescore. Note the cap of 120 is not reached
here: only 114 thumbnails could be fetched (the rest are on refused hosts), so on this machine the process
converges in one rescore.

### H. Defects 8 to 14

- **Bare "エディ" on Saint Laurent Paris titles** (`score_items`, source mercari_jp): "Saint Laurent Paris エディ スキニーデニム 28"
  Hedi 0.70 tier A; "サンローランパリ エディ L01 ライダース 46" Hedi 0.83 tier S; "SAINT LAURENT PARIS エディスリマン期 ブーツ" 0.70 A;
  "サンローラン エディ ジャケット 48" 0.70 A; "SAINT LAURENT Paris バイカー エディ着" 0.70 A. **"Saint Laurent Paris エディション限定 Tシャツ"
  and "サンローランパリ 限定エディション スニーカー": era None, conf 0, tier C: エディション does not resolve to Hedi.**
  Also "Dior Homme エディ ジャケット" Hedi 0.70, "CELINE エディ 21AW ボンバー" Hedi 0.80. FIXED.
- **Tier distribution** (1,578 rows, all active): S 86 (5.5%), A 620 (39.3%), B 360 (22.8%), C 308 (19.5%), X 204
  (12.9%). **S+A = 706 = 44.7% of all rows and 51.4% of the 1,374 non-rejected rows. Still about half. NOT FIXED.**
  Caveat: the corpus is brand-targeted scrapes, so the share is probably higher than it would be on an open feed.
- **Docs versus code**: ARCHITECTURE now says there is no LLM client, the Haiku fallback is "not built" and
  `MAX_LLM_ITEMS_PER_DAY` is a reserved name that nothing reads (grep confirms: only `config/settings.yaml` and
  workflow env). Timeouts: "between 3 (keepalive) and 20 (daily comps)"; actual values 3, 8, 9, 10, 12, 12, 15, 20.
  FIXED.
- **Scraper exit codes**: fresh breaker state, `python -m scrapers.run fast --source grailed`: one request, 403 in
  0.9 s, status `blocked`, **exit 0**. A second run made no request (rung parked) and also exits 0. The rule is
  now exit 1 only when every attempted source has status `error`; `tests/test_scrapers_run.py::test_unexpected_error_on_every_source_fails_the_job`
  passes. FIXED. Side note: the parked second run still increments `consecutive_failures` (2 after 2 runs, only 1
  real request), so the breaker opens after the third scheduled run, not the third real block.
- **Filter sheet count**: in Playwright, opening the sheet made `GET /api/profile` and one `GET /api/feed?count=1`;
  choosing a brand made one `GET /api/feed?brand=...&count=1`. No paging. Label "Show 1000+ listings" (cap).
  FIXED.
- **`DEV_NO_AUTH`**: Worker on 127.0.0.1: `/api/health` 200. Code: honoured only when the value is "1" **and** the
  request URL hostname is 127.0.0.1, localhost or [::1]. With `Host: grail.example.com` or
  `Host: localhost.evil.com` against the same Worker: 503 "Cloudflare Access is not configured". With
  `Host: 127.0.0.1:8787`: 200. FIXED (on the deployed edge the hostname is the routed one, not testable here).

### I. Regression sweep

`python -m pytest tests -q`: 162 passed. `python -m pipeline.run eval`: gate pass, 287 rows, junk_rejection
0.9908, precision_at_50 1.0, era_ok 0.9944; it still lists 4 `tier_bounds_violated` and one `era_wrong`
(Saint Laurent Paris "D02 skinny jeans" resolving to Hedi at 0.63; the builders' own label wants unresolved).
`cd worker && npx tsc --noEmit`: 0 errors. `cd web && npm run check`: 194 files, 0 errors, 0 warnings;
`npm run build`: ok. Local stand-ins (`dev_turso.py` on `verify2.db`, `wrangler dev --port 8787`), Playwright
Chromium at 390x844: feed loads 30 cards of real listings ("1,374 live listings", Grailed banner); tapping "Would cop"
then "Wrong era" sent two `POST /api/feedback` and `feedback` gained rows `(m85604883631, cop)` and
`(m85604883631, wrong_era)`; the drawer shows What it is (era "Hedi Slimane, 2000 to 2007", confidence, evidence
"エディ期, 06ss (season SS06), エディ期 (rules out Kris Van Assche) ..."), What it's worth ($672, 8 sold comps with
price, date, title, link), What it costs, Why this rank; no snake_case or double-underscore ids anywhere in the
text of the drawer or of Trends, Comps, Alerts, Sources; those four pages load with content; 0 uncaught page
errors and 0 console errors beyond image-host refusals. `PRAGMA table_info(feed)` on `verify2.db` includes
`base_key`, while the older `verify.db` does not, so the upgrade path ran. Servers killed afterwards.

### J. New findings

1. **Drawer request loop (new, serious for the free tier).** Opening a listing (tap or `?l=<id>` deep link) issues
   `GET /api/listing/<id>` about 7 times a second, continuously (28 requests by 4 s, 70 by 10 s, the loop never
   settles), until the drawer is closed. In `web/src/lib/Drawer.svelte` the load `$effect` reads `detail`
   (`if (detail && detail.item.listing_id !== id)`) and then assigns `detail = d`, so it re-triggers itself. Cloudflare
   free is 100,000 Worker requests a day; one open drawer is about 600,000 a day, plus Turso reads. Not noticed by
   the first verifier. Closing the drawer stops it.
2. **Every listing at 999,999 yen or more is auto-rejected (`placeholder_price`).** 10 rows in this database at
   900,000 to 2,280,000 yen, including 05AW and 07AW Dior Homme leather jackets and destroyed denim jackets
   (cross-listed on Mercari and Yahoo at 2,280,000 yen: `m23812960587`, `w1246640643`), are tier X. Some are surely
   placeholders (`m58669864082` exactly 999,999), but a 1.4 to 2.3 million yen Hedi leather is a plausible real
   grail. A flag would be safer than a reject. (Also `m12347917116`, 900,000 yen, is tier A.)
3. **Keyword-stuffing is not caught for Dior Homme lists** (`yahoo_jp:z532425638`, `yahoo_jp:c1246727357`: tier A,
   no flag), while a Saint Laurent one is caught. A 33 USD spare button is tier A.
4. **`womens` false positive** on `yahoo_jp:q428404829` whose title says メンズ and "XXS": demoted from A to C.
5. **Alerts omit value confidence.** The delivered alert for `m85604883631` reads "Tier S · great · 50% under /
   fair value $1156" although the value is `low` (3 comps, shrunk). Nothing tells the phone the number is soft.
6. **Top 50 includes 15 auctions with no bids at the opening price** (and one at 2.07 USD with 3 bids, `good`). The
   feed treats an opening bid as a price.
7. First card of the feed is a 10-month-old Mercari listing ("Jan 7", still active) because tier S plus `steal`
   sorts first; no staleness penalty beyond freshness boost.

### Defects still open or new, most serious first

1. **Drawer request loop** (J1): about 7 API calls a second while any drawer is open.
2. **Fair value still pools unlike pieces when the piece type is unresolved** (C): 40 S/A/B rows, 13 `steal` or
   `great`; neck warmer valued at 1,320 as a `steal`. Make the shrink and the archetype filter apply (or cap the label
   at `good`) when `archetype` is NULL; and consider capping `great` on `low` confidence (80 rows).
3. **Filter quality 82.4% against a 90% target** (D) on a small sample: stuffed Dior Homme lists and an accessory
   pass at tier A, one men's shirt demoted by `womens`.
4. **Placeholder-price rule rejects genuine million-yen grails** (J2).
5. **Brand mix and tier inflation** (D, H): top 50 is 34 Dior Homme + 16 Undercover, all S; S+A is 51% of non-rejected
   rows; 15 of the top 50 are unbid auctions at their opening price.
6. **Alerts carry no confidence** (J5).
7. **First rescore moves `sort_key` for 23 rows** (G), 2 of the top 50 change; stable afterwards.
8. **Breaker counts parked, request-less runs as failures** (H), so it opens earlier than "three blocked runs".
9. **Era rows still honest but costly**: Undercover era unresolved and the two contradictory-text rows from defect 8
   were not re-measured here.

### Not verified (needs deployment or accounts), unchanged

Grailed and Mercari US live behaviour, Apify actors and real spend (including the $2.30 per 1k price and field
names), GitHub Actions runs, the embedding weights path, Turso, Cloudflare Access and real JWT signature
verification, the Worker at the Cloudflare edge (including the `DEV_NO_AUTH` host check as the edge presents it),
delivery to the user's own ntfy topic and phone, the weekly brain-refresh task, keepalive against the GitHub API.

## Third check (blind sample, seed 20261126)

Third verifier, 2026-11-24. Database `data/dev/verify3.db` (3,666 listings, read-only except one feedback row
written in check 4: `mercari_jp:m85604883631`, kind `cop`). Labels for checks 1 and 2 were written to disk
before any tier was read and before `tests/`, `data/eval/`, `pipeline/` or this file were opened. Working
files: `/tmp/claude-0/-home-user/3ffcb37d-a3c2-56f0-b3af-af2c5ff03255/scratchpad/verify3/` (ids.json, labels_check1.json,
labels_check2.json, borderline_reasons.txt, top50_titles.txt).

| Check | Target | Result | Verdict |
|---|---|---|---|
| 1a. Irrelevant items that are tier X or C (n=20 I) | >= 90% | 20/20 = 100% (16 X, 4 C) | PASS |
| 1b. Relevant items that are tier S/A/B (n=78 R) | none set | 61/78 = 78.2% (S 2, A 32, B 27, C 16, X 1) | informational, weak |
| 1c. Wanted pieces rejected (tier X) | 0 | 1 of 78 (`no_brand`) | FAIL |
| 2a. Top 50 of default feed relevant (by title) | >= 85% | 50/50 = 100% | PASS |
| 2b. Top 50 variety | not set | 29 Dior Homme, 7 Number (N)ine, 7 Saint Laurent, 6 Undercover, 1 Helmut Lang; nothing else | weak |
| 3a. Steals (n=38, all) and greats (n=15 random of 42; all 42 also checked): never `low` value_conf | 0 low | 0 low, 0 auctions under 2 h (no steal is an auction), 0 empty comps | PASS |
| 3b. Steal comps like-for-like (n=5 steals read) | same brand, era, piece | 3 of 5 fine, 2 not (see below) | FAIL |
| 4a. Drawer requests to `/api/listing/` in 10 s | 1 | 1 | PASS |
| 4b. Internal ids in drawer text | none | none (regex for `x__y`, `kim_jones`, `mercari_jp:`, snake_case) | PASS |
| 4c. Feedback tap writes a row | 1 row | row present in `feedback` | PASS |
| 4d. Filter sheet requests | 1 with `count=1` | `/api/feed?count=1` once (plus one `/api/profile`) | PASS |
| 5a. `python -m pytest tests -q` | pass | last line `...........................  [100%]` (171 dots, exit 0; no summary line is printed) | PASS |
| 5b. `python -m pipeline.run eval` | gate pass | last line ends `"gate": "pass", "failures": []`; precision_at_50 1.0, junk_rejection 0.9908 | PASS |

### Sample sizes
Check 1: 120 listings drawn uniformly, `random.seed(20261126)`; my labels R 78, I 20, B 22 (borderline, excluded
from the percentages). 20 I is small: the 90% target is met at 20/20 but a true rate of 85% would also pass
this sample about 4 times in 100, so it is evidence, not proof. Check 2: 50 titles. Check 3: 38 steals (all), 15
greats (plus a scan of all 42), 5 steals read by hand: five is too few to estimate how often comps are not
like-for-like; the two bad cases below are enough to say the problem exists, not how common it is (but 17 of 38
steals use `brand_archetype` comps, so it is probably common). Check 4: one run, one listing.

### Disagreement table (check 1)
R means I wanted it in the feed; "tier" is what the pipeline did. B-labelled rows are not listed except at the end.

| # | Listing (title shortened) | Mine | Tier | Who is right |
|---|---|---|---|---|
| 66 | 03ss scab期 黒アーカイブ 手縫い パッチワーク (no brand word) | R | X no_brand | Me. "scab" is an Undercover season cue (taxonomy knows 03SS scab, see row 59 which is tier B). Wrongly rejected |
| 0, 42 | Margiela 足袋 tabi boots (x2; 42 is knee-high) | R | C, cap "era evidence leans unwanted" | Me, mostly. Tabi is the house signature across eras; one of the two (row 23) got B for the same boot. Inconsistent |
| 97, 99 | vintage Chanel coin chain belt, CC buckle belt | R | C (`chanel_fake_rate`) | System is defensible: profile says apply the fake penalty hard. C is fine, X would not be |
| 32 | Dior Homme medallion wingtip leather boots | R | C ("era unresolved, everyday piece") | Me. Dior Homme boots with a medallion are not everyday; a Hedi/KVA brand with unresolved era still sits at C while denim with era words reaches S |
| 55 | Helmut Lang honnin-ki handbag/rucksack | R | C ("womens piece") | Disputed. Rucksack-style bags are worn by men; the pipeline's own eval expects A..B here and fails it |
| 93 | Raf Simons long-sleeve shirt archive | R | C (era unresolved) | System is defensible (no era, shirt), me for a 24k yen Raf archive tag |
| 51, 78 | beauty:beast thorn ring, 90s shoulder bag | R | C | Me for a core-brand row in the profile; system defensible because era is unresolved |
| 19, 64 | Undercover 初期 military knit with elbow patches, ladybug JONIO tee | R | C | Me on 19 (初期 military knit), system defensible on 64 |
| 5, 17, 80 | BAPE shark tee / hoodies (80 is 初期) | R | C | System defensible: profile gives BAPE low base weight. 80 (初期 shark hoodie, 80,000 yen) is the one I would raise |
| 3, 18 | Supreme box logo hoodie, Nate Lowman sweater | R | C | System defensible, same reason |
| 1 | マルジェラ 靴箱 (a shoe box) | I | C | System wrong, harmless: an empty box is in the default feed |
| 13 | Lafayette box print "シュプリーム" | I | C | System wrong: lookalike keyword-stuffs Supreme |
| 35 | Rick Owens DRKSHDW SS23 shorts | I | C | System wrong: current-season, wrong era |
| 117 | Undercover 2021 online-limited mask bear tee | I | C | System wrong: current-season merch |
| 14, 20, 26, 79, 98, 118 | Tokio Kumagai, Kazuyuki Kumagai, 291295=HOMME, Cornelian Taurus, Silent by Damir Doma, whiz | B | X no_brand | Acceptable: Japanese or avant-garde labels outside the taxonomy. Worth a taxonomy decision |
| 7, 111 | Rick Jumbolace / 18AW Geobasket | B | B | Acceptable; modern Rick at B is generous but not wrong |

Of the 17 disagreements on relevant pieces, I count 1 clear error (row 66), 4 I would call wrong (0 or 42,
32, 80, 19), 3 inconsistent or disputed (row 0 vs 23, row 55), and the rest are reasonable low-weight calls.
The 22 B items: 3 tier B, 13 tier C, 6 tier X.

### Top of feed (check 2)
Query: `tier_rank < 9 AND status='active'`, top 50 by `tier_rank, sort_key DESC`. All 50 are tier S. Brand mix: Dior
Homme 29, Number (N)ine 7, Saint Laurent 7, Undercover 6, Helmut Lang 1. Sources: Mercari JP 33, Yahoo JP 17.
Auctions: 14 of 50. Deal labels: overpriced 21, fair 17, good 8, great 3, steal 1. `value_conf`: low 30, med 15,
high 5. Two near-duplicates inside the 50 (rows 21 and 24 the same 06SS Dirty Snow 31, rows 23 and 28 the same
ivory lamb jacket 46) count as relevant but waste slots.

Ordering notes. Good: every row is a real Hedi-era or Miyashita-era piece; the feed does not contain junk at the
top; the S tier is now 119 rows over six brands (Dior Homme 71, Undercover 17, N(n)ine 14, Saint Laurent 12, Raf
Simons 4, Helmut Lang 1), so the top-50 ceiling is partly a size problem. Not good: (1) the order inside S follows
desirability, not value, so 21 of the first 50 (42%) are labelled overpriced and 12 of the first 20 are only fair or
overpriced; a buyer looking for deals scrolls past them. (2) 60% of the top 50 have low value confidence, so the
"fair value" behind the badge is weak. (3) Slot 1 is a 52%-under row whose fair value ($1,212) is a pooled
"season" figure at low confidence, and its photo shows cut-off shorts while the title says pants; the headline
deal at the top of the feed is the least trustworthy number on the page. (4) Rick Owens, Margiela, Raf Simons,
Celine, Balmain, Chanel and Gucci never appear in the top 50 (Raf has 4 S rows overall).

### Check 3, comps that are not like-for-like
Five steals read (random seed 7):
1. `dior homme スキニーデニム archive 29` ($75, fair $358, 150 comps, `brand_archetype`): NOT like-for-like. Comps
   mix Hedi, Kris (09SS to 14AW) and an unknown-era grey skinny; prices run $207 to $723. The listing has no era.
2. `JOSEPH HOMME Coated Biker Dior homme` ($50, fair $358, same 150 comps): NOT like-for-like and not a Dior Homme
   piece at all. It is a Joseph Homme jacket with "Dior homme" in the title, and it is compared with Dior Homme
   denim.
3. Gucci Tom Ford leather jacket 44 ($202, fair $960, 10 comps): fine (same era, same piece type; spread $500
   to $1,130, the $202 price is a real outlier).
4. Dior Homme 05AW eyelet belt ($365 vs fair $800, 12 comps): fine in kind (Hedi belts); one cited comp
   ($226, a keyword-stuffed list title) is junk and drags the median down, which makes this steal conservative.
5. Saint Laurent Paris Hedi damaged denim (24) ($72 vs $261, high, 16 comps): fine.
Also seen in the 38 steals (not in the five): `Rick Owens似 メガバンパー ジオバスケット` ("Rick Owens-like", tier B,
$59 against a $731 genuine Geobasket median) and `リックオウエンス ジオバスケット` at $72 against the same $731 (price
of a fake or a placeholder). 17 of 38 steals are priced on `brand_archetype` (pooled all-era) comps, 20 on
`era_archetype`, 1 on `season`.

### Defects still open, most serious first
1. Lookalike listings reach label `steal` in the default feed: "Rick Owens似 ... ジオバスケット" and "JOSEPH HOMME
   Coated Biker Dior homme" (both tier B, steal). The `junk_not_rejected` row in the eval (Margiela "レプリカ") is the
   same class. A steal badge on a copy is the worst failure this product has.
2. 17 of 38 steals price a listing with no era against pooled brand-wide comps (e.g. Dior Homme denim, 150 comps
   across all eras). The label rule allows `steal` on `med` confidence at that comp level; a 76% discount against a
   mixed pool is mostly an era mismatch, not a deal.
3. A wanted piece is rejected: `03ss scab期 ... パッチワーク` (Undercover, no brand word) is X `no_brand` while the
   same season with the brand word is tier B. Season-only cues for a core brand should resolve the brand.
4. Top of the feed ordering: 42% of the top 50 overpriced, 60% low value confidence, slot 1 is a low-confidence 52%
   deal, and the S tier is 60% Dior Homme (71 of 119), so the top 50 shows six brands at most. Brand variety is not
   fixed.
5. Core and adjacent brand pieces with unresolved era sit at C even when substantial (Dior Homme medallion boots,
   beauty:beast bag and ring, Undercover 初期 knit, Raf archive shirt, Margiela tabi 0 vs 23 inconsistent).
   Roughly 20% of the relevant sample (16 of 78) is C.
6. 4 of 20 irrelevant items are tier C and so appear in the default feed: an empty Margiela shoe box, a Supreme
   lookalike ("Lafayette"), SS23 Rick shorts, a 2021 Undercover mask-bear tee.
7. Japanese labels outside the taxonomy (Tokio Kumagai, Kazuyuki Kumagai Attachment, Cornelian Taurus, whiz,
   291295=HOMME, Silent by Damir Doma) are X `no_brand`; fine if intended, unclear if intended.
8. Minor: `pytest -q` prints no summary line; the shop listings and other sources (Grailed, Mercari US) were not part
   of this sample, so nothing is said about them. Not verified here: anything needing deployment.

## After the third check (builders' note, not independently verified)

The third check's open defects 1, 2, 3 and 5 were changed afterwards. These changes are covered by
new regression tests (`tests/test_pipeline_calibration.py`, 176 tests passing) and by the builders'
own rescore of the 3,666-listing dataset, but **no fresh blind sample has been drawn since**, so treat
them as fixed-by-test rather than verified.

| Third-check defect | Change | Evidence |
|---|---|---|
| 1. Lookalikes labelled `steal` ("Rick Owens似 …", "JOSEPH HOMME … Dior homme") | A resemblance marker attached to the matched brand now rejects the listing; a short `other_brands` list rejects other labels' pieces that name a wanted brand as a comparison | Both rows are now tier X (`lookalike:rick owens+似`, `other_brand:joseph homme`) |
| 2. Unknown-era listings valued against all-era comps (17 of 38 steals) | Unknown-era listings are compared with unknown-era comps; when too few exist the pool is marked `era_pooled` and confidence drops to low, which cannot earn `steal` or `great` | Steals: 32, all medium or high confidence, none `era_pooled` |
| 3. Undercover "03ss scab期" rejected as `no_brand` | A grail season's own name next to that season's code now identifies the brand (confidence 0.6) | The row is now Undercover, tier A; "scab" with no matching code still rejects |
| 5. Unknown-era core-brand boots at tier C | Only everyday types (tees, shirts, trousers, bags, belts, accessories, sneakers) drop to C when the era is unknown | Unknown-era Dior Homme boots are tier B with the tag-photo flag |
| (ordering) | Low-confidence value now weighs 0.4 instead of 0.5 in the deal score | The headline row is a medium-confidence `great`, not a low-confidence one |

Still open, by design or for lack of data:
- **Tier-first ordering.** Inside the S tier most rows are fairly priced or overpriced, so the top 50
  of "Best" is mostly not deals. The Steals tab and the discount sort are the deal views.
- **One market's comps.** Every fair value here rests on Japanese sold prices. Grailed sold comps,
  the intended pricing backbone, have never been ingested.
- **Brands outside the taxonomy** (Tokio Kumagai, Cornelian Taurus, Mihara Yasuhiro, Dries Van Noten
  and others) are rejected as `no_brand` and visible only in the Rejected tab.
- **S tier is about 60% Dior Homme** in this dataset, which was scraped with Dior-heavy searches.
- **Comps are like-for-like by brand, era, piece type and named-season stratum only.** Fit, wash,
  fabric and condition are not matched; two of five steals read by the third verifier cited comps
  that a buyer would not call the same piece.
