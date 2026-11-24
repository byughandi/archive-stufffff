import asyncio
import json

import httpx

from core.models import known_ids
from scrapers.common.queries import Query
from scrapers.mercari_jp import (MercariJP, comp_from_search, listing_from_item, listing_from_search,
                                 urls_for)
from tests.conftest import fixture_json

Q = Query("ja:test", "ディオールオム エディ期", "ja", "dior_homme")


def make(ctx, calls, item_status=200, enrich=0):
    onsale, sold, item = (fixture_json(n) for n in ("mercari_search_onsale.json", "mercari_search_sold.json", "mercari_item.json"))

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.path.endswith("entities:search"):
            body = json.loads(req.content)
            statuses = body["searchCondition"]["status"]
            data = sold if "STATUS_SOLD_OUT" in statuses else onsale
            return httpx.Response(200, json=data)
        if req.url.path.endswith("items/get"):
            if item_status == 404:
                return httpx.Response(404, json={"result": "error"})
            return httpx.Response(200, json=item)
        return httpx.Response(500)

    async def nosleep(s):
        pass

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MercariJP(ctx, client=client, sleep=nosleep, enrich=enrich)


def run(coro):
    return asyncio.run(coro)


def test_parse_search_fixture(fx):
    raw = fixture_json("mercari_search_onsale.json")["items"]
    ls = [listing_from_search(r, fx, "q") for r in raw]
    assert all(ls)
    l = ls[0]
    assert l.source == "mercari_jp" and l.currency == "JPY" and l.region == "JP" and l.lang == "ja"
    assert l.price == 70500 and abs(l.price_usd - 70500 / 150) < 1e-6
    assert l.proxy_url == "https://buyee.jp/mercari/item/m97415686496" and l.url.endswith("/item/m97415686496")
    assert any(x.brand_raw == "Dior Homme" for x in ls) and l.status == "active" and l.listed_at == 1795490591
    assert any(x.size_raw for x in ls)                       # sizes parsed where Mercari provides them
    assert any(x.is_auction for x in ls)                     # the auction block is mapped
    assert urls_for("2JZwrvBAzeL5yYT3S4ycg2")[0].endswith("/shops/product/{id}")


def test_parse_sold_comps(fx):
    raw = fixture_json("mercari_search_sold.json")["items"]
    comps = [comp_from_search(r, fx) for r in raw]
    assert all(comps) and comps[0].sold_price_usd > 0 and comps[0].sold_at > 1_700_000_000
    assert comp_from_search({**raw[0], "status": "ITEM_STATUS_ON_SALE"}, fx) is None


def test_item_detail_has_description_and_seller(fx):
    l = listing_from_item(fixture_json("mercari_item.json")["data"], fx)
    assert l.description and "ディオールオム" in l.description
    assert l.seller.review_count == 3390 and l.seller.sales_count == 2278 and 4.5 < l.seller.rating <= 5
    assert l.status == "active"


def test_incremental_stop_second_run_inserts_nothing(ctx):
    calls: list[str] = []
    s = make(ctx, calls)
    r1 = run(s.scrape([Q]))
    n_items = len(fixture_json("mercari_search_onsale.json")["items"])
    assert r1.inserted == n_items and r1.queries == 1
    first_calls = len(calls)
    assert first_calls == 2          # page 1 had new ids -> page 2 (same fixture) was all known -> stop
    r2 = run(make(ctx, calls).scrape([Q]))
    assert r2.inserted == 0
    assert len(calls) - first_calls == 1                        # known-only first page: no second page
    assert len(known_ids(ctx.db, "mercari_jp", ["m97415686496"])) == 1
    row = ctx.db.one("SELECT needs_score, proxy_url FROM listings WHERE id='mercari_jp:m97415686496'")
    assert row["needs_score"] == 1 and row["proxy_url"].startswith("https://buyee.jp/")


def test_dry_run_writes_nothing(ctx):
    ctx.dry_run = True
    r = run(make(ctx, []).scrape([Q]))
    assert r.inserted == 0 and r.skipped_dry > 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM listings") == 0


def test_comps_stored_once(ctx):
    r1 = run(make(ctx, []).comps([Q]))
    assert r1.comps == len(fixture_json("mercari_search_sold.json")["items"])
    assert run(make(ctx, []).comps([Q])).comps == 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM comps_sold WHERE classified = 0") == r1.comps


def test_enrichment_is_capped_per_run_and_adds_description(ctx):
    run(make(ctx, [], enrich=2).scrape([Q]))
    # the mock serves the same detail for every id: exactly `enrich` priciest new listings get a description
    assert ctx.db.scalar("SELECT COUNT(*) FROM listings WHERE description IS NOT NULL") == 2
    assert ctx.db.scalar("SELECT COUNT(*) FROM sellers WHERE sales_count = 2278") >= 1


def test_recheck_detects_removed_and_sold(ctx):
    run(make(ctx, []).scrape([Q]))
    sid = "m97415686496"
    r = run(make(ctx, [], item_status=404).recheck([sid]))
    assert r.updated == 1 and ctx.db.scalar("SELECT status FROM listings WHERE id=?", (f"mercari_jp:{sid}",)) == "removed"
    # a sold item and a changed price
    item = fixture_json("mercari_item.json")
    item["data"]["status"], item["data"]["price"] = "sold_out", 60000

    def handler(req):
        return httpx.Response(200, json=item)

    async def nosleep(s):
        pass

    c = MercariJP(ctx, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=nosleep)
    r = run(c.recheck([sid]))
    row = ctx.db.one("SELECT status, price, description FROM listings WHERE id=?", (f"mercari_jp:{sid}",))
    assert row["status"] == "sold" and row["price"] == 60000 and row["description"]
    assert ctx.db.scalar("SELECT COUNT(*) FROM listing_snapshots WHERE listing_id=?", (f"mercari_jp:{sid}",)) >= 1


def test_block_is_typed(ctx):
    from scrapers.common.http import Blocked
    import pytest

    async def nosleep(s):
        pass

    c = MercariJP(ctx, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403))), sleep=nosleep)
    with pytest.raises(Blocked):
        run(c.scrape([Q]))
