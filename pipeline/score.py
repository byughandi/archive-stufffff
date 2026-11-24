"""Stage 7 and the cascade driver: deal score, explain JSON, and writes to listing_entities / scores / feed.

discount   = (fair_value - landed) / fair_value
deal_score = discount x value_conf_w x era_conf_w x condition_factor x size_fit x seller_trust - 0.5 x risk

Fair value is expressed as the cost of acquiring a typical comparable in the comps' market: JP comps are turned
into a landed-equivalent with the same Japan cost model as the listing (so a JP listing valued on JP comps is
compared like for like; `explain.value.market` says "JP"); US comps are used as sticker prices. The JP->US
uplift is a knob (`jp_to_us_uplift`, default 1.0), never invented.

Labels: steal (>= 40% under, value_conf med+), great (25-40%, or >= 40% on low confidence), good (15-25%),
fair (within +-15%), overpriced (> 15% over), suspicious (>= 40% under with serious risk; shown, never alerted),
unknown (no usable fair value).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field

from core.config import japan_costs, settings
from core.db import Database, now
from core.taxonomy import Taxonomy, load_taxonomy

from . import VERSION, cfg
from .classify import Entities, Matcher, get_matcher
from .comps import CompsIndex, market_of
from .desirability import era_matters, finalize, parts
from .embed import get_embedder, hamming, phash_urls, visual_grail_match
from .filter import Filter, FilterResult, flag, get_filter
from .normalize import condition_norm, find_crossposts, landed_cost, norm_text, parse_size, size_fit, tokenize
from .ranker import FEATURES, Ranker, load_ranker

TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "X": 9}
VC_W = {"high": 1.0, "med": 0.8, "low": 0.4, "none": 0.0}   # a soft number counts for less than half a firm one
LISTING_COLS = ("l.id, l.source, l.region, l.lang, l.url, l.proxy_url, l.title, l.description, l.brand_raw,"
                " l.category_raw, l.size_raw, l.condition_raw, l.price, l.currency, l.price_usd, l.shipping_usd,"
                " l.prev_price_usd, l.price_changed_at, l.seller_id, l.image_url, l.phash, l.is_auction,"
                " l.auction_end_at, l.bids, l.buy_now_usd, l.status, l.listed_at, l.first_seen_at, l.canonical_id, l.needs_score,"
                " s.rating AS seller_rating, s.review_count AS seller_reviews")


@dataclass
class Context:
    tax: Taxonomy
    matcher: Matcher
    filt: Filter
    ranker: Ranker
    comps: CompsIndex | None
    jpy_per_usd: float
    fx_fallback: bool
    jc: dict
    size_profile: dict
    rarity: dict = field(default_factory=dict)
    ig_trend: dict = field(default_factory=dict)
    known_phash: list = field(default_factory=list)   # [(phash, listing_id, seller_id)]
    at: int = 0
    use_embed: bool = True
    use_phash: bool = False


def build_context(db: Database | None, offline: bool = False, use_phash: bool | None = None) -> Context:
    tax = load_taxonomy()
    jc = japan_costs()
    if db is None or offline:
        fb = settings()["fx"]["fallback_per_usd"]
        jpy, fxfb = float(fb["JPY"]), True
        if db is not None:
            raw = db.kv_get("fx_rates")
            if raw:
                jpy, fxfb = float(json.loads(raw)["per_usd"].get("JPY", jpy)), False
    else:
        from core.fx import load_fx
        fx = load_fx(db)
        jpy, fxfb = float(fx.per_usd.get("JPY", 150.0)), fx.fallback
    ctx = Context(tax=tax, matcher=get_matcher(), filt=get_filter(), ranker=load_ranker(db), comps=None,
                  jpy_per_usd=jpy, fx_fallback=fxfb, jc=jc, size_profile={}, at=now())
    prof = None
    if db is not None:
        raw = db.kv_get("size_profile")
        if raw:
            try:
                prof = json.loads(raw)
            except Exception:
                prof = None
    ctx.size_profile = prof or (settings().get("size_profile") or {})
    if db is not None and not offline:
        ctx.comps = CompsIndex.from_db(db, tax)
        ctx.rarity = ctx.comps.counts()
        since = now() - int(float(cfg("rarity_window_days")) * 86400)
        for r in db.query("SELECT e.brand, e.era, e.archetype, COUNT(*) AS n FROM listing_entities e JOIN listings l"
                          " ON l.id = e.listing_id WHERE l.first_seen_at >= ? AND e.brand IS NOT NULL"
                          " GROUP BY 1, 2, 3", (since,)):
            k = (r["brand"], r["era"], r["archetype"])
            ctx.rarity[k] = ctx.rarity.get(k, 0) + int(r["n"])
        wk = db.scalar("SELECT MAX(week) FROM trend_scores WHERE source = 'ig'")
        if wk:
            for r in db.query("SELECT entity_kind, entity_id, score FROM trend_scores WHERE source='ig' AND week=?", (wk,)):
                ctx.ig_trend[(r["entity_kind"], r["entity_id"])] = float(r["score"])
        ctx.known_phash = [(r["phash"], r["id"], r["seller_id"]) for r in
                           db.query("SELECT id, seller_id, phash FROM listings WHERE phash IS NOT NULL")]
        ctx.use_phash = True if use_phash is None else use_phash
    return ctx


# ------------------------------------------------------------------------------------------------ analysis
@dataclass
class Result:
    listing: dict
    tnorm: str = ""
    ent: Entities | None = None
    filt: FilterResult | None = None
    size_norm: str | None = None
    cond: float | None = None
    cost: dict | None = None
    taste: float | None = None
    junk: float | None = None
    parts: dict | None = None
    features: dict | None = None
    prob: float | None = None
    desir: dict | None = None
    value: dict | None = None
    deal: dict | None = None
    tier: str = "X"
    reject_reason: str | None = None
    flags: list = field(default_factory=list)
    fair_value: float | None = None
    sort_key: float = 0.0
    explain: dict | None = None


def _is_current_retail(source: str | None, ctx: Context) -> bool:
    if not source or not source.startswith("shop:"):
        return False
    slug = source.split(":", 1)[1]
    for w in (ctx.tax.sellers or {}).get("webshops") or []:
        if w.get("stock") == "current_retail" and slug and slug in str(w.get("url", "")).lower():
            return True
    return False


def analyze(listing: dict, ctx: Context) -> Result:
    r = Result(listing=listing)
    title = listing.get("title") or ""
    r.tnorm = norm_text(title)
    desc = listing.get("description")
    retail = _is_current_retail(listing.get("source"), ctx)
    r.ent = ctx.matcher.classify(title, desc, listing.get("brand_raw"), norm=r.tnorm, current_retail=retail)
    toks = tokenize(r.tnorm)
    dtoks = tokenize(norm_text(desc)) if desc else []
    r.filt = ctx.filt.apply(listing, r.ent, r.tnorm, toks, dtoks)
    if retail and r.ent.brand:
        r.filt.add(flag("current_retail", 1, listing.get("source")))
        r.filt.cap("C", "current-season retail stock")
    if listing.get("_duplicate_of"):
        r.filt.reject_reason = r.filt.reject_reason or f"duplicate_of:{listing['_duplicate_of']}"
    arch = r.ent.archetype
    r.size_norm = parse_size(listing.get("size_raw"), r.tnorm, arch)
    full = r.tnorm + " " + norm_text(desc)
    r.cond = condition_norm(listing.get("source") or "", listing.get("condition_raw"), full)
    wc = ctx.tax.archetypes.get(arch, {}).get("ship_weight_class") if arch else None
    basis = float(listing.get("price_usd") or 0)
    if listing.get("is_auction"):
        # auctions: buy-now price is the real ask; otherwise the current bid (label capped later unless ending)
        if listing.get("buy_now_usd"):
            basis = float(listing["buy_now_usd"])
            listing["_auction_basis"] = "buy_now"
        else:
            end = listing.get("auction_end_at")
            ending = end is not None and 0 <= int(end) - ctx.at <= 2 * 3600
            if ending:
                r.filt.add(flag("ending_soon", 1))
                listing["_auction_basis"] = "ending_soon"
            else:
                # A start price with no bids yet is no more a final price than a live bid is: an auction for
                # a wanted piece gets bid up. Both are capped at "good" and never alerted until the last 2 hours.
                bids = int(listing.get("bids") or 0)
                r.filt.add(flag("auction_in_progress", 1, f"{bids} bids" if bids else "no bids yet"))
                listing["_auction_basis"] = "current_bid"
    listed = listing.get("listed_at")
    if listed and not listing.get("is_auction") and ctx.at - int(listed) > float(cfg("stale_after_days")) * 86400:
        r.filt.add(flag("stale_listing", 1, f"listed {int((ctx.at - int(listed)) / 86400)} days ago"))
    r.cost = landed_cost(listing.get("region") or "US", basis, listing.get("shipping_usd"),
                         wc, full, ctx.jpy_per_usd, ctx.jc, cfg("proxy"), ctx.fx_fallback)
    if listing.get("_auction_basis"):
        r.cost["auction_basis"] = listing["_auction_basis"]
    r.reject_reason = r.filt.reject_reason
    return r


def _features(r: Result, ctx: Context) -> dict:
    p = r.parts
    flags = {f["id"] for f in r.filt.flags}
    return {"has_brand": p["has_brand"], "brand_w": p["brand_w"], "era_resolved": p["era_resolved"],
            "era_w": p["era_w"], "era_conf": r.ent.era_conf if r.ent.brand else 0.0, "unwanted_era": p["unwanted"],
            "season": 1.0 if r.ent.season else 0.0, "piece_w": p["piece_w"], "trend": p["trend"],
            "taste": float(r.taste or 0.0), "junk": float(r.junk or 0.0), "risk": r.filt.risk,
            "stuffing": 1.0 if "keyword_stuffing" in flags else 0.0,
            "archetype_known": 1.0 if r.ent.archetype else 0.0,
            "below_floor": 1.0 if "below_floor" in flags else 0.0, "rarity": p["rarity"]}


def score_results(results: list[Result], ctx: Context) -> str:
    """Stages 3-7 for analysed rows. Returns the embedding backend name."""
    tax = ctx.tax
    live = [r for r in results if not r.reject_reason]
    backend = "skipped"
    if live and ctx.use_embed:
        emb = get_embedder()
        backend = emb.backend
        t, j = emb.similarities([r.listing.get("title") or "" for r in live], [r.ent.concepts for r in live])
        for r, a, b in zip(live, t, j):
            r.taste, r.junk = round(float(a), 4), round(float(b), 4)
    for r in live:
        r.parts = parts(r.ent, tax, ctx.rarity, ctx.ig_trend)
        r.features = _features(r, ctx)
        r.prob = ctx.ranker.prob(r.features)
        r.desir = finalize(r.parts, r.prob, r.ent, r.filt, tax)
        r.tier = r.desir["tier"]
    # perceptual hashes on a capped number of top candidates
    if ctx.use_phash and live:
        cap = int(cfg("phash_cap"))
        cands = sorted([r for r in live if r.listing.get("image_url") and not r.listing.get("phash")],
                       key=lambda r: -r.desir["score"])[:cap]
        hashes = phash_urls([r.listing["image_url"] for r in cands], timeout=float(cfg("phash_timeout")))
        for r in cands:
            h = hashes.get(r.listing["image_url"])
            if h:
                r.listing["phash"] = h
                r.listing["_phash_new"] = True
                ctx.known_phash.append((h, r.listing["id"], r.listing.get("seller_id")))
        for r in live:
            h = r.listing.get("phash")
            if not h:
                continue
            for h2, lid, sid in ctx.known_phash:
                if lid != r.listing["id"] and hamming(h, h2) <= 4:
                    same = sid and sid == r.listing.get("seller_id") and not str(sid).endswith(":0")
                    if not same:
                        r.filt.add(flag("dup_photo", 3, lid), 0.25)
                        break
    for r in live:
        _deal(r, ctx)
    for r in results:
        if r.reject_reason:
            r.tier = "X"
        _assemble(r, ctx, backend)
    return backend


def _deal(r: Result, ctx: Context) -> None:
    tax = ctx.tax
    ent, lst = r.ent, r.listing
    region = lst.get("region") or "US"
    market = "JP" if region == "JP" else "US"
    era = ent.era if ent.era_conf >= cfg("era_resolved") else None
    flags_ids = {f["id"] for f in r.filt.flags}
    if "bundle" in flags_ids:
        v = {"level": "none", "conf": "none", "note": "bundle: no per-item value"}
    elif ctx.comps is not None:
        v = ctx.comps.value(ent.brand, era, ent.season, ent.archetype, market, r.size_norm)
    else:
        v = CompsIndex([], tax).value(ent.brand, era, ent.season, ent.archetype, market, r.size_norm)
    landed = r.cost["landed_usd"]
    fair = rng = None
    basis = None
    if v.get("median"):
        uplift = float(cfg("jp_to_us_uplift"))
        wc = tax.archetypes.get(ent.archetype, {}).get("ship_weight_class") if ent.archetype else None
        if v.get("market") == "JP":
            def eq(x):
                return landed_cost("JP", x * uplift, None, wc, "", ctx.jpy_per_usd, ctx.jc, cfg("proxy"))["landed_usd"]
            fair, rng = eq(v["median"]), [eq(v["p25"]), eq(v["p75"])]
            basis = "landed_equivalent_of_jp_sold"
        else:
            fair, rng = v["median"], [v["p25"], v["p75"]]
            basis = "sold_price"
    r.value = v
    r.fair_value = round(fair, 2) if fair else None
    risk = r.filt.risk
    extra_flags: list[dict] = []
    if fair:
        discount = (fair - landed) / fair
    else:
        discount = None
    base_risk = risk
    base_serious = any(f["severity"] >= 3 for f in r.filt.flags) or any(f["id"] == "below_floor" for f in r.filt.flags)
    if discount is not None and r.tier in ("S", "A") and discount >= 0.55:
        extra_flags.append(flag("too_good", 2, f"{discount:.0%} under fair value"))
        risk += 0.2
    sr, srev = lst.get("seller_rating"), lst.get("seller_reviews")
    if srev is not None and int(srev) == 0:
        trust = 0.8
        extra_flags.append(flag("new_seller", 2))
        risk += 0.1
    elif sr is not None and srev:
        trust = 0.8 + 0.2 * min(1.0, int(srev) / 50.0) * (float(sr) / 5.0)
    else:
        trust = 0.9
    if r.cost.get("fx_fallback"):
        extra_flags.append(flag("fx_fallback", 1))
    for f in extra_flags:
        r.filt.add(f)
    risk = min(1.0, risk)
    cond = r.cond if r.cond is not None else 0.8
    cf = 0.6 + 0.4 * cond
    sf, sf_why = size_fit(r.size_norm, ent.archetype, ctx.size_profile)
    em = era_matters(tax, ent.brand)
    ecw = (0.5 + 0.5 * ent.era_conf) if em else 1.0
    vcw = VC_W.get(v.get("conf", "none"), 0.0)
    factors = [{"k": "value_conf", "label": "Value confidence", "v": vcw},
               {"k": "era_conf", "label": "Era confidence", "v": round(ecw, 3)},
               {"k": "condition", "label": "Condition", "v": round(cf, 3)},
               {"k": "size_fit", "label": "Size fit", "v": sf, "why": sf_why},
               {"k": "seller_trust", "label": "Seller trust", "v": round(trust, 3)}]
    if discount is None:
        label, score = "unknown", 0.0
    else:
        score = discount * vcw * ecw * cf * sf * trust - 0.5 * risk
        # suspicious = too good AND independent risk evidence (too_good alone only lowers the score)
        if discount >= 0.4 and (base_risk >= 0.3 or base_serious):
            label = "suspicious"
        elif v.get("conf") not in ("high", "med"):
            # A big discount against a soft number is a lead, not a verdict: low-confidence value never earns
            # more than "good", whatever the percentage says.
            label = "good" if discount >= 0.15 else "fair" if discount >= -0.15 else "overpriced"
        elif discount >= 0.4:
            label = "steal"
        elif discount >= 0.25:
            label = "great"
        elif discount >= 0.15:
            label = "good"
        elif discount >= -0.15:
            label = "fair"
        else:
            label = "overpriced"
    if lst.get("_auction_basis") == "current_bid" and label in ("steal", "great", "suspicious"):
        label = "good"   # a low current bid with days left is not a deal
    if lst.get("_auction_basis") == "current_bid":
        score = min(score, -0.08)  # ranks with the fairly priced, below anything with a real discount
    r.deal = {"discount": round(discount, 4) if discount is not None else None, "score": round(score, 4),
              "label": label, "risk": round(risk, 3), "factors": factors}
    r.value = dict(v, fair_value_usd=r.fair_value, range_usd=[round(x, 2) for x in rng] if rng else None,
                   basis=basis)


def _sort_key(r: Result, ctx: Context) -> float:
    lst = r.listing
    if r.tier == "X":
        return 0.0
    base = r.deal["score"] if r.deal else 0.0
    t_list = lst.get("listed_at") or lst.get("first_seen_at") or ctx.at
    age_h = max(0.0, (ctx.at - int(t_list)) / 3600.0)
    boost = float(cfg("fresh_boost")) * 0.5 ** (age_h / float(cfg("fresh_half_life_hours")))
    prev, pc = lst.get("prev_price_usd"), lst.get("price_changed_at")
    if prev and pc and ctx.at - int(pc) < 3 * 86400 and float(prev) > float(lst.get("price_usd") or 0):
        drop = (float(prev) - float(lst["price_usd"])) / float(prev)
        boost += float(cfg("drop_boost")) * min(1.0, drop / 0.3)
    # A listing that has sat unsold for months is telling you something the comps are not.
    age_d = age_h / 24.0
    if age_d > float(cfg("stale_after_days")):
        boost -= float(cfg("stale_penalty")) * min(1.0, (age_d - float(cfg("stale_after_days"))) / 120.0)
    # deterministic tie-break inside a tier (rows without a fair value all have deal_score 0)
    boost += (r.desir["score"] if r.desir else 0.0) / 10000.0
    return round(base + boost, 5)


def _assemble(r: Result, ctx: Context, backend: str) -> None:
    tax, ent = ctx.tax, r.ent
    flags = list(r.filt.flags) + (r.desir["flags"] if r.desir else [])
    seen = set()
    r.flags = [f for f in flags if not (f["id"] in seen or seen.add(f["id"]))]
    entities = None
    if ent.brand or ent.archetype:
        b = tax.brands.get(ent.brand) if ent.brand else None
        e = tax.eras.get(ent.era) if ent.era else None
        s = tax.seasons.get(ent.season) if ent.season else None
        a = tax.archetypes.get(ent.archetype) if ent.archetype else None
        entities = {
            "brand": {"id": ent.brand, "name": b["name"], "conf": ent.brand_conf, "matched": ent.brand_matched,
                      "via": ent.brand_via} if b else None,
            "era": {"id": ent.era, "name": e.get("designer") or e["id"], "years": e.get("years"),
                    "conf": ent.era_conf, "resolved": ent.era_conf >= cfg("era_resolved"),
                    "cues": list(dict.fromkeys(ent.era_cues)), "anti_cues": ent.era_anti} if e else
                   ({"id": None, "name": "Unresolved", "years": None, "conf": 0.0, "resolved": False, "cues": [],
                     "anti_cues": ent.era_anti} if ent.brand and era_matters(tax, ent.brand) else None),
            "season": {"id": ent.season, "name": f"{s.get('code')} {s.get('name')}".replace(" UNKNOWN", ""),
                       "conf": ent.season_conf, "matched": ent.season_matched} if s else None,
            "archetype": {"id": ent.archetype, "name": a["name"], "matched": ent.archetype_matched} if a else None,
        }
    r.sort_key = _sort_key(r, ctx)
    ex: dict = {"entities": entities, "flags": r.flags}
    if r.reject_reason:
        ex.update({"desirability": None, "value": None, "cost": r.cost, "deal": None, "similarity": None,
                   "ranker": None, "reject_reason": r.reject_reason})
    else:
        ex["desirability"] = {k: r.desir[k] for k in ("score", "tier", "ceiling", "ceiling_reason", "factors")}
        v = r.value or {}
        ex["value"] = None if v.get("conf", "none") == "none" else {
            "fair_value_usd": r.fair_value, "conf": v.get("conf"), "level": v.get("level"), "market": v.get("market"),
            "basis": v.get("basis"), "comp_count": v.get("count"), "effective_count": v.get("eff"),
            "range_usd": v.get("range_usd"), "sticker_median_usd": round(v["median"], 2) if v.get("median") else None,
            "size_bucket": v.get("size_bucket"), "uplift": float(cfg("jp_to_us_uplift")),
            "stratum": v.get("stratum"), "shrunk": v.get("shrunk"), "era_pooled": v.get("era_pooled"),
            "band": v.get("band"),
            "band_source": v.get("band_source"),
            "note": ("JP listing valued on JP sold prices only (landed-equivalent, no JP->US uplift)"
                     if v.get("market") == "JP" and (r.listing.get("region") == "JP") else v.get("note")),
            "comps": v.get("comps", [])}
        ex["cost"] = r.cost
        ex["deal"] = r.deal
        ex["similarity"] = {"taste": r.taste, "junk": r.junk, "visual": visual_grail_match(r.listing.get("image_url")),
                            "backend": backend}
        ex["ranker"] = {"prob": round(r.prob, 4), "model": ctx.ranker.name,
                        "features": {k: round(float(r.features[k]), 4) for k in FEATURES}}
    ex["size_norm"] = r.size_norm
    ex["condition_norm"] = r.cond
    r.explain = ex


# ------------------------------------------------------------------------------------------------ offline API
def score_items(items: list[dict], ctx: Context | None = None) -> list[Result]:
    """Run the full cascade on plain dicts (eval set, tests). No DB writes."""
    ctx = ctx or build_context(None, offline=True)
    res = []
    for i, it in enumerate(items):
        lst = {"id": it.get("id") or f"item:{i}", "source": it.get("source") or "grailed",
               "region": it.get("region") or ("JP" if (it.get("source") or "").startswith(("mercari_jp", "yahoo_jp")) else "US"),
               "title": it.get("title") or "", "description": it.get("description"), "brand_raw": it.get("brand_raw"),
               "price_usd": float(it.get("price_usd") or 0), "shipping_usd": it.get("shipping_usd"),
               "price": it.get("price"), "currency": it.get("currency"),
               "condition_raw": it.get("condition_raw"), "size_raw": it.get("size_raw"),
               "listed_at": it.get("listed_at"), "first_seen_at": it.get("first_seen_at") or ctx.at,
               "is_auction": it.get("is_auction", 0), "bids": it.get("bids"), "auction_end_at": it.get("auction_end_at"),
               "buy_now_usd": it.get("buy_now_usd"), "url": it.get("url"), "image_url": it.get("image_url")}
        res.append(analyze(lst, ctx))
    score_results(res, ctx)
    return res


def feed_order(results: list[Result]) -> list[Result]:
    return sorted(results, key=lambda r: (TIER_RANK[r.tier], -r.sort_key, r.listing["id"]))


# ------------------------------------------------------------------------------------------------ DB writes
def _rows(r: Result, ctx: Context) -> list[tuple[str, tuple]]:
    lst, ent, t = r.listing, r.ent, ctx.at
    resolved = ent.era_conf >= cfg("era_resolved")
    era = ent.era if resolved else None
    flags_ids = json.dumps([f["id"] for f in r.flags])
    vconf = (r.value or {}).get("conf", "none") if not r.reject_reason else None
    level = (r.value or {}).get("level") if not r.reject_reason else None
    comp_count = (r.value or {}).get("count") if not r.reject_reason else None
    deal = r.deal or {}
    model_version = f"{VERSION}|{ctx.ranker.name}|{(r.explain.get('similarity') or {}).get('backend', '-')}"
    landed = r.cost["landed_usd"]
    out = [
        ("INSERT INTO listing_entities (listing_id, brand, era, season, archetype, line, brand_conf, era_conf,"
         " season_conf, matched) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(listing_id) DO UPDATE SET brand=excluded.brand,"
         " era=excluded.era, season=excluded.season, archetype=excluded.archetype, line=excluded.line,"
         " brand_conf=excluded.brand_conf, era_conf=excluded.era_conf, season_conf=excluded.season_conf,"
         " matched=excluded.matched",
         (lst["id"], ent.brand, era, ent.season, ent.archetype, ent.line, ent.brand_conf, ent.era_conf,
          ent.season_conf, json.dumps(ent.matched_json(), ensure_ascii=False))),
        ("INSERT INTO scores (listing_id, relevant_prob, taste_sim, junk_sim, visual_match, desirability, tier,"
         " reject_reason, fair_value_usd, value_conf, comp_count, comp_level, discount, deal_score, deal_label, risk,"
         " flags, explain, model_version, scored_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
         " ON CONFLICT(listing_id) DO UPDATE SET relevant_prob=excluded.relevant_prob, taste_sim=excluded.taste_sim,"
         " junk_sim=excluded.junk_sim, visual_match=excluded.visual_match, desirability=excluded.desirability,"
         " tier=excluded.tier, reject_reason=excluded.reject_reason, fair_value_usd=excluded.fair_value_usd,"
         " value_conf=excluded.value_conf, comp_count=excluded.comp_count, comp_level=excluded.comp_level,"
         " discount=excluded.discount, deal_score=excluded.deal_score, deal_label=excluded.deal_label,"
         " risk=excluded.risk, flags=excluded.flags, explain=excluded.explain, model_version=excluded.model_version,"
         " scored_at=excluded.scored_at",
         (lst["id"], r.prob, r.taste, r.junk, None, r.desir["score"] if r.desir else None, r.tier, r.reject_reason,
          r.fair_value, vconf, comp_count, level, deal.get("discount"), deal.get("score", 0.0) or 0.0,
          deal.get("label"), deal.get("risk", r.filt.risk), flags_ids,
          json.dumps(r.explain, ensure_ascii=False, default=str), model_version, t)),
        ("INSERT INTO feed (listing_id, source, region, url, proxy_url, title, image_url, price, currency, price_usd,"
         " landed_usd, prev_price_usd, size_norm, condition_norm, brand, era, season, archetype, era_conf, tier,"
         " tier_rank, desirability, fair_value_usd, value_conf, comp_count, discount, deal_score, deal_label,"
         " suspicious, flags, reject_reason, is_auction, auction_end_at, bids, status, listed_at, price_changed_at,"
         " sort_key, base_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
         " ON CONFLICT(listing_id) DO UPDATE SET source=excluded.source, region=excluded.region, url=excluded.url,"
         " proxy_url=excluded.proxy_url, title=excluded.title, image_url=excluded.image_url, price=excluded.price,"
         " currency=excluded.currency, price_usd=excluded.price_usd, landed_usd=excluded.landed_usd,"
         " prev_price_usd=excluded.prev_price_usd, size_norm=excluded.size_norm, condition_norm=excluded.condition_norm,"
         " brand=excluded.brand, era=excluded.era, season=excluded.season, archetype=excluded.archetype,"
         " era_conf=excluded.era_conf, tier=excluded.tier, tier_rank=excluded.tier_rank,"
         " desirability=excluded.desirability, fair_value_usd=excluded.fair_value_usd, value_conf=excluded.value_conf,"
         " comp_count=excluded.comp_count, discount=excluded.discount, deal_score=excluded.deal_score,"
         " deal_label=excluded.deal_label, suspicious=excluded.suspicious, flags=excluded.flags,"
         " reject_reason=excluded.reject_reason, is_auction=excluded.is_auction, auction_end_at=excluded.auction_end_at,"
         " bids=excluded.bids, status=excluded.status, listed_at=excluded.listed_at,"
         " price_changed_at=excluded.price_changed_at, sort_key=excluded.sort_key, base_key=excluded.base_key",
         (lst["id"], lst["source"], lst.get("region") or "US", lst.get("url") or "", lst.get("proxy_url"), lst["title"],
          lst.get("image_url"), lst.get("price") or lst["price_usd"], lst.get("currency") or "USD", lst["price_usd"],
          landed, lst.get("prev_price_usd"), r.size_norm, r.cond, ent.brand, era, ent.season, ent.archetype,
          ent.era_conf, r.tier, TIER_RANK[r.tier], r.desir["score"] if r.desir else None, r.fair_value, vconf,
          comp_count, deal.get("discount"), deal.get("score", 0.0) or 0.0, deal.get("label"),
          1 if deal.get("label") == "suspicious" else 0, flags_ids, r.reject_reason, int(lst.get("is_auction") or 0),
          lst.get("auction_end_at"), lst.get("bids"), lst.get("status") or "active",
          int(lst.get("listed_at") or lst.get("first_seen_at") or t), lst.get("price_changed_at"), r.sort_key,
          r.sort_key)),
        ("UPDATE listings SET needs_score = 0, size_norm = ?, condition_norm = ?, landed_usd = ?, canonical_id = ?,"
         " phash = COALESCE(?, phash) WHERE id = ?",
         (r.size_norm, r.cond, landed, lst.get("_duplicate_of"), lst.get("phash") if lst.get("_phash_new") else None,
          lst["id"])),
    ]
    return out


def _visible(r: Result) -> tuple:
    return (r.tier, (r.deal or {}).get("label"), r.reject_reason, json.dumps([f["id"] for f in r.flags]),
            r.fair_value, round((r.deal or {}).get("score", 0.0) or 0.0, 2))


def _changed(old: dict | None, r: Result) -> bool:
    if old is None:
        return True
    tier, label, rej, flags, fair, ds = _visible(r)
    if (old["tier"], old["deal_label"], old["reject_reason"], old["flags"]) != (tier, label, rej, flags):
        return True
    of = old["fair_value_usd"]
    if (of is None) != (fair is None) or (of and fair and abs(of - fair) / of > 0.02):
        return True
    return abs(float(old["deal_score"] or 0) - ds) > 0.02


# ------------------------------------------------------------------------------------------------ taxonomy sync
def taxonomy_version(tax: Taxonomy) -> str:
    from core.config import TAXONOMY_DIR
    h = hashlib.sha1()
    for p in sorted(TAXONOMY_DIR.glob("*.yaml")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def sync_taxonomy(db: Database, force: bool = False) -> dict:
    tax = load_taxonomy()
    ver = taxonomy_version(tax)
    if not force and db.kv_get("taxonomy_version") == ver:
        return {"synced": False, "version": ver}
    rows = []
    for b in tax.brands.values():
        rows.append((str(b["id"]), "brand", b["name"], None, float(b.get("base_weight", 5)),
                     tax.trend_prior(str(b["id"])), json.dumps({"group": b.get("group"),
                                                                "era_matters": era_matters(tax, str(b["id"]))})))
    for e in tax.eras.values():
        rows.append((e["id"], "era", str(e.get("designer") if e.get("designer") not in (None, "UNKNOWN", "") else e["id"].split("__", 1)[-1].replace("_", " ").title()), str(e["brand"]),
                     float(e.get("weight", 5)), tax.trend_prior(str(e["brand"]), e["id"]),
                     json.dumps({"years": e.get("years"), "designer": e.get("designer")})))
    for s in tax.seasons.values():
        rows.append((s["id"], "season", f"{s.get('code')} {s.get('name')}".replace(" UNKNOWN", "").strip(),
                     s.get("era") if s.get("era") in tax.eras else str(s["brand"]),
                     float(s.get("weight", 5)), tax.trend_prior(str(s["brand"]), s.get("era"), s["id"]),
                     json.dumps({"code": s.get("code"), "year": s.get("year"), "brand": str(s["brand"])})))
    for a in tax.archetypes.values():
        rows.append((a["id"], "archetype", a["name"], None, float(a.get("base_desirability", 5)), None,
                     json.dumps({"ship_weight_class": a.get("ship_weight_class")})))
    ids = [r[0] for r in rows]
    stmts = [("INSERT INTO taxonomy_entities (id, kind, name, parent, weight, trend_prior, data) VALUES (?,?,?,?,?,?,?)"
              " ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, name=excluded.name, parent=excluded.parent,"
              " weight=excluded.weight, trend_prior=excluded.trend_prior, data=excluded.data", r) for r in rows]
    stmts.append((f"DELETE FROM taxonomy_entities WHERE id NOT IN ({','.join('?' * len(ids))})", tuple(ids)))
    db.batch(stmts)
    db.kv_set("taxonomy_version", ver)
    return {"synced": True, "version": ver, "entities": len(rows)}


# ------------------------------------------------------------------------------------------------ DB driver
def rerank_diversity(db: Database, dry_run: bool = False) -> dict:
    """Stop one brand and piece type from filling the top of a tier.

    Within each (tier, brand, piece type) group the best row keeps its key and each following row gives up a
    small, capped amount. Thirty Hedi denim steals are all worth seeing, but not before the single best
    Number (N)ine or Rick Owens deal. Idempotent: computed from `base_key`, writes only rows that move.
    """
    step, cap = float(cfg("diversity_step")), float(cfg("diversity_cap"))
    rows = db.query("SELECT listing_id, tier_rank, brand, archetype, base_key, sort_key FROM feed"
                    " WHERE status = 'active' AND tier_rank < 9")
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["tier_rank"], r["brand"], r["archetype"]), []).append(r)
    stmts = []
    want: dict[str, float] = {}
    for g in groups.values():
        g.sort(key=lambda r: (-float(r["base_key"] or 0), r["listing_id"]))
        for i, r in enumerate(g):
            want[r["listing_id"]] = float(r["base_key"] or 0) - min(cap, step * i)
    # second, gentler pass per brand: one house with many piece types should not own the top of a tier either
    bstep, bcap = float(cfg("diversity_brand_step")), float(cfg("diversity_brand_cap"))
    brands: dict[tuple, list[dict]] = {}
    for r in rows:
        brands.setdefault((r["tier_rank"], r["brand"]), []).append(r)
    for g in brands.values():
        g.sort(key=lambda r: (-want[r["listing_id"]], r["listing_id"]))
        for i, r in enumerate(g):
            want[r["listing_id"]] -= min(bcap, bstep * i)
    for r in rows:
        w = round(want[r["listing_id"]], 5)
        if abs(w - float(r["sort_key"] or 0)) > 1e-6:
            stmts.append(("UPDATE feed SET sort_key = ? WHERE listing_id = ?", (w, r["listing_id"])))
    if stmts and not dry_run:
        for k in range(0, len(stmts), 800):
            db.batch(stmts[k:k + 800])
    return {"groups": len(groups), "moved": len(stmts)}


def load_listings(db: Database, mode: str, limit: int | None) -> list[dict]:
    where = "l.needs_score = 1" if mode == "queue" else "l.status = 'active'"
    sql = f"SELECT {LISTING_COLS} FROM listings l LEFT JOIN sellers s ON s.id = l.seller_id WHERE {where} ORDER BY l.first_seen_at"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.query(sql)


def run_score(db: Database, mode: str = "queue", limit: int | None = None, dry_run: bool = False,
              use_phash: bool | None = None, chunk: int = 2000) -> dict:
    t0 = time.time()
    tax_sync = sync_taxonomy(db) if not dry_run else {"synced": False}
    ctx = build_context(db, use_phash=use_phash)
    rows = load_listings(db, mode, limit)
    if not rows:
        return {"scored": 0, "written": 0, "tiers": {}, "labels": {}, "seconds": round(time.time() - t0, 2),
                "embed_backend": "none", "taxonomy": tax_sync}
    # cross-post detection against all active rows
    active = db.query("SELECT id, source, seller_id, title, price_usd, first_seen_at, size_norm FROM listings"
                      " WHERE status = 'active'")
    dup = find_crossposts(active, {r["id"] for r in rows})
    for r in rows:
        if r["id"] in dup:
            r["_duplicate_of"] = dup[r["id"]]
    old = {}
    if mode != "queue":
        for o in db.query("SELECT listing_id, tier, deal_label, reject_reason, flags, fair_value_usd, deal_score FROM scores"):
            old[o["listing_id"]] = o
    tiers: dict[str, int] = {}
    labels: dict[str, int] = {}
    written = 0
    backend = "none"
    t_embed = 0.0
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        results = [analyze(dict(r), ctx) for r in part]
        te = time.time()
        backend = score_results(results, ctx)
        t_embed += time.time() - te
        stmts = []
        for r in results:
            tiers[r.tier] = tiers.get(r.tier, 0) + 1
            if r.deal:
                labels[r.deal["label"]] = labels.get(r.deal["label"], 0) + 1
            if mode == "queue" or _changed(old.get(r.listing["id"]), r) or r.listing.get("needs_score"):
                stmts += _rows(r, ctx)
                written += 1
        if not dry_run and stmts:
            for k in range(0, len(stmts), 800):
                db.batch(stmts[k:k + 800])
    diversity = rerank_diversity(db, dry_run)
    return {"scored": len(rows), "written": 0 if dry_run else written, "duplicates": len(dup), "diversity": diversity,
            "tiers": dict(sorted(tiers.items(), key=lambda kv: TIER_RANK[kv[0]])), "labels": labels,
            "seconds": round(time.time() - t0, 2), "stages_3_7_seconds": round(t_embed, 2),
            "per_sec": round(len(rows) / max(1e-6, time.time() - t0), 1), "embed_backend": backend,
            "ranker": ctx.ranker.name, "taxonomy": tax_sync, "dry_run": dry_run}
