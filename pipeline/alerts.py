"""Alerts: match new/changed feed rows against saved searches and push to ntfy.

- The built-in global rule (is_global = 1) is created if missing: tier S, or label steal; never suspicious.
- Never alerted: suspicious rows, rejected rows, auctions still in progress (flag auction_in_progress).
- Dedupe through alerts_sent: one alert per listing per rule; re-alert only after a further >= 10% price drop.
- At most `alerts.max_per_run` messages per run (config/settings.yaml).
- NTFY_TOPIC unset (or --dry-run): print what would be sent. SITE_URL set: click-through opens the site drawer
  ({SITE_URL}/?l=<id>) and the body carries the marketplace URL (plus the Buyee link for Japan).
"""
from __future__ import annotations

import json
import os
import time

import httpx

from core.config import settings
from core.db import Database, now

from .normalize import norm_text

TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "X": 9}
GLOBAL_RULE = {"min_tier": "S", "labels": ["steal"], "mode": "any", "never_labels": ["suspicious"]}


def ensure_global_rule(db: Database) -> int:
    row = db.one("SELECT id FROM saved_searches WHERE is_global = 1 ORDER BY id LIMIT 1")
    if row:
        return int(row["id"])
    db.execute("INSERT INTO saved_searches (name, rule, enabled, is_global, created_at) VALUES (?,?,1,1,?)",
               ("Tier S or steal (built-in)", json.dumps(GLOBAL_RULE), now()))
    return int(db.scalar("SELECT id FROM saved_searches WHERE is_global = 1 ORDER BY id LIMIT 1"))


def matches(rule: dict, row: dict, is_global: bool = False) -> bool:
    if row.get("tier") == "X" or row.get("deal_label") == "suspicious" or row.get("suspicious"):
        return False
    flags = row.get("_flags") or []
    if "auction_in_progress" in flags:
        return False
    if is_global:
        return row["tier"] == "S" or row.get("deal_label") == "steal"
    if rule.get("q") and norm_text(rule["q"]) not in norm_text(row.get("title")):
        return False
    for k in ("brand", "era", "archetype"):
        if rule.get(k) and row.get(k) != rule[k]:
            return False
    if rule.get("sizes") and (row.get("size_norm") or "") not in {str(s).upper() for s in rule["sizes"]} | set(rule["sizes"]):
        return False
    if rule.get("max_landed_usd") and float(row.get("landed_usd") or 0) > float(rule["max_landed_usd"]):
        return False
    if rule.get("min_tier") and TIER_RANK[row["tier"]] > TIER_RANK[rule["min_tier"]]:
        return False
    if rule.get("labels") and row.get("deal_label") not in rule["labels"]:
        return False
    if rule.get("sources") and row.get("source") not in rule["sources"]:
        return False
    if rule.get("region") and row.get("region") != rule["region"]:
        return False
    return True


def message(row: dict) -> dict:
    site = os.environ.get("SITE_URL", "").rstrip("/")
    disc = row.get("discount")
    pct = f"{disc * 100:.0f}% under" if disc is not None and disc > 0 else (
        f"{-disc * 100:.0f}% over" if disc is not None else "no fair value")
    fv = f"${row['fair_value_usd']:.0f}" if row.get("fair_value_usd") else "n/a"
    if row.get("fair_value_usd"):
        conf = {"high": "high", "med": "medium", "low": "low"}.get(row.get("value_conf") or "", "low")
        fv += f" ({conf} confidence, {int(row.get('comp_count') or 0)} sold)"
    lines = [f"Tier {row['tier']} · {row.get('deal_label') or 'unknown'} · {pct}",
             f"Price ${row['price_usd']:.0f} · landed ${row['landed_usd']:.0f} · fair value {fv}"]
    if site:
        lines.append(row["url"])
        if row.get("proxy_url"):
            lines.append(f"Proxy: {row['proxy_url']}")
        click = f"{site}/?l={row['listing_id']}"
    else:
        click = row["url"]
        if row.get("proxy_url"):
            lines.append(f"Proxy: {row['proxy_url']}")
    return {"title": row["title"][:120], "body": "\n".join(lines), "click": click,
            "tags": "fire" if row["tier"] == "S" else "moneybag"}


