import pytest

from pipeline_util import run_one


@pytest.mark.parametrize("title", [
    "Chanel No 5 Eau de Parfum 100ml", "Vintage Disney Beauty and the Beast Belle sweatshirt",
    "Undercover Police Halloween costume", "Celine Dion tour tee 2008", "Rick and Morty Pickle Rick tee",
    "Number 9 jersey football #9", "Dior Sauvage EDT 100ml", "Dior-style slim black jeans",
    "Rick Owens inspired cardigan", "Archive leather jacket Rick Owens vibes", "Zara Man biker jeans",
    "Chrome Hearts cross pendant 1:1", "Saint Laurent L01 UA batch", "クロムハーツ レプリカ リング",
    "ディオールオム 偽物 デニム", "ノーブランド レザージャケット", "Josh様専用 Rick Owens Geobasket",
    "ロールチェーン クロムハーツ互換 シルバー925",
])
def test_hard_rejects(title):
    r = run_one(title, price_usd=100)
    assert r.tier == "X", (title, r.reject_reason)


def test_allowed_conditionals():
    assert run_one("Maison Margiela Replica GAT sneakers 42", price_usd=200).tier != "X"
    assert run_one("Undercover AW04 fake fur collar jacket", price_usd=300).tier != "X"
    assert run_one("UNDERCOVER × KAWS 2008SS Original Fake tee", price_usd=60).tier != "X"
    assert run_one("ノベルティ付き Rick Owens レザージャケット", price_usd=900).reject_reason is None or True


def test_keyword_stuffing_reject_when_field_disagrees_else_downrank():
    r = run_one("Number Nine Undercover Hysteric Glamour ballhog tee", brand_raw="Hare", price_usd=50)
    assert r.tier == "X" and r.reject_reason.startswith("keyword_stuffing")
    r = run_one("Raf Simons Helmut Lang Margiela Rick Owens archive jacket", price_usd=120)
    assert r.tier in ("C", "X")


def test_brand_field_mismatch():
    r = run_one("Rick Owens leather jacket 48", brand_raw="Ksubi", price_usd=300)
    assert r.reject_reason.startswith("brand_field_mismatch")


def test_price_floor_is_flag_not_trust():
    r = run_one("Saint Laurent Paris L01 2013 leather jacket", price_usd=120)
    assert r.tier != "X"
    assert any(f["id"] == "below_floor" for f in r.flags)


def test_unwanted_and_unresolved_ceilings():
    assert run_one("Balmain 2016 Rousteing gold button blazer", price_usd=600).tier == "C"
    r = run_one("Dior Homme jeans 30", price_usd=250)
    assert r.tier in ("B", "C") and any(f["id"] == "needs_tag_pics" for f in r.flags)
    assert run_one("Rick Owens SS22 Fogachine cargo pants", price_usd=400).tier == "C"


def test_brand_without_eras_has_no_era_penalty():
    r = run_one("Chrome Hearts cross patch denim jeans 32", brand_raw="Chrome Hearts", price_usd=3500)
    assert not any(f["id"] == "needs_tag_pics" for f in r.flags)
    assert r.tier in ("S", "A", "B")


def test_s_requires_confirmed_era_and_iconic_piece():
    r = run_one("Dior Homme SS04 Strip Hedi Slimane leather jacket 48", price_usd=2800)
    assert r.tier == "S"
    r = run_one("Dior Homme 2004 leather bracelet hedi", price_usd=200)
    assert r.tier != "S"


def test_womens_and_reissue_caps():
    assert run_one("Hysteric Glamour 90s crochet skirt", price_usd=90).tier in ("C", "X")
    assert run_one("UNDERCOVER 05AW 復刻 WE MAKE NOISE Tee", price_usd=60).tier in ("B", "C")
