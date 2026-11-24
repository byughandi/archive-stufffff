"""Mercari US is behind a Cloudflare challenge from the build machine: mock-tested only."""
import httpx
import pytest

from core.models import upsert_listings
from scrapers import mercari_us
from scrapers.common.http import Blocked
from scrapers.common.queries import Query
from tests.conftest import polite

Q = Query("en:dior_homme::", "dior homme", "en", "dior_homme")
CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Enable JavaScript and cookies to continue</body></html>"
ITEMS = [{"id": "m1", "name": "Dior Homme jacket", "price": 450, "status": "on_sale", "brand": {"name": "Dior Homme"},
          "photos": [{"imageUrl": "https://i/1.jpg"}], "seller": {"id": "9", "name": "bob", "rating": 4.9}},
         {"id": "m2", "name": "Dior Homme jeans", "price": 220, "status": "on_sale"}]


def page(items):
    import json
    nd = {"props": {"pageProps": {"apollo": {"search": {"items": items}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script></html>'


def site(html, status=200):
    return lambda req: httpx.Response(status, text=html, headers={"content-type": "text/html"})


def actor(items, log=None):
    def h(req):
        if log is not None:
            log.append(str(req.url))
        return httpx.Response(200, json=items)
    return h


def test_direct_rung_used_when_site_answers(ctx):
    c, rec = polite(site(page(ITEMS)), min_delay=0, max_delay=0)
    r = mercari_us.run(ctx, [Q], client=c)
    assert r.rung == "direct" and r.inserted == 2 and len(rec.requests) == 1       # exactly one honest request
    assert ctx.db.scalar("SELECT price_usd FROM listings WHERE id='mercari_us:m1'") == 450
    assert mercari_us.run(ctx, [Q], client=polite(site(page(ITEMS)), min_delay=0, max_delay=0)[0]).inserted == 0


def test_challenge_falls_to_apify_and_direct_is_parked(ctx, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    c, rec = polite(site(CHALLENGE), min_delay=0, max_delay=0)
    log: list[str] = []
    ac, arec = polite(actor(ITEMS, log))
    r = mercari_us.run(ctx, [Q, Q], client=c, apify_client=ac)
    assert r.rung == "apify" and r.inserted == 2 and len(rec.requests) == 1 and len(arec.requests) == 1
    # next run: apify is throttled by its minimum interval and the direct rung is parked -> Blocked, no site request
    c2, rec2 = polite(site(CHALLENGE), min_delay=0, max_delay=0)
    with pytest.raises(Blocked):
        mercari_us.run(ctx, [Q], client=c2, apify_client=ac)
    assert rec2.requests == []


def test_403_is_blocked_not_retried(ctx, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    c, rec = polite(site("denied", 403), min_delay=0, max_delay=0)
    with pytest.raises(Blocked):
        mercari_us.run(ctx, [Q], client=c)
    assert len(rec.requests) == 1


def test_unknown_page_layout_is_error_not_block_and_tries_apify(ctx, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    c, _ = polite(site("<html>hello</html>"), min_delay=0, max_delay=0)
    ac, _ = polite(actor(ITEMS))
    r = mercari_us.run(ctx, [Q], client=c, apify_client=ac)
    assert r.rung == "apify"


def test_sold_actor_feeds_comps_and_flips_known_listing(ctx, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    c, _ = polite(site(page(ITEMS)), min_delay=0, max_delay=0)
    mercari_us.run(ctx, [Q], client=c)
    sold = [{"id": "m1", "name": "Dior Homme jacket", "price": 430, "status": "sold", "updated": 1795600000},
            {"id": "m9", "name": "Dior Homme tee", "price": 90, "status": "sold", "updated": 1795600100}]
    ac, _ = polite(actor(sold))
    r = mercari_us.comps(ctx, [Q], apify_client=ac)
    assert r.comps == 2 and r.updated == 1
    assert ctx.db.scalar("SELECT status FROM listings WHERE id='mercari_us:m1'") == "sold"
    assert ctx.db.scalar("SELECT sold_price_usd FROM comps_sold WHERE id='mercari_us:m1'") == 430
    again = mercari_us.comps(ctx, [Q], apify_client=ac)          # throttled: no second paid run in a day
    assert again.comps == 0 and "throttled" in again.note
