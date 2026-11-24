"""getascraper/mercari-us-scraper: mapping checked against REAL dataset items from a run on 2026-11-24."""
import json
from pathlib import Path

from core.fx import Fx
from scrapers import apify, mercari_us

ITEMS = json.loads((Path(__file__).parent / "fixtures" / "mercari_us_actor.json").read_text())
FX = Fx({"USD": 1.0}, 0, False)


def test_real_item_maps():
    l = mercari_us.listing_from_item(ITEMS[1], FX, "q")
    assert l.id == "mercari_us:m59390067613" and l.url == "https://www.mercari.com/us/item/m59390067613/"
    assert l.title == "dior homme by hedi slimane aw07 black sweater" and l.price_usd == 250 and l.status == "active"
    assert l.brand_raw == "Dior" and l.condition_raw == "like_new" and l.category_raw == "Men > Sweaters > Crewneck"
    assert l.image_url.startswith("https://u-mercari-images.mercdn.net/") and l.seller.id == "mercari_us:101597443"


def test_input_and_cost_model():
    a = apify.actor_for("MERCARI_US")
    assert a.id == "getascraper/mercari-us-scraper"
    i = apify.mercari_us_input(a, "dior homme hedi", 12, sold=True)
    assert i["keyword"] == "dior homme hedi" and i["status"] == ["sold_out"] and i["limit"] == 12
    assert i["proxyConfiguration"]["apifyProxyGroups"] == ["RESIDENTIAL"]
    assert apify.MERCARI_US_SEARCH_FEE == 0.04


def test_real_titles_through_the_cascade():
    from pipeline.score import score_items
    rs = {r.listing["title"]: r for r in score_items(
        [dict(title=i["title"], brand_raw=i["brand"], price_usd=i["price"], source="mercari_us") for i in ITEMS])}
    assert rs["dior homme by hedi slimane aw07 black sweater"].ent.era == "dior_homme__hedi"
    assert rs["Dior Homme SS06 Jeans"].ent.season == "dior_homme__ss06"
    generic = rs["Men's Navy Blue Cargo Pants with Men's Navy Blue Cargo Pants with Buckle Details"]
    assert generic.tier in ("C", "X")      # brand field says Dior, title says nothing: not a wanted piece
