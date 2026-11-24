"""Mercari Japan via the `mercapi` library (signed requests to api.mercari.jp).

Verified live 2026-11-24 from the build machine: search (on sale / sold out), item detail.
We parse the raw JSON captured by a response hook (richer than mercapi's mapped classes: brand,
size, auction block) and use mercapi for request signing, paging tokens and the item endpoint.
"""
from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData

from core.db import now
from core.models import Listing, Seller, SoldComp, known_ids, upsert_comps, upsert_listings
from scrapers.common import Ctx, RunResult
from scrapers.common.http import Blocked, FetchError
from scrapers.common.queries import Query, mark_run

SOURCE = "mercari_jp"
ITEM_URL = "https://jp.mercari.com/item/{id}"
BUYEE_URL = "https://buyee.jp/mercari/item/{id}"
# Mercari Shops products have non-"m123" ids and their own URLs (Buyee form is from memory: unverified).
SHOP_URL = "https://jp.mercari.com/shops/product/{id}"
BUYEE_SHOP_URL = "https://buyee.jp/mercari/shops/product/{id}"


def is_shop_id(sid: str) -> bool:
    return not (sid.startswith("m") and sid[1:].isdigit())


def urls_for(sid: str) -> tuple[str, str]:
    return (SHOP_URL, BUYEE_SHOP_URL) if is_shop_id(sid) else (ITEM_URL, BUYEE_URL)
MAX_PAGES = 3
DEEP_PAGES = 8
SOLD_STATES = {"ITEM_STATUS_SOLD_OUT", "ITEM_STATUS_TRADING", "sold_out", "trading"}


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _iso(v: Any) -> int | None:
    if not v:
        return None
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def listing_from_search(raw: dict, ctx_fx, query_id: str | None = None) -> Listing | None:
    price = _int(raw.get("price"))
    if raw.get("isNoPrice") or not price:
        return None
    sid = str(raw["id"])
    url, proxy = urls_for(sid)
    status = "sold" if raw.get("status") in SOLD_STATES else "active"
    thumbs = list(raw.get("thumbnails") or [])
    brand = (raw.get("itemBrand") or {}).get("name")
    size = (raw.get("itemSize") or {}).get("name") or ", ".join(s.get("name", "") for s in raw.get("itemSizes") or []) or None
    auction = raw.get("auction") or None
    cond = raw.get("itemConditionId")
    created = _int(raw.get("created"))
    return Listing(
        source=SOURCE, source_id=sid, url=url.format(id=sid), proxy_url=proxy.format(id=sid),
        title=raw.get("name") or "", price=float(price), currency="JPY", price_usd=ctx_fx.to_usd(price, "JPY"),
        region="JP", lang="ja", brand_raw=brand, category_raw=str(raw.get("categoryId") or "") or None,
        size_raw=size or None, condition_raw=str(cond) if cond else None,
        seller=Seller(SOURCE, str(raw["sellerId"])) if raw.get("sellerId") else None,
        image_url=thumbs[0] if thumbs else None, image_urls=thumbs[:4],
        is_auction=bool(auction), auction_end_at=_iso(auction.get("bidDeadline")) if auction else None,
        bids=_int(auction.get("totalBid")) if auction else None,
        status=status, listed_at=created, sold_at=_int(raw.get("updated")) if status == "sold" else None,
        sold_price_usd=ctx_fx.to_usd(price, "JPY") if status == "sold" else None, query_id=query_id,
    )


def comp_from_search(raw: dict, fx) -> SoldComp | None:
    price = _int(raw.get("price"))
    if raw.get("isNoPrice") or not price or raw.get("status") not in SOLD_STATES:
        return None
    thumbs = raw.get("thumbnails") or []
    size = (raw.get("itemSize") or {}).get("name")
    return SoldComp(
        SOURCE, str(raw["id"]), raw.get("name") or "", fx.to_usd(price, "JPY"), _int(raw.get("updated")) or now(),
        url=urls_for(str(raw["id"]))[0].format(id=raw["id"]), image_url=thumbs[0] if thumbs else None,
        brand_raw=(raw.get("itemBrand") or {}).get("name"), size_raw=size,
        condition_raw=str(raw.get("itemConditionId") or "") or None,
    )


