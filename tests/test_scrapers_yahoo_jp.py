import httpx
import pytest

from core.models import known_ids
from scrapers.common.http import FetchError
from scrapers.common.queries import Query
from scrapers.yahoo_jp import (YahooJP, comp_from_closed, listing_from_item_page, listing_from_search,
                               search_items, search_url)
from tests.conftest import fixture_text, polite

Q = Query("ja:test", "ディオールオム エディ期", "ja", "dior_homme")
OPEN, CLOSED = fixture_text("yahoo_search_open.html"), fixture_text("yahoo_search_closed.html")


def serve(open_html=OPEN, closed_html=CLOSED, item_html=None):
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if "closedsearch" in path:
            return httpx.Response(200, text=closed_html, headers={"content-type": "text/html"})
        if "/jp/auction/" in path:
            return httpx.Response(200, text=item_html or "", headers={"content-type": "text/html"})
        return httpx.Response(200, text=open_html, headers={"content-type": "text/html"})
    return handler


def test_parse_open_search(fx):
    items = search_items(OPEN)
    assert len(items) == 12
    ls = [listing_from_search(i, fx, "q") for i in items]
    l = ls[0]
    assert l.source == "yahoo_jp" and l.source_id == "l1253470528" and l.currency == "JPY"
    assert l.is_auction and l.bids == 3 and l.price == 330 and l.auction_end_at == 1795954214
    assert l.listed_at and l.proxy_url == "https://buyee.jp/item/yahoo/auction/l1253470528"
    assert l.seller.rating and 4.9 < l.seller.rating < 5.0 and l.condition_raw == "USED40"
    assert "ジーンズ" in l.category_raw and l.shipping_usd == 810 / 150
    bn = next(x for x in ls if x.buy_now_usd)
    assert bn.source_id == "e1253223917" and bn.buy_now_usd == 178000 / 150


def test_closed_comps_only_sold_auctions(fx):
    items = search_items(CLOSED)
    comps = [comp_from_closed(i, fx) for i in items]
    assert all(comps) and comps[0].sold_price_usd == 84701 / 150 and comps[0].sold_at > 1_700_000_000
    unsold = dict(items[0], bidCount=0)
    assert comp_from_closed(unsold, fx) is None


def test_item_page_parse(fx):
    l = listing_from_item_page(fixture_text("yahoo_item_open.html"), fx)
    assert l.source_id == "l1253470528" and l.status == "active" and l.bids == 3
    assert "ディオールオム" in l.description and l.seller.review_count == 376
    assert l.brand_raw and "Dior" in l.brand_raw
    closed = fixture_text("yahoo_item_open.html").replace('"status": "open"', '"status": "closed"')
    assert listing_from_item_page(closed, fx).status == "sold"
    assert listing_from_item_page(closed.replace('"bids": 3', '"bids": 0'), fx).status == "ended"


def test_layout_change_is_a_clear_error():
    with pytest.raises(FetchError):
        search_items("<html>no next data</html>")


def test_urls():
    assert "s1=new" in search_url("ディオール", "new") and "o1=a" in search_url("x", "ending")
    assert search_url("x", "closed").startswith("https://auctions.yahoo.co.jp/closedsearch/closedsearch?")
    assert "b=51" in search_url("x", "new", 1)


def test_incremental_second_run_inserts_nothing_and_stops_paging(ctx):
    c, rec = polite(serve())
    y = YahooJP(ctx, c)
    r1 = y.scrape([Q])
    assert r1.inserted > 0
    # open fixture has 12 items (<50) so page 2 is never requested; 'ending' adds one request
    assert len(rec.requests) == 2
    r2 = YahooJP(ctx, c).scrape([Q])
    assert r2.inserted == 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM listings WHERE source='yahoo_jp' AND is_auction=1") > 0
    assert len(known_ids(ctx.db, "yahoo_jp", ["l1253470528"])) == 1


def test_full_pages_continue_until_known(ctx):
    items = search_items(OPEN)
    c, rec = polite(serve())
    from scrapers import yahoo_jp
    old = yahoo_jp.PAGE_SIZE
    yahoo_jp.PAGE_SIZE = 12          # pretend a page holds 12 so a "full" page triggers paging
    try:
        YahooJP(ctx, c).scrape([Q], modes=("new",))
        assert len(rec.requests) == 2        # page 1 (new ids) then page 2 (same ids, all known) -> stop
    finally:
        yahoo_jp.PAGE_SIZE = old


def test_comps_run(ctx):
    c, _ = polite(serve())
    r = YahooJP(ctx, c).comps([Q])
    assert r.comps == 12
    assert YahooJP(ctx, c).comps([Q]).comps == 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM comps_sold WHERE source='yahoo_jp'") == 12


def test_recheck_marks_sold_and_removed(ctx):
    c, _ = polite(serve())
    YahooJP(ctx, c).scrape([Q], modes=("new",))
    closed = fixture_text("yahoo_item_open.html").replace('"status": "open"', '"status": "closed"')
    c2, _ = polite(serve(item_html=closed))
    r = YahooJP(ctx, c2).recheck(["l1253470528"])
    row = ctx.db.one("SELECT status, description FROM listings WHERE id='yahoo_jp:l1253470528'")
    assert r.updated == 1 and row["status"] == "sold" and row["description"]
    c3, _ = polite(lambda req: httpx.Response(404))
    YahooJP(ctx, c3).recheck(["e1253223917"])
    assert ctx.db.scalar("SELECT status FROM listings WHERE id='yahoo_jp:e1253223917'") == "removed"
