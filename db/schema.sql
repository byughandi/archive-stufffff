-- Grail Radar schema (libSQL / SQLite). Applied idempotently by core/db.py:migrate().
-- Times are unix seconds (INTEGER). Money is REAL in the stated currency; *_usd is USD.

CREATE TABLE IF NOT EXISTS listings (
  id              TEXT PRIMARY KEY,            -- '<source>:<source_id>'
  source          TEXT NOT NULL,               -- grailed | mercari_us | mercari_jp | yahoo_jp | shop:<slug> | ...
  source_id       TEXT NOT NULL,
  url             TEXT NOT NULL,
  proxy_url       TEXT,                        -- Buyee/ZenMarket deep link for JP sources
  region          TEXT NOT NULL DEFAULT 'US',  -- US | JP | EU | ...
  lang            TEXT NOT NULL DEFAULT 'en',
  title           TEXT NOT NULL,
  description     TEXT,
  brand_raw       TEXT,                        -- marketplace brand/designer field, as given
  category_raw    TEXT,
  size_raw        TEXT,
  condition_raw   TEXT,
  size_norm       TEXT,                        -- normalized by pipeline (e.g. 'M', '48', 'W30', 'EU43')
  condition_norm  REAL,                        -- 0..1 (1 = new)
  price           REAL NOT NULL,
  currency        TEXT NOT NULL,
  price_usd       REAL NOT NULL,
  shipping_usd    REAL,                        -- seller-stated shipping when known
  landed_usd      REAL,                        -- price + proxy fee + intl shipping + duties (pipeline)
  seller_id       TEXT,                        -- FK sellers.id
  image_url       TEXT,                        -- hotlinked thumbnail, never rehosted
  image_urls      TEXT,                        -- JSON array, max 4
  phash           TEXT,                        -- perceptual hash of thumbnail (hex), optional
  is_auction      INTEGER NOT NULL DEFAULT 0,
  auction_end_at  INTEGER,
  bids            INTEGER,
  buy_now_usd     REAL,
  status          TEXT NOT NULL DEFAULT 'active',  -- active | sold | ended | removed
  listed_at       INTEGER,                     -- marketplace's own created time when known
  first_seen_at   INTEGER NOT NULL,
  last_seen_at    INTEGER NOT NULL,
  price_changed_at INTEGER,
  prev_price_usd  REAL,                        -- price before the most recent change
  sold_at         INTEGER,
  sold_price_usd  REAL,
  canonical_id    TEXT,                        -- set when this row is a cross-post of another listing
  needs_score     INTEGER NOT NULL DEFAULT 1,  -- pipeline work queue
  query_id        TEXT                         -- saved search that first surfaced it
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_listings_source ON listings(source, source_id);
CREATE INDEX IF NOT EXISTS ix_listings_queue  ON listings(needs_score) WHERE needs_score = 1;
CREATE INDEX IF NOT EXISTS ix_listings_status ON listings(status, source, last_seen_at);
CREATE INDEX IF NOT EXISTS ix_listings_seller ON listings(seller_id);
CREATE INDEX IF NOT EXISTS ix_listings_phash  ON listings(phash) WHERE phash IS NOT NULL;

-- Price history. One row only when price or status actually changes.
CREATE TABLE IF NOT EXISTS listing_snapshots (
  listing_id TEXT NOT NULL,
  at         INTEGER NOT NULL,
  price      REAL NOT NULL,
  price_usd  REAL NOT NULL,
  status     TEXT NOT NULL,
  PRIMARY KEY (listing_id, at)
);

CREATE TABLE IF NOT EXISTS sellers (
  id            TEXT PRIMARY KEY,              -- '<source>:<seller_source_id>'
  source        TEXT NOT NULL,
  username      TEXT,
  rating        REAL,                          -- 0..5 when the source exposes one
  review_count  INTEGER,
  sales_count   INTEGER,
  joined_at     INTEGER,
  ig_handle     TEXT,                          -- linked via data/taxonomy/sellers.yaml
  trust         REAL NOT NULL DEFAULT 0.5,     -- 0..1, computed by pipeline
  updated_at    INTEGER NOT NULL
);

-- Sold comps: the pricing backbone.
CREATE TABLE IF NOT EXISTS comps_sold (
  id             TEXT PRIMARY KEY,             -- '<source>:<source_id>'
  source         TEXT NOT NULL,
  url            TEXT,
  title          TEXT NOT NULL,
  image_url      TEXT,
  brand          TEXT,
  era            TEXT,
  season         TEXT,
  archetype      TEXT,
  era_conf       REAL,
  size_norm      TEXT,
  condition_norm REAL,
  sold_price_usd REAL NOT NULL,
  sold_at        INTEGER NOT NULL,
  brand_raw      TEXT,
  size_raw       TEXT,
  condition_raw  TEXT,
  description    TEXT,
  classified     INTEGER NOT NULL DEFAULT 0,  -- pipeline sets 1 after filling brand/era/season/archetype
  ingested_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_comps_key ON comps_sold(brand, era, archetype, sold_at);
CREATE INDEX IF NOT EXISTS ix_comps_season ON comps_sold(season, sold_at) WHERE season IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_comps_queue ON comps_sold(classified) WHERE classified = 0;

-- Taxonomy mirror so the Worker can serve filter lists and names without reading YAML.
CREATE TABLE IF NOT EXISTS taxonomy_entities (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,                   -- brand | era | season | archetype
  name        TEXT NOT NULL,
  parent      TEXT,                            -- era -> brand, season -> era
  weight      REAL,
  trend_prior REAL,
  data        TEXT                             -- JSON extras
);
CREATE INDEX IF NOT EXISTS ix_tax_kind ON taxonomy_entities(kind);

CREATE TABLE IF NOT EXISTS listing_entities (
  listing_id   TEXT PRIMARY KEY,
  brand        TEXT,
  era          TEXT,
  season       TEXT,
  archetype    TEXT,
  line         TEXT,
  brand_conf   REAL,
  era_conf     REAL,
  season_conf  REAL,
  matched      TEXT                            -- JSON: which aliases / cues fired, for explainability
);

-- Full score breakdown (the "why this score" drawer reads `explain`).
CREATE TABLE IF NOT EXISTS scores (
  listing_id     TEXT PRIMARY KEY,
  relevant_prob  REAL,                         -- ranker (or hand-weighted formula) output
  taste_sim      REAL,
  junk_sim       REAL,
  visual_match   REAL,
  desirability   REAL,                         -- 0..100
  tier           TEXT NOT NULL,                -- S | A | B | C | X
  reject_reason  TEXT,                         -- set when tier = X
  fair_value_usd REAL,
  value_conf     TEXT,                         -- high | med | low | none
  comp_count     INTEGER,
  comp_level     TEXT,                         -- season | era_archetype | brand_archetype | brand | price_band
  discount       REAL,                         -- (fair - landed) / fair
  deal_score     REAL,
  deal_label     TEXT,                         -- steal | great | good | fair | overpriced | suspicious | unknown
  risk           REAL,
  flags          TEXT,                         -- JSON array of flag ids
  explain        TEXT,                         -- JSON: entities, comps used (ids+urls), factor breakdown
  model_version  TEXT,
  scored_at      INTEGER NOT NULL
);

-- Denormalized read model for the Worker. One indexed table, no joins at request time.
CREATE TABLE IF NOT EXISTS feed (
  listing_id     TEXT PRIMARY KEY,
  source         TEXT NOT NULL,
  region         TEXT NOT NULL,
  url            TEXT NOT NULL,
  proxy_url      TEXT,
  title          TEXT NOT NULL,
  image_url      TEXT,
  price          REAL NOT NULL,
  currency       TEXT NOT NULL,
  price_usd      REAL NOT NULL,
  landed_usd     REAL NOT NULL,
  prev_price_usd REAL,
  size_norm      TEXT,
  condition_norm REAL,
  brand          TEXT,
  era            TEXT,
  season         TEXT,
  archetype      TEXT,
  era_conf       REAL,
  tier           TEXT NOT NULL,
  tier_rank      INTEGER NOT NULL,             -- S=0 A=1 B=2 C=3 X=9
  desirability   REAL,
  fair_value_usd REAL,
  value_conf     TEXT,
  comp_count     INTEGER,
  discount       REAL,
  deal_score     REAL NOT NULL DEFAULT 0,
  deal_label     TEXT,
  suspicious     INTEGER NOT NULL DEFAULT 0,
  flags          TEXT,
  reject_reason  TEXT,
  is_auction     INTEGER NOT NULL DEFAULT 0,
  auction_end_at INTEGER,
  bids           INTEGER,
  status         TEXT NOT NULL DEFAULT 'active',
  listed_at      INTEGER NOT NULL,             -- listed_at or first_seen_at
  price_changed_at INTEGER,
  sort_key       REAL NOT NULL DEFAULT 0,      -- base_key minus the diversity penalty; what the feed sorts by
  base_key       REAL NOT NULL DEFAULT 0       -- deal_score + freshness and price-drop boosts
);
CREATE INDEX IF NOT EXISTS ix_feed_default ON feed(status, tier_rank, sort_key DESC);
CREATE INDEX IF NOT EXISTS ix_feed_new     ON feed(status, listed_at DESC);
CREATE INDEX IF NOT EXISTS ix_feed_deal    ON feed(status, deal_label, sort_key DESC);
CREATE INDEX IF NOT EXISTS ix_feed_brand   ON feed(status, brand, tier_rank, sort_key DESC);
CREATE INDEX IF NOT EXISTS ix_feed_region  ON feed(status, region, tier_rank, sort_key DESC);
CREATE INDEX IF NOT EXISTS ix_feed_auction ON feed(status, is_auction, auction_end_at);

CREATE TABLE IF NOT EXISTS trend_scores (
  entity_kind TEXT NOT NULL,                   -- brand | era | season | archetype
  entity_id   TEXT NOT NULL,
  week        TEXT NOT NULL,                   -- ISO week start date 'YYYY-MM-DD'
  score       REAL NOT NULL,                   -- 0..1
  mentions    INTEGER NOT NULL DEFAULT 0,
  source      TEXT NOT NULL DEFAULT 'ig',      -- ig | prior | listings
  PRIMARY KEY (entity_kind, entity_id, week, source)
);

CREATE TABLE IF NOT EXISTS ig_posts (
  id         TEXT PRIMARY KEY,
  handle     TEXT NOT NULL,
  posted_at  INTEGER,
  caption    TEXT,
  hashtags   TEXT,                             -- JSON array
  likes      INTEGER,
  comments   INTEGER,
  image_url  TEXT,
  embedding  BLOB,                             -- CLIP vector (float16), never the image
  entities   TEXT,                             -- JSON matched taxonomy ids
  ingested_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ig_handle ON ig_posts(handle, posted_at);

CREATE TABLE IF NOT EXISTS feedback (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id  TEXT NOT NULL,
  kind        TEXT NOT NULL,                   -- up | down | cop | fake | wrong_era | wrong_brand | bought | watch | unwatch
  note        TEXT,
  features    TEXT,                            -- JSON snapshot of ranker features at tap time
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_feedback_listing ON feedback(listing_id, created_at);

CREATE TABLE IF NOT EXISTS watchlist (
  listing_id TEXT PRIMARY KEY,
  added_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  rule       TEXT NOT NULL,                    -- JSON: {brand, era, archetype, sizes[], max_landed_usd, min_tier, labels[], q}
  enabled    INTEGER NOT NULL DEFAULT 1,
  is_global  INTEGER NOT NULL DEFAULT 0,       -- the built-in "S-tier or Steal" rule
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts_sent (
  listing_id TEXT NOT NULL,
  rule_id    INTEGER NOT NULL,
  price_usd  REAL NOT NULL,
  sent_at    INTEGER NOT NULL,
  PRIMARY KEY (listing_id, rule_id)
);

CREATE TABLE IF NOT EXISTS source_health (
  source               TEXT PRIMARY KEY,
  last_run_at          INTEGER,
  last_ok_at           INTEGER,
  last_status          TEXT,                   -- ok | empty | blocked | error | paused
  last_error           TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  breaker_until        INTEGER,                -- circuit breaker: skip source until this time
  rung                 TEXT,                   -- which access path is in use (direct | library | apify)
  items_day            TEXT,                   -- 'YYYY-MM-DD' the counter below belongs to
  items_today          INTEGER NOT NULL DEFAULT 0,
  items_total          INTEGER NOT NULL DEFAULT 0
);

-- Rotation state for taxonomy-generated saved searches.
CREATE TABLE IF NOT EXISTS search_cursor (
  source      TEXT NOT NULL,
  query_id    TEXT NOT NULL,
  last_run_at INTEGER,
  last_top_id TEXT,
  hits_total  INTEGER NOT NULL DEFAULT 0,
  kept_total  INTEGER NOT NULL DEFAULT 0,      -- how many survived filtering (drives rotation priority)
  PRIMARY KEY (source, query_id)
);

CREATE TABLE IF NOT EXISTS spend_ledger (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  at      INTEGER NOT NULL,
  vendor  TEXT NOT NULL,                       -- apify | anthropic
  kind    TEXT NOT NULL,                       -- actor id or 'llm_fallback'
  units   REAL NOT NULL DEFAULT 0,
  usd     REAL NOT NULL DEFAULT 0,
  note    TEXT
);
CREATE INDEX IF NOT EXISTS ix_spend_at ON spend_ledger(vendor, at);

-- Small key/value store: ranker coefficients, FX rates, Algolia credentials cache, run stats.
CREATE TABLE IF NOT EXISTS kv (
  k          TEXT PRIMARY KEY,
  v          TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
