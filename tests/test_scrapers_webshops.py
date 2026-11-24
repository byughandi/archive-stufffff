import json

import httpx

from core.taxonomy import load_taxonomy
from scrapers.webshops import Webshops, js_to_json, shopify_listing, slug_for
from tests.conftest import fixture_json, polite

SHOP = {"name": "DRIEW Garments", "url": "https://driewgarments.com/", "platform": "shopify",
        "brands_focus": ["dior_homme"]}
MARAIS = {"name": "MARAIS (AU) Rick Owens Archive", "url": "https://marais.com.au/collections/rick-owens-archive",
          "platform": "shopify", "brands_focus": ["rick_owens"]}


def serve(products, meta=None, calls=None):
    meta = meta or {"currency": "CAD", "country": "CA"}

    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(req.url))
        if req.url.path == "/meta.json":
            return httpx.Response(200, json=meta)
        if req.url.path.endswith("/products.json"):
            if "/collections/" in req.url.path:
                return httpx.Response(200, json={"products": []})
            page = int(req.url.params.get("page", "1"))
            return httpx.Response(200, json={"products": products if page == 1 else []})
        return httpx.Response(404)
    return handler


def shop_obj(tax=None):
    return Webshops


def test_slug():
    assert slug_for(SHOP) == "driewgarments" and slug_for(MARAIS) == "marais"


def test_listing_uses_only_available_variants_and_currency(fx):
    prods = fixture_json("shopify_products.json")["products"]
    ls = [shopify_listing(p, "https://driewgarments.com", "driewgarments", "DRIEW", "CAD", "CA", fx) for p in prods]
    avail = [l for l in ls if l.status == "active"]
    assert len(avail) == 4 and len(ls) - len(avail) == 2
    l = avail[0]
    assert l.source == "shop:driewgarments" and l.currency == "CAD" and abs(l.price_usd - l.price / 1.4) < 1e-6
    assert l.url.startswith("https://driewgarments.com/products/") and l.size_raw and l.region == "CA"
    assert l.brand_raw and l.image_url and l.seller.source == "shop:driewgarments"


def test_incremental_second_run_inserts_nothing_and_skips_unchanged(ctx):
    prods = fixture_json("shopify_products.json")["products"]
    calls: list[str] = []
    c, _ = polite(serve(prods, calls=calls), min_delay=0, max_delay=0)
    w = Webshops(ctx, c)
    r1 = w.scrape_shop(SHOP)
    assert r1.inserted == 4                       # the 2 sold-out products are never stored
    assert ctx.db.scalar("SELECT COUNT(*) FROM listings WHERE source='shop:driewgarments'") == 4
    assert ctx.db.kv_get("shop_meta:driewgarments")
    n = len(calls)
    r2 = Webshops(ctx, c).scrape_shop(SHOP)
    assert r2.inserted == 0 and r2.seen == 0      # watermark: nothing new, nothing changed
    assert len(calls) - n == 1                    # one request: page 1 only, then stop


def test_updated_known_product_flips_to_sold(ctx):
    prods = fixture_json("shopify_products.json")["products"]
    c, _ = polite(serve(prods), min_delay=0, max_delay=0)
    Webshops(ctx, c).scrape_shop(SHOP)
    changed = json.loads(json.dumps(prods))
    changed[0]["updated_at"] = "2099-01-01T00:00:00+00:00"
    for v in changed[0]["variants"]:
        v["available"] = False
    c2, _ = polite(serve(changed), min_delay=0, max_delay=0)
    r = Webshops(ctx, c2).scrape_shop(SHOP)
    assert r.updated == 1 and ctx.db.scalar("SELECT COUNT(*) FROM listings WHERE status='sold'") == 1


def test_missing_collection_falls_back_to_brand_filtered_store(ctx):
    prods = fixture_json("shopify_products.json")["products"]
    for p in prods:
        p["tags"], p["vendor"], p["title"] = [], "OTHER", "Generic piece"
    prods[0]["vendor"], prods[1]["title"] = "RICK OWENS", "Rick Owens DRKSHDW jacket"
    c, _ = polite(serve(prods, {"currency": "AUD", "country": "AU"}), min_delay=0, max_delay=0)
    r = Webshops(ctx, c).scrape_shop(MARAIS)
    assert "empty or gone" in r.note and r.inserted == 2
    row = ctx.db.one("SELECT currency, region FROM listings WHERE source='shop:marais'")
    assert (row["currency"], row["region"]) == ("AUD", "AU")


def test_recheck_marks_sold_via_js_endpoint(ctx):
    prods = fixture_json("shopify_products.json")["products"]
    c, _ = polite(serve(prods), min_delay=0, max_delay=0)
    w = Webshops(ctx, c)
    w.scrape_shop(SHOP)
    lid = ctx.db.scalar("SELECT id FROM listings WHERE source='shop:driewgarments' LIMIT 1")
    p = next(p for p in prods if f"shop:driewgarments:{p['id']}" == lid)
    js = {"id": p["id"], "title": p["title"], "handle": p["handle"], "description": "", "vendor": p["vendor"],
          "type": "", "tags": [], "published_at": p["published_at"], "images": ["//cdn.shopify.com/x.jpg"], "options": [{"name": "Size"}],
          "variants": [{"available": False, "price": 41200, "option1": "IT 44"}]}

    def handler(req):
        return httpx.Response(200, json=js) if req.url.path.endswith(".js") else httpx.Response(404)

    c2, _ = polite(handler, min_delay=0, max_delay=0)
    r = Webshops(ctx, c2).recheck([lid])
    assert r.updated == 1 and ctx.db.scalar("SELECT status FROM listings WHERE id=?", (lid,)) == "sold"
    c3, _ = polite(lambda req: httpx.Response(404), min_delay=0, max_delay=0)
    Webshops(ctx, c3).recheck([lid])
    assert ctx.db.scalar("SELECT status FROM listings WHERE id=?", (lid,)) == "removed"


def test_js_adapter_converts_cents():
    out = js_to_json({"id": 1, "handle": "h", "variants": [{"price": 58000}], "images": ["//a/b.jpg"]})
    assert out["variants"][0]["price"] == "580.00" and out["images"][0]["src"] == "https://a/b.jpg"


def test_sellers_yaml_shops_have_known_platform():
    shops = load_taxonomy().sellers["webshops"]
    assert shops and all(s["platform"] in ("shopify", "bigcartel") for s in shops)
