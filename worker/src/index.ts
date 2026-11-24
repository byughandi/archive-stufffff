/**
 * Grail Radar Worker: static site (via the ASSETS binding) + read-mostly JSON API under /api.
 * No scoring happens here. Every query is a single indexed read of rows the pipeline precomputed.
 */
import { createClient, type Client, type InValue } from "@libsql/client/web";

export interface Env {
  ASSETS: Fetcher;
  TURSO_DATABASE_URL: string;
  TURSO_AUTH_TOKEN?: string;
  ACCESS_TEAM_DOMAIN?: string;
  ACCESS_AUD?: string;
  ALLOWED_EMAIL?: string;
  DEV_NO_AUTH?: string;
}

type Row = Record<string, unknown>;
const json = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
const bad = (msg: string, status = 400) => json({ error: msg }, status);
const now = () => Math.floor(Date.now() / 1000);

// ---------------------------------------------------------------- database
let client: Client | null = null;
let clientUrl = "";
function db(env: Env): Client {
  if (!client || clientUrl !== env.TURSO_DATABASE_URL) {
    clientUrl = env.TURSO_DATABASE_URL;
    client = createClient({ url: env.TURSO_DATABASE_URL, authToken: env.TURSO_AUTH_TOKEN || undefined });
  }
  return client;
}
async function q(env: Env, sql: string, args: InValue[] = []): Promise<Row[]> {
  const rs = await db(env).execute({ sql, args });
  return rs.rows.map((r) => {
    const o: Row = {};
    rs.columns.forEach((c, i) => (o[c] = typeof r[i] === "bigint" ? Number(r[i]) : r[i]));
    return o;
  });
}
const marks = (n: number) => Array(n).fill("?").join(",");

// ---------------------------------------------------------------- Cloudflare Access
type Jwk = JsonWebKey & { kid: string };
let jwks: { at: number; keys: Map<string, CryptoKey> } | null = null;
const b64u = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

async function accessKeys(team: string, force = false) {
  if (jwks && !force && Date.now() - jwks.at < 3600_000) return jwks.keys;
  const resp = await fetch(`https://${team}/cdn-cgi/access/certs`);
  if (!resp.ok) throw new Error(`access certs ${resp.status}`);
  const body = (await resp.json()) as { keys: Jwk[] };
  const keys = new Map<string, CryptoKey>();
  for (const k of body.keys) {
    keys.set(k.kid, await crypto.subtle.importKey("jwk", k, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]));
  }
  jwks = { at: Date.now(), keys };
  return keys;
}

/** Returns the authenticated email, or a Response to send back. Fails closed. */
async function authenticate(req: Request, env: Env): Promise<string | Response> {
  // Local development only. The bypass is ignored unless the request is addressed to a loopback host, so a
  // DEV_NO_AUTH variable that leaks into a deployed Worker opens nothing.
  const host = new URL(req.url).hostname;
  if (env.DEV_NO_AUTH === "1" && (host === "127.0.0.1" || host === "localhost" || host === "[::1]")) return "dev@localhost";
  const team = (env.ACCESS_TEAM_DOMAIN || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
  const aud = env.ACCESS_AUD || "";
  if (!team || !aud) return bad("Cloudflare Access is not configured for this Worker.", 503);
  const cookie = /(?:^|;\s*)CF_Authorization=([^;]+)/.exec(req.headers.get("cookie") || "");
  const token = req.headers.get("cf-access-jwt-assertion") || (cookie ? cookie[1] : "");
  if (!token) return bad("Not signed in.", 401);
  try {
    const [h, p, s] = token.split(".");
    const header = JSON.parse(new TextDecoder().decode(b64u(h)));
    const payload = JSON.parse(new TextDecoder().decode(b64u(p)));
    if (header.alg !== "RS256") throw new Error("alg");
    let key = (await accessKeys(team)).get(header.kid);
    if (!key) key = (await accessKeys(team, true)).get(header.kid);
    if (!key) throw new Error("kid");
    const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64u(s), new TextEncoder().encode(`${h}.${p}`));
    if (!ok) throw new Error("signature");
    const auds: string[] = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
    if (!auds.includes(aud)) throw new Error("aud");
    if (payload.iss !== `https://${team}`) throw new Error("iss");
    if (typeof payload.exp !== "number" || payload.exp < now()) throw new Error("exp");
    const email = String(payload.email || "");
    if (env.ALLOWED_EMAIL && email.toLowerCase() !== env.ALLOWED_EMAIL.toLowerCase()) return bad("Forbidden.", 403);
    return email || "user";
  } catch {
    return bad("Invalid session.", 401);
  }
}

