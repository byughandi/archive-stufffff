"""Grailed is unreachable from the build machine: these tests use SYNTHETIC pages and hits whose
shapes are from memory. They prove the plumbing; the first live CI run proves the shapes."""
import json

import httpx
import pytest

from core import health
from core.models import known_ids
from scrapers import apify, grailed
from scrapers.common.http import Blocked
from scrapers.common.queries import Query
from tests.conftest import fixture_text, polite

APP, KEY = "TESTAPP123", "k" * 32
HOME = f"""<html><head><script>window.PUBLIC_CONFIG = {{"ALGOLIA_APPLICATION_ID": "{APP}",
"ALGOLIA_SEARCH_KEY": "{KEY}", "ALGOLIA_INDEX": "Listing_production"}};</script></head>
<body>"Listing_by_date_production" "Listing_sold_production" "Listing_by_heat_production"</body></html>"""
Q = Query("en:dior_homme::", "dior homme hedi", "en", "dior_homme")


def hit(i, price=500, sold=False):
    h = {"objectID": str(i), "title": f"Dior Homme jacket {i}", "designers": [{"name": "Dior Homme"}], "price": price,
         "size": "m", "category_path": "menswear.outerwear.leather_jackets", "condition": "is_gently_used",
         "cover_photo": {"url": f"https://media.grailed.test/{i}.jpg"}, "created_at": "2026-11-23T10:00:00.000Z",
         "created_at_i": 1795500000 + i,
         "user": {"id": 77, "username": "archivedude", "seller_score": {"rating_average": 4.8, "rating_count": 120},
                  "sold_count": 300}}
    if sold:
        h.update(sold=True, sold_price=price - 50, sold_at_i=1795600000 + i)
    return h


class Algolia:
    def __init__(self, pages=None, valid_key=KEY, indices=("Listing_production", "Listing_by_date_production", "Listing_sold_production")):
        self.pages = pages if pages is not None else {0: [hit(1), hit(2), hit(3)]}
        self.valid_key, self.indices, self.log = valid_key, set(indices), []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.log.append(str(req.url))
        host = req.url.host
        if host == "www.grailed.com":
            return httpx.Response(200, text=HOME, headers={"content-type": "text/html"})
        assert host == f"{APP.lower()}-dsn.algolia.net"
        if req.headers.get("x-algolia-api-key") != self.valid_key:
            return httpx.Response(403, json={"message": "Invalid Application-ID or API key", "status": 403})
        body = json.loads(req.content)
        if req.url.path.endswith("/objects"):
            return httpx.Response(200, json={"results": [
                next((h for h in sum(self.pages.values(), []) if h["objectID"] == r["objectID"] and r["indexName"] != "Listing_sold_production"), None)
                for r in body["requests"]]})
        r = body["requests"][0]
        if r["indexName"] not in self.indices:
            return httpx.Response(404, json={"message": f"Index {r['indexName']} does not exist", "status": 404})
        page = int(dict(p.split("=") for p in r["params"].split("&"))["page"])
        hits = self.pages.get(page, [])
        if r["indexName"] == "Listing_sold_production":
            hits = [hit(900 + i, sold=True) for i in range(3)]
        return httpx.Response(200, json={"results": [{"hits": hits, "page": page, "nbPages": max(self.pages) + 1}]})


def make(ctx, algolia):
    c, rec = polite(algolia, min_delay=0, max_delay=0)
    return grailed.Grailed(ctx, c), rec


def test_extract_credentials_variants():
    app, key, names = grailed.extract_credentials(HOME)
    assert (app, key) == (APP, KEY) and "Listing_by_date_production" in names
    app, key, _ = grailed.extract_credentials('fetch("https://abcde12345-dsn.algolia.net/1/indexes/*/queries?x-algolia-application-id=ABCDE12345&x-algolia-api-key=' + "z" * 40 + '")')
    assert app == "ABCDE12345" and key == "z" * 40
    assert grailed.extract_credentials("<html>nothing</html>")[:2] == (None, None)
    idx = grailed.classify_indices(["Listing_production", "Listing_by_date_production", "Listing_sold_production", "Listing_by_heat_production"])
    assert idx == {"live": "Listing_production", "by_date": "Listing_by_date_production", "sold": "Listing_sold_production"}


def test_discovery_from_page_then_kv_cache_then_env(ctx, monkeypatch):
    g, rec = make(ctx, Algolia())
    r1 = g.scrape([Q])
    assert r1.inserted == 3 and r1.rung == "direct"
    assert any("www.grailed.com" in u for u in rec.urls)
    cached = json.loads(ctx.db.kv_get("grailed_algolia"))
    assert cached["app_id"] == APP and cached["indices"]["by_date"] == "Listing_by_date_production"
    # second run: credentials come from kv, no page fetch
    g2, rec2 = make(ctx, Algolia())
    r2 = g2.scrape([Q])
    assert r2.inserted == 0
    assert not any("www.grailed.com" in u for u in rec2.urls)
    # env override beats the cache
    ctx.db.kv_set("grailed_algolia", json.dumps({"app_id": "OLD", "api_key": "old", "indices": {}}))
    monkeypatch.setenv("GRAILED_ALGOLIA_APP_ID", APP)
    monkeypatch.setenv("GRAILED_ALGOLIA_KEY", KEY)
    g3, rec3 = make(ctx, Algolia())
    assert g3.scrape([Q]).inserted == 0 and not any("www.grailed.com" in u for u in rec3.urls)


