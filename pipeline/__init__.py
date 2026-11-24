"""Grail Radar scoring pipeline (the cascade in docs/ARCHITECTURE.md, output contract in docs/CONTRACTS.md §2).

Stage 0 normalize.py  -> Stage 1 filter.py -> Stage 2 classify.py -> Stage 3 embed.py -> Stage 4 ranker.py
-> Stage 5 desirability.py -> Stage 6 comps.py -> Stage 7 score.py; alerts.py, trends.py, run.py (CLI).

Runtime knobs live in `config/settings.yaml` under an optional `scoring:` mapping and can be overridden with
environment variables `GR_<KEY>` (upper case). Nothing here makes a paid call.
"""
from __future__ import annotations

import os

from core.config import settings

VERSION = "gr-pipeline-1.0"

DEFAULTS: dict = {
    # market value
    "jp_to_us_uplift": 1.0,          # do NOT invent an uplift: JP comps are compared like-for-like unless set
    "comp_half_life_days": 90.0,
    "comp_window_days": 365.0,
    "comp_max_shown": 8,
    "comp_shrink_k": 6.0,            # pseudo-count pulling a thin season median toward its era+type pool
    # price floors in brands.yaml are US-market tripwires; Japanese asking prices run lower
    "jp_floor_factor": 0.5,
    # era resolution thresholds
    "era_resolved": 0.5,             # below: era unresolved -> ceiling B + needs_tag_pics (if era matters)
    "era_confirmed": 0.65,           # S tier requires at least this
    # desirability / rarity
    "rarity_window_days": 180.0,
    # proxy used for JP landed cost (ids from config/japan_costs.yaml)
    "proxy": "buyee",
    # images
    "phash_cap": 120,                # thumbnails hashed per run (top candidates only)
    "phash_timeout": 6.0,
    # ranker
    "ranker_min_labels": 200,
    # freshness boost in feed.sort_key
    "fresh_boost": 0.06,
    "fresh_half_life_hours": 36.0,
    "drop_boost": 0.08,
    # diversity: each further row of the same tier + brand + piece type gives up `step`, up to `cap`
    "diversity_step": 0.012,
    "diversity_cap": 0.15,
    "diversity_brand_step": 0.006,
    "diversity_brand_cap": 0.18,
    # staleness: a fixed-price listing unsold this long loses up to `stale_penalty` of sort key over 120 more days
    "stale_after_days": 60.0,
    "stale_penalty": 0.12,
}


def cfg(key: str):
    env = os.environ.get("GR_" + key.upper())
    base = DEFAULTS.get(key)
    if env is not None:
        try:
            return type(base)(env) if base is not None else env
        except (TypeError, ValueError):
            return env
    try:
        over = (settings().get("scoring") or {}).get(key)
    except Exception:  # settings unreadable in an odd test environment
        over = None
    return base if over is None else over