// ---------------------------------------------------------------- feed
const FEED_COLS =
  "f.listing_id, f.source, f.region, f.url, f.proxy_url, f.title, f.image_url, f.price, f.currency, f.price_usd," +
  " f.landed_usd, f.prev_price_usd, f.size_norm, f.condition_norm, f.brand, f.era, f.season, f.archetype, f.era_conf," +
  " f.tier, f.tier_rank, f.desirability, f.fair_value_usd, f.value_conf, f.comp_count, f.discount, f.deal_score," +
  " f.deal_label, f.suspicious, f.flags, f.reject_reason, f.is_auction, f.auction_end_at, f.bids, f.status," +
  " f.listed_at, f.price_changed_at";
const SORTS: Record<string, string> = {
  best: "f.tier_rank ASC, f.sort_key DESC",
  newest: "f.listed_at DESC",
  price_asc: "f.landed_usd ASC",
  price_desc: "f.landed_usd DESC",
  discount: "f.discount DESC",
  ending: "f.auction_end_at ASC",
};
const CONF_AT_LEAST: Record<string, string[]> = { low: ["low", "med", "high"], med: ["med", "high"], high: ["high"] };
const list = (v: string | null) => (v ? v.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 30) : []);
const num = (v: string | null) => (v !== null && v !== "" && Number.isFinite(Number(v)) ? Number(v) : null);

async function decorate(env: Env, rows: Row[]) {
  const ids = rows.map((r) => String(r.listing_id));
  const watched = new Set<string>();
  const fb = new Map<string, string[]>();
  if (ids.length) {
    const [w, f] = await Promise.all([
      q(env, `SELECT listing_id FROM watchlist WHERE listing_id IN (${marks(ids.length)})`, ids),
      q(env, `SELECT DISTINCT listing_id, kind FROM feedback WHERE listing_id IN (${marks(ids.length)})`, ids),
    ]);
    w.forEach((r) => watched.add(String(r.listing_id)));
    f.forEach((r) => fb.set(String(r.listing_id), [...(fb.get(String(r.listing_id)) || []), String(r.kind)]));
  }
  return rows.map((r) => {
    let flags: unknown = [];
    try { flags = r.flags ? JSON.parse(String(r.flags)) : []; } catch { /* keep [] */ }
    return { ...r, flags, watched: watched.has(String(r.listing_id)), my_feedback: fb.get(String(r.listing_id)) || [] };
  });
}

async function feed(env: Env, url: URL) {
  const p = url.searchParams;
  const tab = p.get("tab") || "feed";
  const where: string[] = [];
  const args: InValue[] = [];
  let join = "";
  let sort = SORTS[p.get("sort") || ""] || SORTS.best;
  const t = now();

  if (tab === "watchlist") {
    join = " JOIN watchlist w ON w.listing_id = f.listing_id";
    sort = p.get("sort") ? sort : "w.added_at DESC";
  } else {
    where.push("f.status = 'active'");
  }
  if (tab === "rejected") where.push("f.tier = 'X'");
  else if (tab !== "watchlist") where.push("f.tier_rank < 9");
  if (tab === "steals") { where.push("f.deal_label = 'steal'"); if (!p.get("sort")) sort = "f.sort_key DESC"; }
  if (tab === "grails") where.push("f.tier = 'S'");
  if (tab === "heat") where.push("f.tier = 'A'");
  if (tab === "new") { where.push("f.listed_at >= ?"); args.push(t - 3600); if (!p.get("sort")) sort = SORTS.newest; }
  if (tab === "japan") where.push("f.region = 'JP'");
  if (tab === "ending") {
    where.push("f.is_auction = 1", "f.auction_end_at > ?", "f.auction_end_at < ?");
    args.push(t, t + 86400);
    if (!p.get("sort")) sort = SORTS.ending;
  }

  for (const [param, col] of [["brand", "f.brand"], ["era", "f.era"], ["archetype", "f.archetype"], ["size", "f.size_norm"],
    ["source", "f.source"], ["region", "f.region"], ["label", "f.deal_label"], ["tier", "f.tier"]] as const) {
    const vals = list(p.get(param));
    if (vals.length) { where.push(`${col} IN (${marks(vals.length)})`); args.push(...vals); }
  }
  const minP = num(p.get("min_price")), maxP = num(p.get("max_price"));
  if (minP !== null) { where.push("f.landed_usd >= ?"); args.push(minP); }
  if (maxP !== null) { where.push("f.landed_usd <= ?"); args.push(maxP); }
  const conf = CONF_AT_LEAST[p.get("min_conf") || ""];
  if (conf) { where.push(`f.value_conf IN (${marks(conf.length)})`); args.push(...conf); }
  if (p.get("hide_suspicious") === "1") where.push("f.suspicious = 0");
  const text = (p.get("q") || "").trim().slice(0, 60);
  if (text) { where.push("f.title LIKE ? ESCAPE '\\'"); args.push(`%${text.replace(/[\\%_]/g, "\\$&")}%`); }

  const whereSql = where.length ? " WHERE " + where.join(" AND ") : "";
  if (p.get("count") === "1") {
    // One capped count for the filter sheet's "Show N listings" button, instead of paging the feed.
    const r = await q(env, `SELECT COUNT(*) AS n FROM (SELECT 1 FROM feed f${join}${whereSql} LIMIT 1001)`, args);
    const n = Number(r[0]?.n || 0);
    return json({ count: Math.min(n, 1000), capped: n > 1000 });
  }
  const limit = Math.min(Math.max(num(p.get("limit")) || 30, 1), 60);
  const offset = Math.max(num(p.get("cursor")) || 0, 0);
  const sql = `SELECT ${FEED_COLS} FROM feed f${join}${whereSql}` +
    ` ORDER BY ${sort}, f.listing_id LIMIT ? OFFSET ?`;
  const rows = await q(env, sql, [...args, limit + 1, offset]);
  const more = rows.length > limit;
  return json({ items: await decorate(env, rows.slice(0, limit)), next_cursor: more ? String(offset + limit) : null });
}

