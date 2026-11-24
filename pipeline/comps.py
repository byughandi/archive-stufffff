"""Stage 6: market value from sold comps.

1. `classify_queued` runs the same Stage 1-2 code over `comps_sold` rows with classified = 0. Junk comps
   (rejected, bundles, reference-only brands) keep brand NULL so they can never pollute a price.
2. `CompsIndex.value` matches hierarchically: season -> era+archetype -> brand+archetype -> brand ->
   price_bands.yaml prior -> none, with a minimum effective (recency-weighted) comp count per level.
   Fair value = recency-weighted median (half-life `comp_half_life_days`) with weighted IQR, after trimming
   outliers beyond 3.5x of the median. Same-market comps are preferred; the market used is reported.
   A size bucket is used only when comps are plentiful. Up to 8 comps (with URLs) are returned.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

from core.db import Database, now
from core.taxonomy import Taxonomy

from . import cfg
from .classify import get_matcher
from .filter import get_filter
from .normalize import condition_norm, norm_text, parse_size, tokenize

MIN_EFF = {"season": 2.5, "era_archetype": 3.0, "brand_archetype": 4.0, "brand": 6.0}
JP_SOURCES = ("mercari_jp", "yahoo_jp", "rakuma", "2nd_street", "ragtag", "kindal", "treasure_factory", "jp_")


def market_of(source: str | None) -> str:
    s = (source or "").lower()
    return "JP" if s.startswith(JP_SOURCES) else "US"


# ------------------------------------------------------------------------------------------- classify comps
def classify_comp(row: dict) -> dict:
    """Return the column values for one comp (brand None when the comp is junk)."""
    m, f = get_matcher(), get_filter()
    tnorm = norm_text(row.get("title"))
    ent = m.classify(row.get("title") or "", row.get("description"), row.get("brand_raw"), norm=tnorm)
    toks = tokenize(tnorm)
    dtoks = tokenize(norm_text(row.get("description"))) if row.get("description") else []
    res = f.apply({"title": row.get("title"), "brand_raw": row.get("brand_raw"),
                   "price_usd": row.get("sold_price_usd")}, ent, tnorm, toks, dtoks)
    junk = res.reject_reason is not None or any(x["id"] in ("bundle", "keyword_stuffing") for x in res.flags)
    if junk:
        return {"brand": None, "era": None, "season": None, "archetype": ent.archetype, "era_conf": None,
                "size_norm": None, "condition_norm": None, "reject": res.reject_reason or "bundle/stuffing"}
    return {"brand": ent.brand, "era": ent.era if ent.era_conf >= cfg("era_resolved") else None,
            "season": ent.season, "archetype": ent.archetype, "era_conf": ent.era_conf,
            "size_norm": parse_size(row.get("size_raw"), tnorm, ent.archetype),
            "condition_norm": condition_norm(row.get("source") or "", row.get("condition_raw"), tnorm),
            "reject": None}


def classify_queued(db: Database, limit: int | None = None, all_rows: bool = False) -> dict:
    t0 = time.time()
    where = "" if all_rows else "WHERE classified = 0"
    sql = f"SELECT id, source, title, description, brand_raw, size_raw, condition_raw, sold_price_usd FROM comps_sold {where}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = db.query(sql)
    stmts, kept, junk = [], 0, 0
    for r in rows:
        v = classify_comp(r)
        if v["brand"]:
            kept += 1
        else:
            junk += 1
        stmts.append(("UPDATE comps_sold SET brand=?, era=?, season=?, archetype=?, era_conf=?, size_norm=?,"
                      " condition_norm=?, classified=1 WHERE id=?",
                      (v["brand"], v["era"], v["season"], v["archetype"], v["era_conf"], v["size_norm"],
                       v["condition_norm"], r["id"])))
    for i in range(0, len(stmts), 500):
        db.batch(stmts[i:i + 500])
    return {"classified": len(rows), "kept": kept, "junk": junk, "seconds": round(time.time() - t0, 2)}


# ------------------------------------------------------------------------------------------- stats
def wquantile(vals: list[float], weights: list[float], q: float) -> float:
    """Weighted quantile with linear interpolation between neighbours (each value sits at the midpoint of
    its weight). Picking the next value up, as a step function does, biases small bimodal samples upward."""
    pairs = sorted(zip(vals, weights))
    tot = sum(w for _, w in pairs)
    if tot <= 0 or len(pairs) == 1:
        return pairs[len(pairs) // 2][0]
    pos, acc = [], 0.0
    for _, w in pairs:
        pos.append((acc + w / 2.0) / tot)
        acc += w
    if q <= pos[0]:
        return pairs[0][0]
    if q >= pos[-1]:
        return pairs[-1][0]
    for i in range(1, len(pairs)):
        if q <= pos[i]:
            span = pos[i] - pos[i - 1]
            f = (q - pos[i - 1]) / span if span > 0 else 0.0
            return pairs[i - 1][0] + f * (pairs[i][0] - pairs[i - 1][0])
    return pairs[-1][0]


@dataclass
class Comp:
    id: str
    source: str
    url: str | None
    title: str
    brand: str | None
    era: str | None
    season: str | None
    archetype: str | None
    size_norm: str | None
    price: float
    sold_at: int
    market: str


class CompsIndex:
    def __init__(self, comps: list[Comp], tax: Taxonomy, at: int | None = None):
        self.tax = tax
        self.at = at or now()
        hl = float(cfg("comp_half_life_days"))
        window = float(cfg("comp_window_days")) * 86400
        self.comps = [c for c in comps if c.brand and c.price > 0 and self.at - c.sold_at <= window]
        self.w = {c.id: 0.5 ** (max(0.0, self.at - c.sold_at) / 86400.0 / hl) for c in self.comps}
        self.by: dict[tuple, list[Comp]] = {}
        for c in self.comps:
            self.by.setdefault(("brand", c.brand), []).append(c)
            if c.archetype:
                self.by.setdefault(("ba", c.brand, c.archetype), []).append(c)
                if c.era:
                    self.by.setdefault(("ea", c.era, c.archetype), []).append(c)
            if c.season:
                self.by.setdefault(("season", c.season), []).append(c)

    @classmethod
    def from_db(cls, db: Database, tax: Taxonomy) -> "CompsIndex":
        window = int(float(cfg("comp_window_days")) * 86400)
        rows = db.query("SELECT id, source, url, title, brand, era, season, archetype, size_norm, sold_price_usd,"
                        " sold_at FROM comps_sold WHERE classified = 1 AND brand IS NOT NULL AND sold_at >= ?",
                        (now() - window,))
        return cls([Comp(r["id"], r["source"], r["url"], r["title"], r["brand"], r["era"], r["season"], r["archetype"],
                         r["size_norm"], float(r["sold_price_usd"] or 0), int(r["sold_at"] or 0), market_of(r["source"]))
                    for r in rows], tax)

    def counts(self) -> dict:
        out: dict = {}
        for c in self.comps:
            if self.at - c.sold_at <= float(cfg("rarity_window_days")) * 86400:
                k = (c.brand, c.era, c.archetype)
                out[k] = out.get(k, 0) + 1
        return out

    def _stats(self, cs: list[Comp]) -> dict | None:
        if not cs:
            return None
        vals = [c.price for c in cs]
        ws = [self.w[c.id] for c in cs]
        med = wquantile(vals, ws, 0.5)
        keep = [(c, w) for c, w in zip(cs, ws) if med / 3.5 <= c.price <= med * 3.5]
        if not keep:
            return None
        cs2 = [c for c, _ in keep]
        vals = [c.price for c in cs2]
        ws = [w for _, w in keep]
        med = wquantile(vals, ws, 0.5)
        return {"median": med, "p25": wquantile(vals, ws, 0.25), "p75": wquantile(vals, ws, 0.75),
                "eff": sum(ws), "n": len(cs2), "comps": cs2}

    def value(self, brand: str | None, era: str | None, season: str | None, archetype: str | None,
              market: str, size_norm: str | None = None) -> dict:
        """Hierarchical fair value. Returns sticker-price stats in the comps' market (score.py converts)."""
        if not brand:
            return {"level": "none", "conf": "none"}
        levels: list[tuple[str, list[Comp]]] = []
        # A season's comps span everything shown that season; without a piece type they are not comparable
        # (a neck warmer must not be valued like the season's leather jacket). No piece type means the brand
        # level only, at low confidence.
        if season and archetype:
            levels.append(("season", [c for c in self.by.get(("season", season), []) if c.archetype == archetype]))
        if era and archetype:
            levels.append(("era_archetype", self.by.get(("ea", era, archetype), [])))
        # When the listing's era is unknown, comps of a known (usually the prized) era are not its peers:
        # compare with unknown-era comps when there are enough, otherwise pool everything and say it is soft.
        era_pooled = False

        def by_era(cs: list[Comp], level: str) -> list[Comp]:
            nonlocal era_pooled
            if era:
                return [c for c in cs if c.era in (None, era)]
            if len({c.era for c in cs}) <= 1:
                return cs
            same = [c for c in cs if c.era is None]
            st = self._stats(same)
            if st and st["eff"] >= MIN_EFF[level]:
                return same
            era_pooled = True
            return cs

        if archetype:
            levels.append(("brand_archetype", by_era(self.by.get(("ba", brand, archetype), []), "brand_archetype")))
        levels.append(("brand", by_era(self.by.get(("brand", brand), []), "brand")))
        for level, cs in levels:
            if not cs:
                continue
            # Named-season pieces (Luster, Strip, Scab...) sell for multiples of plain pieces of the same
            # brand, era and type. Below the season level, compare like with like first: a plain piece
            # against plain comps, a named-season piece against named-season comps. Fall back to the whole
            # pool only when the matching stratum is too thin, and say so (it lowers confidence).
            pools: list[tuple[list[Comp], str | None]] = [(cs, None)]
            if level != "season":
                named = season is not None
                stratum_cs = [c for c in cs if (c.season is not None) == named]
                if stratum_cs and len(stratum_cs) != len(cs):
                    pools = [(stratum_cs, "named_season" if named else "plain"), (cs, "mixed_seasons")]
            pick, mk, stratum = None, None, None
            for pool_all, stratum_label in pools:
                same = [c for c in pool_all if c.market == market]
                for pool, label in ((same, market), (pool_all, "mixed")):
                    st = self._stats(pool)
                    if st and st["eff"] >= MIN_EFF[level]:
                        pick, stratum = st, stratum_label
                        mk = label if label != "mixed" or len({c.market for c in pool}) > 1 else pool[0].market
                        break
                if pick:
                    break
            if not pick:
                continue
            size_used = False
            if size_norm and pick["n"] >= 30:
                sz = [c for c in pick["comps"] if c.size_norm == size_norm]
                st = self._stats(sz)
                if st and st["n"] >= 10 and st["eff"] >= max(8.0, MIN_EFF[level] * 2):
                    pick, size_used = st, True
            # A handful of season comps can straddle very different pieces (a belt, a sample jacket). Shrink a
            # thin season median toward the wider like-for-like pool of the same era and piece type.
            shrunk = None
            if level == "season" and era and archetype:
                parent = [c for c in self.by.get(("ea", era, archetype), []) if c.season is not None]
                pst = self._stats([c for c in parent if c.market == market] or parent)
                k = float(cfg("comp_shrink_k"))
                if pst and pst["eff"] >= MIN_EFF["era_archetype"] and k > 0:
                    wgt = pick["eff"] / (pick["eff"] + k)
                    pick = dict(pick, **{q: wgt * pick[q] + (1 - wgt) * pst[q] for q in ("median", "p25", "p75")})
                    shrunk = {"toward": "named-season pieces of the same era and type", "weight_on_season": round(wgt, 2),
                              "parent_median": round(pst["median"], 2), "parent_count": pst["n"]}
            disp = (pick["p75"] - pick["p25"]) / pick["median"] if pick["median"] > 0 else 9
            if pick["eff"] >= 8 and disp <= 0.5 and level in ("season", "era_archetype"):
                conf = "high"
            elif pick["eff"] >= 5 and disp <= 0.75 and level != "brand":
                conf = "med"
            else:
                conf = "low"
            if not archetype or (era_pooled and level in ("brand_archetype", "brand")):
                conf = "low"
            if stratum == "mixed_seasons":   # plain and named-season comps pooled: one notch less sure
                conf = {"high": "med", "med": "low"}.get(conf, conf)
            shown = sorted(pick["comps"], key=lambda c: -self.w[c.id])[: int(cfg("comp_max_shown"))]
            return {"level": level, "conf": conf, "median": pick["median"], "p25": pick["p25"], "p75": pick["p75"],
                    "eff": round(pick["eff"], 2), "count": pick["n"], "market": mk, "size_bucket": size_used, "stratum": stratum, "shrunk": shrunk,
                    "era_pooled": bool(era_pooled and level in ("brand_archetype", "brand")),
                    "dispersion": round(disp, 3),
                    "comps": [{"id": c.id, "title": c.title[:140], "price_usd": round(c.price, 2), "sold_at": c.sold_at,
                               "url": c.url, "source": c.source} for c in shown]}
        band = self._band(brand, era, season, archetype)
        if band:
            return band
        return {"level": "none", "conf": "none"}

    def _band(self, brand, era, season, archetype) -> dict | None:
        best, spec = None, -1
        for b in self.tax.price_bands:
            if str(b.get("brand")) != brand or b.get("basis") != "sold":
                continue
            s = 0
            ok = True
            for key, val in (("season", season), ("era", era), ("archetype", archetype)):
                want = b.get(key)
                if want in (None, "UNKNOWN"):
                    continue
                if want != val:
                    ok = False
                    break
                s += 1
            # A band is one observed sale of one specific piece. It is only evidence for the same season;
            # applying a Geobasket price to every Rick Owens sneaker is worse than saying "no comps".
            if ok and s > spec and b.get("season") not in (None, "UNKNOWN") and b.get("season") == season:
                best, spec = b, s
        if not best:
            return None
        med = float(best["median"])
        lo, hi = float(best.get("low", med)), float(best.get("high", med))
        return {"level": "price_band", "conf": "low", "median": med, "p25": min(lo, med * 0.7),
                "p75": max(hi, med * 1.3), "eff": 0.0, "count": int(best.get("n_observed") or 1)
                if str(best.get("n_observed", "1")).isdigit() else 1, "market": "US", "size_bucket": False,
                "dispersion": None, "comps": [], "band": best.get("piece"), "band_source": best.get("source"),
                "note": f"No sold comps. Based on one researched sale: {best.get('piece')}"}
