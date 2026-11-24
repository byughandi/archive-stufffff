export type Tier = 'S' | 'A' | 'B' | 'C' | 'X';
export type DealLabel = 'steal' | 'great' | 'good' | 'fair' | 'overpriced' | 'suspicious' | 'unknown';
export type FeedbackKind = 'up' | 'down' | 'cop' | 'fake' | 'wrong_era' | 'wrong_brand' | 'bought';

export interface FeedItem {
  listing_id: string;
  source: string;
  region: string;
  url: string;
  proxy_url: string | null;
  title: string;
  image_url: string | null;
  price: number;
  currency: string;
  price_usd: number;
  landed_usd: number;
  prev_price_usd: number | null;
  size_norm: string | null;
  condition_norm: number | null;
  brand: string | null;
  era: string | null;
  season: string | null;
  archetype: string | null;
  era_conf: number | null;
  tier: Tier;
  tier_rank: number;
  desirability: number | null;
  fair_value_usd: number | null;
  value_conf: 'high' | 'med' | 'low' | 'none' | null;
  comp_count: number | null;
  discount: number | null;
  deal_score: number;
  deal_label: DealLabel | null;
  suspicious: number;
  flags: string[];
  reject_reason: string | null;
  is_auction: number;
  auction_end_at: number | null;
  bids: number | null;
  status: string;
  listed_at: number;
  price_changed_at: number | null;
  watched: boolean;
  my_feedback: string[];
}

export interface FeedResponse {
  items: FeedItem[];
  next_cursor: string | null;
}

export interface ExplainEntity {
  id: string;
  name: string;
  conf?: number;
  matched?: string[];
  years?: [number, number | null] | null;
  cues?: string[];
  anti_cues?: string[];
}
export interface Explain {
  entities: null | {
    brand?: ExplainEntity | null;
    era?: ExplainEntity | null;
    season?: ExplainEntity | null;
    archetype?: ExplainEntity | null;
  };
  desirability: null | {
    score: number;
    tier: Tier;
    ceiling: string | null;
    ceiling_reason: string | null;
    factors: { k: string; label: string; v: number; w?: number }[] | null;
  };
  value: null | {
    fair_value_usd: number | null;
    conf: string;
    level: string;
    market: string;
    comp_count: number;
    range_usd: [number, number] | null;
    comps: { id: string; title: string; price_usd: number; sold_at: number; url: string | null; source: string }[] | null;
  };
  cost: null | {
    price_usd: number;
    proxy_fee_usd: number | null;
    domestic_shipping_usd: number | null;
    intl_shipping_usd: number | null;
    duty_usd: number | null;
    landed_usd: number;
    fx_fallback: boolean;
  };
  deal: null | {
    discount: number | null;
    score: number;
    label: string;
    risk: number | null;
    factors: { k: string; label: string; v: number }[] | null;
  };
  flags: null | { id: string; label: string; severity: number }[];
  similarity: null | { taste: number | null; junk: number | null; visual: number | null };
  ranker: null | { prob: number | null; model: string };
}

export interface ListingDetail {
  item: FeedItem;
  explain: Explain | null;
  snapshots: { at: number; price_usd: number; status: string }[];
  feedback: string[];
  watched: boolean;
  description: string | null;
  images: string[];
  size_raw: string | null;
  condition_raw: string | null;
  brand_raw: string | null;
  seller: { username: string | null; rating: number | null; review_count: number | null; sales_count: number | null; trust: number | null } | null;
}

export interface TaxEntity {
  id: string;
  kind: string;
  name: string;
  parent: string | null;
  weight: number | null;
  trend_prior: number | null;
  years?: (number | null)[] | null;
  code?: string | null;
  /** Era names repeat within a brand; the label adds the years. */
  label?: string;
  active?: number;
}
export interface Taxonomy {
  brands: TaxEntity[];
  eras: TaxEntity[];
  archetypes: TaxEntity[];
  seasons?: TaxEntity[];
}

export interface SourceHealth {
  source: string;
  last_run_at: number | null;
  last_ok_at: number | null;
  last_status: string | null;
  last_error: string | null;
  consecutive_failures: number;
  breaker_until: number | null;
  rung: string | null;
  items_day: string | null;
  items_today: number;
  items_total: number;
}
export interface Health {
  sources: SourceHealth[];
  counts: { active?: number; rejected?: number; today?: number; comps?: number; feedback?: number };
  spend: { apify_month_usd: number; apify_cap_usd: number; llm_month_usd: number };
  runs: { job: string; at: number; stats: Record<string, unknown> | null }[];
}

export interface Rule {
  q?: string;
  brand?: string;
  era?: string;
  archetype?: string;
  sizes?: string[];
  max_landed_usd?: number;
  min_tier?: string;
  labels?: string[];
  sources?: string[];
  region?: string;
}
export interface SavedSearch {
  id: number;
  name: string;
  rule: Rule;
  enabled: number;
  is_global: number;
  created_at: number;
}
export interface SizeProfile {
  tops: string[];
  bottoms: string[];
  shoes: string[];
  tailoring: string[];
}

export interface TrendSeries {
  kind: string;
  id: string;
  name: string;
  points: { week: string; score: number; mentions: number }[];
}
export interface Trends {
  heat: { id: string; kind: string; name: string; parent: string | null; trend_prior: number; label: string }[];
  series: TrendSeries[];
  rising: { kind: string; id: string; name: string; delta: number }[];
}

export interface Comp {
  id: string;
  source: string;
  url: string | null;
  title: string;
  image_url: string | null;
  brand: string | null;
  era: string | null;
  season: string | null;
  archetype: string | null;
  size_norm: string | null;
  sold_price_usd: number;
  sold_at: number;
}
export interface CompsResponse {
  stats: { count: number; median: number | null; p25: number | null; p75: number | null };
  comps: Comp[];
  by_month: { month: string; median: number | null; count: number }[];
}
