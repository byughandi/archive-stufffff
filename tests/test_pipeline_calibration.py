"""Calibration rules found by reviewing the real feed. Each one caught a real mis-ranking."""
import time

from pipeline.comps import Comp, CompsIndex
from pipeline.score import score_items
from core.taxonomy import load_taxonomy

from pipeline_util import run_one

NOW = int(time.time())
NOT_A_DEAL = ("good", "fair", "overpriced", "unknown")


def test_zero_bid_auction_with_days_left_is_not_a_steal():
    a = score_items([dict(title="Dior Homme SS04 Strip Hedi Slimane denim 29", price_usd=5, source="yahoo_jp",
                          region="JP", is_auction=1, bids=0, auction_end_at=NOW + 5 * 86400)])[0]
    assert a.deal["label"] in NOT_A_DEAL
    assert any(f["id"] == "auction_in_progress" for f in a.filt.flags)


def test_auction_in_its_last_two_hours_is_scored_normally():
    a = score_items([dict(title="Dior Homme SS04 Strip Hedi Slimane denim 29", price_usd=300, source="yahoo_jp",
                          region="JP", is_auction=1, bids=0, auction_end_at=NOW + 3600)])[0]
    assert any(f["id"] == "ending_soon" for f in a.filt.flags)
    assert not any(f["id"] == "auction_in_progress" for f in a.filt.flags)


def test_plain_pieces_are_valued_against_plain_comps():
    """Named-season denim sells for multiples of plain denim of the same era; they must not share a median."""
    def comp(i, season, price):
        return Comp(f"c:{i}", "mercari_jp", None, "t", "dior_homme", "dior_homme__hedi", season, "denim", None,
                    price, NOW - 86400, "JP")
    comps = [comp(i, None, 300) for i in range(8)] + [comp(100 + i, "dior_homme__aw03", 900) for i in range(8)]
    idx = CompsIndex(comps, load_taxonomy(), at=NOW)
    plain = idx.value("dior_homme", "dior_homme__hedi", None, "denim", "JP")
    assert plain["stratum"] == "plain" and plain["median"] == 300
    # a named season with too few comps of its own falls back to other named-season comps, not to plain ones
    named = idx.value("dior_homme", "dior_homme__hedi", "dior_homme__ss04", "denim", "JP")
    assert named["stratum"] == "named_season" and named["median"] == 900


def test_s_tier_needs_a_named_piece_not_just_the_right_type():
    plain = run_one("Dior Homme Hedi Slimane era bootcut denim 30", price_usd=300, source="grailed")
    assert plain.tier == "A"
    named = run_one("Dior Homme AW03 Luster clawmark denim Hedi Slimane 30", price_usd=900, source="grailed")
    assert named.tier == "S"


def test_explicit_season_code_beats_a_keyword_stuffed_season_name():
    r = run_one("初期 1997AW UNDERCOVER ネイティブ柄 ニット セーター アンダーカバー SCAB 90s", price_usd=150,
                source="yahoo_jp", region="JP")
    assert r.ent.season != "undercover__ss03"


def test_kaws_bee_dior_is_kim_jones_era():
    r = run_one("DIOR HOMME KAWS bee embroidered denim black 31", price_usd=400, source="grailed")
    assert r.tier in ("C", "X")


def test_chrome_hearts_keychain_is_not_rejected_as_merch():
    r = run_one("クロムハーツ CLIP NO2 クロスボール キーチェーン", price_usd=900, source="mercari_jp", region="JP")
    assert r.tier != "X"


# ---- second verification round ------------------------------------------------------------------
def test_no_piece_type_means_brand_level_low_confidence():
    def comp(i, arch, price):
        return Comp(f"s:{i}", "mercari_jp", None, "t", "dior_homme", "dior_homme__hedi", "dior_homme__ss04", arch, None,
                    price, NOW - 86400, "JP")
    idx = CompsIndex([comp(i, "leather_jacket", 1500) for i in range(8)], load_taxonomy(), at=NOW)
    v = idx.value("dior_homme", "dior_homme__hedi", "dior_homme__ss04", None, "JP")
    assert v["level"] == "brand" and v["conf"] == "low"      # never the season's leather-jacket median at "med"


def test_low_confidence_value_never_earns_great_or_steal():
    r = run_one("Dior Homme SS04 Strip Hedi Slimane denim 29", price_usd=100, source="grailed")   # price-band prior
    assert r.value.get("conf") in ("low", "none")
    assert r.deal["label"] in ("good", "fair", "overpriced", "unknown", "suspicious")


def test_placeholder_is_about_the_shape_of_the_price_not_its_size():
    real = run_one("Dior Homme 05AW エディ期 レザージャケット 46", price=1_480_000, currency="JPY", price_usd=9300,
                   source="mercari_jp", region="JP")
    assert real.reject_reason != "placeholder_price"
    fake = run_one("Dior Homme 05AW エディ期 レザージャケット 46", price=999_999, currency="JPY", price_usd=6286,
                   source="mercari_jp", region="JP")
    assert fake.reject_reason == "placeholder_price"


