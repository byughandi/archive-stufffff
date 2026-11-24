"""Grailed via its public Algolia search index.

STATUS: mock-tested only. www.grailed.com is hard-blocked (Cloudflare) from the build machine,
so credential discovery and the live hit shape could not be verified here. The first live run
has to happen in CI; see docs/RUNBOOK.md. Everything below is therefore written tolerantly:
credentials and index names are discovered at run time, hit fields are read with several
fallback names, and nothing is hardcoded except the last-resort index names (clearly marked).

Ladder
  rung 1 `direct`: Algolia search-only key found via env / kv cache / the Grailed page
  rung 3 `apify` : an Apify Grailed actor, narrow incremental searches, budget-guarded
A blocked rung is parked for 6 h (kv) so we do not knock on the same door every 10 minutes.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

from core.db import Database, now
from core.models import Listing, Seller, SoldComp, known_ids, upsert_comps, upsert_listings
from scrapers import apify
from scrapers.common import Ctx, RunResult
from scrapers.common.http import Blocked, Parked, FetchError, NotFound, PoliteClient
from scrapers.common.ladder import block, interval_due, mark, on_cooldown
from scrapers.common.queries import Query, mark_run

SOURCE = "grailed"
SITE = "https://www.grailed.com"
KV_KEY = "grailed_algolia"
MAX_PAGES = 3
DEEP_PAGES = 10
HITS = 48
# Apify fallback sizing. The actor costs $0.003 per listing, so volumes are small on purpose: roughly
# $0.55 a month of live listings and $2.20 a month of sold comps inside the $2.75 Grailed budget.
APIFY_QUERIES = int(os.environ.get("APIFY_GRAILED_QUERIES", 1))
APIFY_MAX_ITEMS = int(os.environ.get("APIFY_GRAILED_ITEMS", 6))
APIFY_MIN_INTERVAL = 24 * 3600
APIFY_COMP_QUERIES = int(os.environ.get("APIFY_GRAILED_COMP_QUERIES", 2))
APIFY_COMP_ITEMS = int(os.environ.get("APIFY_GRAILED_COMP_ITEMS", 12))
APIFY_COMP_MIN_INTERVAL = 22 * 3600

# LAST-RESORT DEFAULTS ONLY: reported (not verified) by Apify actor READMEs. Discovery wins.
DEFAULT_INDICES = {"live": "Listing_production", "by_date": "Listing_by_date_production",
                   "sold": "Listing_sold_production"}


class CredsError(FetchError):
    """Could not obtain Algolia credentials."""


@dataclass
class Creds:
    app_id: str
    api_key: str
    indices: dict[str, str] = field(default_factory=dict)   # live | by_date | sold
    origin: str = "unknown"                                  # env | kv | page

    def dump(self) -> str:
        return json.dumps({"app_id": self.app_id, "api_key": self.api_key, "indices": self.indices,
                           "saved_at": now()})


# ---- credential discovery --------------------------------------------------------------------
_APP_PATTERNS = [
    r"""ALGOLIA[_A-Z]*APP(?:LICATION)?[_A-Z]*ID["']?\s*[:=]\s*["']([A-Za-z0-9]{8,14})["']""",
    r"""["'][A-Za-z_]*algolia[A-Za-z_]*app[A-Za-z_]*id["']\s*:\s*["']([A-Za-z0-9]{8,14})["']""",
    r"""x-algolia-application-id["'=:\s]+([A-Za-z0-9]{8,14})""",
    r"""\b([A-Za-z0-9]{8,14})-dsn\.algolia\.net""",
    r"""\b([A-Za-z0-9]{8,14})\.algolia\.net""",
]
_KEY_PATTERNS = [
    r"""ALGOLIA[_A-Z]*(?:SEARCH)?[_A-Z]*KEY["']?\s*[:=]\s*["']([A-Za-z0-9=+/_\-]{20,})["']""",
    r"""["'][A-Za-z_]*algolia[A-Za-z_]*key["']\s*:\s*["']([A-Za-z0-9=+/_\-]{20,})["']""",
    r"""x-algolia-api-key["'=:\s]+([A-Za-z0-9=+/_\-]{20,})""",
]
_INDEX_PATTERN = r"""["']((?:Listing|listing)[A-Za-z0-9_]*)["']"""


