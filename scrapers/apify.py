"""Minimal Apify client with a hard spend guard.

Apify is the paid fallback (free $5/month credit, no overage). Before every run we read this
month's total from `spend_ledger` and refuse if the run could take the month past 90% of the
credit (config/settings.yaml: apify.monthly_credit_usd * apify.stop_at_fraction). After every run
we write the estimated cost (items x per-1k price) to `spend_ledger`.

Actor ids and per-1k prices come from config/sources.yaml, overridable by env:
  APIFY_ACTOR_<KEY>=owner/actor      APIFY_PRICE_<KEY>=<usd per 1000 items>
with KEY in GRAILED, MERCARI_US, MERCARI_US_SOLD, INSTAGRAM.

Neither apify.com nor api.apify.com was reachable when this was written, so every actor INPUT
mapping below is from memory/READMEs and must be confirmed against the actor's input schema
before first use. The mappings are isolated in the `*_input` functions.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from core.config import settings, sources_config
from core.db import Database, now
from scrapers.common.http import Blocked, FetchError, PoliteClient

API = "https://api.apify.com/v2"
DEFAULT_PRICE_PER_1K = 3.0       # conservative when sources.yaml says UNKNOWN
VENDOR = "apify"

# Fallback actors when sources.yaml has no usable entry (ids from research, unverified).
DEFAULT_ACTORS = {
    "GRAILED": ("piotrv1001/grailed-listings-scraper", 3.0),   # verified with real runs, see config/sources.yaml
    "MERCARI_US": ("getascraper/mercari-us-scraper", 2.05),
    "MERCARI_US_SOLD": ("devilscrapes/mercari-sold-listings", 2.51),
    "INSTAGRAM": ("apify/instagram-scraper", 2.3),
}
# Per-purpose monthly caps (USD) so the fallbacks cannot eat the Instagram budget.
# Grailed sold prices are the pricing backbone, so it gets the largest share. The three add up to the
# $4.50 stop (90% of the free $5). Override with APIFY_BUDGET_<SOURCE>_USD.
DEFAULT_CAPS = {"grailed": 2.75, "mercari_us": 0.5, "instagram": 1.25}


class SpendGuard(Exception):
    """A run was refused because it would take the month past the stop-at fraction."""


class ApifyUnavailable(Exception):
    """No token configured."""


@dataclass
class Actor:
    key: str
    id: str
    price_per_1k: float


def month_start(at: int | None = None) -> int:
    d = dt.datetime.fromtimestamp(at if at is not None else now(), dt.timezone.utc)
    return int(d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())


def month_total(db: Database, at: int | None = None, note_prefix: str | None = None) -> float:
    sql = "SELECT COALESCE(SUM(usd), 0) FROM spend_ledger WHERE vendor = ? AND at >= ?"
    args: list[Any] = [VENDOR, month_start(at)]
    if note_prefix:
        sql += " AND note LIKE ?"
        args.append(note_prefix + "%")
    return float(db.scalar(sql, args) or 0.0)


def credit_limit() -> float:
    cfg = settings()["apify"]
    return float(cfg["monthly_credit_usd"]) * float(cfg["stop_at_fraction"])


def source_cap(source: str) -> float:
    env = os.environ.get(f"APIFY_BUDGET_{source.upper()}_USD")
    return float(env) if env else DEFAULT_CAPS.get(source, 0.5)


def check_budget(db: Database, est_usd: float, source: str | None = None, at: int | None = None) -> None:
    total = month_total(db, at)
    if total + est_usd > credit_limit() + 1e-9:
        raise SpendGuard(f"apify month total ${total:.2f} + est ${est_usd:.2f} would pass "
                         f"{credit_limit():.2f} (90% of credit)")
    if source:
        spent = month_total(db, at, note_prefix=f"source:{source}")
        if spent + est_usd > source_cap(source) + 1e-9:
            raise SpendGuard(f"apify budget for {source}: ${spent:.2f} + est ${est_usd:.2f} > cap ${source_cap(source):.2f}")


def actor_for(key: str) -> Actor:
    """Resolve actor id and per-1k price: env override > config/sources.yaml > built-in default."""
    default_id, default_price = DEFAULT_ACTORS[key]
    aid = os.environ.get(f"APIFY_ACTOR_{key}")
    price: float | None = float(os.environ[f"APIFY_PRICE_{key}"]) if os.environ.get(f"APIFY_PRICE_{key}") else None
    src = {"GRAILED": "grailed", "MERCARI_US": "mercari_us", "MERCARI_US_SOLD": "mercari_us"}.get(key)
    if not aid and src:
        actors = (sources_config().get(src) or {}).get("apify_actors") or []
        want = default_id
        for a in actors:
            first = str(a["id"]).split()[0]
            if first == want:
                aid = first
                if price is None and isinstance(a.get("price_per_1k_usd"), (int, float)):
                    price = float(a["price_per_1k_usd"])
    return Actor(key, aid or default_id, price if price is not None else default_price)


def token() -> str:
    t = os.environ.get("APIFY_TOKEN", "")
    if not t:
        raise ApifyUnavailable("APIFY_TOKEN is not set")
    return t


# ---- INPUT MAPPINGS: confirm against the actor's input schema before first use --------------------
def grailed_input(actor: Actor, query: str, max_items: int, sold: bool = False) -> dict:
    """Input for piotrv1001/grailed-listings-scraper (schema verified 2026-11-24). One search query per run.
    `scrapeDetails` stays off: it quadruples the per-listing price and the pipeline does not need it."""
    return {"searchQuery": query, "soldOnly": bool(sold), "department": "all", "scrapeDetails": False,
            "maxItems": int(max_items), "proxyConfiguration": {"useApifyProxy": True}}


def mercari_us_input(actor: Actor, queries: list[str], max_items: int, sold: bool = False) -> dict:
    # CONFIRM AGAINST INPUT SCHEMA (unverified): typical shape {"keywords": [...], "maxItems": N,
    # "sort": "newest", "status": "on_sale"|"sold"}.
    return {"keywords": queries, "maxItems": max_items, "sort": "newest", "status": "sold" if sold else "on_sale"}


def instagram_input(actor: Actor, handles: list[str], posts_per_account: int) -> dict:
    # CONFIRM AGAINST INPUT SCHEMA: apify/instagram-scraper documents directUrls + resultsType
    # "posts" + resultsLimit; verify before first use.
    return {"directUrls": [f"https://www.instagram.com/{h}/" for h in handles], "resultsType": "posts",
            "resultsLimit": posts_per_account, "addParentData": False}


# ---------------------------------------------------------------------------------------------------
def run_actor(db: Database, actor: Actor, run_input: dict, *, max_items: int, source: str,
              client: PoliteClient | None = None, timeout_s: int = 240) -> list[dict]:
    """Start an actor synchronously and return its dataset items. Raises SpendGuard / ApifyUnavailable."""
    tok = token()
    est = max_items / 1000.0 * actor.price_per_1k
    check_budget(db, est, source)
    http = client or PoliteClient(timeout=timeout_s + 60, min_delay=0.0, max_delay=0.1, max_retries=1)
    url = f"{API}/acts/{actor.id.replace('/', '~')}/run-sync-get-dataset-items"
    params = {"timeout": timeout_s, "maxItems": max_items, "maxTotalChargeUsd": round(max(est, 0.01), 4), "clean": "true"}
    try:
        resp = http.post(url, params=params, json=run_input, headers={"Authorization": f"Bearer {tok}"})
    except Blocked:
        raise
    items = resp.json()
    if not isinstance(items, list):
        raise FetchError(f"apify: unexpected response for {actor.id}: {str(items)[:200]}")
    cost = len(items) / 1000.0 * actor.price_per_1k
    db.execute("INSERT INTO spend_ledger (at, vendor, kind, units, usd, note) VALUES (?,?,?,?,?,?)",
               (now(), VENDOR, actor.id, float(len(items)), cost, f"source:{source}"))
    return items
