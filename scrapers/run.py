"""CLI: python -m scrapers.run <fast|slow|comps|recheck|trends> [--source X] [--max-queries N] [--dry-run]

Each source runs inside its own try/except with health recording, so one blocked source never
fails the job. Raw responses go to raw/<source>/<utc-timestamp>.jsonl.gz. One JSON summary line
per source is printed at the end. Exit code is 0 unless every attempted source failed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from typing import Callable

from core import health
from core.db import Database, connect
from core.fx import load_fx
from scrapers import apify, grailed, instagram_trends, mercari_jp, mercari_us, webshops, yahoo_jp
from scrapers.common import Ctx, RawWriter, RunResult
from scrapers.common.http import Blocked, Parked
from scrapers.common.queries import Query, en_queries, ja_queries, next_queries

log = logging.getLogger("scrapers")

DEFAULT_QUERIES = {"grailed": 8, "mercari_us": 2, "mercari_jp": 10, "yahoo_jp": 6}
DEFAULT_COMP_QUERIES = {"grailed": 6, "mercari_us": 1, "mercari_jp": 6, "yahoo_jp": 4}
DEFAULT_RECHECK = 40
LANG = {"grailed": "en", "mercari_us": "en", "mercari_jp": "ja", "yahoo_jp": "ja"}
SOURCES_BY_MODE = {
    "fast": ["grailed", "mercari_us"],
    "slow": ["mercari_jp", "yahoo_jp", "webshops"],
    "comps": ["grailed", "mercari_jp", "yahoo_jp", "mercari_us"],
    "recheck": ["mercari_jp", "yahoo_jp", "webshops", "grailed"],
    "trends": ["instagram"],
}


def _queries(ctx: Ctx, source: str, mode: str) -> list[Query]:
    n = ctx.max_queries or (DEFAULT_COMP_QUERIES if mode == "comps" else DEFAULT_QUERIES)[source]
    cursor = f"{source}:comps" if mode == "comps" else source
    pool = ja_queries() if LANG[source] == "ja" else en_queries()
    return next_queries(ctx.db, cursor, pool, n)


# ---- recheck selection -------------------------------------------------------------------------
def recheck_ids(db: Database, source: str, limit: int) -> list[str]:
    """Tracked active listings (in `feed` with tier S/A/B), least recently re-checked first."""
    cond = "l.source LIKE 'shop:%'" if source == "webshops" else "l.source = ?"
    cursor = "recheck:webshops" if source == "webshops" else f"recheck:{source}"
    args: list = [cursor] + ([] if source == "webshops" else [source]) + [limit]
    rows = db.query(
        "SELECT l.id, l.source_id FROM feed f JOIN listings l ON l.id = f.listing_id"
        " LEFT JOIN search_cursor c ON c.source = ? AND c.query_id = l.id"
        f" WHERE f.tier IN ('S','A','B') AND f.status = 'active' AND {cond}"
        " ORDER BY COALESCE(c.last_run_at, 0) ASC LIMIT ?", args)
    return [r["id"] if source == "webshops" else r["source_id"] for r in rows]


def explicit_ids(db: Database, source: str, ids: list[str]) -> list[str]:
    out = []
    for i in ids:
        full = i if ":" in i else f"{source}:{i}"
        if source == "webshops" and full.startswith("shop:"):
            out.append(full)
        elif full.startswith(source + ":"):
            out.append(full.split(":", 1)[1])
    return out


# ---- source runners -----------------------------------------------------------------------------
def run_fast_or_slow(ctx: Ctx, source: str, mode: str,
                     gate: Callable[[str], bool] = lambda key: True) -> list[tuple[str, RunResult | Exception]]:
    if source == "grailed":
        return [("grailed", _call(lambda: grailed.run(ctx, _queries(ctx, source, mode))))]
    if source == "mercari_us":
        return [("mercari_us", _call(lambda: mercari_us.run(ctx, _queries(ctx, source, mode))))]
    if source == "mercari_jp":
        return [("mercari_jp", _call(lambda: mercari_jp.run(ctx, _queries(ctx, source, mode))))]
    if source == "yahoo_jp":
        return [("yahoo_jp", _call(lambda: yahoo_jp.YahooJP(ctx).scrape(_queries(ctx, source, mode))))]
    if source == "webshops":
        w = webshops.Webshops(ctx)
        out: list[tuple[str, RunResult | Exception]] = []
        for s in w.shops():
            key = f"shop:{webshops.slug_for(s)}"
            out.append((key, _call(lambda s=s: w.scrape_shop(s)) if gate(key) else RunResult(key, "scrape", note="paused")))
        return out
    raise ValueError(source)


def run_comps(ctx: Ctx, source: str) -> list[tuple[str, RunResult | Exception]]:
    q = lambda: _queries(ctx, source, "comps")  # noqa: E731
    if source == "grailed":
        return [("grailed", _call(lambda: grailed.comps(ctx, q())))]
    if source == "mercari_jp":
        return [("mercari_jp", _call(lambda: mercari_jp.run_comps(ctx, q())))]
    if source == "yahoo_jp":
        return [("yahoo_jp", _call(lambda: yahoo_jp.YahooJP(ctx).comps(q())))]
    if source == "mercari_us":
        return [("mercari_us", _call(lambda: mercari_us.comps(ctx, q())))]
    return []


def run_recheck(ctx: Ctx, source: str, ids: list[str] | None, limit: int) -> list[tuple[str, RunResult | Exception]]:
    got = explicit_ids(ctx.db, source, ids) if ids else recheck_ids(ctx.db, source, limit)
    got = got[:limit]
    if not got:
        return [(source, RunResult(source, "recheck", note="nothing to re-check"))]
    if source == "mercari_jp":
        return [("mercari_jp", _call(lambda: mercari_jp.run_recheck(ctx, got)))]
    if source == "yahoo_jp":
        return [("yahoo_jp", _call(lambda: yahoo_jp.YahooJP(ctx).recheck(got)))]
    if source == "webshops":
        return [("webshops", _call(lambda: webshops.Webshops(ctx).recheck(got)))]
    if source == "grailed":
        return [("grailed", _call(lambda: grailed.Grailed(ctx).recheck(got)))]
    return []


def _call(fn: Callable[[], RunResult]) -> RunResult | Exception:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - one source must never take the job down
        log.warning("source failed: %r", e)
        return e


def summarize(db: Database, key: str, mode: str, out: RunResult | Exception, seconds: float, dry: bool) -> dict:
    s: dict = {"source": key, "mode": mode, "seconds": round(seconds, 1)}
    if isinstance(out, Parked):
        return s | {"status": "parked", "note": str(out)[:200]}   # nothing was requested: no new failure
    if isinstance(out, Exception):
        blocked = isinstance(out, Blocked)
        tripped = False if dry else health.record_failure(db, key, blocked, f"{type(out).__name__}: {out}")
        s |= {"status": "paused" if tripped else ("blocked" if blocked else "error"), "error": str(out)[:200]}
        if tripped:
            s["breaker"] = "open 6h"
        return s
    d = out.as_dict()
    s |= {k: v for k, v in d.items() if k not in ("source", "mode")}
    if out.note == "paused":
        s["status"] = "paused"
        return s
    if "throttled" in (out.note or "") or out.note == "nothing to re-check":
        s["status"] = "skipped"
        return s
    if not dry and key != "webshops":
        health.record_ok(db, key, out.stored, out.rung)
    s["status"] = "ok" if (out.stored or out.updated or out.skipped_dry) else "empty"
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scrapers.run")
    ap.add_argument("mode", choices=list(SOURCES_BY_MODE))
    ap.add_argument("--source", help="restrict to one source (grailed|mercari_us|mercari_jp|yahoo_jp|webshops|instagram)")
    ap.add_argument("--max-queries", type=int, help="saved searches per source (recheck: ids per source)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and parse, write nothing")
    ap.add_argument("--deep", action="store_true", help="first-fill: allow more pages per query")
    ap.add_argument("--ids", help="recheck: comma separated listing ids (source_id or full id) instead of the feed")
    ap.add_argument("--force", action="store_true", help="ignore an open circuit breaker")
    args = ap.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"), format="%(levelname)s %(name)s: %(message)s")

    db = connect()
    db.migrate()
    ctx = Ctx(db, load_fx(db), dry_run=args.dry_run, max_queries=args.max_queries, deep=args.deep)
    sources = list(SOURCES_BY_MODE[args.mode])
    if args.source:
        if args.source not in sources and not (args.source == "webshops" and args.mode in ("slow", "recheck")):
            print(f"source {args.source!r} is not part of mode {args.mode!r} ({sources})", file=sys.stderr)
            return 2
        sources = [args.source]
    elif args.mode == "fast":
        n = int(db.kv_get("run_counter:fast") or 0) + 1
        if not args.dry_run:
            db.kv_set("run_counter:fast", str(n))
        if n % 2:                       # Mercari US only every second fast run
            sources.remove("mercari_us")

    summaries: list[dict] = []
    for source in sources:
        t0 = time.time()
        gate_key = "instagram" if source == "instagram" else source
        if source != "webshops" and not args.dry_run and not args.force and not health.allowed(db, gate_key):
            summaries.append({"source": source, "mode": args.mode, "status": "paused",
                              "breaker_s": health.breaker_remaining(db, gate_key)})
            continue
        ctx.raw = RawWriter(f"{source}", enabled=not args.dry_run and os.environ.get("GR_RAW", "1") != "0")
        try:
            if args.mode in ("fast", "slow"):
                outs = run_fast_or_slow(ctx, source, args.mode,
                                        lambda k: args.dry_run or args.force or health.allowed(db, k))
            elif args.mode == "comps":
                outs = run_comps(ctx, source)
            elif args.mode == "recheck":
                ids = [x for x in (args.ids or "").split(",") if x] or None
                outs = run_recheck(ctx, source, ids, args.max_queries or DEFAULT_RECHECK)
            else:
                outs = [("instagram", _call(lambda: instagram_trends.run(ctx)))]
        finally:
            ctx.raw.close()
        elapsed = time.time() - t0
        for key, out in outs:
            summaries.append(summarize(db, key, args.mode, out, elapsed / max(len(outs), 1), args.dry_run))
    for s in summaries:
        print(json.dumps(s, ensure_ascii=False))
    # a run that tripped the breaker did fail; a source that was merely gated by an open breaker did not run
    attempted = [s for s in summaries if s["status"] not in ("skipped", "parked") and not (s["status"] == "paused" and "error" not in s)]
    # A block is a handled state (recorded in source_health, next rung or breaker takes over), so the job
    # carries on to scoring and alerts. Only unexpected errors on every attempted source fail the job.
    return 1 if attempted and all(s["status"] == "error" for s in attempted) else 0


if __name__ == "__main__":
    sys.exit(main())
