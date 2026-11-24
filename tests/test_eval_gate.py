"""Quality gate: fails CI when scoring regresses on the labelled gold set (data/eval/labeled_listings.jsonl)."""
import json

from pipeline.run import GATE, evaluate, gate, load_baseline, load_eval


def test_eval_set_shape():
    rows = load_eval()
    assert len(rows) >= 200
    need = {"id", "origin", "lang", "source", "title", "description", "brand_raw", "price_usd", "label_relevant",
            "expect_brand", "expect_era", "expect_tier_max", "expect_tier_min", "note"}
    assert all(need <= set(r) for r in rows)
    eras = [r for r in rows if r["expect_brand"] in ("dior_homme", "saint_laurent", "celine", "balmain") and r["expect_era"]]
    assert len(eras) >= 30
    assert {r["origin"] for r in rows} >= {"real_mercari_jp", "handwritten_en"}


def test_gate():
    m = evaluate()
    fails = gate(m, load_baseline())
    if fails:
        print(json.dumps(m["details"], ensure_ascii=False, indent=1)[:6000])
    assert m["junk_rejection"] >= GATE["junk_rejection"]
    assert m["precision_at_50"] >= GATE["precision_at_50"]
    assert m["era_ok"] >= GATE["era_ok"]
    assert m["junk_patterns_failed"] == 0, m["details"]["junk_patterns_not_rejected"]
    assert not fails, fails