def seller_from_item(d: dict) -> Seller | None:
    s = d.get("seller") or {}
    if not s.get("id"):
        return None
    r = s.get("ratings") or {}
    good, normal, bad = (int(r.get(k) or 0) for k in ("good", "normal", "bad"))
    total = good + normal + bad
    return Seller(SOURCE, str(s["id"]), username=s.get("name"),
                  rating=round(5 * good / total, 2) if total else None,
                  review_count=_int(s.get("num_ratings")), sales_count=_int(s.get("num_sell_items")),
                  joined_at=_int(s.get("created")))


def listing_from_item(d: dict, fx, query_id: str | None = None) -> Listing:
    """Full detail record (`data` of /items/get) -> Listing, with description and seller stats."""
    sid = str(d["id"])
    raw_status = d.get("status")
    status = "active" if raw_status == "on_sale" else ("sold" if raw_status in SOLD_STATES else "removed")
    price = int(d.get("price") or 0)
    cond = (d.get("item_condition") or {}).get("id")
    cat = d.get("item_category_ntiers") or d.get("item_category") or {}
    thumbs = list(d.get("thumbnails") or [])
    photos = list(d.get("photos") or thumbs)
    auc = d.get("auction_info") or None
    return Listing(
        source=SOURCE, source_id=sid, url=ITEM_URL.format(id=sid), proxy_url=BUYEE_URL.format(id=sid),
        title=d.get("name") or "", price=float(price), currency="JPY", price_usd=fx.to_usd(price, "JPY"),
        region="JP", lang="ja", description=d.get("description") or None,
        category_raw=cat.get("name"), condition_raw=str(cond) if cond else None,
        seller=seller_from_item(d), image_url=(thumbs or photos or [None])[0], image_urls=(thumbs or photos)[:4],
        is_auction=bool(auc), status=status, listed_at=_int(d.get("created")),
        sold_at=_int(d.get("updated")) if status == "sold" else None,
        sold_price_usd=fx.to_usd(price, "JPY") if status == "sold" else None, query_id=query_id,
    )