def test_mapping_listing_and_seller(ctx):
    g, _ = make(ctx, Algolia())
    g.scrape([Q])
    row = ctx.db.one("SELECT * FROM listings WHERE id='grailed:1'")
    assert row["price"] == 500 and row["price_usd"] == 500 and row["size_raw"] == "m" and row["brand_raw"] == "Dior Homme"
    assert row["url"] == "https://www.grailed.com/listings/1" and row["image_url"].endswith("/1.jpg")
    s = ctx.db.one("SELECT * FROM sellers WHERE id='grailed:77'")
    assert (s["username"], s["rating"], s["review_count"], s["sales_count"]) == ("archivedude", 4.8, 120, 300)


def test_incremental_stop_pages_until_known(ctx):
    pages = {0: [hit(1), hit(2)], 1: [hit(3), hit(4)], 2: [hit(5)]}
    g, rec = make(ctx, Algolia(pages))
    assert g.scrape([Q]).inserted == 5
    n_first = len([u for u in rec.urls if "queries" in u])
    g2, rec2 = make(ctx, Algolia(pages))
    assert g2.scrape([Q]).inserted == 0
    assert len([u for u in rec2.urls if "queries" in u and True]) < n_first       # stopped after the first known page


def test_stale_key_triggers_one_rediscovery_and_retry(ctx):
    ctx.db.kv_set("grailed_algolia", json.dumps({"app_id": APP, "api_key": "stale", "indices": {
        "by_date": "Listing_by_date_production", "live": "Listing_production"}}))
    g, rec = make(ctx, Algolia())
    r = g.scrape([Q])
    assert r.inserted == 3
    assert sum("www.grailed.com" in u for u in rec.urls) == 1                    # re-discovered exactly once
    assert json.loads(ctx.db.kv_get("grailed_algolia"))["api_key"] == KEY


def test_unknown_index_names_are_probed_and_dropped(ctx):
    g, _ = make(ctx, Algolia(indices=("Listing_production",)))
    idx = g.resolve_indices()
    assert idx == {"live": "Listing_production"}


def test_sold_index_gives_comps(ctx):
    g, _ = make(ctx, Algolia())
    r = g.comps([Q])
    assert r.comps == 3
    row = ctx.db.one("SELECT sold_price_usd, sold_at FROM comps_sold WHERE id='grailed:900'")
    assert row["sold_price_usd"] == 450 and row["sold_at"] == 1795600900


def test_recheck_by_object_id(ctx):
    g, _ = make(ctx, Algolia({0: [hit(1), hit(2)]}))
    g.scrape([Q])
    ctx.db.execute("UPDATE listings SET price = 999 WHERE id='grailed:1'")
    changed = {0: [hit(1, price=420)]}                      # 1 cheaper, 2 gone from live, not in sold index
    g2, _ = make(ctx, Algolia(changed))
    r = g2.recheck(["1", "2"])
    assert r.updated == 2
    assert ctx.db.scalar("SELECT price FROM listings WHERE id='grailed:1'") == 420
    assert ctx.db.scalar("SELECT status FROM listings WHERE id='grailed:2'") == "removed"


# ---- the ladder -----------------------------------------------------------------------------------
def blocked_site(req):
    return httpx.Response(403, text=fixture_text("grailed_blocked.html"), headers={"content-type": "text/html"})


def actor_handler(items, log):
    def h(req):
        log.append(str(req.url))
        return httpx.Response(200, json=items)
    return h


def test_blocked_homepage_falls_to_apify_and_parks_direct_rung(ctx, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    log: list[str] = []
    c, rec = polite(blocked_site, min_delay=0, max_delay=0)
    ac, arec = polite(actor_handler([{"id": 11, "title": "Dior Homme coat", "price": 300, "url": "https://www.grailed.com/listings/11-x",
                                      "designer": "Dior Homme", "size": "L", "image": "https://i/1.jpg"}], log))
    r = grailed.run(ctx, [Q], client=c, apify_client=ac)
    assert r.rung == "apify" and r.inserted == 1
    row = ctx.db.one("SELECT url, price_usd, brand_raw FROM listings WHERE id='grailed:11'")
    assert row["url"].endswith("11-x") and row["price_usd"] == 300 and row["brand_raw"] == "Dior Homme"
    assert ctx.db.scalar("SELECT COUNT(*) FROM spend_ledger WHERE vendor='apify'") == 1
    assert len(rec.requests) == 1
    # the next run does not touch grailed.com again (rung parked) and, with apify throttled, reports Blocked
    c2, rec2 = polite(blocked_site, min_delay=0, max_delay=0)
    with pytest.raises(Blocked):
        grailed.run(ctx, [Q], client=c2, apify_client=ac)
    assert rec2.requests == []


def test_blocked_without_apify_token_raises_blocked(ctx, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    c, _ = polite(blocked_site, min_delay=0, max_delay=0)
    with pytest.raises(Blocked):
        grailed.run(ctx, [Q], client=c)


def test_apify_refused_by_spend_guard_raises_blocked(ctx, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    ctx.db.execute("INSERT INTO spend_ledger (at, vendor, kind, units, usd, note) VALUES (strftime('%s','now'), 'apify', 'x', 1, 4.49, 'source:instagram')")
    c, _ = polite(blocked_site, min_delay=0, max_delay=0)
    ac, arec = polite(actor_handler([], []))
    with pytest.raises(Blocked):
        grailed.run(ctx, [Q], client=c, apify_client=ac)
    assert arec.requests == []


def test_three_blocked_runs_open_breaker(ctx, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    for i in range(3):
        ctx.db.kv_set("rung_blocked:grailed:direct", "0")        # un-park so each run really tries once
        c, _ = polite(blocked_site, min_delay=0, max_delay=0)
        with pytest.raises(Blocked):
            grailed.run(ctx, [Q], client=c)
        health.record_failure(ctx.db, "grailed", True, "blocked")
    assert not health.allowed(ctx.db, "grailed")
