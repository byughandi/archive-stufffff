"""Saved searches generated from the taxonomy (never "scrape everything") plus rotation.

JP sources: `aliases_ja.search_queries` + katakana brand x era term for core brands.
EN sources: brand alias x era alias (x archetype for the biggest brands) for brands in the
core / jp_archive / eu_archive groups, plus a few for rapper staples.

`next_queries()` rotates through them with the `search_cursor` table: priority is time since
the last run multiplied by the query weight, so core brands come round more often; queries
never run yet go first (heaviest first).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.db import Database, now
from core.taxonomy import Taxonomy, load_taxonomy

GROUP_WEIGHT = {"core": 3.0, "jp_archive": 2.0, "eu_archive": 1.5, "rapper_staple": 1.0}
BIG_BRAND_WEIGHT = 9          # base_weight at or above this also gets brand x era x archetype
TOP_ARCHETYPES = ("leather_jacket", "biker_jacket", "denim", "boots", "coat", "hoodie", "knit", "pants")
RAPPER_ARCHETYPES = ("hoodie", "graphic_tee", "jewelry")
MAX_ERA_ALIASES = 2


@dataclass(frozen=True)
class Query:
    query_id: str          # stable: lang:brand:era:archetype:text
    text: str
    lang: str
    brand: str | None = None
    era: str | None = None
    archetype: str | None = None
    weight: float = 1.0


def _w(tax: Taxonomy, brand_id: str | None) -> float:
    b = tax.brands.get(brand_id or "")
    if not b:
        return 1.0
    return GROUP_WEIGHT.get(b.get("group"), 1.0) * (float(b.get("base_weight", 5)) / 10.0 + 0.5)


def _dedupe(qs: list[Query]) -> list[Query]:
    """One query per distinct text (first wins); ids stay unique too."""
    seen: dict[str, Query] = {}
    texts: set[str] = set()
    for q in qs:
        if q.query_id in seen or q.text in texts:
            continue
        seen[q.query_id] = q
        texts.add(q.text)
    return list(seen.values())


def _arch_name(a: dict) -> str:
    return a["name"].split("/")[0].strip().lower()


def ja_queries(tax: Taxonomy | None = None) -> list[Query]:
    tax = tax or load_taxonomy()
    out: list[Query] = []
    texts: set[str] = set()
    for row in tax.ja.get("search_queries", []):
        text = str(row["query"]).strip()
        texts.add(text)
        out.append(Query(f"ja:{text}", text, "ja", row.get("brand"), row.get("era"), None, _w(tax, row.get("brand"))))
    ja_brands = tax.ja.get("brands", {})
    ja_eras = tax.ja.get("eras", {})
    for bid, brand in tax.brands.items():
        if brand.get("group") != "core":
            continue
        names = ja_brands.get(bid) or []
        if not names:
            continue
        kata = names[0]
        for era in tax.eras_by_brand.get(bid, []):
            for term in (ja_eras.get(era["id"]) or [])[:1]:
                text = term if kata in term else f"{kata} {term}"
                if text not in texts:
                    texts.add(text)
                    out.append(Query(f"ja:{text}", text, "ja", bid, era["id"], None, _w(tax, bid) * 0.8))
    return _dedupe(out)


def _brand_names(brand: dict) -> list[str]:
    names = [brand["name"].lower()]
    for a in brand.get("aliases", [])[:2]:
        if a.lower() not in names and len(a) > 3:
            names.append(a.lower())
    return names[:2]


def en_queries(tax: Taxonomy | None = None) -> list[Query]:
    tax = tax or load_taxonomy()
    out: list[Query] = []
    for bid, brand in tax.brands.items():
        group = brand.get("group")
        if group not in GROUP_WEIGHT:
            continue
        base = _w(tax, bid)
        name = brand["name"].lower()
        big = float(brand.get("base_weight", 0)) >= BIG_BRAND_WEIGHT and group == "core"
        if group == "rapper_staple":
            out.append(Query(f"en:{bid}::", name, "en", bid, None, None, base))
            for arch in RAPPER_ARCHETYPES[:2]:
                a = tax.archetypes.get(arch)
                if a:
                    out.append(Query(f"en:{bid}::{arch}", f"{name} {_arch_name(a)}", "en", bid, None, arch, base * 0.7))
            continue
        out.append(Query(f"en:{bid}::", name, "en", bid, None, None, base * 0.5))
        for era in tax.eras_by_brand.get(bid, []):
            era_terms: list[str] = []
            for a in [era.get("designer"), *era.get("aliases", [])]:
                if a and str(a).lower() not in era_terms and str(a).lower() != "unknown" and len(str(a)) > 2:
                    era_terms.append(str(a).lower())
            for bn in _brand_names(brand)[:1] if len(era_terms) > 1 else _brand_names(brand)[:2]:
                for term in era_terms[:MAX_ERA_ALIASES]:
                    text = term if bn in term else f"{bn} {term}"
                    out.append(Query(f"en:{bid}:{era['id']}:{'~'.join(text.split())}", text, "en", bid, era["id"], None, base))
            if big:
                for arch in TOP_ARCHETYPES:
                    a = tax.archetypes.get(arch)
                    if not a:
                        continue
                    term = era_terms[0] if era_terms else ""
                    text = " ".join(x for x in (name if name not in term else "", term, _arch_name(a)) if x)
                    out.append(Query(f"en:{bid}:{era['id']}:{arch}", text, "en", bid, era["id"], arch, base * 0.6))
    return _dedupe(out)


def queries_for(lang: str, tax: Taxonomy | None = None) -> list[Query]:
    return ja_queries(tax) if lang == "ja" else en_queries(tax)


# ---- rotation ---------------------------------------------------------------------------

def _priority(q: Query, row: dict | None, t: int) -> float:
    if row is None or not row.get("last_run_at"):
        return 1e12 + q.weight           # never run: first, heaviest first
    age = max(t - int(row["last_run_at"]), 1)
    hits = int(row.get("hits_total") or 0)
    kept = int(row.get("kept_total") or 0)
    yield_bonus = 1.0 + (kept / (hits + 20.0))   # queries that produce survivors come round a bit more
    return age * q.weight * yield_bonus


def next_queries(db: Database, source: str, queries: list[Query], n: int, at: int | None = None) -> list[Query]:
    t = at if at is not None else now()
    rows = {r["query_id"]: r for r in db.query("SELECT * FROM search_cursor WHERE source = ?", (source,))}
    ranked = sorted(queries, key=lambda q: (-_priority(q, rows.get(q.query_id), t), q.query_id))
    return ranked[:max(n, 0)]


def mark_run(db: Database, source: str, q: Query | str, top_id: str | None = None, hits: int = 0, kept: int = 0,
             at: int | None = None) -> None:
    qid = q if isinstance(q, str) else q.query_id
    db.execute(
        "INSERT INTO search_cursor (source, query_id, last_run_at, last_top_id, hits_total, kept_total)"
        " VALUES (?,?,?,?,?,?) ON CONFLICT(source, query_id) DO UPDATE SET last_run_at = excluded.last_run_at,"
        " last_top_id = COALESCE(excluded.last_top_id, last_top_id),"
        " hits_total = hits_total + excluded.hits_total, kept_total = kept_total + excluded.kept_total",
        (source, qid, at if at is not None else now(), top_id, hits, kept),
    )


# ---- coarse relevance guard (for engines that pad results with loosely matching items) -----------

def anchor_terms(q: Query, tax: Taxonomy | None = None) -> list[str]:
    """Lower-cased brand names (JA + EN) that a result should mention. Empty = no guard."""
    tax = tax or load_taxonomy()
    if not q.brand or q.brand not in tax.brands:
        return []
    b = tax.brands[q.brand]
    terms = {b["name"].lower(), *(a.lower() for a in b.get("aliases", []) if len(a) > 3)}
    terms |= {n.lower() for n in tax.ja.get("brands", {}).get(q.brand, [])}
    first = q.text.split()[0].lower() if q.text.split() else ""
    if first:
        terms.add(first)
    return sorted(terms)


def mentions(text: str, terms: list[str]) -> bool:
    t = text.lower()
    return not terms or any(x in t for x in terms)