async function listing(env: Env, id: string) {
  const [f, s, snaps, l] = await Promise.all([
    q(env, `SELECT ${FEED_COLS} FROM feed f WHERE f.listing_id = ?`, [id]),
    q(env, "SELECT explain, scored_at, model_version FROM scores WHERE listing_id = ?", [id]),
    q(env, "SELECT at, price_usd, status FROM listing_snapshots WHERE listing_id = ? ORDER BY at", [id]),
    q(env, "SELECT description, image_urls, size_raw, condition_raw, brand_raw, seller_id FROM listings WHERE id = ?", [id]),
  ]);
  if (!f.length) return bad("Listing not found.", 404);
  const [item] = await decorate(env, f);
  let explain: unknown = null, images: unknown = [];
  try { explain = s[0]?.explain ? JSON.parse(String(s[0].explain)) : null; } catch { /* null */ }
  try { images = l[0]?.image_urls ? JSON.parse(String(l[0].image_urls)) : []; } catch { /* [] */ }
  let seller: Row | null = null;
  if (l[0]?.seller_id) {
    seller = (await q(env, "SELECT username, rating, review_count, sales_count, trust FROM sellers WHERE id = ?", [String(l[0].seller_id)]))[0] || null;
  }
  return json({
    item, explain, snapshots: snaps, feedback: item.my_feedback, watched: item.watched,
    description: l[0]?.description ?? null, images, size_raw: l[0]?.size_raw ?? null,
    condition_raw: l[0]?.condition_raw ?? null, brand_raw: l[0]?.brand_raw ?? null, seller,
    scored_at: s[0]?.scored_at ?? null, model_version: s[0]?.model_version ?? null,
  });
}

// ---------------------------------------------------------------- writes
const FEEDBACK_KINDS = new Set(["up", "down", "cop", "fake", "wrong_era", "wrong_brand", "bought"]);
async function body(req: Request): Promise<Row | null> {
  try {
    const text = await req.text();
    if (text.length > 8000) return null;
    const v = JSON.parse(text);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Row) : null;
  } catch { return null; }
}

async function postFeedback(env: Env, req: Request) {
  const b = await body(req);
  const id = String(b?.listing_id || ""), kind = String(b?.kind || "");
  if (!id || !FEEDBACK_KINDS.has(kind)) return bad("listing_id and a valid kind are required.");
  if (b?.undo === true) {
    await q(env, "DELETE FROM feedback WHERE listing_id = ? AND kind = ?", [id, kind]);
    return json({ ok: true, undone: true });
  }
  const feat = await q(env,
    "SELECT relevant_prob, taste_sim, junk_sim, desirability, tier, discount, deal_label, risk FROM scores WHERE listing_id = ?", [id]);
  // Yes and No are exclusive: recording one clears the other.
  const clear = kind === "up" ? [kind, "down"] : kind === "down" ? [kind, "up"] : [kind];
  await q(env, `DELETE FROM feedback WHERE listing_id = ? AND kind IN (${marks(clear.length)})`, [id, ...clear]);
  await q(env, "INSERT INTO feedback (listing_id, kind, note, features, created_at) VALUES (?,?,?,?,?)",
    [id, kind, b?.note ? String(b.note).slice(0, 300) : null, feat[0] ? JSON.stringify(feat[0]) : null, now()]);
  return json({ ok: true });
}

