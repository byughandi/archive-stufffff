"""Stage 2: deterministic, explainable taxonomy matching (brand, line, era, season, archetype).

Everything that fires is recorded so `listing_entities.matched` and `explain.entities` can show it.

Brand: aliases (EN + JA) are strong; `ambiguous_aliases` (and JA strings listed under `ambiguous_brands` in
aliases_ja.yaml) count only with supporting context: an era alias, a season code or season name, a model name of
that brand, or the marketplace brand field. A brand mention followed by a "reference" marker (風, 似, タイプ, 系,
っぽい, 好き, など, 等, 互換, style, type, vibes, inspired ...) is a reference, not the brand.

Era: every era of the matched brand is scored from independent cues (era aliases incl. JA terms like エディ期,
season codes in every common spelling, years, season names, model names, keywords, made-in, generic JA cues
like 初期 / 本人期) and anti-cues push the other way. `era_conf` = (1 - exp(-s/2.5)) * dominance. Nothing is
assumed: a bare "Dior Homme jeans" is era-unresolved with conf 0.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from core.taxonomy import Taxonomy, load_taxonomy

from .normalize import Match, PhraseIndex, Token, longest_only, norm_text, tok_strings, tokenize

CURRENT_YEAR = 2026
KIND_CAP = {"model": 1.5, "keyword": 1.0, "made_in": 0.3}   # max total per era from one cue kind

# --------------------------------------------------------------------------------------------- season codes
_HALF = {"ss": "ss", "s/s": "ss", "s-s": "ss", "aw": "aw", "fw": "aw", "a/w": "aw", "f/w": "aw",
         "春夏": "ss", "秋冬": "aw", "spring": "ss", "summer": "ss", "fall": "aw", "autumn": "aw",
         "winter": "aw", "spring/summer": "ss", "fall/winter": "aw", "autumn/winter": "aw"}
_HW = r"(ss|aw|fw|s/s|a/w|f/w)"
# "fw14", "fw 14", "fw/14", "fw'14", "f/w 2014"
_CODE_A = re.compile(rf"(?<![a-z0-9]){_HW}\s?[/.]?\s?'?(\d{{4}}|\d{{2}})(?:\s?-\s?(?:\d{{2,4}}))?(?![0-9])")
# "14fw", "2014 aw", "07秋冬". The digits must not be the tail of a model name ("L01 FW/14" is not "01 FW").
_CODE_B = re.compile(rf"(?<![a-z0-9.])(\d{{4}}|\d{{2}})(?:\s?-\s?(\d{{2,4}}))?\s?{_HW[:-1]}|春夏|秋冬)")
_CODE_C = re.compile(r"(?<![a-z])(spring/summer|fall/winter|autumn/winter|spring|summer|fall|autumn|winter)\s?'?(\d{4}|\d{2})(?![0-9])")
_YEAR_JA = re.compile(r"(?<![0-9])(\d{4}|\d{2})\s?年(?!代)")
_YEAR = re.compile(r"(?<![0-9a-z.,/¥$#])(19[89]\d|20[0-2]\d)(?![0-9]|\s?(?:円|yen|cm|mm|g\b|点))")
_DECADE = re.compile(r"(?<![0-9])(80|90|00|10)\s?(?:'?s|年代)(?![a-z])")
_Y2K = re.compile(r"(?<![a-z0-9])y2k(?![a-z0-9])")
_CHANEL = re.compile(r"(?<![0-9a-z])(\d{2})\s?([pacv])(?![a-z0-9])")


@dataclass(slots=True)
class Code:
    half: str | None     # 'ss' | 'aw' | None
    year: int
    kind: str            # code | year_strong | year | decade
    raw: str
    pos: int


def _yy(s: str) -> int | None:
    v = int(s)
    if len(s) == 4:
        y = v
    else:
        y = 2000 + v if v <= (CURRENT_YEAR - 2000 + 1) else 1900 + v
    return y if 1975 <= y <= CURRENT_YEAR + 1 else None


def parse_codes(norm: str, chanel: bool = False) -> list[Code]:
    out: list[Code] = []
    taken: list[tuple[int, int]] = []

    def add(m, half, ys, kind):
        y = _yy(ys)
        if y is None:
            return
        if any(a <= m.start() < b or a < m.end() <= b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        out.append(Code(half, y, kind, m.group(0).strip(), m.start()))

    for m in _CODE_A.finditer(norm):
        add(m, _HALF[m.group(1)], m.group(2), "code")
    for m in _CODE_B.finditer(norm):
        add(m, _HALF[m.group(3)], m.group(1), "code")
    for m in _CODE_C.finditer(norm):
        add(m, _HALF[m.group(1)], m.group(2), "code")
    for m in _YEAR_JA.finditer(norm):
        add(m, None, m.group(1), "year_strong")
    for m in _YEAR.finditer(norm):
        add(m, None, m.group(1), "year")
    if chanel:
        for m in _CHANEL.finditer(norm):
            add(m, "ss" if m.group(2) in "pc" else "aw", m.group(1), "code")
    for m in _DECADE.finditer(norm):
        d = int(m.group(1))
        y = 2000 + d if d <= 20 else 1900 + d
        if not any(a <= m.start() < b for a, b in taken):
            out.append(Code(None, y, "decade", m.group(0), m.start()))
    for m in _Y2K.finditer(norm):
        out.append(Code(None, 2000, "decade", "y2k", m.start()))
    return out


def is_code_like(phrase: str) -> bool:
    """True if a phrase is just a season code / year (those are handled by parse_codes, never double counted)."""
    n = norm_text(phrase)
    if re.fullmatch(r"(19|20)\d\d|\d\d'?s|\d\ds", n):
        return True
    cs = [c for c in parse_codes(n) if c.kind in ("code", "year_strong", "year")]
    if not cs:
        return False
    rest = n
    for c in cs:
        rest = rest.replace(c.raw, " ")
    return len(rest.strip()) == 0


# --------------------------------------------------------------------------------------------- markers
_REF_AFTER = [tok_strings(p) for p in (
    "風", "似", "タイプ", "系", "っぽい", "ぽい", "好き", "好", "など", "等", "互換", "適合", "対応", "ライク", "テイスト",
    "style", "type", "inspired", "vibe", "vibes", "esque", "-style", "like", "look", "lookalike", "dupe")]
_STYLE_OK_NEXT = {"no", "number", "num", "code", "#", "id"}
_FUU_EXCLUDE = set("合景船車呂味格邪神貌潮雅情土習俗速力向化刺流紀鈴")
_REF_BEFORE = [tok_strings(p) for p in ("和製", "like", "similar to", "inspired by", "alternative to")]
_COLLAB = {"x", "×", "+", "&", "collab", "コ", "by", "with"}
_SEP = {"/", "&", "+", "や", "と", "-", "(", ")", ":", "×", "x", "'", ".", "*", "#"}


@dataclass
class Entities:
    brand: str | None = None
    brand_conf: float = 0.0
    brand_matched: list[str] = field(default_factory=list)
    brand_via: str | None = None                 # alias | ja | ambiguous+context | brand_field
    brands_all: list[str] = field(default_factory=list)      # every non-reference brand found, in order
    collab_brands: list[str] = field(default_factory=list)
    reference_brands: list[str] = field(default_factory=list)  # mentioned only as "X風 / X style / X好き"
    reference_matches: list[str] = field(default_factory=list)
    brand_refs: list[str] = field(default_factory=list)   # "alias+marker" hits attached to the PICKED brand
    line: str | None = None
    era: str | None = None
    era_conf: float = 0.0
    era_cues: list[str] = field(default_factory=list)
    era_anti: list[str] = field(default_factory=list)
    era_scores: dict = field(default_factory=dict)
    era_conflict: bool = False
    season: str | None = None
    season_conf: float = 0.0
    season_matched: list[str] = field(default_factory=list)
    archetype: str | None = None
    archetype_matched: list[str] = field(default_factory=list)
    grail_piece: dict | None = None
    model_entry: dict | None = None
    model_matched: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)       # canonical ids for the TF-IDF fallback

    def matched_json(self) -> dict:
        return {
            "brand": {"matched": self.brand_matched, "via": self.brand_via, "all": self.brands_all,
                      "collab": self.collab_brands, "references": self.reference_brands},
            "era": {"cues": self.era_cues, "anti_cues": self.era_anti,
                    "scores": {k: round(v, 2) for k, v in self.era_scores.items()}, "conflict": self.era_conflict},
            "season": self.season_matched, "archetype": self.archetype_matched,
            "piece": self.grail_piece.get("name") if self.grail_piece else None,
            "model": self.model_matched, "codes": self.codes, "line": self.line,
        }


@dataclass
class BrandCues:
    era_idx: PhraseIndex
    season_idx: PhraseIndex
    piece_idx: PhraseIndex
    model_idx: PhraseIndex
    line_idx: PhraseIndex
    eras: list[dict]
    seasons_by_code: dict
    earliest_era: str | None


class Matcher:
    def __init__(self, tax: Taxonomy):
        self.tax = tax
        self.season_name_idx = PhraseIndex()
        for sdef in tax.seasons.values():
            if float(sdef.get("weight", 0)) >= 8:
                for a in sdef.get("aliases") or []:
                    if not is_code_like(a) and len(norm_text(a)) >= 4:
                        self.season_name_idx.add(a, sdef["id"])
        self.brand_idx = PhraseIndex()
        ja = tax.ja or {}
        ja_amb = {str(k): set(v or []) for k, v in (ja.get("ambiguous_brands") or {}).items()}
        for bid, b in tax.brands.items():
            amb = set(b.get("ambiguous_aliases") or [])
            for a in b.get("aliases") or []:
                kind = "dual" if a in amb else "alias"
                self.brand_idx.add(a, (bid, kind))
                parts = a.split()
                if len(parts) > 1 and all(p.isalpha() and p.isascii() for p in parts):
                    joined = "".join(parts)
                    if len(joined) >= 8:
                        self.brand_idx.add(joined, (bid, kind))
            for a in amb:
                if a not in (b.get("aliases") or []):
                    self.brand_idx.add(a, (bid, "ambiguous"))
            for a in (ja.get("brands") or {}).get(bid, []) or []:
                self.brand_idx.add(str(a), (bid, "ja_ambiguous" if str(a) in ja_amb.get(bid, set()) else "ja"))
            for a in ja_amb.get(bid, set()):
                self.brand_idx.add(str(a), (bid, "ja_ambiguous"))
        # archetypes
        self.arch_idx = PhraseIndex()
        weak = set((tax.ja.get("weak_archetype_terms") or [])) | {"chain", "pin", "cuff", "tie", "sweat", "runner",
                                                                   "pullover", "boot", "vest tailored", "kicks",
                                                                   "シルバー", "SV925", "925 silver", "シューズ"}
        for aid, a in tax.archetypes.items():
            for al in a.get("aliases") or []:
                self.arch_idx.add(al, (aid, al in weak))
            for al in (ja.get("archetypes") or {}).get(aid, []) or []:
                self.arch_idx.add(str(al), (aid, str(al) in weak))
        # global JA generic era terms
        self.generic_idx = PhraseIndex()
        self.generic_idx.add_many(["初期", "最初期", "初期型"], "early")
        # negative / reference markers handled in filter; brand-scoped cue indexes built lazily
        self._cues: dict[str, BrandCues] = {}
        self.ba_by_brand: dict[str, list[dict]] = {}
        for e in tax.brand_archetypes:
            self.ba_by_brand.setdefault(str(e["brand"]), []).append(e)

    # ------------------------------------------------------------------ brand-scoped cue index
    def cues(self, bid: str) -> BrandCues:
        c = self._cues.get(bid)
        if c:
            return c
        tax = self.tax
        brand = tax.brands[bid]
        brand_alias_toks = {tok_strings(a) for a in (brand.get("aliases") or []) + (brand.get("ambiguous_aliases") or [])
                            + [str(x) for x in ((tax.ja.get("brands") or {}).get(bid) or [])]}
        era_idx, season_idx, piece_idx, model_idx, line_idx = (PhraseIndex() for _ in range(5))
        eras = tax.eras_by_brand.get(bid, [])
        ja_eras = (tax.ja.get("eras") or {})
        for e in eras:
            eid = e["id"]
            # an era alias that is also a plain brand name ("martin margiela", "マルタンマルジェラ") is weak evidence:
            # sellers use the old name for every period
            for a in (e.get("aliases") or []):
                if not is_code_like(a):
                    era_idx.add(a, (eid, "alias", 1.0 if tok_strings(a) in brand_alias_toks else 3.0))
            for a in ja_eras.get(eid, []) or []:
                era_idx.add(str(a), (eid, "alias", 1.0 if tok_strings(str(a)) in brand_alias_toks else 3.0))
            cues = e.get("cues") or {}
            for k in cues.get("keywords") or []:
                if is_code_like(k):
                    continue
                if tok_strings(k) in brand_alias_toks:
                    continue   # the brand's own name ("saint laurent paris") is not evidence for one era over another
                era_idx.add(k, (eid, "keyword", 1.0))
            for k in cues.get("model_names") or []:
                if isinstance(k, str) and k != "UNKNOWN":
                    era_idx.add(k, (eid, "model", 1.5))
            for k in cues.get("made_in") or []:
                if isinstance(k, str) and k != "UNKNOWN":
                    era_idx.add(f"made in {k}", (eid, "made_in", 0.3))
            for k in e.get("anti_cues") or []:
                if is_code_like(k):
                    continue
                era_idx.add(k, (eid, "anti", -2.0))
        seasons_by_code: dict = {}
        for s in tax.seasons_by_brand.get(bid, []):
            code = str(s.get("code") or "").lower()
            if code and len(code) == 4:
                seasons_by_code[(code[:2].replace("fw", "aw"), int(s["year"]))] = s
            for a in s.get("aliases") or []:
                if not is_code_like(a) and tok_strings(a) not in brand_alias_toks:
                    season_idx.add(a, (s["id"], "name"))
            for a in s.get("ambiguous_aliases") or []:
                season_idx.add(a, (s["id"], "ambiguous"))
            for p in s.get("grail_pieces") or []:
                for a in p.get("aliases") or []:
                    piece_idx.add(a, (s["id"], p))
        for e in self.ba_by_brand.get(bid, []):
            for mn in e.get("model_names") or []:
                model_idx.add(mn, e)
        for ln in brand.get("lines") or []:
            for a in ln.get("aliases") or []:
                line_idx.add(a, ln["id"])
        earliest = min(eras, key=lambda e: e["years"][0])["id"] if eras else None
        c = BrandCues(era_idx, season_idx, piece_idx, model_idx, line_idx, eras, seasons_by_code, earliest)
        self._cues[bid] = c
        return c

    # ------------------------------------------------------------------ helpers
    def resolve_brand_field(self, brand_raw: str | None) -> str | None:
        """Map a marketplace brand/designer field to a brand id (ambiguous aliases allowed: it is a structured field)."""
        if not brand_raw:
            return None
        toks = tokenize(norm_text(brand_raw))
        ms = longest_only(self.brand_idx.find(toks))
        if not ms:
            return None
        ms.sort(key=lambda m: (m.i, -(m.j - m.i)))
        return ms[0].payload[0]

    @staticmethod
    def _is_reference(toks: list[Token], m_end: int, brand_spans: list[tuple[int, int]]) -> str | None:
        """Return the marker if the brand mention at [.., m_end) is followed (through other brand mentions and
        separators only) by a reference marker."""
        k = m_end
        n = len(toks)
        while k < n:
            span = next((s for s in brand_spans if s[0] == k), None)
            if span:
                k = span[1]
                continue
            if toks[k].t in _SEP:
                k += 1
                continue
            break
        if k >= n:
            return None
        for mk in _REF_AFTER:
            L = len(mk)
            if tuple(t.t for t in toks[k:k + L]) == mk:
                if mk == ("風",) and k + 1 < n and toks[k + 1].t in _FUU_EXCLUDE:
                    return None
                if mk == ("style",) and k + 1 < n and toks[k + 1].t in _STYLE_OK_NEXT:
                    return None
                if mk == ("系",) and k + 1 < n and toks[k + 1].t in ("列",):
                    return None
                if mk in (("look",), ("like",)) and k + 1 < n and toks[k + 1].t not in ("風",):
                    # "look"/"like" right after a brand is "X look jacket" -> reference only at title end or before archetype words
                    return "".join(mk) if mk == ("like",) else None
                return "".join(mk)
        return None

    # ------------------------------------------------------------------ main entry
    def classify(self, title: str, description: str | None = None, brand_raw: str | None = None,
                 norm: str | None = None, current_retail: bool = False) -> Entities:
        tnorm = norm if norm is not None else norm_text(title)
        dnorm = norm_text(description) if description else ""
        full = tnorm + (" \n " + dnorm if dnorm else "")
        toks = tokenize(tnorm)
        dtoks = tokenize(dnorm) if dnorm else []
        ent = Entities()

        # ---- brand candidates (title first, description only adds context)
        bm = longest_only(self.brand_idx.find(toks))
        spans = [(m.i, m.j) for m in bm]
        field_brand = self.resolve_brand_field(brand_raw)
        cand: dict[str, dict] = {}
        for m in sorted(bm, key=lambda m: m.i):
            bid, kind = m.payload
            ref = self._is_reference(toks, m.j, spans)
            if not ref:
                for mk in _REF_BEFORE:
                    if m.i >= len(mk) and tuple(t.t for t in toks[m.i - len(mk):m.i]) == mk:
                        ref = "".join(mk) + "(before)"
            c = cand.setdefault(bid, {"kinds": set(), "matched": [], "pos": m.i, "refs": [], "nonref": 0})
            c["matched"].append(m.phrase)
            if ref:
                c["refs"].append(f"{m.phrase}+{ref}")
            else:
                c["kinds"].add(kind)
                c["nonref"] += 1
        codes = parse_codes(full, chanel=("chanel" in cand))
        if current_retail:   # a current-season retail shop: the piece is from this year whatever the title says
            codes.append(Code(None, CURRENT_YEAR, "year_strong", "current retail stock", 0))
        ent.codes = [c.raw for c in codes]
        strong_codes = [c for c in codes if c.kind in ("code", "year_strong") and c.raw != "current retail stock"]

        def has_context(bid: str) -> bool:
            if field_brand == bid:
                return True
            if strong_codes:
                return True
            bc = self.cues(bid)
            for mm in bc.era_idx.find(toks) + (bc.era_idx.find(dtoks) if dtoks else []):
                if mm.payload[1] in ("alias", "model"):
                    return True
            if bc.season_idx.find(toks) or bc.model_idx.find(toks) or bc.piece_idx.find(toks):
                return True
            return False

        confirmed: list[tuple[int, str, float, str]] = []
        for bid, c in cand.items():
            if c["nonref"] == 0:
                ent.reference_brands.append(bid)
                ent.reference_matches += c["refs"]
                continue
            kinds = c["kinds"]
            if kinds & {"alias", "ja"}:
                conf, via = (0.98 if c["nonref"] > 1 else 0.95), ("ja" if "ja" in kinds and "alias" not in kinds else "alias")
            elif "dual" in kinds:
                conf, via = 0.85, "alias"
            elif has_context(bid):
                conf, via = 0.7, "ambiguous+context"
            else:
                continue
            if c["refs"]:
                ent.reference_matches += c["refs"]
            confirmed.append((c["pos"], bid, conf, via))
        confirmed.sort()
        ent.brands_all = [b for _, b, _, _ in confirmed]
        if confirmed:
            pick = confirmed[0]
            if field_brand and any(b == field_brand for _, b, _, _ in confirmed):
                pick = next(x for x in confirmed if x[1] == field_brand)
            elif field_brand and pick[3] == "ambiguous+context" and not cand.get(field_brand, {}).get("refs"):
                # a weak title match never overrides the marketplace brand field
                pick = (pick[0], field_brand, 0.8, "brand_field")
                confirmed = [pick] + [x for x in confirmed if x[1] != pick[1] and x[3] != "ambiguous+context"]
                ent.brands_all = [b for _, b, _, _ in confirmed]
            _, ent.brand, ent.brand_conf, ent.brand_via = pick
            ent.brand_matched = cand[ent.brand]["matched"] if ent.brand in cand else [brand_raw or ""]
            ent.brand_refs = list(cand[ent.brand]["refs"]) if ent.brand in cand else []
            # collab partners: brands joined to the primary by x / × / + / collab
            for pos, bid, _, _ in confirmed:
                if bid == ent.brand or bid not in cand or ent.brand not in cand:
                    continue
                a, b = sorted([cand[bid]["pos"], cand[ent.brand]["pos"]])
                between = [t.t for t in toks[a:b + 6]]
                if any(t in _COLLAB for t in between) or "コラボ" in tnorm or "collab" in tnorm:
                    ent.collab_brands.append(bid)
        elif field_brand and not cand.get(field_brand, {}).get("refs"):
            ent.brand, ent.brand_conf, ent.brand_via = field_brand, 0.7, "brand_field"
            ent.brand_matched = [brand_raw or ""]
            ent.brands_all = [field_brand]

        if not ent.brand:
            # No brand in the title, but a grail season's own name next to that season's code is as good as
            # a signature: "03ss scab期" can only be Undercover. The code must agree on the year.
            for m in self.season_name_idx.find(toks):
                sdef = self.tax.seasons[m.payload]
                half = str(sdef.get("code") or "")[:2].lower().replace("fw", "aw")
                if any(c.kind == "code" and c.year == int(sdef["year"]) and (c.half is None or c.half == half) for c in codes):
                    ent.brand, ent.brand_conf, ent.brand_via = str(sdef["brand"]), 0.6, "season_name"
                    ent.brand_matched, ent.brands_all = [m.phrase], [str(sdef["brand"])]
                    break
        # ---- archetype (needs brand for model names)
        self._archetype(ent, toks)
        if ent.brand:
            self._brand_scoped(ent, toks, dtoks, codes, tnorm)
        ent.concepts = [x for x in (ent.brand, ent.era if ent.era_conf >= 0.5 else None, ent.season, ent.archetype) if x]
        return ent

    def _archetype(self, ent: Entities, toks: list[Token]) -> None:
        ms = longest_only(self.arch_idx.find(toks))
        if not ms:
            return
        strong = [m for m in ms if not m.payload[1]]
        pool = strong or ms
        ids = [m.payload[0] for m in sorted(pool, key=lambda m: m.i)]
        # the head noun comes last in both English and Japanese ("ring boots", "リングブーツ", "knit hoodie")
        pick = ids[-1]
        s = set(ids)
        # tie-breaks: a biker leather jacket is a biker jacket; a denim jacket stays denim; JP パーカー = hoodie
        if "biker_jacket" in s and pick in ("leather_jacket", "coat", "blazer"):
            pick = "biker_jacket"
        if pick == "blazer" and len(s) > 1:   # "ジャケット" is generic; any more specific word wins
            pick = [i for i in ids if i != "blazer"][-1]
        if pick == "coat" and "hoodie" in s and any(m.phrase == "パーカー" for m in pool):
            pick = "hoodie"
        ent.archetype = pick
        ent.archetype_matched = [m.phrase for m in pool if m.payload[0] == pick]

    def _brand_scoped(self, ent: Entities, toks, dtoks, codes: list[Code], tnorm: str) -> None:
        tax = self.tax
        bc = self.cues(ent.brand)
        all_toks = toks + dtoks
        # line
        lm = bc.line_idx.find(toks)
        if lm:
            ent.line = lm[0].payload
        # model names (brand_archetypes)
        mm = longest_only(bc.model_idx.find(toks))
        season_names = {m.phrase for m in bc.season_idx.find(toks)}
        if mm:
            ent.model_matched = [m.phrase for m in mm]
            ent.model_entry = mm[0].payload
            if not ent.archetype and mm[0].phrase not in season_names:
                ent.archetype = mm[0].payload.get("archetype")
                ent.archetype_matched = [mm[0].phrase]
        # seasons by name
        scores: dict[str, float] = {e["id"]: 0.0 for e in bc.eras}
        cues: list[str] = []
        anti: list[str] = []
        season_hits: list[tuple[str, float, str]] = []
        for m in longest_only(bc.season_idx.find(toks)):
            sid, kind = m.payload
            s = tax.seasons[sid]
            if kind == "ambiguous":
                nxt = toks[m.j].t if m.j < len(toks) else ""
                ok = nxt == "期" or any(c.kind == "code" and c.year == int(s["year"]) and
                                         (c.half is None or str(s.get("code", "")).lower().startswith(c.half))
                                         for c in codes)
                if not ok:
                    continue
                season_hits.append((sid, 0.85, m.phrase))
            else:
                season_hits.append((sid, 0.8, m.phrase))
        # seasons by code
        for c in codes:
            if c.kind == "code" and c.half:
                s = bc.seasons_by_code.get((c.half, c.year))
                if s:
                    season_hits.append((s["id"], 0.9, c.raw))
        # An explicit season code outranks a season name: sellers append other seasons' names as keywords
        # ("1997AW ... scab but beautiful"). Keep a name-matched season only if a stated code agrees on the year.
        code_years = {c.year for c in codes if c.kind == "code"}
        if code_years:
            season_hits = [h for h in season_hits if h[1] >= 0.9 or int(tax.seasons[h[0]]["year"]) in code_years]
        # grail pieces
        pm = longest_only(bc.piece_idx.find(toks))
        if pm:
            sid, piece = pm[0].payload
            ent.grail_piece = dict(piece, season=sid, matched=pm[0].phrase)
            if not ent.archetype and piece.get("archetype"):
                ent.archetype = piece["archetype"]
                ent.archetype_matched = [pm[0].phrase]
        # era evidence --------------------------------------------------
        if bc.eras:
            by_era: dict[str, list[Match]] = {}
            for m in bc.era_idx.find(all_toks):
                by_era.setdefault(m.payload[0], []).append(m)
            for eid, ms in by_era.items():
                best: dict[str, tuple[float, str]] = {}
                for m in longest_only(ms):          # longest-match within one era, each phrase counted once
                    _, kind, w = m.payload
                    key = norm_text(m.phrase)
                    if key not in best or abs(w) > abs(best[key][0]):
                        best[key] = (w, kind)
                used: dict[str, float] = {}
                for ph, (w, kind) in best.items():
                    cap = KIND_CAP.get(kind)
                    if cap is not None and w > 0:   # several weak cues of one kind do not add up to proof
                        w = max(0.0, min(w, cap - used.get(kind, 0.0)))
                        used[kind] = used.get(kind, 0.0) + w
                    scores[eid] += w
                    if w < 0:
                        anti.append(f"{ph}\x00{eid}")   # evidence against era `eid`; resolved to text below
                    else:
                        cues.append(ph + ("" if kind == "alias" else f" ({kind})"))
            for sid, conf, raw in season_hits:
                eid = tax.seasons[sid].get("era")
                if eid in scores:
                    scores[eid] += 3.0
                    cues.append(f"{raw} (season {tax.seasons[sid].get('code')})")
            used_years = {(tax.seasons[s].get("year")) for s, _, _ in season_hits}
            for c in codes:
                if c.kind == "code" and c.half and bc.seasons_by_code.get((c.half, c.year)):
                    continue  # already counted as a season hit
                w = {"code": 3.0, "year_strong": 2.0, "year": 2.0, "decade": 0.5}[c.kind]
                if c.raw == "y2k":
                    w = 0.3
                if c.kind != "decade" and c.year in used_years:
                    continue
                if c.kind == "decade":
                    hits = [e for e in bc.eras if _overlap(e["years"], c.year, c.year + 9)]
                else:
                    hits = [e for e in bc.eras if _in_era(e["years"], c.year)]
                if not hits or len(hits) == len(bc.eras) and c.kind == "decade":
                    continue
                for e in hits:
                    scores[e["id"]] += w / len(hits)
                cues.append(f"{c.raw} ({c.kind})")
            for m in self.generic_idx.find(toks):
                if bc.earliest_era and len(bc.eras) > 1:
                    scores[bc.earliest_era] += 2.0
                    cues.append(f"{m.phrase} (early)")
                    break
            pos = {k: max(0.0, v) for k, v in scores.items()}
            tot = sum(pos.values())
            ent.era_scores = {k: v for k, v in scores.items() if v != 0}
            # Evidence against a losing era supports the winner; only evidence against the winner itself is
            # counter-evidence worth showing. Named by designer, never by internal id.
            lead = max(pos, key=pos.get) if tot > 0 else None
            shown: list[str] = []
            for item in anti:
                ph, _, eid = item.partition("\x00")
                who = tax.eras.get(eid, {}).get("designer") or eid
                text = f"{ph} (points away from {who})" if eid == lead or lead is None else f"{ph} (rules out {who})"
                (shown if eid == lead or lead is None else cues).append(text)
            ent.era_cues, ent.era_anti = cues, shown
            if tot > 0:
                win = max(pos, key=pos.get)
                sw = pos[win]
                conf = (1 - math.exp(-sw / 2.5)) * (sw / tot)
                ent.era, ent.era_conf = win, round(conf, 3)
                second = sorted(pos.values())[-2] if len(pos) > 1 else 0.0
                ent.era_conflict = second >= 1.5
                # A stated season code is harder evidence than a seller's era word. "08SS ... Hedi" cannot be
                # Hedi Slimane: when every stated code falls outside the winning era's years, the era is in
                # doubt, whatever the title claims.
                code_years = [c.year for c in codes if c.kind == "code"]
                wy = tax.eras[win]["years"]
                if code_years and not any(_in_era(wy, y) for y in code_years):
                    ent.era_conflict = True
                    ent.era_conf = round(min(ent.era_conf, 0.45), 3)
                    who = tax.eras[win].get("designer") or win
                    ent.era_anti.append(f"season code {min(code_years)} is outside {who}'s years")
        # season choice: prefer a season consistent with the winning era
        if season_hits:
            season_hits.sort(key=lambda h: (tax.seasons[h[0]].get("era") == ent.era, h[1]), reverse=True)
            sid, conf, raw = season_hits[0]
            ent.season, ent.season_conf = sid, conf
            ent.season_matched = sorted({h[2] for h in season_hits if h[0] == sid})


def _in_era(years: list, y: int) -> bool:
    a, b = years[0], years[1] if years[1] is not None else CURRENT_YEAR + 1
    return a <= y <= b


def _overlap(years: list, a: int, b: int) -> bool:
    s, e = years[0], years[1] if years[1] is not None else CURRENT_YEAR + 1
    return s <= b and a <= e


@lru_cache(maxsize=1)
def get_matcher() -> Matcher:
    return Matcher(load_taxonomy())
