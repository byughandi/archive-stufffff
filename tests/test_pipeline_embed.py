from pipeline.embed import Embedder, hamming, visual_grail_match


def test_tfidf_fallback_scores_grail_above_junk():
    e = Embedder(mode="off")
    assert e.backend == "tfidf-char+concepts"
    t, j = e.similarities(["Dior Homme SS04 Strip Hedi denim 29", "Chanel No 5 perfume 100ml"],
                          [["dior_homme", "dior_homme__hedi", "dior_homme__ss04", "denim"], []])
    assert t[0] > t[1]
    assert j[1] > j[0]


def test_cross_lingual_via_concepts():
    e = Embedder(mode="off")
    t, _ = e.similarities(["ディオールオム エディ期 デニム"], [["dior_homme", "dior_homme__hedi", "denim"]])
    t0, _ = e.similarities(["ディオールオム エディ期 デニム"], [[]])
    assert t[0] > t0[0]


def test_phash_helpers_and_clip_hook():
    assert hamming("ffff", "fffe") == 1
    assert visual_grail_match("http://x") is None