const RULE_KEYS = ["q", "brand", "era", "archetype", "sizes", "max_landed_usd", "min_tier", "labels", "sources", "region"];
function cleanRule(input: unknown): string | null {
  if (!input || typeof input !== "object") return null;
  const out: Row = {};
  for (const k of RULE_KEYS) {
    const v = (input as Row)[k];
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) continue;
    out[k] = Array.isArray(v) ? v.slice(0, 20).map(String) : typeof v === "number" ? v : String(v).slice(0, 80);
  }
  return Object.keys(out).length ? JSON.stringify(out) : null;
}

async function searches(env: Env, req: Request, id: string | null) {
  if (req.method === "GET") {
    const rows = await q(env, "SELECT id, name, rule, enabled, is_global, created_at FROM saved_searches ORDER BY is_global DESC, id");
    const kv = await q(env, "SELECT v, updated_at FROM kv WHERE k = 'alert_delivery'");
    let delivery: unknown = null;
    try { if (kv[0]) delivery = { ...(JSON.parse(String(kv[0].v)) as Row), updated_at: kv[0].updated_at }; } catch { /* null */ }
    return json({ searches: rows.map((r) => ({ ...r, rule: JSON.parse(String(r.rule || "{}")) })), delivery });
  }
  if (req.method === "DELETE" && id) {
    await q(env, "DELETE FROM saved_searches WHERE id = ? AND is_global = 0", [Number(id)]);
    return json({ ok: true });
  }
  const b = await body(req);
  if (!b) return bad("Invalid body.");
  if (req.method === "POST") {
    const rule = cleanRule(b.rule), name = String(b.name || "").trim().slice(0, 60);
    if (!rule || !name) return bad("A name and at least one rule field are required.");
    await q(env, "INSERT INTO saved_searches (name, rule, enabled, is_global, created_at) VALUES (?,?,1,0,?)", [name, rule, now()]);
    return json({ ok: true });
  }
  if (req.method === "PUT" && id) {
    const sets: string[] = [], args: InValue[] = [];
    if (typeof b.enabled === "boolean") { sets.push("enabled = ?"); args.push(b.enabled ? 1 : 0); }
    if (typeof b.name === "string" && b.name.trim()) { sets.push("name = ?"); args.push(b.name.trim().slice(0, 60)); }
    const rule = cleanRule(b.rule);
    if (rule) { sets.push("rule = ?"); args.push(rule); }
    if (!sets.length) return bad("Nothing to update.");
    // The global rule can be switched on and off, but its definition is fixed.
    await q(env, `UPDATE saved_searches SET ${sets.join(", ")} WHERE id = ?${rule ? " AND is_global = 0" : ""}`, [...args, Number(id)]);
    return json({ ok: true });
  }
  return bad("Method not allowed.", 405);
}

// ---------------------------------------------------------------- read models
let taxCache: { at: number; body: unknown } | null = null;
async function taxonomy(env: Env) {
  if (taxCache && Date.now() - taxCache.at < 300_000) return json(taxCache.body);
  const [ents, counts] = await Promise.all([
    q(env, "SELECT id, kind, name, parent, weight, trend_prior, data FROM taxonomy_entities WHERE kind IN ('brand','era','season','archetype') ORDER BY name"),
    q(env, "SELECT brand, COUNT(*) AS n FROM feed WHERE status = 'active' AND tier_rank < 9 AND brand IS NOT NULL GROUP BY brand"),
  ]);
  const n = new Map(counts.map((r) => [String(r.brand), Number(r.n)]));
  const shaped = ents.map((e) => {
    let data: Row = {};
    try { data = e.data ? (JSON.parse(String(e.data)) as Row) : {}; } catch { /* {} */ }
    const years = Array.isArray(data.years) ? (data.years as (number | null)[]) : null;
    const span = years && years[0] ? `${years[0]}–${years[1] ?? "now"}` : null;
    // Eras are named after designers, which is not unique within a brand; `label` adds the years.
    return {
      id: String(e.id), kind: String(e.kind), name: String(e.name), parent: e.parent ?? null, weight: e.weight ?? null,
      trend_prior: e.trend_prior ?? null, years, code: data.code ?? null,
      label: e.kind === "era" && span ? `${e.name}, ${span}` : String(e.name),
    };
  });
  const out = {
    brands: shaped.filter((e) => e.kind === "brand").map((e) => ({ ...e, active: n.get(String(e.id)) || 0 })),
    eras: shaped.filter((e) => e.kind === "era"),
    seasons: shaped.filter((e) => e.kind === "season"),
    archetypes: shaped.filter((e) => e.kind === "archetype"),
  };
  taxCache = { at: Date.now(), body: out };
  return json(out);
}

