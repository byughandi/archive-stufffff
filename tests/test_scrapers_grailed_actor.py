"""piotrv1001/grailed-listings-scraper: mapping checked against REAL dataset items saved from two runs on
2026-11-24 (tests/fixtures/grailed_actor_live.json, grailed_actor_sold.json)."""
import json
from pathlib import Path

import httpx

from core.db import connect
from core.fx import Fx
from scrapers import apify, grailed
from scrapers.common import Ctx
from scrapers.common.http import PoliteClient
from scrapers.common.queries import Query

FIX = Path(__file__).parent / "fixtures"
LIVE = json.loads((FIX / "grailed_actor_live.json").read_text())
SOLD = json.loads((FIX / "grailed_actor_sold.json").read_text())
FX = Fx({"USD": 1.0, "JPY": 150.0}, 0, False)


def test_live_item_maps_every_field_the_pipeline_reads():
    l = grailed._apify_listing(LIVE[1], FX, "q1")
    assert l.id == "grailed:111069124" and l.url == "https://www.grailed.com/listings/111069124"
    assert l.title.startswith("SS06 Dior Homme Hedi Slimane") and l.price_usd == 1575 and l.currency == "USD"
    assert l.brand_raw == "Dior × Hedi Slimane" and l.category_raw == "outerwear.light_jackets" and l.size_raw == "s"
    assert l.shipping_usd == 18.99 and l.status == "active" and l.listed_at == 1793661689
    assert l.seller.username == "Sneer" and l.seller.review_count == 2508 and 4.9 < l.seller.rating < 5
    assert l.image_url.startswith("https://media-assets.grailed.com/")


def test_sold_item_uses_the_final_sold_price_not_the_asking_price():
    c = grailed._apify_comp(SOLD[0])
    assert c.id == "grailed:98355605" and c.sold_price_usd == 1250 and c.sold_at == 1787283326   # asked 1399
    assert grailed._apify_comp(LIVE[0]) is None                                                    # not sold


def test_input_matches_the_actors_schema():
    a = apify.actor_for("GRAILED")
    assert a.id == "piotrv1001/grailed-listings-scraper" and a.price_per_1k == 3.0
    assert apify.grailed_input(a, "dior homme hedi", 6, sold=True) == {
        "searchQuery": "dior homme hedi", "soldOnly": True, "department": "all", "scrapeDetails": False,
        "maxItems": 6, "proxyConfiguration": {"useApifyProxy": True}}


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    db = connect(); db.migrate()
    return Ctx(db=db, fx=FX, dry_run=False)


def _client(payloads):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content))
        return httpx.Response(200, json=payloads[min(len(calls) - 1, len(payloads) - 1)])
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None, min_delay=0, max_delay=0), calls


def test_sold_comps_run_stores_comps_charges_the_ledger_and_is_throttled(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    client, calls = _client([SOLD])
    qs = [Query("en:saint_laurent:l01", "saint laurent paris l01", "en", "saint_laurent"),
          Query("en:dior_homme:hedi", "dior homme hedi", "en", "dior_homme")]
    res = grailed.comps_apify(ctx, qs, client)
    assert res.comps == len(SOLD) and all(c["soldOnly"] is True for c in calls) and len(calls) == 2
    assert ctx.db.scalar("SELECT COUNT(*) FROM comps_sold WHERE source = 'grailed'") == len(SOLD)
    spent = ctx.db.scalar("SELECT SUM(usd) FROM spend_ledger WHERE note = 'source:grailed'")
    assert abs(spent - 2 * len(SOLD) * 0.003) < 1e-9
    again = grailed.comps_apify(ctx, qs, client)                     # same day: throttled, no new spend
    assert again.comps == 0 and len(calls) == 2


def test_live_fallback_inserts_listings_once(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    client, calls = _client([LIVE])
    qs = [Query("en:dior_homme:hedi", "dior homme hedi slimane", "en", "dior_homme")]
    res = grailed.run_apify(ctx, qs, client)
    assert res.inserted == len(LIVE) and calls[0]["soldOnly"] is False and calls[0]["searchQuery"] == "dior homme hedi slimane"
    monkeypatch.setenv("APIFY_GRAILED_INTERVAL_S", "0")
    assert grailed.run_apify(ctx, qs, client).inserted == 0          # same items again: nothing new


def test_real_grailed_titles_classify_sensibly():
    """The first real English Grailed listings this project saw. They also caught a parser bug:
    "L01 FW/14" used to be read as season "01 FW"."""
    from pipeline.score import score_items
    by = {r.listing["title"]: r for r in score_items(
        [dict(title=i["title"], brand_raw=i["designer"], price_usd=i["price"], source="grailed") for i in LIVE]
        + [dict(title="Saint Laurent Paris L01 FW/14 (Hedi Era) *FINAL PRICE*", brand_raw="Saint Laurent Paris", price_usd=1550, source="grailed"),
           dict(title="Saint Laurent Paris L01 Leather Jacket FW17", brand_raw="Saint Laurent Paris", price_usd=900, source="grailed")])}
    assert all(r.ent.brand == "dior_homme" for t, r in by.items() if t.startswith(("SS0", "AW0", "04 Dior", "Dior Homme")))
    assert by["SS07 Dior Homme Hedi Slimane Sky Faded Jake Denim Jeans"].tier == "S"
    assert by["04 Dior Homme Hedi Slimane Clawmark Denim"].tier == "S"
    bee = by["Dior Homme Hedi Slimane Bee Polo Men 48 Blue Iconic Archive"]
    assert bee.ent.era_conf < 0.5 and bee.tier in ("B", "C")         # the bee is a later-era tell, whatever the title claims
    hedi = by["Saint Laurent Paris L01 FW/14 (Hedi Era) *FINAL PRICE*"]
    assert hedi.ent.era == "saint_laurent__hedi" and hedi.ent.era_conf >= 0.65 and hedi.ent.season == "saint_laurent__aw14"
    assert by["Saint Laurent Paris L01 Leather Jacket FW17"].ent.era_conf < 0.5   # FW17 is after Hedi left
