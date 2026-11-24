"""Stage 5: desirability score (0..100) and tier S/A/B/C (X = rejected, set by filter).

score = 100 * (0.35 brand_era + 0.25 piece + 0.12 trend + 0.06 rarity + 0.22 ranker_prob)

- brand_era = brand base_weight/10 x era factor. Resolved era: conf-weighted blend of the era weight and the
  brand's mean era weight; unresolved on a brand with several eras: the mean (no "good era" assumption); brands
  with no era entries: neutral 0.8, no era penalty.
- piece = max(archetype base desirability, brand_archetypes override (era must match, or era unresolved and the
  model name matched), matched season weight, matched grail piece weight) / 10.
- trend = Taxonomy.trend_prior, blended 70/30 with the latest Instagram `trend_scores` when they exist.
- rarity = how rarely this brand+era+archetype appears in listings + comps over the last 180 days.

Tier rules (ceilings are applied after thresholds, and every one is written to explain):
- S needs score >= 84, a confirmed era (era_conf >= era_confirmed) with era weight >= 8 where era matters, AND an
  iconic season/piece or a top brand-archetype (weight >= 9). Brands without eras: iconic piece + base >= 8.
- era unresolved on a brand where era matters -> ceiling B + flag needs_tag_pics.
- unwanted era (weight <= 4: Kim Jones Dior, Vaccarello SLP, Rousteing Balmain, N(N) relaunch, recent Rick...)
  -> ceiling C; weight 5-6 (good-KVA, Renzo Margiela, mid Rick...) -> ceiling B.
"""
from __future__ import annotations

import math

from core.taxonomy import Taxonomy

from . import cfg
from .classify import Entities
from .filter import FilterResult, flag

W = {"brand_era": 0.35, "piece": 0.25, "trend": 0.12, "rarity": 0.06, "ranker": 0.22}
THRESHOLDS = {"S": 84.0, "A": 68.0, "B": 54.0}
LABELS = {"brand_era": "Brand and era", "piece": "Season / piece", "trend": "Trend heat", "rarity": "Rarity",
          "ranker": "Taste model"}
ORDER = "SABCX"
# With the era unknown and nothing specific named, these are most likely recent mainline: filler. Outerwear,
# leather, denim, knits, hoodies, boots, tailoring and jewelry keep their "ask for tag photos" place in B.
_EVERYDAY = {"graphic_tee", "shirt", "pants", "bag", "belt", "accessory", "sneakers"}


def era_matters(tax: Taxonomy, brand: str | None) -> bool:
    return bool(brand) and len(tax.eras_by_brand.get(brand, [])) >= 2


def parts(ent: Entities, tax: Taxonomy, rarity_counts: dict | None = None, ig_trend: dict | None = None) -> dict:
    p: dict = {"has_brand": 1.0 if ent.brand else 0.0}
    if not ent.brand:
        return {**p, "brand_w": 0.0, "era_factor": 0.0, "era_w": 0.0, "era_resolved": 0.0, "unwanted": 0.0,
                "piece_w": 0.0, "trend": 0.0, "rarity": 0.5, "iconic": False, "era_matters": False, "piece_src": None,
                "era_weight": None}
    b = tax.brands[ent.brand]
    eras = tax.eras_by_brand.get(ent.brand, [])
    resolved = ent.era is not None and ent.era_conf >= cfg("era_resolved")
    era = tax.eras.get(ent.era) if resolved else None
    era_weight = float(era.get("weight", 5)) if era else None
    matters = len(eras) >= 2
    if eras:
        mean_w = sum(float(e.get("weight", 5)) for e in eras) / len(eras) / 10.0
        if era:
            c = ent.era_conf
            ef = c * era_weight / 10.0 + (1 - c) * mean_w
        else:
            ef = mean_w if matters else 0.75
    else:
        ef = 0.8
    brand_w = float(b.get("base_weight", 5)) / 10.0
    # piece
    cands: list[tuple[float, str]] = []
    if ent.archetype and ent.archetype in tax.archetypes:
        cands.append((float(tax.archetypes[ent.archetype].get("base_desirability", 5)) / 10.0, f"archetype:{ent.archetype}"))
    for e in tax.brand_archetypes:
        if str(e.get("brand")) != ent.brand or e.get("archetype") != ent.archetype:
            continue
        e_era = e.get("era")
        if e_era in (None, "UNKNOWN") or (resolved and e_era == ent.era):
            # A named model (L01, Geobasket, 19cm...) is a specific piece; the bare type is not.
            src = f"model:{ent.model_matched[0]}" if ent.model_entry is e and ent.model_matched else f"brand_archetype:{e_era or 'any'}"
            cands.append((float(e["desirability"]) / 10.0, src))
        elif not resolved and ent.model_entry is e:
            cands.append((0.9 * float(e["desirability"]) / 10.0, f"model:{ent.model_matched[0]}"))
    season_iconic = False
    if ent.season:
        s = tax.seasons[ent.season]
        if not resolved or s.get("era") == ent.era:
            # a season name alone is not a piece: weight by what the piece is (a badge set from a grail season is
            # not a grail); the season's own grail-piece archetypes count fully
            piece_arch = {gp.get("archetype") for gp in s.get("grail_pieces") or []}
            base = float(tax.archetypes[ent.archetype].get("base_desirability", 5)) if ent.archetype in tax.archetypes else 0
            mult = 1.0 if ent.archetype in piece_arch else 0.95 if base >= 7 else 0.88 if base >= 6 else 0.8 if base else 0.72
            sw = float(s.get("weight", 5))
            cands.append((sw / 10.0 * mult, f"season:{ent.season}"))
            season_iconic = sw >= 9 and mult >= 0.95
    if ent.grail_piece:
        gp = ent.grail_piece
        f = 1.0 if ent.season == gp.get("season") else 0.85
        cands.append((f * float(gp.get("weight", 5)) / 10.0, f"piece:{gp.get('name')}"))
    piece_w, piece_src = max(cands) if cands else (0.35, None)
    # Iconic = a grail season, a named grail piece or a named model. "Hedi-era denim" as a type is heat (A),
    # not a grail (S): S has to mean a specific piece a collector would name.
    iconic = season_iconic or any(v >= 0.9 for v, src in cands if src.startswith(("piece:", "model:")))
    # trend
    trend = tax.trend_prior(ent.brand, ent.era if resolved else None, ent.season, ent.archetype)
    if ig_trend:
        ig = [ig_trend.get(k) for k in (("brand", ent.brand), ("era", ent.era if resolved else None),
                                         ("season", ent.season), ("archetype", ent.archetype)) if ig_trend.get(k) is not None]
        if ig:
            trend = 0.7 * trend + 0.3 * max(ig)
    # rarity
    if rarity_counts:
        n = rarity_counts.get((ent.brand, ent.era if resolved else None, ent.archetype), 0)
        rarity = max(0.0, 1.0 - math.log1p(n) / math.log1p(200))
    else:
        rarity = 0.5
    unwanted = 1.0 if (era_weight is not None and era_weight <= 4) else 0.0
    return {**p, "brand_w": brand_w, "era_factor": ef, "era_w": (era_weight or 0) / 10.0 if era else 0.0,
            "era_resolved": 1.0 if resolved else 0.0, "unwanted": unwanted, "piece_w": piece_w,
            "piece_src": piece_src, "trend": trend, "rarity": rarity, "iconic": iconic, "era_matters": matters,
            "era_weight": era_weight}