def listing_from_product(b: dict, fx, query_id: str | None = None) -> Listing:
    """Mercari Shops product (`/v1/marketplaces/shops/products/<id>`) -> Listing."""
    sid = str(b["name"])
    d = b.get("productDetail") or {}
    price = _int(b.get("price")) or 0
    shop = d.get("shop") or {}
    stats = shop.get("shopStats") or {}
    variants = d.get("variants") or []
    sold = bool(variants) and all(v.get("soldOut") for v in variants)
    photos = [p.get("uri") if isinstance(p, dict) else p for p in d.get("photos") or []]
    photos = [p for p in photos if p]
    thumb = b.get("thumbnail")
    url, proxy = urls_for(sid)
    return Listing(
        source=SOURCE, source_id=sid, url=url.format(id=sid), proxy_url=proxy.format(id=sid),
        title=b.get("displayName") or "", price=float(price), currency="JPY", price_usd=fx.to_usd(price, "JPY"),
        region="JP", lang="ja", description=d.get("description") or None,
        brand_raw=(d.get("brand") or {}).get("displayName"),
        condition_raw=(d.get("condition") or {}).get("displayName"),
        seller=Seller(SOURCE, str(shop["name"]), username=shop.get("displayName"), rating=_f(stats.get("score")),
                      review_count=_int(stats.get("reviewCount"))) if shop.get("name") else None,
        image_url=thumb or (photos[0] if photos else None), image_urls=([thumb] if thumb else photos)[:4],
        status="sold" if sold else "active", listed_at=_iso(b.get("createTime")),
        sold_at=_iso(b.get("updateTime")) if sold else None,
        sold_price_usd=fx.to_usd(price, "JPY") if sold else None, query_id=query_id,
    )


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class MercariJP:
    def __init__(self, ctx: Ctx, client: httpx.AsyncClient | None = None,
                 sleep: Callable[[float], Any] = asyncio.sleep, rng: random.Random | None = None,
                 min_delay: float = 1.0, max_delay: float = 3.0, enrich: int | None = None):
        self.ctx = ctx
        self._sleep, self._rng = sleep, rng or random.Random()
        self.min_delay, self.max_delay = min_delay, max_delay
        self.enrich = int(os.environ.get("MERCARI_JP_ENRICH", "12")) if enrich is None else enrich   # detail calls per run
        self._enriched = 0
        self.requests = 0
        self._last_body: Any = None
        self._first = True
        self.client = client or httpx.AsyncClient(timeout=30)
        self.client.event_hooks.setdefault("response", []).append(self._hook)
        self.m = Mercapi(httpx_client=self.client)

    async def _hook(self, resp: httpx.Response) -> None:
        await resp.aread()
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:2000]
        self._last_body = body if resp.status_code == 200 else None
        self.ctx.rawlog(str(resp.request.url), resp.status_code, body)
        if resp.status_code in (403, 429):
            raise Blocked(f"{resp.status_code} {resp.request.url}", resp.status_code, str(resp.request.url))
        if resp.status_code >= 500:
            raise FetchError(f"{resp.status_code} {resp.request.url}", resp.status_code, str(resp.request.url))

    async def _pace(self) -> None:
        if not self._first:
            await self._sleep(self._rng.uniform(self.min_delay, self.max_delay))
        self._first = False
        self.requests += 1

    async def _retry(self, fn: Callable[[], Any], tries: int = 3):
        for i in range(tries):
            await self._pace()
            try:
                return await fn()
            except Blocked as e:
                if e.status == 429 and i < tries - 1:
                    await self._sleep(2 ** (i + 1) + self._rng.random())
                    continue
                raise
            except (FetchError, httpx.TransportError) as e:
                if i == tries - 1:
                    raise FetchError(f"mercari_jp: {e!r}") from e
                await self._sleep(2 ** (i + 1) + self._rng.random())

    async def _search(self, text: str, sold: bool, token: str | None = None) -> tuple[list[dict], str]:
        status = SearchRequestData.Status.STATUS_SOLD_OUT if sold else SearchRequestData.Status.STATUS_ON_SALE

        async def call():
            return await self.m.search(
                text, status=[status], sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
                sort_order=SearchRequestData.SortOrder.ORDER_DESC, page_token=token or None)

        await self._retry(call)
        body = self._last_body or {}
        return body.get("items", []), (body.get("meta") or {}).get("nextPageToken", "")

    async def _detail(self, sid: str) -> Listing | None:
        """Full record as a Listing; None when Mercari answers 404 (listing removed)."""
        shop = is_shop_id(sid)

        async def call():
            self._last_body = None
            try:
                return await (self.m.product(sid) if shop else self.m.item(sid))
            except Blocked:
                raise
            except (KeyError, TypeError, AttributeError, ValueError):
                if self._last_body:      # mercapi's own mapping drifted but the response itself was fine
                    return None
                raise

        await self._retry(call)
        body = self._last_body
        if not isinstance(body, dict):
            return None
        if shop:
            return listing_from_product(body, self.ctx.fx) if body.get("name") else None
        return listing_from_item(body["data"], self.ctx.fx) if isinstance(body.get("data"), dict) else None

    # ---- public API ----------------------------------------------------------------
    async def scrape(self, queries: list[Query]) -> RunResult:
        res = RunResult(SOURCE, "scrape", rung="library")
        pages = DEEP_PAGES if self.ctx.deep else MAX_PAGES
        for q in queries:
            collected: dict[str, Listing] = {}
            new_ids: list[str] = []
            top = None
            token: str | None = None
            for page in range(pages):
                raw_items, nxt = await self._search(q.text, False, token)
                token = nxt
                ls = [l for l in (listing_from_search(r, self.ctx.fx, q.query_id) for r in raw_items) if l]
                if not ls:
                    break
                top = top or ls[0].source_id
                known = known_ids(self.ctx.db, SOURCE, [l.source_id for l in ls])
                fresh = [l for l in ls if l.source_id not in known and l.id not in collected]
                collected.update({l.id: l for l in ls})
                new_ids += [l.source_id for l in fresh]
                if not fresh or not nxt:      # a page of only known ids: caught up
                    break
            res.queries += 1
            res.seen += len(collected)
            if not self.ctx.dry_run:
                await self._enrich([collected[f"{SOURCE}:{i}"] for i in new_ids if f"{SOURCE}:{i}" in collected])
                stats = upsert_listings(self.ctx.db, collected.values())
                res.inserted += stats.inserted
                res.updated += stats.price_changed + stats.status_changed
                mark_run(self.ctx.db, SOURCE, q, top, hits=len(collected), kept=stats.inserted)
            else:
                res.skipped_dry += len(new_ids)
        res.requests = self.requests
        return res

    async def _enrich(self, fresh: list[Listing]) -> None:
        """Detail call (description, seller stats) for the new listings most worth it: priciest first."""
        for l in sorted((x for x in fresh if x.price_usd >= 60), key=lambda x: -x.price_usd):
            if self._enriched >= self.enrich:
                return
            self._enriched += 1
            try:
                full = await self._detail(l.source_id)
            except (Blocked, FetchError):
                return
            if not full:
                continue
            l.description, l.seller = full.description, full.seller or l.seller
            if full.category_raw:
                l.category_raw = full.category_raw

    async def comps(self, queries: list[Query]) -> RunResult:
        res = RunResult(SOURCE, "comps", rung="library")
        for q in queries:
            raw_items, _ = await self._search(q.text, True)
            comps = [c for c in (comp_from_search(r, self.ctx.fx) for r in raw_items) if c]
            res.queries += 1
            res.seen += len(comps)
            if not self.ctx.dry_run:
                res.comps += upsert_comps(self.ctx.db, comps)
                mark_run(self.ctx.db, f"{SOURCE}:comps", q, hits=len(comps))
            else:
                res.skipped_dry += len(comps)
        res.requests = self.requests
        return res

    async def recheck(self, ids: list[str]) -> RunResult:
        """Re-fetch tracked listings: detect sold / removed / price change; keep description + seller fresh."""
        res = RunResult(SOURCE, "recheck", rung="library")
        for sid in ids:
            old = self.ctx.db.one("SELECT price, price_usd, currency, title, status, description FROM listings WHERE id = ?",
                                  (f"{SOURCE}:{sid}",))
            if old is None:
                continue
            l = await self._detail(sid)
            res.seen += 1
            if l is None:
                url, proxy = urls_for(sid)
                l = Listing(SOURCE, sid, url.format(id=sid), old["title"], old["price"], old["currency"],
                            old["price_usd"], region="JP", lang="ja", status="removed", proxy_url=proxy.format(id=sid))
            if self.ctx.dry_run:
                res.skipped_dry += int(l.status != old["status"] or abs(l.price - old["price"]) > 1e-6)
                continue
            stats = upsert_listings(self.ctx.db, [l])
            res.updated += stats.price_changed + stats.status_changed
            if l.description and not old.get("description"):
                self.ctx.db.execute("UPDATE listings SET description = ? WHERE id = ? AND description IS NULL",
                                    (l.description[:4000], l.id))
            mark_run(self.ctx.db, f"recheck:{SOURCE}", f"{SOURCE}:{sid}")
        res.requests = self.requests
        return res

    async def close(self) -> None:
        await self.client.aclose()


def run(ctx: Ctx, queries: list[Query]) -> RunResult:
    async def go():
        s = MercariJP(ctx)
        try:
            return await s.scrape(queries)
        finally:
            await s.close()
    return asyncio.run(go())


def run_comps(ctx: Ctx, queries: list[Query]) -> RunResult:
    async def go():
        s = MercariJP(ctx)
        try:
            return await s.comps(queries)
        finally:
            await s.close()
    return asyncio.run(go())


def run_recheck(ctx: Ctx, ids: list[str]) -> RunResult:
    async def go():
        s = MercariJP(ctx)
        try:
            return await s.recheck(ids)
        finally:
            await s.close()
    return asyncio.run(go())
