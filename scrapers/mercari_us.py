"""Mercari US: the test ladder.

STATUS: mock-tested only. www.mercari.com answers the build machine with a Cloudflare managed
challenge ("Just a moment..." / 403), so neither rung could be run live.

Rung 1 `direct` : ONE honest attempt per run with a plain GET of the public search page. A 403 or
                  challenge page raises `Blocked`; we never try to solve or evade it. If a page
                  does come back we parse `__NEXT_DATA__` tolerantly; an unrecognised page is a
                  plain failure, not a block.
Rung 3 `apify`  : an Apify Mercari US actor, narrow incremental saved searches, budget-guarded
                  (per-source monthly cap + the global 90% guard in scrapers/apify.py).
The first healthy rung is used; `source_health.rung` records which (set by run.py from the result).
A blocked direct rung is parked for 6 h so the "single attempt" does not repeat every 20 minutes.

Sold tracking: the sold actor feeds `comps_sold` and also flips any known active listing to
`sold`, which is what sell-through comps need.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from core.models import Listing, Seller, SoldComp, known_ids, upsert_comps, upsert_listings
from scrapers import apify
from scrapers.common import Ctx, RunResult
from scrapers.common.http import Blocked, Parked, FetchError, PoliteClient, next_data
from scrapers.common.ladder import block, interval_due, mark, on_cooldown
from scrapers.common.queries import Query, mark_run

SOURCE = "mercari_us"
SITE = "https://www.mercari.com"
SEARCH = SITE + "/search/?keyword={q}&sortBy=2&status=on_sale"   # sortBy=2 = newest (unverified)
# Each actor run costs $0.04 per search plus $0.00275 per listing, so the $0.50 monthly budget buys about
# seven small runs: one search of 12 listings every four days.
APIFY_QUERIES = 1
APIFY_MAX_ITEMS = int(os.environ.get("APIFY_MERCARI_US_ITEMS", 12))
APIFY_MIN_INTERVAL = 96 * 3600
SOLD_MIN_INTERVAL = 14 * 24 * 3600
SOLD_MAX_ITEMS = 10


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _walk_items(o: Any, out: list[dict]) -> None:
    """Find dicts that look like Mercari items (id + name + price) anywhere in a JSON tree."""
    if isinstance(o, dict):
        if {"id", "name", "price"} <= o.keys() and isinstance(o.get("name"), str):
            out.append(o)
        else:
            for v in o.values():
                _walk_items(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_items(v, out)


def parse_search_html(html: str) -> list[dict]:
    nd = next_data(html)
    items: list[dict] = []
    if nd:
        _walk_items(nd, items)
    if not items:
        raise FetchError("mercari_us: search page returned no recognisable items (layout unknown)")
    return items


def _money(v: Any) -> float | None:
    """Mercari US prices appear as dollars or as cents (>= 10000 and integer for a $-priced item is ambiguous);
    actors usually return dollars. We take the number as dollars."""
    return _num(v)


def listing_from_item(it: dict, fx, query_id: str | None = None, sold: bool = False) -> Listing | None:
    # Actor items (getascraper/mercari-us-scraper) use listing_id / title / condition_id / category_path /
    # media.image_urls / seller_id / listing_status; the site's own JSON uses id / name / photos / seller{}.
    sid = it.get("listing_id") or it.get("id") or it.get("itemId")
    price = _money(it.get("price"))
    if not sid or price is None:
        return None
    sid = str(sid)
    status = str(it.get("listing_status") or it.get("status") or "").lower()
    is_sold = sold or status in ("sold_out", "sold", "trading")
    photos = ((it.get("media") or {}).get("image_urls") or it.get("photos") or it.get("images")
              or ([it["thumbnail"]] if it.get("thumbnail") else []))
    photos = [p.get("imageUrl") or p.get("url") if isinstance(p, dict) else p for p in photos]
    photos = [p for p in photos if p]
    seller = it.get("seller") or ({"id": it["seller_id"], "reviewCount": it.get("seller_review_count")} if it.get("seller_id") else {})
    brand = it.get("brand")
    brand = brand.get("name") if isinstance(brand, dict) else brand
    size = it.get("size")
    size = size.get("name") if isinstance(size, dict) else size
    cond = it.get("condition_id") or it.get("itemCondition") or it.get("condition")
    cond = cond.get("name") if isinstance(cond, dict) else cond
    return Listing(
        source=SOURCE, source_id=sid, url=it.get("url") or f"{SITE}/us/item/{sid}/", title=it.get("title") or it.get("name") or "",
        price=price, currency="USD", price_usd=price, region="US", lang="en", description=it.get("description"),
        brand_raw=brand, size_raw=size, condition_raw=cond,
        category_raw=" > ".join(it["category_path"]) if isinstance(it.get("category_path"), list) else None,
        seller=Seller(SOURCE, str(seller.get("id") or seller.get("name")), username=seller.get("name"),
                      rating=_num(seller.get("rating") or seller.get("averageRating")),
                      review_count=seller.get("reviewCount") or seller.get("numRatings")) if seller else None,
        image_url=photos[0] if photos else None, image_urls=photos[:4],
        status="sold" if is_sold else "active", listed_at=_ts(it.get("created") or it.get("createdAt")),
        sold_at=_ts(it.get("updated") or it.get("updatedAt")) if is_sold else None,
        sold_price_usd=price if is_sold else None, query_id=query_id,
    )


def _ts(v: Any) -> int | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def direct_attempt(ctx: Ctx, queries: list[Query], client: PoliteClient | None = None) -> RunResult:
    """Rung 1: exactly one request. Blocked => parked by the caller."""
    http = client or PoliteClient(on_response=lambda r: ctx.rawlog(str(r.url), r.status_code, r.text[:20000]))
    q = queries[0]
    html = http.get(SEARCH.format(q=quote(q.text))).text
    items = parse_search_html(html)
    ls = [l for l in (listing_from_item(i, ctx.fx, q.query_id) for i in items) if l]
    res = RunResult(SOURCE, "scrape", rung="direct", queries=1, seen=len(ls), requests=1)
    if not ctx.dry_run:
        stats = upsert_listings(ctx.db, ls)
        res.inserted, res.updated = stats.inserted, stats.price_changed + stats.status_changed
        mark_run(ctx.db, SOURCE, q, ls[0].source_id if ls else None, hits=len(ls), kept=stats.inserted)
    return res


def apify_scrape(ctx: Ctx, queries: list[Query], client: PoliteClient | None = None) -> RunResult:
    if not interval_due(ctx.db, "apify:mercari_us", int(os.environ.get("APIFY_MERCARI_US_INTERVAL_S", APIFY_MIN_INTERVAL))):
        raise apify.SpendGuard("apify fallback throttled (min interval between paid runs)")
    actor = apify.actor_for("MERCARI_US")
    qs = queries[:APIFY_QUERIES]
    ls: list[Listing] = []
    for q in qs:
        items = apify.run_actor(ctx.db, actor, apify.mercari_us_input(actor, q.text, APIFY_MAX_ITEMS),
                                max_items=APIFY_MAX_ITEMS, source="mercari_us", client=client,
                                fixed_usd=apify.MERCARI_US_SEARCH_FEE)
        ctx.rawlog("apify:" + actor.id, 200, items)
        ls += [l for l in (listing_from_item(i, ctx.fx, q.query_id) for i in items) if l]
    mark(ctx.db, "apify:mercari_us")
    res = RunResult(SOURCE, "scrape", rung="apify", queries=len(qs), seen=len(ls))
    if not ctx.dry_run:
        stats = upsert_listings(ctx.db, ls)
        res.inserted, res.updated = stats.inserted, stats.price_changed + stats.status_changed
        for q in qs:
            mark_run(ctx.db, SOURCE, q)
    return res


def run(ctx: Ctx, queries: list[Query], client: PoliteClient | None = None, apify_client: PoliteClient | None = None) -> RunResult:
    """Pick the first healthy rung. Raises the last error when none works (Blocked counts toward the breaker)."""
    last: Exception | None = None
    if not queries:
        return RunResult(SOURCE, "scrape", note="no queries")
    if not on_cooldown(ctx.db, SOURCE, "direct"):
        try:
            return direct_attempt(ctx, queries, client)
        except Blocked as e:
            block(ctx.db, SOURCE, "direct")
            last = e
        except FetchError as e:
            last = e
    else:
        last = Parked("mercari_us direct rung parked for 6 h after a block")
    try:
        return apify_scrape(ctx, queries, apify_client)
    except (apify.ApifyUnavailable, apify.SpendGuard) as e:
        raise last if last is not None else e


def comps(ctx: Ctx, queries: list[Query], apify_client: PoliteClient | None = None) -> RunResult:
    """Sold items via the sold actor: `comps_sold` rows, and known active listings flip to sold."""
    res = RunResult(SOURCE, "comps", rung="apify")
    if not interval_due(ctx.db, "apify:mercari_us_sold", int(os.environ.get("APIFY_MERCARI_US_SOLD_INTERVAL_S", SOLD_MIN_INTERVAL))):
        res.note = "sold actor throttled (min interval)"
        return res
    actor = apify.actor_for("MERCARI_US_SOLD")
    qs = queries[:1]
    items = apify.run_actor(ctx.db, actor, apify.mercari_us_input(actor, qs[0].text, SOLD_MAX_ITEMS, sold=True),
                            max_items=SOLD_MAX_ITEMS, source="mercari_us", client=apify_client,
                            fixed_usd=apify.MERCARI_US_SEARCH_FEE) if qs else []
    mark(ctx.db, "apify:mercari_us_sold")
    ctx.rawlog("apify:" + actor.id, 200, items)
    sold = [l for l in (listing_from_item(i, ctx.fx, sold=True) for i in items) if l]
    res.queries, res.seen = len(qs), len(sold)
    if ctx.dry_run:
        return res
    now_ts = __import__("time").time()
    comps_ = [SoldComp(SOURCE, l.source_id, l.title, l.price_usd, l.sold_at or int(now_ts), url=l.url,
                       image_url=l.image_url, brand_raw=l.brand_raw, size_raw=l.size_raw, condition_raw=l.condition_raw)
              for l in sold]
    res.comps = upsert_comps(ctx.db, comps_)
    known = known_ids(ctx.db, SOURCE, [l.source_id for l in sold])
    flips = [l for l in sold if l.source_id in known]       # tracked listings that have now sold
    if flips:
        st = upsert_listings(ctx.db, flips)
        res.updated = st.status_changed + st.price_changed
    return res
