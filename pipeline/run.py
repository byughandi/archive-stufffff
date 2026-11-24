"""CLI: python -m pipeline.run <score|comps|rescore|retrain|trends|alerts|prune|eval|taxonomy|refresh-report|all>
[--limit N] [--dry-run]

Each command prints a one-line JSON summary and stores it in kv `run_stats:<command>`.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

from core.config import ROOT, settings
from core.db import Database, connect, now

from . import cfg

EVAL_PATH = ROOT / "data" / "eval" / "labeled_listings.jsonl"
BASELINE_PATH = ROOT / "data" / "eval" / "baseline.json"
GATE = {"junk_rejection": 0.90, "precision_at_50": 0.85, "era_ok": 0.85}
TIER_ORDER = "SABCX"


# ------------------------------------------------------------------------------------------------ eval
def load_eval(path: Path = EVAL_PATH) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def evaluate(rows: list[dict] | None = None, ranker=None, verbose: bool = False) -> dict:
    """Score the gold set offline (no DB, no comps, fallback FX) and compute the gate metrics."""
    from .score import build_context, feed_order, score_items

    rows = rows if rows is not None else load_eval()
    ctx = build_context(None, offline=True)
    if ranker is not None:
        ctx.ranker = ranker
    res = score_items(rows, ctx)
    by_id = {r.listing["id"]: (row, r) for row, r in zip(rows, res)}
    # junk rejection
    junk = [(row, r) for row, r in by_id.values() if not row["label_relevant"]]
    junk_ok = [(row, r) for row, r in junk if r.tier in ("X", "C")]
    # precision@50 by feed order
    order = feed_order(res)
    top = order[:50]
    p50 = sum(by_id[r.listing["id"]][0]["label_relevant"] for r in top) / max(1, len(top))
    # era subset
    era_rows = [(row, r) for row, r in by_id.values() if row.get("expect_era") is not None]
    era_ok, era_strict, era_fail = 0, 0, []
    for row, r in era_rows:
        want = row["expect_era"]
        got = r.ent.era if r.ent and r.ent.era_conf >= cfg("era_resolved") else "unresolved"
        if got == want:
            era_ok += 1
            era_strict += 1
        elif got == "unresolved":
            era_ok += 1          # honestly unresolved, not wrong
        else:
            era_fail.append({"id": row["id"], "title": row["title"], "want": want, "got": got,
                             "conf": r.ent.era_conf if r.ent else 0, "cues": r.ent.era_cues if r.ent else []})
    # named junk patterns must be rejected (tier X)
    pat_fail = [{"id": row["id"], "pattern": row["junk_pattern"], "title": row["title"], "tier": r.tier}
                for row, r in by_id.values() if row.get("junk_pattern") and r.tier != "X"]
    patterns = sorted({row["junk_pattern"] for row in rows if row.get("junk_pattern")})
    # tier bounds (reported, not gated)
    tb_fail = []
    for row, r in by_id.values():
        lo, hi = row.get("expect_tier_min"), row.get("expect_tier_max")
        t = TIER_ORDER.index(r.tier)
        if (hi and t < TIER_ORDER.index(hi)) or (lo and t > TIER_ORDER.index(lo)):
            tb_fail.append({"id": row["id"], "title": row["title"], "tier": r.tier, "want": f"{hi or 'S'}..{lo or 'X'}",
                            "reason": r.reject_reason or (r.desir or {}).get("ceiling_reason"),
                            "score": (r.desir or {}).get("score")})
    brand_fail = [{"id": row["id"], "title": row["title"], "want": row.get("expect_brand"),
                   "got": r.ent.brand if r.ent else None}
                  for row, r in by_id.values()
                  if row.get("label_relevant") and row.get("expect_brand") and (r.ent.brand if r.ent else None) != row["expect_brand"]]
    m = {
        "rows": len(rows),
        "junk_rejection": round(len(junk_ok) / max(1, len(junk)), 4),
        "precision_at_50": round(p50, 4),
        "era_ok": round(era_ok / max(1, len(era_rows)), 4),
        "era_strict": round(era_strict / max(1, len(era_rows)), 4),
        "era_rows": len(era_rows),
        "junk_patterns": len(patterns),
        "junk_patterns_failed": len(pat_fail),
        "tier_bounds_ok": round(1 - len(tb_fail) / max(1, len(rows)), 4),
        "brand_ok_on_relevant": round(1 - len(brand_fail) / max(1, sum(r["label_relevant"] for r in rows)), 4),
        "tiers": dict(collections.Counter(r.tier for r in res)),
        "embed_backend": next(((r.explain.get("similarity") or {}).get("backend") for r in res
                               if r.explain and r.explain.get("similarity")), None),
    }
    m["details"] = {
        "junk_not_rejected": [{"id": row["id"], "title": row["title"], "tier": r.tier,
                               "score": (r.desir or {}).get("score")} for row, r in junk if r.tier not in ("X", "C")],
        "top50_irrelevant": [{"id": r.listing["id"], "title": r.listing["title"], "tier": r.tier}
                             for r in top if not by_id[r.listing["id"]][0]["label_relevant"]],
        "era_wrong": era_fail, "junk_patterns_not_rejected": pat_fail, "tier_bounds_violated": tb_fail,
        "brand_wrong": brand_fail,
        "relevant_rejected": [{"id": row["id"], "title": row["title"], "reason": r.reject_reason}
                              for row, r in by_id.values() if row["label_relevant"] and r.tier == "X"],
    }
    return m


def gate(m: dict, baseline: dict | None = None) -> list[str]:
    fails = []
    for k, v in GATE.items():
        if m[k] < v:
            fails.append(f"{k} {m[k]} < {v}")
    if m["junk_patterns_failed"]:
        fails.append(f"{m['junk_patterns_failed']} named junk patterns not rejected")
    if baseline and m["precision_at_50"] < float(baseline.get("precision_at_50", 0)) - 1e-9:
        fails.append(f"precision_at_50 {m['precision_at_50']} below baseline {baseline['precision_at_50']}")
    return fails


def load_baseline() -> dict | None:
    return json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else None


# ------------------------------------------------------------------------------------------------ prune
def prune(db: Database, dry_run: bool = False) -> dict:
    ret = settings().get("retention", {})
    t = now()
    rej_cut = t - int(ret.get("rejected_days", 7)) * 86400
    end_cut = t - int(ret.get("ended_days", 30)) * 86400
    rejected = [r["listing_id"] for r in db.query(
        "SELECT f.listing_id FROM feed f JOIN listings l ON l.id = f.listing_id WHERE f.tier = 'X' AND l.first_seen_at < ?",
        (rej_cut,))]
    ended = db.query("SELECT id, source, url, title, image_url, brand_raw, size_raw, condition_raw, description,"
                     " status, sold_at, sold_price_usd, price_usd, last_seen_at FROM listings"
                     " WHERE status IN ('sold','ended','removed') AND last_seen_at < ?", (end_cut,))
    stmts = []
    copied = 0
    for r in ended:
        if r["status"] == "sold":
            copied += 1
            stmts.append(("INSERT INTO comps_sold (id, source, url, title, image_url, sold_price_usd, sold_at, brand_raw,"
                          " size_raw, condition_raw, description, classified, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)"
                          " ON CONFLICT(id) DO NOTHING",
                          (r["id"], r["source"], r["url"], r["title"], r["image_url"],
                           r["sold_price_usd"] or r["price_usd"], r["sold_at"] or r["last_seen_at"], r["brand_raw"],
                           r["size_raw"], r["condition_raw"], r["description"], t)))
    ids = rejected + [r["id"] for r in ended]
    for i in range(0, len(ids), 300):
        chunk = ids[i:i + 300]
        q = ",".join("?" * len(chunk))
        for tbl, col in (("feed", "listing_id"), ("scores", "listing_id"), ("listing_entities", "listing_id"),
                         ("listing_snapshots", "listing_id"), ("listings", "id")):
            stmts.append((f"DELETE FROM {tbl} WHERE {col} IN ({q})", tuple(chunk)))
    if not dry_run and stmts:
        for i in range(0, len(stmts), 300):
            db.batch(stmts[i:i + 300])
    return {"rejected_deleted": len(rejected), "ended_deleted": len(ended), "sold_copied_to_comps": copied,
            "dry_run": dry_run, "note": "raw_json_days: no raw JSON table in the schema; nothing to prune"}


# ------------------------------------------------------------------------------------------------ refresh report
_STOP = set("the and with for from size used new item rare vintage archive authentic made japan mens men womens"
            " black white grey gray navy brown red blue condition free shipping".split()) | {
    "サイズ", "ブラック", "ホワイト", "グレー", "ネイビー", "希少", "レア", "美品", "極美品", "新品", "未使用", "中古", "送料無料",
    "アーカイブ", "古着", "メンズ", "レディース", "ヴィンテージ", "黒", "白", "日本製", "正規品", "名作", "人気"}


def _unmatched_terms(m, text: str) -> list[str]:
    from .normalize import norm_text, tokenize
    toks = tokenize(norm_text(text))
    covered = set()
    hits = m.brand_idx.find(toks) + m.arch_idx.find(toks) + m.generic_idx.find(toks)
    for b in {x.payload[0] for x in m.brand_idx.find(toks)}:
        c = m.cues(b)
        hits += c.era_idx.find(toks) + c.season_idx.find(toks) + c.model_idx.find(toks) + c.piece_idx.find(toks)
    for h in hits:
        covered.update(range(h.i, h.j))
    words, cur = [], ""
    for k, t in enumerate(toks):
        if k in covered:
            if cur:
                words.append(cur)
                cur = ""
            continue
        if not t.t.isascii():
            cur += t.t
            continue
        if cur:
            words.append(cur)
            cur = ""
        if t.t.isalpha() and len(t.t) >= 3:
            words.append(t.t)
    if cur:
        words.append(cur)
    return [w for w in words if w not in _STOP and (w.isascii() or len(w) >= 2) and not w.isdigit()]


def refresh_report(db: Database, limit: int | None = None) -> dict:
    from .classify import get_matcher
    from .normalize import norm_text, tokenize

    m = get_matcher()
    since = now() - 7 * 86400
    texts = [(r["title"], r["title"]) for r in db.query(
        "SELECT title FROM listings WHERE first_seen_at >= ?" + (f" LIMIT {int(limit)}" if limit else ""), (since,))]
    texts += [((r["caption"] or "")[:300], (r["caption"] or "")[:80]) for r in db.query(
        "SELECT caption FROM ig_posts WHERE ingested_at >= ?", (since,))]
    cnt: collections.Counter = collections.Counter()
    ex: dict[str, list[str]] = {}
    for text, show in texts:
        words = _unmatched_terms(m, text)
        grams = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        for g in set(grams):
            cnt[g] += 1
            if len(ex.setdefault(g, [])) < 2:
                ex[g].append(show)
    unmatched = [{"term": t, "count": c, "examples": ex[t]} for t, c in cnt.most_common(60)]
    wk = db.scalar("SELECT MAX(week) FROM trend_scores WHERE source='ig'")
    movers = []
    if wk:
        prev = db.scalar("SELECT MAX(week) FROM trend_scores WHERE source='ig' AND week < ?", (wk,))
        cur = {(r["entity_kind"], r["entity_id"]): r["score"] for r in
               db.query("SELECT entity_kind, entity_id, score FROM trend_scores WHERE source='ig' AND week=?", (wk,))}
        old = {(r["entity_kind"], r["entity_id"]): r["score"] for r in
               db.query("SELECT entity_kind, entity_id, score FROM trend_scores WHERE source='ig' AND week=?", (prev,))} if prev else {}
        movers = sorted([{"kind": k[0], "id": k[1], "score": v, "delta": round(v - old.get(k, 0.0), 4)}
                         for k, v in cur.items()], key=lambda x: -abs(x["delta"]))[:30]
    fb = db.query("SELECT f.kind, f.listing_id, l.title, e.brand, e.era FROM feedback f LEFT JOIN listings l ON l.id = f.listing_id"
                  " LEFT JOIN listing_entities e ON e.listing_id = f.listing_id WHERE f.created_at >= ?", (since,))
    grouped: dict[str, dict] = {}
    for r in fb:
        g = grouped.setdefault(r["kind"], {"count": 0, "items": []})
        g["count"] += 1
        if r["kind"] in ("wrong_era", "wrong_brand", "fake") and len(g["items"]) < 40:
            g["items"].append({"listing_id": r["listing_id"], "title": r["title"], "brand": r["brand"], "era": r["era"]})
    rbl = db.query("SELECT DISTINCT s.listing_id, l.title, s.reject_reason FROM scores s JOIN feedback f ON f.listing_id = s.listing_id"
                   " LEFT JOIN listings l ON l.id = s.listing_id WHERE s.tier = 'X' AND f.kind IN ('up','cop','bought')")
    unres = db.query("SELECT f.brand, COUNT(*) AS n FROM feed f WHERE f.status='active' AND f.tier != 'X' AND f.brand IS NOT NULL"
                     " AND (f.era IS NULL) GROUP BY f.brand ORDER BY n DESC LIMIT 20")
    from core.taxonomy import load_taxonomy
    tax = load_taxonomy()
    unres = [r for r in unres if len(tax.eras_by_brand.get(r["brand"], [])) >= 2]
    return {"trend_scores": movers, "unmatched_terms": unmatched, "feedback": grouped,
            "rejected_but_liked": rbl, "top_unresolved_eras": unres}


# ------------------------------------------------------------------------------------------------ main
def score_queue(db, limit, dry_run, use_phash):
    """Score the work queue. On a database that has never been scored, rarity (how common a brand, era and
    piece type is among scored rows) is unknown during the first pass, so a second full pass follows to make
    the first result match what every later rescore will say."""
    from .score import run_score
    cold = not dry_run and not db.scalar("SELECT COUNT(*) FROM scores")
    out = run_score(db, "queue", limit, dry_run, use_phash=use_phash)
    if cold and out.get("scored"):
        second = run_score(db, "all", limit, dry_run, use_phash=False)
        out.update({"tiers": second["tiers"], "labels": second["labels"], "diversity": second.get("diversity"),
                    "cold_start_second_pass": {"written": second["written"], "seconds": second["seconds"]}})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline.run")
    ap.add_argument("command", choices=["score", "comps", "rescore", "retrain", "trends", "alerts", "prune", "eval",
                                        "taxonomy", "refresh-report", "all"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-phash", action="store_true")
    ap.add_argument("--write-baseline", action="store_true", help="eval: store current metrics as the baseline")
    a = ap.parse_args(argv)
    t0 = time.time()
    rc = 0
    if a.command == "eval":
        m = evaluate()
        base = load_baseline()
        fails = gate(m, base)
        if a.write_baseline and not fails:
            BASELINE_PATH.write_text(json.dumps({k: m[k] for k in ("precision_at_50", "junk_rejection", "era_ok",
                                                                   "era_strict", "rows")}, indent=2) + "\n")
        for k, v in m["details"].items():
            if v:
                print(f"## {k} ({len(v)})", file=sys.stderr)
                for x in v[:40]:
                    print("   ", json.dumps(x, ensure_ascii=False), file=sys.stderr)
        summary = {k: v for k, v in m.items() if k != "details"}
        summary.update({"gate": "pass" if not fails else "fail", "failures": fails, "baseline": base,
                        "seconds": round(time.time() - t0, 2)})
        rc = 0 if not fails else 1
        db = None
    else:
        db = connect()
        db.migrate()
        from .score import run_score, sync_taxonomy
        if a.command == "score":
            summary = score_queue(db, a.limit, a.dry_run, False if a.no_phash else None)
        elif a.command == "rescore":
            summary = run_score(db, "all", a.limit, a.dry_run, use_phash=False if a.no_phash else None)
        elif a.command == "comps":
            from .comps import classify_queued
            summary = classify_queued(db, a.limit) if not a.dry_run else {"dry_run": True}
        elif a.command == "taxonomy":
            summary = sync_taxonomy(db, force=True) if not a.dry_run else {"dry_run": True}
        elif a.command == "alerts":
            from .alerts import run_alerts
            summary = run_alerts(db, a.dry_run)
        elif a.command == "trends":
            from .trends import run_trends
            summary = run_trends(db, a.dry_run)
        elif a.command == "prune":
            summary = prune(db, a.dry_run)
        elif a.command == "retrain":
            from .ranker import retrain
            summary = retrain(db, lambda rk: evaluate(ranker=rk)["precision_at_50"], int(cfg("ranker_min_labels"))) \
                if not a.dry_run else {"dry_run": True}
        elif a.command == "refresh-report":
            print(json.dumps(refresh_report(db, a.limit), ensure_ascii=False, default=str))
            return 0
        else:  # all
            from .alerts import run_alerts
            from .comps import classify_queued
            summary = {"comps": classify_queued(db, a.limit) if not a.dry_run else None,
                       "score": score_queue(db, a.limit, a.dry_run, False if a.no_phash else None),
                       "alerts": run_alerts(db, a.dry_run)}
        summary["seconds_total"] = round(time.time() - t0, 2)
    line = json.dumps({"command": a.command, **summary}, ensure_ascii=False, default=str)
    print(line)
    if db is not None and not a.dry_run:
        try:
            db.kv_set(f"run_stats:{a.command}", json.dumps({"at": now(), **json.loads(line)}, ensure_ascii=False))
        except Exception:
            pass
    elif a.command == "eval" and (__import__("os").environ.get("GR_DB_PATH") or __import__("os").environ.get("TURSO_DATABASE_URL")):
        try:
            d = connect()
            d.migrate()
            d.kv_set("run_stats:eval", json.dumps({"at": now(), **json.loads(line)}, ensure_ascii=False))
        except Exception:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
