import time

from core.taxonomy import load_taxonomy
from pipeline.comps import Comp, CompsIndex, classify_comp, wquantile

NOW = int(time.time())


def comp(i, price, days, **kw):
    d = dict(brand="dior_homme", era="dior_homme__hedi", season=None, archetype="denim", size_norm=None)
    d.update(kw)
    return Comp(f"c{i}", kw.pop("source", "mercari_jp"), f"https://x/{i}", "t", d["brand"], d["era"], d["season"],
                d["archetype"], d["size_norm"], price, NOW - days * 86400, "JP" if d.get("market", "JP") == "JP" else "US")


def test_weighted_quantile():
    assert wquantile([1, 2, 3], [1, 1, 1], 0.5) == 2
    assert 1 <= wquantile([1, 2, 3], [10, 1, 1], 0.5) < 1.5      # the heavy value dominates
    # small bimodal samples interpolate between the two middle values instead of jumping to the upper one
    assert abs(wquantile([226, 566, 786, 1823, 1886, 1886], [1] * 6, 0.5) - (786 + 1823) / 2) < 1e-6


def test_hierarchy_and_recency():
    tax = load_taxonomy()
    cs = [comp(i, 400 + i, i * 5) for i in range(10)] + [comp(100, 9000, 1)]   # outlier trimmed
    idx = CompsIndex(cs, tax, at=NOW)
    v = idx.value("dior_homme", "dior_homme__hedi", None, "denim", "JP")
    assert v["level"] == "era_archetype" and 400 <= v["median"] <= 410
    assert v["market"] == "JP" and len(v["comps"]) <= 8 and v["comps"][0]["url"]
    v = idx.value("dior_homme", "dior_homme__hedi", None, "leather_jacket", "JP")
    assert v["level"] == "brand"            # falls back
    assert v["conf"] == "low"


def test_price_band_and_none():
    idx = CompsIndex([], load_taxonomy(), at=NOW)
    v = idx.value("dior_homme", "dior_homme__hedi", "dior_homme__ss04", "denim", "US")
    assert v["level"] == "price_band" and v["conf"] == "low"
    assert idx.value("kmrii", None, None, "denim", "US")["level"] == "none"


def test_junk_comps_never_get_a_brand():
    assert classify_comp({"title": "Dior Sauvage EDT 100ml", "sold_price_usd": 80})["brand"] is None
    assert classify_comp({"title": "ナンバーナイン ニット 長袖シャツ他13点セット", "sold_price_usd": 900})["brand"] is None
    v = classify_comp({"title": "ディオールオム エディ期 04SS ストリップ デニム", "sold_price_usd": 900})
    assert v["brand"] == "dior_homme" and v["era"] == "dior_homme__hedi" and v["season"] == "dior_homme__ss04"
