"""Daily FX rates (currency units per 1 USD), cached in the `kv` table."""
from __future__ import annotations

import json
import logging

import httpx

from .config import settings
from .db import Database, now

log = logging.getLogger(__name__)
_KEY = "fx_rates"


class Fx:
    def __init__(self, per_usd: dict[str, float], fetched_at: int, fallback: bool):
        self.per_usd = per_usd
        self.fetched_at = fetched_at
        self.fallback = fallback

    def to_usd(self, amount: float, currency: str) -> float:
        cur = (currency or "USD").upper()
        if cur == "USD":
            return float(amount)
        rate = self.per_usd.get(cur)
        if not rate:
            raise KeyError(f"no FX rate for {cur}")
        return float(amount) / rate

    def from_usd(self, amount_usd: float, currency: str) -> float:
        cur = (currency or "USD").upper()
        return float(amount_usd) * (1.0 if cur == "USD" else self.per_usd[cur])


def load_fx(db: Database | None = None, client: httpx.Client | None = None) -> Fx:
    cfg = settings()["fx"]
    cached = None
    if db is not None:
        raw = db.kv_get(_KEY)
        if raw:
            cached = json.loads(raw)
            if now() - cached["fetched_at"] < cfg["refresh_hours"] * 3600:
                return Fx(cached["per_usd"], cached["fetched_at"], False)
    try:
        resp = (client or httpx).get(cfg["api_url"], timeout=15)
        resp.raise_for_status()
        rates = {k.upper(): float(v) for k, v in resp.json()["rates"].items()}
        rates["USD"] = 1.0
        if db is not None:
            db.kv_set(_KEY, json.dumps({"per_usd": rates, "fetched_at": now()}))
        return Fx(rates, now(), False)
    except Exception as e:  # network or shape problem: fall back, never crash a scrape over FX
        log.warning("fx fetch failed (%s); using %s", e, "cached rates" if cached else "static fallback")
        if cached:
            return Fx(cached["per_usd"], cached["fetched_at"], False)
        return Fx({k.upper(): float(v) for k, v in cfg["fallback_per_usd"].items()}, 0, True)