def test_title_listing_every_piece_type_is_capped():
    r = run_one("ディオールオム 07AW デニムパンツ ジャケット コート Tシャツ ニット ブルゾン ブーツ ベルト エディ期", price_usd=120,
                source="yahoo_jp", region="JP")
    assert r.tier in ("C", "X") and any(f["id"] == "type_stuffing" for f in r.filt.flags)


def test_spare_button_is_not_a_piece():
    assert run_one("希少 エディ期 Dior homme の替えボタン 2個", price_usd=33, source="mercari_jp", region="JP").tier == "X"


def test_mens_dress_shirt_is_not_flagged_womens():
    r = run_one("Dior Homme 比翼 ドレスシャツ 36 メンズ エディ期", price_usd=120, source="yahoo_jp", region="JP")
    assert not any(f["id"] == "womens" for f in r.filt.flags)


def test_right_era_everyday_piece_is_solid_not_heat():
    assert run_one("Dior Homme Hedi Slimane era leather belt 85", price_usd=150, source="grailed").tier == "B"
    assert run_one("HELMUT LANG 1999 本人期 ボンテージパンツ", price_usd=400, source="mercari_jp", region="JP").tier in ("S", "A")


def test_alert_says_how_sure_the_value_is():
    from pipeline.alerts import message
    m = message({"tier": "S", "deal_label": "good", "discount": 0.5, "price_usd": 465, "landed_usd": 580,
                 "fair_value_usd": 1156, "value_conf": "low", "comp_count": 3, "url": "https://x", "proxy_url": None,
                 "listing_id": "a:1", "title": "04SS Dior HOMME STRIP期"})
    assert "low confidence" in m["body"] and "3 sold" in m["body"]


# ---- third verification round -------------------------------------------------------------------
def test_seller_saying_it_resembles_the_brand_is_a_lookalike():
    r = run_one("Rick Owens似 メガバンパー ジオバスケット", price_usd=120, source="mercari_jp", region="JP")
    assert r.tier == "X" and str(r.reject_reason).startswith("lookalike")
    real = run_one("Rick Owens ジオバスケット 42", price_usd=500, source="mercari_jp", region="JP")
    assert real.tier != "X"


def test_another_labels_piece_naming_a_wanted_brand_is_rejected():
    r = run_one("JOSEPH HOMME Coated Biker Dior homme", price_usd=110, source="mercari_jp", region="JP")
    assert r.tier == "X" and str(r.reject_reason).startswith("other_brand")


def test_grail_season_name_plus_its_code_identifies_the_brand():
    r = run_one("【超希少】03ss scab期 黒アーカイブ 手縫い パッチワーク ほつれ加工", price_usd=900, source="mercari_jp", region="JP")
    assert r.ent.brand == "undercover" and r.tier != "X"
    # the name alone, with no matching season code, proves nothing
    assert run_one("HUNDREDCLUB パッチワーク クラスト scab デニムパンツ", price_usd=90, source="mercari_jp", region="JP").tier == "X"


def test_unknown_era_listing_is_not_valued_like_the_prized_era():
    def comp(i, era, price):
        return Comp(f"e:{i}", "mercari_jp", None, "t", "dior_homme", era, None, "denim", None, price, NOW - 86400, "JP")
    idx = CompsIndex([comp(i, "dior_homme__hedi", 700) for i in range(10)] + [comp(50 + i, None, 150) for i in range(6)],
                     load_taxonomy(), at=NOW)
    v = idx.value("dior_homme", None, None, "denim", "JP")
    assert v["median"] == 150                                  # unknown-era comps are the peers
    thin = CompsIndex([comp(i, "dior_homme__hedi", 700) for i in range(10)] + [comp(50, None, 150)],
                      load_taxonomy(), at=NOW).value("dior_homme", None, None, "denim", "JP")
    assert thin["conf"] == "low" and thin["era_pooled"]        # too few peers: pooled, and marked soft


def test_unknown_era_boots_keep_their_place_but_plain_tees_do_not():
    assert run_one("Dior Homme メダリオン レザーブーツ 41", price_usd=300, source="mercari_jp", region="JP").tier == "B"
    assert run_one("UNDERCOVER Tシャツ ホワイト ロゴプリント", price_usd=40, source="mercari_jp", region="JP").tier == "C"


def test_season_code_outranks_the_sellers_era_claim():
    """"08SS ... Hedi" was shown as Hedi Slimane; SS08 is the first season after he left."""
    r = run_one("Dior HOMME 2008 08ss 00s Hedi archive all pattern V Tee XXS", price_usd=100, source="yahoo_jp", region="JP")
    assert r.ent.era_conf < 0.5 and r.ent.era_conflict
    assert any(f["id"] == "needs_tag_pics" for f in r.explain["flags"]) and r.tier in ("B", "C")
    ok = run_one("Dior Homme 07AW エディ期 デニム 28", price_usd=300, source="mercari_jp", region="JP")
    assert ok.ent.era == "dior_homme__hedi" and ok.ent.era_conf >= 0.65