def finalize(pt: dict, ranker_prob: float, ent: Entities, filt: FilterResult, tax: Taxonomy) -> dict:
    vals = {"brand_era": pt["brand_w"] * pt["era_factor"], "piece": pt["piece_w"], "trend": pt["trend"],
            "rarity": pt["rarity"], "ranker": ranker_prob}
    score = 100.0 * sum(W[k] * vals[k] for k in W)
    tier = "S" if score >= THRESHOLDS["S"] else "A" if score >= THRESHOLDS["A"] else "B" if score >= THRESHOLDS["B"] else "C"
    ceiling, reason = filt.ceiling, filt.ceiling_reason
    new_flags: list[dict] = []

    def cap(t: str, why: str):
        nonlocal ceiling, reason
        if ceiling is None or ORDER.index(t) > ORDER.index(ceiling):
            ceiling, reason = t, why

    if tier == "S":
        b = tax.brands[ent.brand]
        if pt["era_matters"]:
            ok = (ent.era_conf >= cfg("era_confirmed") and (pt["era_weight"] or 0) >= 8 and pt["iconic"])
            why = "S needs a confirmed wanted era and an iconic season/piece"
        else:
            ok = pt["iconic"] and float(b.get("base_weight", 5)) >= 8
            why = "S needs an iconic piece on a top brand"
        if not ok:
            cap("A", why)
    # "Heat" has to mean something a collector would stop for: a named season, piece or model, or a strong
    # piece type (outerwear, leather, denim, knits, hoodies). A right-era belt or plain shirt is solid, not heat.
    specific_any = bool(ent.season or ent.grail_piece or ent.model_matched)
    base_any = float(tax.archetypes.get(ent.archetype, {}).get("base_desirability", 0)) if ent.archetype else 0.0
    if tier in ("S", "A") and not specific_any and base_any < 7:
        cap("B", "right brand and era, everyday piece")
    if pt["era_matters"] and not pt["era_resolved"]:
        cap("B", "era unresolved")
        new_flags.append(flag("needs_tag_pics", 1))
        # With no era, season, named piece or model, only the piece type is left to go on. An unknown-era
        # leather jacket is still worth a look; an unknown-era tee, shirt, bag or belt is most likely recent
        # mainline and belongs with the filler.
        specific = bool(ent.season or ent.grail_piece or ent.model_matched)
        if not specific and (ent.archetype in _EVERYDAY or not ent.archetype):
            cap("C", "era unresolved, everyday piece")
        # unresolved, but nearly all the positive evidence points at unwanted eras -> treat like one
        pos = {k: v for k, v in (ent.era_scores or {}).items() if v > 0}
        tot = sum(pos.values())
        bad = sum(v for k, v in pos.items() if float(tax.eras.get(k, {}).get("weight", 5)) <= 4)
        if tot >= 1.0 and bad / tot >= 0.6:
            cap("C", "era evidence leans unwanted")
            new_flags.append(flag("era_leans_unwanted", 1))
    if pt["era_weight"] is not None:
        if pt["era_weight"] <= 4:
            cap("C", f"unwanted era ({ent.era})")
            new_flags.append(flag("unwanted_era", 1, ent.era))
        elif pt["era_weight"] <= 6:
            cap("B", f"secondary era ({ent.era})")
    if ceiling and ORDER.index(tier) < ORDER.index(ceiling):
        tier = ceiling
    factors = [{"k": k, "label": LABELS[k], "v": round(vals[k], 3), "w": W[k]} for k in W]
    if pt.get("piece_src"):
        factors[1]["src"] = pt["piece_src"]
    return {"score": round(score, 1), "tier": tier, "ceiling": ceiling, "ceiling_reason": reason,
            "factors": factors, "flags": new_flags}