def extract_credentials(text: str) -> tuple[str | None, str | None, list[str]]:
    """Tolerant extraction of (app id, search key, index names) from HTML / JSON / JS text."""
    def first(patterns: list[str]) -> str | None:
        for p in patterns:
            m = re.search(p, text, re.I if "ALGOLIA" not in p else 0)
            if m:
                return m.group(1)
        return None

    app, key = first(_APP_PATTERNS), first(_KEY_PATTERNS)
    names = list(dict.fromkeys(re.findall(_INDEX_PATTERN, text)))
    return app, key, [n for n in names if "_" in n]


def classify_indices(names: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in names:
        low = n.lower()
        if "sold" in low:
            out.setdefault("sold", n)
        elif "date" in low or "recent" in low or "new" in low:
            out.setdefault("by_date", n)
        elif "heat" in low or "price" in low or "bump" in low:
            continue
        else:
            out.setdefault("live", n)
    return out


def _script_urls(html: str) -> list[str]:
    srcs = re.findall(r"""<script[^>]+src=["']([^"']+\.js[^"']*)["']""", html)
    srcs = [s if s.startswith("http") else (SITE + s if s.startswith("/") else f"{SITE}/{s}") for s in srcs]
    srcs = [s for s in srcs if "grailed" in urlsplit(s).netloc or "cloudfront" in s or "_next" in s]
    return sorted(dict.fromkeys(srcs), key=lambda s: ("main" not in s and "app" not in s, s))[:6]


class Grailed:
    def __init__(self, ctx: Ctx, client: PoliteClient | None = None):
        self.ctx = ctx
        self.http = client or PoliteClient(
            min_delay=1.0, max_delay=2.5, on_response=lambda r: ctx.rawlog(
                str(r.url), r.status_code, r.text if len(r.text) < 400_000 else f"<{len(r.text)} bytes>"))
        self.creds: Creds | None = None
        self._rediscovered = False

    # -- credentials --
    def _from_env(self) -> Creds | None:
        app, key = os.environ.get("GRAILED_ALGOLIA_APP_ID"), os.environ.get("GRAILED_ALGOLIA_KEY")
        if not (app and key):
            return None
        kv = self._kv()
        return Creds(app, key, (kv.indices if kv and kv.app_id == app else {}), "env")

    def _kv(self) -> Creds | None:
        raw = self.ctx.db.kv_get(KV_KEY)
        if not raw:
            return None
        try:
            d = json.loads(raw)
            return Creds(d["app_id"], d["api_key"], d.get("indices") or {}, "kv")
        except (ValueError, KeyError):
            return None

    def discover(self) -> Creds:
        """Fetch a Grailed page and read app id, search key and index names out of it."""
        html = self.http.get(SITE + "/").text
        app, key, names = extract_credentials(html)
        if not (app and key):
            for js in _script_urls(html):
                try:
                    text = self.http.get(js).text
                except (NotFound, FetchError):
                    continue
                a, k, n = extract_credentials(text)
                app, key, names = app or a, key or k, names + n
                if app and key:
                    break
        if not (app and key):
            raise CredsError("could not find Algolia app id / search key in the Grailed page or its bundles")
        creds = Creds(app, key, classify_indices(names), "page")
        return creds

    def get_creds(self, force: bool = False) -> Creds:
        if not force:
            if self.creds:
                return self.creds
            c = self._from_env() or self._kv()
            if c:
                self.creds = c
                return c
        c = self._from_env() if (force and self._from_env()) else None
        self.creds = c or self.discover()
        return self.creds

    def _save(self) -> None:
        if self.creds and not self.ctx.dry_run:
            self.ctx.db.kv_set(KV_KEY, self.creds.dump())

    # -- algolia --
    def _post(self, path: str, body: dict) -> dict:
        c = self.get_creds()
        url = f"https://{c.app_id.lower()}-dsn.algolia.net{path}"
        headers = {"x-algolia-application-id": c.app_id, "x-algolia-api-key": c.api_key,
                   "Referer": SITE + "/", "Origin": SITE, "Accept": "application/json"}
        try:
            return self.http.post(url, json=body, headers=headers).json()
        except Blocked as e:
            if e.status == 403 and not self._rediscovered:      # stale/rotated key: re-discover once
                self._rediscovered = True
                self.creds = None
                self.get_creds(force=True)
                self._save()
                return self._post(path, body)
            raise

    def resolve_indices(self) -> dict[str, str]:
        c = self.get_creds()
        have = dict(c.indices)
        for k, default in DEFAULT_INDICES.items():     # last resort, then verify by probing
            have.setdefault(k, default)
        ok: dict[str, str] = {}
        for k, name in have.items():
            try:
                self._query(name, "", 0, 0)
                ok[k] = name
            except NotFound:
                continue
        c.indices = ok
        self._save()
        if "by_date" not in ok and "live" not in ok:
            raise CredsError(f"no usable Grailed index found (tried {sorted(have.values())})")
        return ok

    def _query(self, index: str, text: str, page: int, hits: int = HITS) -> dict:
        params = f"query={quote(text)}&hitsPerPage={hits}&page={page}"
        body = {"requests": [{"indexName": index, "params": params}]}
        data = self._post("/1/indexes/*/queries", body)
        results = data.get("results") or []
        if not results:
            raise FetchError(f"grailed: unexpected Algolia response: {str(data)[:200]}")
        r = results[0]
        if "message" in r and "hits" not in r:
            if "not exist" in str(r["message"]).lower() or r.get("status") == 404:
                raise NotFound(r["message"])
            raise FetchError(f"grailed algolia: {r['message']}")
        return r

    # -- public API --
    def scrape(self, queries: list[Query]) -> RunResult:
        res = RunResult(SOURCE, "scrape", rung="direct")
        idx = self.resolve_indices()
        index = idx.get("by_date") or idx["live"]
        pages = DEEP_PAGES if self.ctx.deep else MAX_PAGES
        for q in queries:
            collected: dict[str, Listing] = {}
            new_count, top = 0, None
            for page in range(pages):
                r = self._query(index, q.text, page)
                ls = [l for l in (listing_from_hit(h, self.ctx.fx, q.query_id) for h in r.get("hits", [])) if l]
                if not ls:
                    break
                top = top or ls[0].source_id
                known = known_ids(self.ctx.db, SOURCE, [l.source_id for l in ls])
                fresh = [l for l in ls if l.source_id not in known and l.id not in collected]
                collected.update({l.id: l for l in ls})
                new_count += len(fresh)
                if not fresh or page + 1 >= int(r.get("nbPages") or 1):
                    break
            res.queries += 1
            res.seen += len(collected)
            if self.ctx.dry_run:
                res.skipped_dry += new_count
                continue
            stats = upsert_listings(self.ctx.db, collected.values())
            res.inserted += stats.inserted
            res.updated += stats.price_changed + stats.status_changed
            mark_run(self.ctx.db, SOURCE, q, top, hits=len(collected), kept=stats.inserted)
        self._save()
        res.requests = sum(self.http.requests.values())
        return res

    def comps(self, queries: list[Query]) -> RunResult:
        res = RunResult(SOURCE, "comps", rung="direct")
        idx = self.resolve_indices()
        if "sold" not in idx:
            raise CredsError("no sold index found")
        for q in queries:
            r = self._query(idx["sold"], q.text, 0)
            comps = [c for c in (comp_from_hit(h, self.ctx.fx) for h in r.get("hits", [])) if c]
            res.queries += 1
            res.seen += len(comps)
            if self.ctx.dry_run:
                res.skipped_dry += len(comps)
                continue
            res.comps += upsert_comps(self.ctx.db, comps)
            mark_run(self.ctx.db, f"{SOURCE}:comps", q, hits=len(comps))
        self._save()
        res.requests = sum(self.http.requests.values())
        return res

    def recheck(self, ids: list[str]) -> RunResult:
        """Look up tracked listings by objectID: still live (price?), moved to the sold index, or gone."""
        res = RunResult(SOURCE, "recheck", rung="direct")
        idx = self.resolve_indices()
        live = idx.get("live") or idx["by_date"]
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            data = self._post("/1/indexes/*/objects", {"requests": [{"indexName": live, "objectID": s} for s in chunk]})
            found = {str(h.get("objectID")): h for h in data.get("results", []) if h}
            sold_found: dict[str, dict] = {}
            missing = [s for s in chunk if s not in found]
            if missing and "sold" in idx:
                d2 = self._post("/1/indexes/*/objects", {"requests": [{"indexName": idx["sold"], "objectID": s} for s in missing]})
                sold_found = {str(h.get("objectID")): h for h in d2.get("results", []) if h}
            for sid in chunk:
                old = self.ctx.db.one("SELECT price, price_usd, currency, title, status, url FROM listings WHERE id = ?", (f"{SOURCE}:{sid}",))
                if old is None:
                    continue
                res.seen += 1
                if sid in found:
                    l = listing_from_hit(found[sid], self.ctx.fx)
                elif sid in sold_found:
                    l = listing_from_hit(sold_found[sid], self.ctx.fx)
                    if l:
                        l.status = "sold"
                else:
                    l = None
                if l is None:
                    l = Listing(SOURCE, sid, old["url"], old["title"], old["price"], old["currency"], old["price_usd"],
                                status="removed")
                if self.ctx.dry_run:
                    res.skipped_dry += int(l.status != old["status"] or abs(l.price - old["price"]) > 1e-6)
                    continue
                stats = upsert_listings(self.ctx.db, [l])
                res.updated += stats.price_changed + stats.status_changed
                mark_run(self.ctx.db, "recheck:grailed", f"{SOURCE}:{sid}")
        res.requests = sum(self.http.requests.values())
        return res


# ---- hit mapping (tolerant: field names are from memory, verify against a real hit in CI) --------

def _g(d: dict, *names, default=None):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return default


def _epoch(v) -> int | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def seller_from_hit(hit: dict) -> Seller | None:
    u = _g(hit, "seller", "user", default={}) or {}
    if not isinstance(u, dict):
        return None
    uid = _g(u, "id", "objectID", "user_id") or _g(hit, "seller_id", "user_id")
    uname = _g(u, "username", "name") or _g(hit, "seller_username")
    if not (uid or uname):
        return None
    sc = _g(u, "seller_score", "score", default={})
    sc = sc if isinstance(sc, dict) else {}
    rating = _num(_g(sc, "rating_average", "average", "rating") or _g(u, "rating_average", "rating"))
    return Seller(SOURCE, str(uid or uname), username=uname, rating=rating,
                  review_count=_g(sc, "rating_count", "feedback_count", "count") or _g(u, "rating_count", "feedback_count", "reviews_count"),
                  sales_count=_g(sc, "sold_count", "sales_count") or _g(u, "sold_count", "sales_count", "total_sales"),
                  joined_at=_epoch(_g(u, "created_at", "joined_at")))


def _photos(hit: dict) -> list[str]:
    out = []
    cp = _g(hit, "cover_photo", "image", "main_image")
    if isinstance(cp, dict):
        cp = _g(cp, "url", "image_url", "src")
    if isinstance(cp, str):
        out.append(cp)
    for p in _g(hit, "photos", "images", default=[]) or []:
        u = _g(p, "url", "image_url", "src") if isinstance(p, dict) else p
        if isinstance(u, str) and u not in out:
            out.append(u)
    return out[:4]


def _designers(hit: dict) -> str | None:
    d = _g(hit, "designers", "designer_names", "designer")
    if isinstance(d, list):
        return " x ".join(str(_g(x, "name") if isinstance(x, dict) else x) for x in d) or None
    return str(d) if d else None


def listing_from_hit(hit: dict, fx, query_id: str | None = None) -> Listing | None:
    sid = _g(hit, "objectID", "id", "listing_id")
    price = _num(_g(hit, "price", "price_i", "current_price"))
    if sid is None or price is None:
        return None
    sid = str(sid)
    cur = str(_g(hit, "currency", "price_currency", default="USD")).upper()
    photos = _photos(hit)
    sold = bool(hit.get("sold")) or _num(hit.get("sold_price")) is not None
    ship = _g(hit, "shipping", default={})
    ship_amt = None
    if isinstance(ship, dict):
        us = _g(ship, "us", "US", default={})
        ship_amt = _num(_g(us, "amount") if isinstance(us, dict) else None)
    sold_price = _num(hit.get("sold_price"))
    return Listing(
        source=SOURCE, source_id=sid, url=f"{SITE}/listings/{sid}", title=str(_g(hit, "title", "name", default="")),
        price=price, currency=cur, price_usd=fx.to_usd(price, cur), region="US", lang="en",
        description=_g(hit, "description"), brand_raw=_designers(hit),
        category_raw=str(_g(hit, "category_path", "category", default="")) or None,
        size_raw=_g(hit, "size", "sizes"), condition_raw=_g(hit, "condition"),
        shipping_usd=ship_amt, seller=seller_from_hit(hit), image_url=photos[0] if photos else None, image_urls=photos,
        status="sold" if sold else "active",
        listed_at=_epoch(_g(hit, "created_at_i", "created_at")),
        sold_at=_epoch(_g(hit, "sold_at_i", "sold_at")) if sold else None,
        sold_price_usd=fx.to_usd(sold_price, cur) if sold_price is not None else None,
        query_id=query_id,
    )


def comp_from_hit(hit: dict, fx) -> SoldComp | None:
    sid = _g(hit, "objectID", "id", "listing_id")
    price = _num(_g(hit, "sold_price", "price"))
    at = _epoch(_g(hit, "sold_at_i", "sold_at", "updated_at_i"))
    if sid is None or not price or at is None:
        return None
    cur = str(_g(hit, "currency", default="USD")).upper()
    photos = _photos(hit)
    return SoldComp(SOURCE, str(sid), str(_g(hit, "title", "name", default="")), fx.to_usd(price, cur), at,
                    url=f"{SITE}/listings/{sid}", image_url=photos[0] if photos else None, brand_raw=_designers(hit),
                    size_raw=_g(hit, "size"), condition_raw=_g(hit, "condition"), description=_g(hit, "description"))


# ---- Apify fallback (rung 3) -----------------------------------------------------------------------

def _iso(v) -> int | None:
    if not v:
        return None
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _actor_seller(item: dict) -> Seller | None:
    sl = item.get("seller") or {}
    if sl.get("id") is None:
        return None
    return Seller(SOURCE, str(sl["id"]), username=sl.get("username"),
                  rating=float(sl["ratingAverage"]) if sl.get("ratingAverage") is not None else None,
                  review_count=int(sl.get("ratingCount") or 0),
                  sales_count=int(sl["totalBoughtAndSold"]) if sl.get("totalBoughtAndSold") is not None else None)


def _apify_listing(item: dict, fx, query_id: str | None) -> Listing | None:
    """One dataset item of piotrv1001/grailed-listings-scraper -> Listing. Field names verified against real
    output: id, url, title, designer ("Dior × Hedi Slimane"), categoryPath, size, condition, price (USD),
    priceDrops (price history, newest last), sold, soldPrice, soldAt, createdAt, coverPhoto,
    shipping.us.amount, seller{id, username, ratingAverage, ratingCount, totalBoughtAndSold}."""
    if item.get("id") is None or not item.get("title") or item.get("price") in (None, 0):
        return None
    price = float(item["price"])
    ship = ((item.get("shipping") or {}).get("us") or {})
    sold = bool(item.get("sold"))
    l = Listing(
        source=SOURCE, source_id=str(item["id"]), url=item.get("url") or f"{SITE}/listings/{item['id']}",
        title=str(item["title"]), price=price, currency="USD", price_usd=price, region="US", lang="en",
        brand_raw=item.get("designer"), category_raw=item.get("categoryPath") or item.get("category"),
        size_raw=item.get("size"), condition_raw=item.get("condition"),
        shipping_usd=float(ship["amount"]) if ship.get("enabled") and ship.get("amount") is not None else None,
        seller=_actor_seller(item), image_url=item.get("coverPhoto"),
        image_urls=[item["coverPhoto"]] if item.get("coverPhoto") else [],
        status="sold" if sold else "active", listed_at=_iso(item.get("createdAt")),
        sold_at=_iso(item.get("soldAt")) if sold else None,
        sold_price_usd=float(item["soldPrice"]) if sold and item.get("soldPrice") else None, query_id=query_id)
    return l


def _apify_comp(item: dict) -> SoldComp | None:
    """A sold dataset item -> SoldComp. `soldPrice` is the final price; `price` is the last asking price."""
    at = _iso(item.get("soldAt"))
    price = item.get("soldPrice") or (item.get("price") if item.get("sold") else None)
    if item.get("id") is None or not price or at is None:
        return None
    return SoldComp(SOURCE, str(item["id"]), str(item.get("title") or ""), float(price), at,
                    url=item.get("url") or f"{SITE}/listings/{item['id']}", image_url=item.get("coverPhoto"),
                    brand_raw=item.get("designer"), size_raw=item.get("size"), condition_raw=item.get("condition"))


def run_apify(ctx: Ctx, queries: list[Query], client: PoliteClient | None = None) -> RunResult:
    """Live listings through the actor: one small run per query (the actor takes one search query per run)."""
    res = RunResult(SOURCE, "scrape", rung="apify")
    if not interval_due(ctx.db, "apify:grailed", int(os.environ.get("APIFY_GRAILED_INTERVAL_S", APIFY_MIN_INTERVAL))):
        raise apify.SpendGuard("apify fallback throttled (min interval between paid runs)")
    actor = apify.actor_for("GRAILED")
    ls: list[Listing] = []
    used: list[Query] = []
    for q in queries[:APIFY_QUERIES]:
        items = apify.run_actor(ctx.db, actor, apify.grailed_input(actor, q.text, APIFY_MAX_ITEMS),
                                max_items=APIFY_MAX_ITEMS, source="grailed", client=client)
        ctx.rawlog("apify:" + actor.id, 200, items)
        ls += [l for l in (_apify_listing(i, ctx.fx, q.query_id) for i in items) if l]
        used.append(q)
    mark(ctx.db, "apify:grailed")
    res.queries, res.seen = len(used), len(ls)
    if not ctx.dry_run:
        stats = upsert_listings(ctx.db, ls)
        res.inserted, res.updated = stats.inserted, stats.price_changed + stats.status_changed
        for q in used:
            mark_run(ctx.db, SOURCE, q)
    return res


def comps_apify(ctx: Ctx, queries: list[Query], client: PoliteClient | None = None) -> RunResult:
    """Sold listings through the actor (`soldOnly`): the pricing backbone when the direct sold index is
    unreachable. Throttled to about one batch a day and bounded by the Grailed Apify budget."""
    res = RunResult(SOURCE, "comps", rung="apify")
    if not interval_due(ctx.db, "apify:grailed_sold", int(os.environ.get("APIFY_GRAILED_COMP_INTERVAL_S", APIFY_COMP_MIN_INTERVAL))):
        res.note = "sold actor throttled (min interval)"
        return res
    actor = apify.actor_for("GRAILED")
    for q in queries[:APIFY_COMP_QUERIES]:
        items = apify.run_actor(ctx.db, actor, apify.grailed_input(actor, q.text, APIFY_COMP_ITEMS, sold=True),
                                max_items=APIFY_COMP_ITEMS, source="grailed", client=client)
        ctx.rawlog("apify:" + actor.id + ":sold", 200, items)
        comps = [c for c in (_apify_comp(i) for i in items) if c]
        res.queries += 1
        res.seen += len(comps)
        if ctx.dry_run:
            res.skipped_dry += len(comps)
            continue
        res.comps += upsert_comps(ctx.db, comps)
        mark_run(ctx.db, f"{SOURCE}:comps", q, hits=len(comps))
    mark(ctx.db, "apify:grailed_sold")
    return res


def comps(ctx: Ctx, queries: list[Query], client: PoliteClient | None = None, apify_client: PoliteClient | None = None) -> RunResult:
    """Sold comps ladder: the direct sold index first; if Grailed blocks it (or it cannot be found), the actor."""
    last: Exception | None = None
    if not on_cooldown(ctx.db, SOURCE, "direct"):
        try:
            return Grailed(ctx, client).comps(queries)
        except Blocked as e:
            block(ctx.db, SOURCE, "direct")
            last = e
        except (CredsError, FetchError) as e:
            last = e
    else:
        last = Parked("grailed direct rung parked for 6 h after a block")
    try:
        return comps_apify(ctx, queries, apify_client)
    except (apify.ApifyUnavailable, apify.SpendGuard) as e:
        raise last if isinstance(last, Blocked) else (last or e) from e


def run(ctx: Ctx, queries: list[Query], client: PoliteClient | None = None, apify_client: PoliteClient | None = None) -> RunResult:
    """Walk the ladder. Raises the last error (Blocked => counts toward the breaker) if every rung fails."""
    last: Exception | None = None
    if not on_cooldown(ctx.db, SOURCE, "direct"):
        g = Grailed(ctx, client)
        try:
            return g.scrape(queries)
        except Blocked as e:
            block(ctx.db, SOURCE, "direct")
            last = e
        except (CredsError, FetchError) as e:
            last = e
    else:
        last = Parked("grailed direct rung parked for 6 h after a block")
    try:
        return run_apify(ctx, queries, apify_client)
    except (apify.ApifyUnavailable, apify.SpendGuard) as e:
        raise last if isinstance(last, Blocked) else (last or e) from e