async function trends(env: Env) {
  const [scores, ents] = await Promise.all([
    q(env, "SELECT entity_kind, entity_id, week, score, mentions, source FROM trend_scores WHERE week >= date('now','-112 days') ORDER BY week"),
    q(env, "SELECT id, kind, name, parent, trend_prior FROM taxonomy_entities WHERE trend_prior IS NOT NULL ORDER BY trend_prior DESC LIMIT 60"),
  ]);
  const names = new Map((await q(env, "SELECT id, name, parent FROM taxonomy_entities")).map((r) => [String(r.id), r]));
  const label = (id: string) => {
    const e = names.get(id);
    if (!e) return id;
    const parent = e.parent ? names.get(String(e.parent)) : null;
    return parent ? `${parent.name}, ${e.name}` : String(e.name);
  };
  const series = new Map<string, { kind: string; id: string; name: string; points: Row[] }>();
  for (const r of scores) {
    if (r.source === "prior") continue;
    const key = `${r.entity_kind}:${r.entity_id}`;
    if (!series.has(key)) series.set(key, { kind: String(r.entity_kind), id: String(r.entity_id), name: label(String(r.entity_id)), points: [] });
    series.get(key)!.points.push({ week: r.week, score: r.score, mentions: r.mentions });
  }
  const all = [...series.values()];
  const rising = all
    .filter((s) => s.points.length >= 2)
    .map((s) => ({ kind: s.kind, id: s.id, name: s.name, delta: Number(s.points[s.points.length - 1].score) - Number(s.points[s.points.length - 2].score) }))
    .filter((s) => s.delta > 0).sort((a, b) => b.delta - a.delta).slice(0, 12);
  return json({ heat: ents.map((e) => ({ ...e, label: label(String(e.id)) })), series: all, rising });
}

const pct = (sorted: number[], f: number) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(f * (sorted.length - 1) + 0.5))] : null);
async function comps(env: Env, url: URL) {
  const p = url.searchParams, where = ["classified = 1", "sold_at >= ?"], args: InValue[] = [now() - 540 * 86400];
  for (const k of ["brand", "era", "archetype", "season"]) {
    const v = p.get(k);
    if (v) { where.push(`${k} = ?`); args.push(v); }
  }
  if (where.length === 2) return bad("Pick at least a brand.");
  const rows = await q(env,
    `SELECT id, source, url, title, image_url, brand, era, season, archetype, size_norm, sold_price_usd, sold_at FROM comps_sold WHERE ${where.join(" AND ")} ORDER BY sold_at DESC LIMIT 400`, args);
  const prices = rows.map((r) => Number(r.sold_price_usd)).sort((a, b) => a - b);
  const months = new Map<string, number[]>();
  for (const r of rows) {
    const m = new Date(Number(r.sold_at) * 1000).toISOString().slice(0, 7);
    months.set(m, [...(months.get(m) || []), Number(r.sold_price_usd)]);
  }
  const by_month = [...months.entries()].sort().map(([month, v]) => {
    v.sort((a, b) => a - b);
    return { month, median: pct(v, 0.5), count: v.length };
  });
  return json({ stats: { count: prices.length, median: pct(prices, 0.5), p25: pct(prices, 0.25), p75: pct(prices, 0.75) }, comps: rows.slice(0, 120), by_month });
}

