import pytest

from pipeline.classify import parse_codes
from pipeline.normalize import norm_text
from pipeline_util import classify


@pytest.mark.parametrize("text,half,year", [
    ("ss04", "ss", 2004), ("04ss", "ss", 2004), ("s/s 2004", "ss", 2004), ("2004ss", "ss", 2004),
    ("aw05", "aw", 2005), ("fw05", "aw", 2005), ("07AW", "aw", 2007), ("2007A/W", "aw", 2007),
    ("98-99AW", "aw", 1998), ("fall 2006", "aw", 2006), ("06秋冬", "aw", 2006),
])
def test_season_code_spellings(text, half, year):
    cs = [c for c in parse_codes(norm_text(text)) if c.kind == "code"]
    assert cs and cs[0].half == half and cs[0].year == year


def test_year_kanji_and_bare_year():
    assert any(c.year == 2007 and c.kind == "year_strong" for c in parse_codes(norm_text("2007年製")))
    assert not any(c.kind == "year" for c in parse_codes(norm_text("¥2000円 送料込み")))


def test_bare_dior_homme_is_era_unresolved():
    e = classify("Dior Homme jeans 30")
    assert e.brand == "dior_homme"
    assert e.era_conf < 0.5


def test_hedi_japanese_cues():
    e = classify("ディオールオム エディ期 07AW デニム 28")
    assert e.brand == "dior_homme" and e.era == "dior_homme__hedi" and e.era_conf >= 0.85
    assert e.season == "dior_homme__aw07" and e.archetype == "denim"
    assert any("エディ期" in c for c in e.era_cues)


def test_kva_and_kim_jones():
    assert classify("Dior Homme 2009 Kris Van Assche slim denim").era == "dior_homme__kva"
    e = classify("Dior Men Kim Jones Oblique hoodie 2019")
    assert e.era == "dior_men__kim_jones"


def test_contradiction_stays_unresolved():
    e = classify("Dior Homme Hedi 2019 bee tee")
    assert e.era_conf < 0.5


def test_slp_hedi_vs_vaccarello():
    assert classify("Saint Laurent Paris 13AW L01 leather jacket").era == "saint_laurent__hedi"
    assert classify("Saint Laurent SS18 crystal denim jacket").era == "saint_laurent__vaccarello"


def test_ambiguous_alias_needs_context():
    assert classify("Dior jacket black").brand is None
    assert classify("Dior 06SS washed denim エディ期").brand == "dior_homme"
    assert classify("Rick leather jacket").brand is None
    assert classify("Rick geobasket 43").brand == "rick_owens"


def test_common_word_season_alias_trap():
    e = classify("Rick Owens release tee black")
    assert e.season is None
    e = classify("Rick Owens SS10 release tank")
    assert e.season == "rick_owens__ss10"
    assert classify("Raf Simons waves tee").season is None
    assert classify("Raf Simons AW04 waves knit").season == "raf_simons__aw04"


def test_reference_brands_are_not_the_brand():
    assert classify("リックオウエンス似 ハイカットスニーカー").brand is None
    assert classify("厚底スニーカー ジオバスケット風").brand is None
    e = classify("Rick Owens Raf Simons 好きに y2k ジャケット")
    assert e.brand is None and set(e.reference_brands) == {"rick_owens", "raf_simons"}
    assert classify("ato スラックス 和製Dior HOMME").brand is None


def test_fuu_inside_other_words_does_not_trigger():
    e = classify("ディオールオム 風合い良好 デニム")
    assert e.brand == "dior_homme"


def test_japanese_variants():
    assert classify("ビューティビースト デニムジャケット").brand == "beauty_beast"
    assert classify("ナンバーナイン 06AW ノワール期 ニット").season == "number_nine__aw06"


def test_archetype_head_noun_last():
    assert classify("SAINT LAURENT PARIS リングブーツ").archetype == "boots"
    assert classify("Raf Simons 2002AW シャツフーディパーカー").archetype == "hoodie"
    assert classify("Saint Laurent L01 ライダース レザージャケット").archetype == "biker_jacket"


def test_brand_field_overrides_weak_title_match():
    e = classify("Tower of Light Jumbo SS T-Shirt", brand_raw="RICK OWENS DRKSHDW")
    assert e.brand == "rick_owens"


def test_current_retail_points_to_recent_era():
    e = classify("Tower Mountain Hoodie in Dark Dust", brand_raw="RICK OWENS", current_retail=True)
    assert e.era == "rick_owens__recent"
