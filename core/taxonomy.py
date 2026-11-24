"""Loads the YAML taxonomy once and exposes it as plain indexed dicts.

This is deliberately a thin loader. Matching logic lives in pipeline/classify.py and query
generation in scrapers/common/queries.py; both read from here so they agree on ids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from .config import TAXONOMY_DIR, load_yaml

UNKNOWN = "UNKNOWN"


def _clean(v):
    return None if v in (UNKNOWN, "", None) else v


@dataclass
class Taxonomy:
    brands: dict[str, dict]
    eras: dict[str, dict]
    seasons: dict[str, dict]
    archetypes: dict[str, dict]
    brand_archetypes: list[dict]
    exemplars: dict
    blocklist: dict
    ja: dict
    sellers: dict
    price_bands: list[dict]
    heat_list: list[dict]
    people: list[dict]
    eras_by_brand: dict[str, list[dict]] = field(default_factory=dict)
    seasons_by_brand: dict[str, list[dict]] = field(default_factory=dict)

    def trend_prior(self, brand: str | None, era: str | None = None, season: str | None = None,
                    archetype: str | None = None) -> float:
        """Most specific matching prior from the R3 heat list; 0.4 when nothing matches."""
        best, best_spec = None, -1
        for row in self.heat_list:
            if _clean(row.get("brand")) != brand:
                continue
            spec = 0
            ok = True
            for key, val in (("era", era), ("season", season), ("archetype", archetype)):
                want = _clean(row.get(key))
                if want is None:
                    continue
                if want != val:
                    ok = False
                    break
                spec += 1
            if ok and spec > best_spec:
                best, best_spec = float(row.get("trend_prior", 0.4)), spec
        return 0.4 if best is None else best


@lru_cache(maxsize=1)
def load_taxonomy() -> Taxonomy:
    def y(name):
        return load_yaml(str(TAXONOMY_DIR / f"{name}.yaml"))

    brands = {str(b["id"]): b for b in y("brands")["brands"]}
    eras = {e["id"]: e for e in y("eras")["eras"]}
    seasons = {s["id"]: s for s in y("seasons")["seasons"]}
    arch = y("archetypes")
    trends = y("trend_priors")
    tax = Taxonomy(
        brands=brands, eras=eras, seasons=seasons,
        archetypes={a["id"]: a for a in arch["archetypes"]},
        brand_archetypes=arch.get("brand_archetypes", []),
        exemplars=y("exemplars"), blocklist=y("blocklist"), ja=y("aliases_ja"), sellers=y("sellers"),
        price_bands=y("price_bands").get("bands", []),
        heat_list=trends.get("heat_list", []), people=trends.get("people", []),
    )
    for e in eras.values():
        tax.eras_by_brand.setdefault(str(e["brand"]), []).append(e)
    for s in seasons.values():
        tax.seasons_by_brand.setdefault(str(s["brand"]), []).append(s)
    return tax
