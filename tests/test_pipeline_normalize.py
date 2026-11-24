from pipeline.normalize import (PhraseIndex, find_crossposts, landed_cost, norm_text, parse_size, size_fit,
                                condition_norm, tokenize)
from core.config import japan_costs

JC = japan_costs()


def toks(s):
    return [t.t for t in tokenize(norm_text(s))]


def test_fullwidth_and_kana_spacing():
    assert norm_text("ＤＩＯＲ　ＨＯＭＭＥ") == "dior homme"
    assert toks("リック オウエンス") == toks("リックオウエンス") == toks("リック・オウエンス")


def test_run_splitting_letters_digits():
    assert toks("07AW") == ["07", "aw"]
    assert toks("UNDERCOVER2018SS")[:1] == ["undercover"]


def test_short_alias_needs_whole_run():
    idx = PhraseIndex()
    idx.add("ss", "x")
    assert not idx.find(tokenize(norm_text("dior 04ss jeans")))
    assert idx.find(tokenize(norm_text("share spirit ss tee")))


def test_long_vowel_kept_no_false_zara():
    idx = PhraseIndex()
    idx.add("ザラ", "zara")
    assert not idx.find(tokenize(norm_text("レザーライダース")))
    assert idx.find(tokenize(norm_text("ザラ ニット")))


def test_latin_word_boundary():
    idx = PhraseIndex()
    idx.add("rick owens", 1)
    assert not idx.find(tokenize(norm_text("maverick owens shirt")))
    assert idx.find(tokenize(norm_text("RickOwens".replace("Owens", " owens"))))


def test_sizes():
    assert parse_size(None, norm_text("Dior Homme jeans W30"), "denim") == "W30"
    assert parse_size(None, norm_text("ディオールオム デニム 28"), "denim") == "W28"
    assert parse_size(None, norm_text("テーラードジャケット 46"), "blazer") == "46"
    assert parse_size(None, norm_text("ジオバスケット 27cm"), "sneakers") == "EU42.5"
    assert parse_size(None, norm_text("ナンバーナイン パーカー サイズ3"), "hoodie") == "L"
    assert parse_size("IT 48", norm_text("Rick Owens pants"), "pants") == "W32"


def test_size_fit_neutral_when_profile_empty():
    assert size_fit("W30", "denim", {})[0] == 1.0
    assert size_fit("W30", "denim", {"bottoms": ["W30"]})[0] == 1.0
    assert size_fit("W34", "denim", {"bottoms": ["W30"]})[0] < 0.5


def test_condition_mercari_ids():
    assert condition_norm("mercari_jp", "1", "") == 1.0
    assert condition_norm("mercari_jp", "6", "") == 0.25
    assert condition_norm("grailed", "is_gently_used", "") == 0.85
    assert condition_norm("mercari_jp", "3", "ジャンク") == 0.15


def test_landed_jp_duty_origin():
    jp = landed_cost("JP", 400, None, "medium", "ディオールオム デニム", 150.0, JC)
    it = landed_cost("JP", 400, None, "medium", "ディオールオム デニム イタリア製", 150.0, JC)
    assert jp["duty_usd"] == 50.0 and it["duty_usd"] == 60.0
    assert jp["landed_usd"] > 400 + 48
    us = landed_cost("US", 400, 15, "medium", "", 150.0, JC)
    assert us["landed_usd"] == 415
    ca = landed_cost("CA", 400, None, "light", "", 150.0, JC)
    assert ca["proxy_fee_usd"] == 0 and ca["landed_usd"] == 400 + 30 + 60


def test_crossposts_same_seller_and_cross_source():
    rows = [
        {"id": "a", "source": "mercari_jp", "seller_id": "mercari_jp:9", "title": "Dior Homme 04SS Strip denim 28", "price_usd": 500, "first_seen_at": 1},
        {"id": "b", "source": "mercari_jp", "seller_id": "mercari_jp:9", "title": "Dior Homme 04SS Strip denim 28", "price_usd": 480, "first_seen_at": 2},
        {"id": "c", "source": "mercari_jp", "seller_id": "mercari_jp:9", "title": "Dior Homme 04SS Strip denim 28", "price_usd": 500, "first_seen_at": 3, "size_norm": "W30"},
        {"id": "d", "source": "yahoo_jp", "seller_id": "y:1", "title": "Dior Homme 04SS Strip denim 28", "price_usd": 501, "first_seen_at": 4},
        {"id": "e", "source": "mercari_jp", "seller_id": "mercari_jp:0", "title": "Dior Homme 04SS Strip denim 28", "price_usd": 300, "first_seen_at": 5},
    ]
    out = find_crossposts(rows)
    assert out["b"] == "a" and out["d"] == "a"
    assert "c" not in out          # different size: not the same item
    assert "e" not in out          # shop placeholder seller id + different price
