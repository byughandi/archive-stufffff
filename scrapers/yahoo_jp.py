"""Yahoo! Auctions Japan: public search pages carry a `__NEXT_DATA__` JSON blob.

Verified live 2026-11-24 (build machine):
  open search   GET /search/search?p=<kw>&s1=new&o1=d&n=50   (301 -> /search/search/<kw>/0?...)
  closed search GET /closedsearch/closedsearch?p=<kw>&n=50&s1=end&o1=d
  item page     GET /jp/auction/<id>
Items live at props.pageProps.initialState.search.items.listing.items (search) and
...initialState.item.detail.item (item page).
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import quote, urlencode

from core.db import now
from core.models import Listing, Seller, SoldComp, known_ids, upsert_comps, upsert_listings
from scrapers.common import Ctx, RunResult
from scrapers.common.http import FetchError, NotFound, PoliteClient, next_data
from scrapers.common.queries import Query, anchor_terms, mark_run, mentions

SOURCE = "yahoo_jp"
BASE = "https://auctions.yahoo.co.jp"
ITEM_URL = BASE + "/jp/auction/{id}"
BUYEE_URL = "https://buyee.jp/item/yahoo/auction/{id}"   # redirects to /item/jdirectitems/auction/<id>
PAGE_SIZE = 50
MAX_PAGES = 2
DEEP_PAGES = 6


def _ts(s: Any) -> int | None:
    if not s:
        return None
    try:
        return int(dt.datetime.fromisoformat(str(s)).timestamp())
    except ValueError:
        return None


def _rating5(good_pct: Any) -> float | None:
    try:
        return round(float(str(good_pct).rstrip("%")) / 20.0, 2)   # "98.5%" -> 4.93
    except (TypeError, ValueError):
        return None


def search_items(html: str) -> list[dict]:
    nd = next_data(html)
    try:
        return nd["props"]["pageProps"]["initialState"]["search"]["items"]["listing"]["items"] or []
    except (TypeError, KeyError):
        raise FetchError("yahoo_jp: __NEXT_DATA__ search listing not found (page layout changed?)")


def listing_from_search(it: dict, fx, query_id: str | None = None) -> Listing | None:
    aid = it.get("auctionId")
    price = it.get("price")
    if not aid or price is None or it.get("isNoPrice"):
        return None
    buy_now = it.get("buyNowPrice")
    fixed = bool(it.get("isFixedPrice"))
    path = [p.get("name") for p in (it.get("categoryPath") or [])[1:] if p.get("name")]
    seller = it.get("seller") or {}
    ship = it.get("currentPriceShippingFee")
    img = it.get("imageUrl")
    left = it.get("leftTime")
    ended = isinstance(left, (int, float)) and left < 0
    return Listing(
        source=SOURCE, source_id=aid, url=ITEM_URL.format(id=aid), proxy_url=BUYEE_URL.format(id=aid),
        title=it.get("title") or "", price=float(price), currency="JPY", price_usd=fx.to_usd(price, "JPY"),
        region="JP", lang="ja", brand_raw=None, category_raw=" > ".join(path) or None,
        condition_raw=it.get("itemCondition"),
        shipping_usd=fx.to_usd(ship, "JPY") if isinstance(ship, (int, float)) else (0.0 if it.get("isFreeShipping") else None),
        seller=Seller(SOURCE, seller["userId"], rating=_rating5(seller.get("goodRating"))) if seller.get("userId") else None,
        image_url=img, image_urls=[img] if img else [],
        is_auction=not fixed, auction_end_at=_ts(it.get("endTime")), bids=it.get("bidCount"),
        buy_now_usd=fx.to_usd(buy_now, "JPY") if buy_now else None,
        status="ended" if ended else "active", listed_at=_ts(it.get("startTime")), query_id=query_id,
    )


def comp_from_closed(it: dict, fx) -> SoldComp | None:
    """Only auctions that actually sold: at least one bid (the closed search lists unsold ones too)."""
    aid, price = it.get("auctionId"), it.get("price")
    if not aid or not price or not (it.get("bidCount") or 0) > 0:
        return None
    return SoldComp(SOURCE, aid, it.get("title") or "", fx.to_usd(price, "JPY"), _ts(it.get("endTime")) or now(),
                    url=ITEM_URL.format(id=aid), image_url=it.get("imageUrl"), condition_raw=it.get("itemCondition"))


def listing_from_item_page(html: str, fx) -> Listing | None:
    """Item page -> Listing with description, bids, status. None if the page is not an item."""
    nd = next_data(html)
    try:
        it = nd["props"]["pageProps"]["initialState"]["item"]["detail"]["item"]
    except (TypeError, KeyError):
        return None
    if not it.get("auctionId"):
        return None
    aid, price = it["auctionId"], it.get("price") or 0
    bids = it.get("bids") or 0
    st = it.get("status")
    status = "active" if st == "open" else ("sold" if st == "closed" and bids > 0 else "ended")
    rating = ((it.get("seller") or {}).get("rating") or {})
    sid = (it.get("seller") or {}).get("aucUserId")
    imgs = [i.get("image") for i in it.get("img") or [] if i.get("image")]
    thumbs = [i.get("thumbnail") for i in it.get("img") or [] if i.get("thumbnail")]
    desc = it.get("description")
    desc = "\n".join(desc) if isinstance(desc, list) else (desc or None)
    cat = [p["name"] for p in ((it.get("category") or {}).get("path") or [])[1:] if p.get("name")]
    return Listing(
        source=SOURCE, source_id=aid, url=ITEM_URL.format(id=aid), proxy_url=BUYEE_URL.format(id=aid),
        title=it.get("title") or "", price=float(price), currency="JPY", price_usd=fx.to_usd(price, "JPY"),
        region="JP", lang="ja", description=desc, category_raw=" > ".join(cat) or None,
        brand_raw=" / ".join(p["name"] for p in ((it.get("brand") or {}).get("path") or [])) or None,
        condition_raw=it.get("conditionName"),
        seller=Seller(SOURCE, sid, rating=_rating5(rating.get("goodRating")), review_count=rating.get("summary")) if sid else None,
        image_url=(thumbs or imgs or [None])[0], image_urls=(imgs or thumbs)[:4],
        is_auction=True, auction_end_at=_ts(it.get("endTime")), bids=bids, status=status,
        listed_at=_ts(it.get("startTime")),
        sold_at=_ts(it.get("endTime")) if status == "sold" else None,
        sold_price_usd=fx.to_usd(price, "JPY") if status == "sold" else None,
    )


def search_url(text: str, mode: str, page: int = 0) -> str:
    """mode: new | ending | closed."""
    params = {"p": text, "n": PAGE_SIZE, "b": 1 + page * PAGE_SIZE}
    if mode == "new":
        params |= {"s1": "new", "o1": "d"}
        return f"{BASE}/search/search?{urlencode(params, quote_via=quote)}"
    if mode == "ending":
        params |= {"s1": "end", "o1": "a"}
        return f"{BASE}/search/search?{urlencode(params, quote_via=quote)}"
    params |= {"s1": "end", "o1": "d"}
    return f"{BASE}/closedsearch/closedsearch?{urlencode(params, quote_via=quote)}"


class YahooJP:
    def __init__(self, ctx: Ctx, client: PoliteClient | None = None):
        self.ctx = ctx
        self.http = client or PoliteClient(on_response=lambda r: ctx.rawlog(str(r.url), r.status_code, r.text))

    def _fetch(self, url: str) -> str:
        return self.http.get(url).text

    def scrape(self, queries: list[Query], modes: tuple[str, ...] = ("new", "ending")) -> RunResult:
        res = RunResult(SOURCE, "scrape", rung="direct")
        for q in queries:
            collected: dict[str, Listing] = {}
            new_count, top = 0, None
            terms = anchor_terms(q)      # Yahoo pads results with loose matches; keep ones that name the brand
            for mode in modes:
                pages = (DEEP_PAGES if self.ctx.deep else MAX_PAGES) if mode == "new" else 1
                for page in range(pages):
                    items = search_items(self._fetch(search_url(q.text, mode, page)))
                    ls = [l for l in (listing_from_search(i, self.ctx.fx, q.query_id) for i in items)
                          if l and mentions(f"{l.title} {l.category_raw or ''}", terms)]
                    if not items:
                        break
                    if mode == "new" and ls:
                        top = top or ls[0].source_id
                    known = known_ids(self.ctx.db, SOURCE, [l.source_id for l in ls])
                    fresh = [l for l in ls if l.source_id not in known and l.id not in collected]
                    collected.update({l.id: l for l in ls})
                    new_count += len(fresh)
                    if mode == "new" and (not fresh or len(items) < PAGE_SIZE):
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
        res.requests = sum(self.http.requests.values())
        return res

    def comps(self, queries: list[Query]) -> RunResult:
        res = RunResult(SOURCE, "comps", rung="direct")
        for q in queries:
            items = search_items(self._fetch(search_url(q.text, "closed")))
            terms = anchor_terms(q)
            comps = [c for c in (comp_from_closed(i, self.ctx.fx) for i in items)
                     if c and mentions(c.title, terms)]
            res.queries += 1
            res.seen += len(items)
            if self.ctx.dry_run:
                res.skipped_dry += len(comps)
                continue
            res.comps += upsert_comps(self.ctx.db, comps)
            mark_run(self.ctx.db, f"{SOURCE}:comps", q, hits=len(comps))
        res.requests = sum(self.http.requests.values())
        return res

    def recheck(self, ids: list[str]) -> RunResult:
        res = RunResult(SOURCE, "recheck", rung="direct")
        for aid in ids:
            old = self.ctx.db.one("SELECT price, price_usd, currency, title, status, description FROM listings WHERE id = ?",
                                  (f"{SOURCE}:{aid}",))
            if old is None:
                continue
            try:
                l = listing_from_item_page(self._fetch(ITEM_URL.format(id=aid)), self.ctx.fx)
            except NotFound:
                l = None
            if l is None:
                l = Listing(SOURCE, aid, ITEM_URL.format(id=aid), old["title"], old["price"], old["currency"],
                            old["price_usd"], region="JP", lang="ja", status="removed",
                            proxy_url=BUYEE_URL.format(id=aid), is_auction=True)
            res.seen += 1
            if self.ctx.dry_run:
                res.skipped_dry += int(l.status != old["status"] or abs(l.price - old["price"]) > 1e-6)
                continue
            stats = upsert_listings(self.ctx.db, [l])
            res.updated += stats.price_changed + stats.status_changed
            if l.description and not old.get("description"):
                self.ctx.db.execute("UPDATE listings SET description = ? WHERE id = ? AND description IS NULL",
                                    (l.description[:4000], l.id))
            mark_run(self.ctx.db, f"recheck:{SOURCE}", f"{SOURCE}:{aid}")
        res.requests = sum(self.http.requests.values())
        return res
