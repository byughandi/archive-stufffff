import json
import time

from core.models import Listing, Seller, SoldComp, upsert_comps, upsert_listings
from pipeline.alerts import matches, run_alerts
from pipeline.comps import classify_queued
from pipeline.run import prune
from pipeline.score import run_score, score_items, sync_taxonomy
from pipeline.trends import run_trends
from pipeline_util import make_db, run_one

NOW = int(time.time())
EXPLAIN_KEYS = {"entities", "desirability", "value", "cost", "deal", "flags", "similarity", "ranker"}


def jp(i, title, price_jpy, **kw):
    return Listing("mercari_jp", f"m{i}", f"https://jp.mercari.com/item/m{i}", title, price_jpy, "JPY", price_jpy / 150,
                   region="JP", lang="ja", proxy_url=f"https://buyee.jp/mercari/item/m{i}", condition_raw="3",
                   seller=Seller("mercari_jp", f"s{i}"), listed_at=NOW - 3600, **kw)


def seed(db):
    upsert_listings(db, [
        jp(1, "ディオールオム エディ期 04SS ストリップ デニム 28", 45000),
        jp(2, "Dior Homme jeans 30", 30000),
        jp(3, "Chanel No 5 香水 100ml", 9000),
        jp(4, "ナンバーナイン 06AW ノワール期 スカル ニット", 60000),
    ])
    comps = [SoldComp("mercari_jp", f"c{i}", "ディオールオム エディ期 デニム 28", 600 + i * 10, NOW - i * 86400 * 7,
                      url=f"https://jp.mercari.com/item/c{i}") for i in range(12)]
    comps += [SoldComp("mercari_jp", "cj", "Dior Sauvage EDT", 50, NOW - 86400)]
    upsert_comps(db, comps)


def test_end_to_end_db(tmp_path, monkeypatch):
    db = make_db(tmp_path, monkeypatch)
    seed(db)
    assert classify_queued(db)["junk"] == 1
    s = run_score(db, "queue", use_phash=False)
    assert s["scored"] == 4 and s["written"] == 4 and s["embed_backend"] == "tfidf-char+concepts"
    assert db.scalar("SELECT COUNT(*) FROM listings WHERE needs_score = 1") == 0
    f = {r["listing_id"]: r for r in db.query("SELECT * FROM feed")}
    assert f["mercari_jp:m3"]["tier"] == "X" and f["mercari_jp:m3"]["reject_reason"]
    assert f["mercari_jp:m1"]["tier"] in ("S", "A") and f["mercari_jp:m1"]["fair_value_usd"]
    assert f["mercari_jp:m2"]["tier"] in ("B", "C") and "needs_tag_pics" in json.loads(f["mercari_jp:m2"]["flags"])
    ex = json.loads(db.scalar("SELECT explain FROM scores WHERE listing_id='mercari_jp:m1'"))
    assert EXPLAIN_KEYS <= set(ex)
    assert ex["entities"]["era"]["id"] == "dior_homme__hedi" and ex["value"]["market"] == "JP"
    assert ex["value"]["comps"] and len(ex["value"]["comps"]) <= 8 and ex["value"]["comps"][0]["url"]
    assert ex["cost"]["proxy_fee_usd"] > 0 and ex["ranker"]["model"] == "formula-v1"
    assert ex["deal"]["label"] in ("steal", "great", "good", "fair", "overpriced", "suspicious")
    # rescore writes only rows whose visible values changed
    assert run_score(db, "all", use_phash=False)["written"] == 0
    # taxonomy mirror
    assert db.scalar("SELECT COUNT(*) FROM taxonomy_entities WHERE kind='brand'") >= 50
    assert sync_taxonomy(db)["synced"] is False
    # alerts: global rule, dedupe
    a = run_alerts(db, since=0)
    assert a["global_rule_id"]
    # no NTFY_TOPIC: alerts are only previewed, so nothing may be recorded as sent and the same
    # listings must still alert once a topic is configured
    assert a["delivered_via"] == "stdout"
    assert db.scalar("SELECT COUNT(*) FROM alerts_sent") == 0
    assert run_alerts(db, since=0)["sent"] == a["sent"]


def test_alerts_delivered_once_and_japanese_titles_survive(tmp_path, monkeypatch):
    import pipeline.alerts as alerts
    db = make_db(tmp_path, monkeypatch)
    seed(db)
    run_score(db, "queue", use_phash=False)
    db.execute("UPDATE feed SET tier = 'S', tier_rank = 0, title = 'Dior Homme 06SS ブリーチデニム エディ期'"
               " WHERE listing_id = 'mercari_jp:m1'")
    posted = []

    class Resp:
        status_code = 200

    def fake_post(url, json=None, timeout=None, **kw):
        posted.append((url, json))
        return Resp()
    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    first = alerts.run_alerts(db, since=0)
    assert first["sent"] >= 1 and first["delivered_via"] == "ntfy"
    url, body = posted[0]
    assert body["topic"] == "test-topic" and "エディ期" in body["title"]      # UTF-8 title sent in the JSON body
    assert db.scalar("SELECT COUNT(*) FROM alerts_sent") == first["sent"]
    assert alerts.run_alerts(db, since=0)["sent"] == 0                        # delivered once, not again


def test_alert_rules():
    row = {"tier": "A", "deal_label": "steal", "title": "Saint Laurent L01", "brand": "saint_laurent",
           "size_norm": "48", "landed_usd": 1200, "source": "grailed", "region": "US", "_flags": []}
    assert matches({}, row, is_global=True)
    assert not matches({}, dict(row, deal_label="suspicious"), is_global=True)
    assert not matches({}, dict(row, _flags=["auction_in_progress"]), is_global=True)
    assert matches({"q": "l01", "brand": "saint_laurent", "sizes": ["48"], "max_landed_usd": 1500, "min_tier": "A"}, row)
    assert not matches({"min_tier": "S"}, row)


def test_deal_labels_and_auctions():
    r = run_one("Dior Homme SS04 Strip Hedi Slimane denim 29", price_usd=200, source="grailed")
    assert r.deal["label"] in ("steal", "great", "suspicious", "good")   # price band prior 800
    a = score_items([dict(title="Dior Homme SS04 Strip Hedi Slimane denim 29", price_usd=5, source="yahoo_jp",
                          is_auction=1, bids=3, auction_end_at=NOW + 3 * 86400)])[0]
    # current bid with days left is never a steal
    assert a.deal is None or a.deal["label"] in ("good", "fair", "overpriced", "unknown")


def test_trends_priors_and_prune(tmp_path, monkeypatch):
    db = make_db(tmp_path, monkeypatch)
    out = run_trends(db)
    assert out["prior_rows"] > 20
    assert db.scalar("SELECT COUNT(*) FROM trend_scores WHERE source='prior'") == out["prior_rows"]
    db.execute("INSERT INTO ig_posts (id, handle, posted_at, caption, hashtags, likes, comments, ingested_at)"
               " VALUES ('p1','a',?,?,?,100,5,?)", (NOW - 86400, "Dior Homme SS04 Strip denim", "[]", NOW))
    assert run_trends(db)["ig_rows"] > 0
    seed(db)
    run_score(db, "queue", use_phash=False)
    db.execute("UPDATE listings SET first_seen_at = ? WHERE id = 'mercari_jp:m3'", (NOW - 30 * 86400,))
    p = prune(db)
    assert p["rejected_deleted"] == 1
    assert db.scalar("SELECT COUNT(*) FROM listings WHERE id='mercari_jp:m3'") == 0