def send(msg: dict, topic: str, server: str) -> bool:
    """Publish one alert. Uses ntfy's JSON publishing so titles in any script (Japanese included) are
    sent as UTF-8; HTTP headers cannot carry them."""
    payload = {"topic": topic, "title": msg["title"][:200] or "Grail Radar", "message": msg["body"],
               "click": msg["click"], "tags": [t for t in str(msg.get("tags", "")).split(",") if t], "priority": 4}
    try:
        r = httpx.post(server.rstrip("/") + "/", json=payload, timeout=15)
        return r.status_code < 300
    except Exception as e:  # never let a notification problem fail the job
        print(json.dumps({"alert_error": str(e)[:200]}))
        return False


def run_alerts(db: Database, dry_run: bool = False, since: int | None = None) -> dict:
    t0 = time.time()
    cfg = settings().get("alerts", {})
    cap = int(cfg.get("max_per_run", 8))
    server = cfg.get("ntfy_server", "https://ntfy.sh")
    # The topic is a shared secret between this job and the phone. It can come from the environment (CI
    # secret) or from the private database (`kv.ntfy_topic`), so a scheduler with no secret store still alerts.
    topic = os.environ.get("NTFY_TOPIC") or db.kv_get("ntfy_topic")
    gid = ensure_global_rule(db)
    last = since if since is not None else int(db.kv_get("alerts_last_run") or (now() - 6 * 3600))
    rules = db.query("SELECT id, name, rule, is_global FROM saved_searches WHERE enabled = 1")
    rows = db.query("SELECT f.*, s.scored_at FROM feed f JOIN scores s ON s.listing_id = f.listing_id"
                    " WHERE f.status = 'active' AND f.tier != 'X' AND s.scored_at >= ?"
                    " ORDER BY f.tier_rank, f.sort_key DESC", (last,))
    sent_prev = {(r["listing_id"], int(r["rule_id"])): float(r["price_usd"])
                 for r in db.query("SELECT listing_id, rule_id, price_usd FROM alerts_sent")}
    out, stmts, n = [], [], 0
    for row in rows:
        try:
            row["_flags"] = json.loads(row.get("flags") or "[]")
        except Exception:
            row["_flags"] = []
        for rule in rules:
            try:
                rj = json.loads(rule["rule"] or "{}")
            except Exception:
                continue
            if not matches(rj, row, bool(rule["is_global"])):
                continue
            key = (row["listing_id"], int(rule["id"]))
            prev = sent_prev.get(key)
            if prev is not None and float(row["price_usd"]) > 0.9 * prev:
                continue
            if n >= cap:
                break
            msg = message(row)
            delivered = False
            if topic and not dry_run:
                delivered = ok = send(msg, topic, server)
            else:
                ok = True   # preview only: printed, counted, but never recorded as sent
                print(json.dumps({"would_send": msg, "rule": rule["name"]}, ensure_ascii=False))
            if ok:
                n += 1
                out.append(row["listing_id"])
                sent_prev[key] = float(row["price_usd"])
                if delivered:
                    stmts.append(("INSERT INTO alerts_sent (listing_id, rule_id, price_usd, sent_at) VALUES (?,?,?,?)"
                                  " ON CONFLICT(listing_id, rule_id) DO UPDATE SET price_usd=excluded.price_usd,"
                                  " sent_at=excluded.sent_at", (row["listing_id"], rule["id"], row["price_usd"], now())))
            break  # one alert per listing per run (first matching rule)
    if stmts:
        db.batch(stmts)
    if topic and not dry_run:   # without a topic nothing was delivered, so the window must not advance
        db.kv_set("alerts_last_run", str(int(t0)))
        prev = {}
        try:
            prev = json.loads(db.kv_get("alert_delivery") or "{}")
        except Exception:
            pass
        last = now() if (n and topic) else prev.get("last_sent_at")
        db.kv_set("alert_delivery", json.dumps({"channel": "ntfy", "configured": bool(topic), "last_sent_at": last}))
    return {"candidates": len(rows), "sent": n, "delivered_via": "ntfy" if topic and not dry_run else "stdout",
            "global_rule_id": gid, "seconds": round(time.time() - t0, 2)}
