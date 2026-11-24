"""Trends: Instagram captions/hashtags -> weekly `trend_scores`, plus research priors as source = 'prior'.

Each post is classified with the same matcher as listings (brand / era / season / archetype). A post's weight is
its engagement (likes + 3 x comments) relative to its account's median, clipped to [0.2, 5]. A week's score for an
entity is 1 - exp(-D / 4), where D is the sum of post weights in that week and earlier weeks, each decayed with a
4-week half-life. Priors from trend_priors.yaml are written for the current week so the Trends page has data
before any Instagram scrape.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import time

from core.db import Database, now
from core.taxonomy import load_taxonomy

from .classify import get_matcher

HALF_LIFE_WEEKS = 4.0
WEEKS_BACK = 12


def week_start(ts: int) -> str:
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def write_priors(db: Database, week: str | None = None) -> int:
    tax = load_taxonomy()
    week = week or week_start(now())
    best: dict[tuple[str, str], float] = {}

    def put(kind, eid, v):
        if eid and eid != "UNKNOWN":
            best[(kind, str(eid))] = max(best.get((kind, str(eid)), 0.0), float(v))

    for row in tax.heat_list:
        v = float(row.get("trend_prior", 0.4))
        if row.get("season") not in (None, "UNKNOWN"):
            put("season", row["season"], v)
        elif row.get("era") not in (None, "UNKNOWN") and row.get("archetype") in (None, "UNKNOWN"):
            put("era", row["era"], v)
        elif row.get("archetype") in (None, "UNKNOWN"):
            put("brand", row.get("brand"), v)
        else:
            put("brand", row.get("brand"), v * 0.95)
    stmts = [("INSERT INTO trend_scores (entity_kind, entity_id, week, score, mentions, source) VALUES (?,?,?,?,0,'prior')"
              " ON CONFLICT(entity_kind, entity_id, week, source) DO UPDATE SET score = excluded.score", (k, e, week, v))
             for (k, e), v in best.items()]
    if stmts:
        db.batch(stmts)
    return len(stmts)


def run_trends(db: Database, dry_run: bool = False) -> dict:
    t0 = time.time()
    m = get_matcher()
    since = now() - (WEEKS_BACK + 8) * 7 * 86400
    posts = db.query("SELECT id, handle, posted_at, caption, hashtags, likes, comments FROM ig_posts"
                     " WHERE posted_at >= ?", (since,))
    by_handle: dict[str, list[float]] = {}
    for p in posts:
        by_handle.setdefault(p["handle"], []).append(float(p["likes"] or 0) + 3 * float(p["comments"] or 0))
    med = {h: max(1.0, statistics.median(v)) for h, v in by_handle.items()}
    # per entity per week raw weights
    raw: dict[tuple[str, str], dict[str, float]] = {}
    cnt: dict[tuple[str, str], dict[str, int]] = {}
    ent_updates = []
    for p in posts:
        tags = []
        try:
            tags = json.loads(p["hashtags"] or "[]")
        except Exception:
            pass
        text = f"{p['caption'] or ''} {' '.join(str(t).replace('_', ' ') for t in tags)}"
        e = m.classify(text)
        ids = {"brand": e.brand, "era": e.era if e.era_conf >= 0.5 else None, "season": e.season,
               "archetype": e.archetype}
        ent_updates.append(("UPDATE ig_posts SET entities = ? WHERE id = ?", (json.dumps(ids), p["id"])))
        if not e.brand:
            continue
        eng = float(p["likes"] or 0) + 3 * float(p["comments"] or 0)
        w = min(5.0, max(0.2, eng / med[p["handle"]]))
        wk = week_start(int(p["posted_at"] or now()))
        for kind, eid in ids.items():
            if eid:
                raw.setdefault((kind, eid), {})[wk] = raw.get((kind, eid), {}).get(wk, 0.0) + w
                cnt.setdefault((kind, eid), {})[wk] = cnt.get((kind, eid), {}).get(wk, 0) + 1
    weeks = [week_start(now() - i * 7 * 86400) for i in range(WEEKS_BACK)][::-1]
    stmts = []
    for key, per in raw.items():
        for wk in weeks:
            d = 0.0
            for w2, v in per.items():
                age = (dt.date.fromisoformat(wk) - dt.date.fromisoformat(w2)).days / 7.0
                if age >= 0:
                    d += v * 0.5 ** (age / HALF_LIFE_WEEKS)
            if d <= 0:
                continue
            stmts.append(("INSERT INTO trend_scores (entity_kind, entity_id, week, score, mentions, source)"
                          " VALUES (?,?,?,?,?,'ig') ON CONFLICT(entity_kind, entity_id, week, source) DO UPDATE SET"
                          " score = excluded.score, mentions = excluded.mentions",
                          (key[0], key[1], wk, round(1 - math.exp(-d / 4.0), 4), cnt[key].get(wk, 0))))
    priors = 0
    if not dry_run:
        priors = write_priors(db)
        for i in range(0, len(stmts), 500):
            db.batch(stmts[i:i + 500])
        for i in range(0, len(ent_updates), 500):
            db.batch(ent_updates[i:i + 500])
    return {"posts": len(posts), "entities": len(raw), "ig_rows": len(stmts), "prior_rows": priors,
            "seconds": round(time.time() - t0, 2), "dry_run": dry_run}
