from core.taxonomy import load_taxonomy
from scrapers.common.queries import anchor_terms, en_queries, ja_queries, mark_run, mentions, next_queries


def test_ja_queries_include_yaml_and_katakana_era_terms_with_stable_unique_ids():
    tax = load_taxonomy()
    qs = ja_queries(tax)
    ids = [q.query_id for q in qs]
    assert len(ids) == len(set(ids))
    texts = {q.text for q in qs}
    assert all(r["query"] in texts for r in tax.ja["search_queries"])
    assert len(qs) > len(tax.ja["search_queries"])             # plus brand x era extras
    assert [q.query_id for q in ja_queries(tax)] == ids        # stable across calls


def test_en_queries_cover_groups_and_big_brands_get_archetypes():
    tax = load_taxonomy()
    qs = en_queries(tax)
    brands = {q.brand for q in qs}
    groups = {tax.brands[b]["group"] for b in brands}
    assert groups == {"core", "jp_archive", "eu_archive", "rapper_staple"}
    assert any(q.archetype for q in qs if tax.brands[q.brand]["group"] == "core")
    assert not any(q.archetype and q.brand == "soloist" for q in qs)       # small brands: no archetype fan-out
    assert len({q.query_id for q in qs}) == len(qs) and len({q.text for q in qs}) == len(qs)


def test_rotation_never_run_first_then_oldest_weighted(db):
    tax = load_taxonomy()
    qs = en_queries(tax)[:30]
    first = next_queries(db, "grailed", qs, 5, at=1000)
    assert len(first) == 5
    for q in first:
        mark_run(db, "grailed", q, at=1000)
    second = next_queries(db, "grailed", qs, 5, at=2000)
    assert not {q.query_id for q in first} & {q.query_id for q in second}      # unrun ones come first
    for q in qs:
        mark_run(db, "grailed", q, at=3000)
    heavy = max(qs, key=lambda q: q.weight)
    light = min(qs, key=lambda q: q.weight)
    mark_run(db, "grailed", heavy, at=4000)
    mark_run(db, "grailed", light, at=4000)
    # both are equally old; the heavier (core) one is due before the lighter one
    pick = next_queries(db, "grailed", [light, heavy], 2, at=9000)
    assert pick[0].query_id == heavy.query_id


def test_anchor_guard():
    tax = load_taxonomy()
    q = next(q for q in ja_queries(tax) if q.brand == "dior_homme")
    terms = anchor_terms(q, tax)
    assert mentions("Dior HOMME 04AW デニム", terms) and mentions("ディオールオム ジャケット", terms)
    assert not mentions("BLUE BLUE western shirt", terms)