async function health(env: Env) {
  const month = Math.floor(Date.UTC(new Date().getUTCFullYear(), new Date().getUTCMonth(), 1) / 1000);
  const [sources, spend, counts, runs] = await Promise.all([
    q(env, "SELECT * FROM source_health ORDER BY source"),
    q(env, "SELECT vendor, SUM(usd) AS usd FROM spend_ledger WHERE at >= ? GROUP BY vendor", [month]),
    q(env, "SELECT (SELECT COUNT(*) FROM feed WHERE status = 'active' AND tier_rank < 9) AS active," +
      " (SELECT COUNT(*) FROM feed WHERE status = 'active' AND tier = 'X') AS rejected," +
      " (SELECT COUNT(*) FROM listings WHERE first_seen_at >= ?) AS today," +
      " (SELECT COUNT(*) FROM comps_sold) AS comps, (SELECT COUNT(*) FROM feedback) AS feedback", [now() - 86400]),
    q(env, "SELECT k, v, updated_at FROM kv WHERE k LIKE 'run_stats:%'"),
  ]);
  const usd = (v: string) => Number(spend.find((r) => r.vendor === v)?.usd || 0);
  return json({
    sources, counts: counts[0] || {},
    spend: { apify_month_usd: usd("apify"), apify_cap_usd: 5, llm_month_usd: usd("anthropic") },
    runs: runs.map((r) => { let v: unknown = null; try { v = JSON.parse(String(r.v)); } catch { /* null */ } return { job: String(r.k).slice(10), at: r.updated_at, stats: v }; }),
  });
}

async function profile(env: Env, req: Request) {
  if (req.method === "GET") {
    const rows = await q(env, "SELECT v FROM kv WHERE k = 'size_profile'");
    let v: unknown = { tops: [], bottoms: [], shoes: [], tailoring: [] };
    try { if (rows[0]) v = JSON.parse(String(rows[0].v)); } catch { /* default */ }
    return json({ size_profile: v });
  }
  const b = await body(req);
  const sp = b?.size_profile as Row | undefined;
  if (!sp || typeof sp !== "object") return bad("size_profile is required.");
  const clean: Row = {};
  for (const k of ["tops", "bottoms", "shoes", "tailoring"]) {
    clean[k] = Array.isArray(sp[k]) ? (sp[k] as unknown[]).slice(0, 12).map((s) => String(s).slice(0, 8)) : [];
  }
  await q(env, "INSERT INTO kv (k, v, updated_at) VALUES ('size_profile', ?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at",
    [JSON.stringify(clean), now()]);
  return json({ ok: true, size_profile: clean });
}

// ---------------------------------------------------------------- router
async function api(req: Request, env: Env, url: URL): Promise<Response> {
  const path = url.pathname.replace(/\/+$/, "");
  const m = req.method;
  if (m !== "GET" && m !== "HEAD") {
    // Same-origin only for anything that writes.
    const origin = req.headers.get("origin");
    if (origin && new URL(origin).host !== url.host) return bad("Cross-origin writes are not allowed.", 403);
  }
  if (path === "/api/feed" && m === "GET") return feed(env, url);
  if (path === "/api/taxonomy" && m === "GET") return taxonomy(env);
  if (path === "/api/trends" && m === "GET") return trends(env);
  if (path === "/api/comps" && m === "GET") return comps(env, url);
  if (path === "/api/health" && m === "GET") return health(env);
  if (path === "/api/feedback" && m === "POST") return postFeedback(env, req);
  if (path === "/api/profile" && (m === "GET" || m === "PUT")) return profile(env, req);
  if (path === "/api/searches") return searches(env, req, null);
  let mm = /^\/api\/searches\/(\d+)$/.exec(path);
  if (mm) return searches(env, req, mm[1]);
  mm = /^\/api\/listing\/(.+)$/.exec(path);
  if (mm && m === "GET") return listing(env, decodeURIComponent(mm[1]));
  mm = /^\/api\/watchlist\/(.+)$/.exec(path);
  if (mm && (m === "PUT" || m === "DELETE")) {
    const id = decodeURIComponent(mm[1]);
    if (m === "PUT") await q(env, "INSERT OR IGNORE INTO watchlist (listing_id, added_at) VALUES (?, ?)", [id, now()]);
    else await q(env, "DELETE FROM watchlist WHERE listing_id = ?", [id]);
    return json({ ok: true });
  }
  return bad("Not found.", 404);
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(req);
    const who = await authenticate(req, env);
    if (who instanceof Response) return who;
    if (!env.TURSO_DATABASE_URL) return bad("Database is not configured.", 503);
    try {
      return await api(req, env, url);
    } catch (e) {
      console.error("api error", url.pathname, e instanceof Error ? e.message : e);
      return bad("Something went wrong reading the database.", 500);
    }
  },
} satisfies ExportedHandler<Env>;
