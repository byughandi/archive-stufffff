"""Stage 0: text normalisation, tokenisation, size / condition normalisation, landed cost, cross-post dedupe.

Matching everywhere in the pipeline runs on *tokens*, so English, Japanese and mixed titles are handled by one
mechanism:
- Latin letters and digits form runs; a run is split at letter/digit transitions ("07AW" -> "07","aw",
  "UNDERCOVER2018SS" -> "undercover","2018","ss"). Whole-word semantics come for free.
- Every kana/kanji character is its own token and "・" and spaces are dropped, so "リック オウエンス",
  "リック・オウエンス" and "リックオウエンス" tokenise identically (substring semantics for Japanese, as the brief
  requires). The long-vowel mark "ー" is kept: dropping it made "ザラ" (Zara) fire inside "レザーライダース".
- Short Latin phrases (<= 3 letters, e.g. "uc", "ss", "ro") must align with a whole run, so "ss" never fires
  inside "04ss" and "ro" never fires inside "ro2".
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

# ----------------------------------------------------------------------------------------------- text
_ACCENTS = str.maketrans("àáâãäåèéêëìíîïòóôõöùúûüçñýÿœæ", "aaaaaaeeeeiiiiooooouuuucnyyoa")
_DECOR = re.compile(r"[【】「」『』\[\]{}<>《》〈〉★☆◆◇■□●○◎◉※♪♫!！?？、。,，;；|｜~〜＿_=“”\"«»…⭐✴✨⚡❤♡♥➡→←↑↓▶▷►▼▲◀◁‼⁉️​⁠﻿]+")
_WS = re.compile(r"\s+")


# Katakana words that merely start with "エディ" and have nothing to do with Hedi Slimane.
_JA_LOANWORDS = (("エディション", "edition"), ("エディーバウアー", "eddie bauer"), ("エディバウアー", "eddie bauer"),
                 ("エディフィス", "edifice"), ("エディトリアル", "editorial"), ("エディター", "editor"),
                 ("エディット", "edit"), ("エディオン", "edion"))


def norm_text(s: str | None) -> str:
    """NFKC (full-width ASCII -> ASCII, half-width kana -> full-width), lowercase, strip accents and decoration."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower().translate(_ACCENTS)
    for ja, en in _JA_LOANWORDS:   # so that a bare "エディ" (Hedi) can be an era cue without firing inside these
        if ja in s:
            s = s.replace(ja, f" {en} ")
    s = s.replace("エディー", "エディ")
    s = s.replace("’", "'").replace("‘", "'").replace("＆", "&")
    s = _DECOR.sub(" ", s)
    return _WS.sub(" ", s).strip()


_CJK = "぀-ゟ゠-ヺー-ヿ㐀-䶿一-鿿豈-﫿々"
_TOKEN_RE = re.compile(rf"[a-z]+|[0-9]+|[{_CJK}]|[&:/().'+#×\-*%@$]")
_RUN_RE = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class Token:
    t: str
    start: int        # char offsets in the normalized string
    end: int
    run: int          # id of the alnum run this token belongs to (-1 for CJK / punctuation)
    run_start: bool
    run_end: bool


def tokenize(norm: str) -> list[Token]:
    runs = [(m.start(), m.end()) for m in _RUN_RE.finditer(norm)]
    run_of: dict[int, tuple[int, int, int]] = {}
    for i, (a, b) in enumerate(runs):
        run_of[a] = (i, a, b)
    out: list[Token] = []
    cur = None
    for m in _TOKEN_RE.finditer(norm):
        a, b = m.start(), m.end()
        ch = m.group()
        if ch[0].isalnum() and ch[0].isascii():
            if a in run_of:
                cur = run_of[a]
            rid, ra, rb = cur if cur and cur[1] <= a < cur[2] else (-1, a, b)
            out.append(Token(ch, a, b, rid, a == ra, b == rb))
        else:
            out.append(Token(ch, a, b, -1, True, True))
    return out


def tok_strings(phrase: str) -> tuple[str, ...]:
    return tuple(t.t for t in tokenize(norm_text(phrase)))


def is_cjk(s: str) -> bool:
    return any(re.match(f"[{_CJK}]", c) for c in s)


# ----------------------------------------------------------------------------------------------- phrase index
@dataclass(slots=True)
class Match:
    i: int            # first token index
    j: int            # one past last token index
    phrase: str
    payload: Any


class PhraseIndex:
    """Exact token-sequence matcher (a dict keyed on the first token). Finds every occurrence of every phrase.

    `plural=True` lets the last Latin token of a phrase of >= 4 letters also match with a trailing "s"/"es".
    """

    def __init__(self, plural: bool = True):
        self.by_first: dict[str, list[tuple[tuple[str, ...], str, Any, bool]]] = {}
        self.plural = plural
        self.size = 0

    def add(self, phrase: str, payload: Any = None) -> None:
        if not phrase or not isinstance(phrase, str):
            return
        toks = tok_strings(phrase)
        if not toks:
            return
        latin_len = sum(len(t) for t in toks if t.isascii() and t.isalnum())
        short = (latin_len <= 3 and all(t.isascii() for t in toks))
        self.by_first.setdefault(toks[0], []).append((toks, phrase, payload, short))
        self.size += 1

    def add_many(self, phrases: Iterable[str], payload: Any = None) -> None:
        for p in phrases or []:
            self.add(p, payload)

    def _eq(self, want: str, got: str, last: bool) -> bool:
        if want == got:
            return True
        if last and self.plural and len(want) >= 4 and want.isalpha() and want.isascii():
            return got == want + "s" or got == want + "es"
        return False

    def find(self, toks: list[Token]) -> list[Match]:
        out: list[Match] = []
        n = len(toks)
        for i, tk in enumerate(toks):
            cands = self.by_first.get(tk.t)
            if not cands and self.plural and tk.t.endswith("s"):
                cands = self.by_first.get(tk.t[:-1]) or self.by_first.get(tk.t[:-2])
            if not cands:
                continue
            for seq, phrase, payload, short in cands:
                m = len(seq)
                if i + m > n:
                    continue
                ok = True
                for k in range(m):
                    if not self._eq(seq[k], toks[i + k].t, k == m - 1):
                        ok = False
                        break
                if not ok:
                    continue
                if seq[0].isascii() and seq[0].isalnum() and not toks[i].run_start and short:
                    continue
                last = toks[i + m - 1]
                if short and last.t.isascii() and last.t.isalnum() and not last.run_end:
                    continue
                # a multi-token Latin phrase must start/end at run boundaries unless the run is split at a
                # letter/digit transition (so "rick owens" never matches inside "maverick owens")
                if seq[0].isascii() and seq[0][0].isalpha() and not toks[i].run_start:
                    prev = toks[i - 1] if i else None
                    if not (prev and prev.run == toks[i].run and prev.t[0].isdigit()):
                        continue
                if last.t.isascii() and last.t[0].isalpha() and not last.run_end:
                    nxt = toks[i + m] if i + m < n else None
                    if not (nxt and nxt.run == last.run and nxt.t[0].isdigit()):
                        continue
                out.append(Match(i, i + m, phrase, payload))
        return out


def longest_only(matches: list[Match]) -> list[Match]:
    """Drop matches fully contained in a longer match (keeps overlapping-but-not-contained ones)."""
    ms = sorted(matches, key=lambda m: (m.i, -(m.j - m.i)))
    keep: list[Match] = []
    for m in ms:
        if any(k.i <= m.i and m.j <= k.j and (k.j - k.i) > (m.j - m.i) for k in keep):
            continue
        keep.append(m)
    return keep


# ----------------------------------------------------------------------------------------------- sizes
TOPS = {"leather_jacket", "biker_jacket", "varsity_jacket", "blazer", "coat", "hoodie", "knit", "shirt", "graphic_tee"}
BOTTOMS = {"denim", "pants"}
SHOES = {"boots", "sneakers"}
_LETTER = {"xxs": "XXS", "xs": "XS", "s": "S", "m": "M", "l": "L", "xl": "XL", "xxl": "XXL", "xxxl": "XXXL",
           "2xl": "XXL", "3xl": "XXXL", "ss": None}
_JP_NUM = {"0": "XS", "1": "S", "2": "M", "3": "L", "4": "XL", "5": "XXL"}
_EU_LETTER = {42: "XXS", 44: "XS", 46: "S", 48: "M", 50: "L", 52: "XL", 54: "XXL", 56: "XXXL"}
# JP cm -> EU (men's, approximate retail conversion table)
_CM_EU = [(24.5, 39), (25.0, 40), (25.5, 40.5), (26.0, 41), (26.5, 42), (27.0, 42.5), (27.5, 43),
          (28.0, 44), (28.5, 44.5), (29.0, 45), (29.5, 45.5), (30.0, 46), (31.0, 47)]


def size_group(archetype: str | None) -> str | None:
    if archetype in TOPS:
        return "tops"
    if archetype in BOTTOMS:
        return "bottoms"
    if archetype in SHOES:
        return "shoes"
    return None


def _eu_from_cm(cm: float) -> str:
    best = min(_CM_EU, key=lambda r: abs(r[0] - cm))
    v = best[1]
    return f"EU{v:g}"


_SIZE_PATTERNS = [
    re.compile(r"(?:size|sz|サイズ|表記|tag size)\s*[:：.]?\s*(w?\d{1,2}(?:\.\d)?|xxs|xs|s|m|l|xl|xxl|xxxl|2xl|3xl|us\s?\d{1,2}(?:\.5)?|eu\s?\d{2})(?![0-9a-z])"),
    re.compile(r"(?<![0-9a-z])(xxs|xs|s|m|l|xl|xxl|xxxl|\d{2}(?:\.\d)?)\s?サイズ"),
    re.compile(r"(?<![0-9a-z])(w\s?\d{2})(?:\s?[x×]\s?l?\d{2})?(?![0-9])"),
    re.compile(r"(?<![0-9a-z.])(\d{2}(?:\.5)?)\s?cm(?![a-z])"),
    re.compile(r"(?<![0-9a-z])(us\s?\d{1,2}(?:\.5)?|eu\s?\d{2}(?:\.5)?)(?![0-9])"),
    re.compile(r"#\s?(\d{2})(?![0-9])"),
]
_TRAIL = re.compile(r"(?<![0-9a-z.\-/])(\d{2})(?:\s?(?:サイズ|size))?\s*$")
_TRAIL_LETTER = re.compile(r"(?<![0-9a-z/])(xxs|xs|s|m|l|xl|xxl|xxxl)\s*$")


def normalize_size(raw_value: str, archetype: str | None, from_cm: bool = False) -> str | None:
    v = raw_value.strip().lower().replace(" ", "")
    g = size_group(archetype)
    if v in _LETTER:
        return _LETTER[v]
    if v.startswith("w") and v[1:].isdigit():
        n = int(v[1:])
        return f"W{n}" if 24 <= n <= 42 else None
    if v.startswith("us"):
        try:
            n = float(v[2:])
        except ValueError:
            return None
        if g == "shoes" or archetype is None:
            return f"EU{n + 33:g}" if 5 <= n <= 14 else None
        return f"W{int(n)}" if 24 <= n <= 42 else None
    if v.startswith("eu"):
        try:
            return f"EU{float(v[2:]):g}"
        except ValueError:
            return None
    try:
        n = float(v)
    except ValueError:
        return None
    if from_cm:
        return _eu_from_cm(n) if 22 <= n <= 32 and (g == "shoes" or g is None) else None
    if g == "shoes":
        if 22 <= n <= 32 and n != int(n) or 22 <= n <= 31 and archetype == "sneakers" and n < 34:
            return _eu_from_cm(n) if n < 33 else None
        if 35 <= n <= 48:
            return f"EU{n:g}"
        if 5 <= n <= 14:
            return f"EU{n + 33:g}"
        return None
    if n != int(n):
        return None
    n = int(n)
    if g == "bottoms":
        if 24 <= n <= 40:
            return f"W{n}"
        if 42 <= n <= 56 and n % 2 == 0:
            return f"W{n - 16}"
        if 0 <= n <= 5:
            return _JP_NUM[str(n)]
        return None
    if g == "tops" or g is None:
        if 0 <= n <= 5:
            return _JP_NUM[str(n)]
        if 42 <= n <= 58 and n % 2 == 0:
            return str(n)
        return None
    return None


def parse_size(size_raw: str | None, title_norm: str, archetype: str | None) -> str | None:
    if size_raw:
        raw = re.sub(r"^(size|it|ita|itl|fr|jp|jpn)\s*", "", norm_text(size_raw).replace("size", "").strip())
        s = normalize_size(raw, archetype)
        if s:
            return s
    for i, pat in enumerate(_SIZE_PATTERNS):
        for m in pat.finditer(title_norm):
            s = normalize_size(m.group(1), archetype, from_cm=(i == 3))
            if s:
                return s
    m = _TRAIL.search(title_norm)
    if m:
        s = normalize_size(m.group(1), archetype)
        if s:
            return s
    m = _TRAIL_LETTER.search(title_norm)
    if m:
        return _LETTER.get(m.group(1))
    return None


def size_letter(size_norm: str | None) -> str | None:
    if not size_norm:
        return None
    if size_norm.isdigit():
        return _EU_LETTER.get(int(size_norm))
    return size_norm if size_norm in _LETTER.values() else None


def size_fit(size_norm: str | None, archetype: str | None, profile: dict | None) -> tuple[float, str]:
    """1.0 = in profile, 0.85 unknown, 0.4 known mismatch. Neutral (1.0) when the profile is empty."""
    profile = profile or {}
    g = size_group(archetype)
    wanted = []
    if g == "tops":
        wanted = list(profile.get("tops") or []) + list(profile.get("tailoring") or [])
    elif g == "bottoms":
        wanted = list(profile.get("bottoms") or [])
    elif g == "shoes":
        wanted = list(profile.get("shoes") or [])
    if not wanted:
        return 1.0, "no_profile"
    if not size_norm:
        return 0.85, "unknown_size"
    want = {str(w).upper().replace(" ", "") for w in wanted}
    sl = size_letter(size_norm)
    if size_norm.upper() in want or (sl and sl in want):
        return 1.0, "fits"
    for w in want:  # adjacent waist / shoe sizes are "close"
        a = re.sub(r"[^0-9.]", "", w)
        b = re.sub(r"[^0-9.]", "", size_norm)
        if a and b and abs(float(a) - float(b)) <= 1.0 and w[:1] == size_norm[:1]:
            return 0.8, "close"
    return 0.4, "mismatch"


# ----------------------------------------------------------------------------------------------- condition
MERCARI_JP_CONDITION = {"1": 1.0, "2": 0.9, "3": 0.8, "4": 0.65, "5": 0.45, "6": 0.25}
_COND_TEXT = [
    (("new with tags", "nwt", "brand new", "deadstock", "新品未使用", "未使用", "新品", "タグ付き"), 1.0),
    (("like new", "mint", "極美品", "ほぼ未使用", "未使用に近い"), 0.92),
    (("excellent", "美品", "gently used", "is_gently_used"), 0.85),
    (("good", "良好", "used", "is_used", "目立った傷や汚れなし"), 0.72),
    (("fair", "worn", "is_worn", "やや傷や汚れあり", "使用感あり", "着用感あり"), 0.6),
    (("poor", "damaged", "全体的に状態が悪い", "傷や汚れあり"), 0.4),
    (("ジャンク", "for parts", "as is", "as-is", "難あり", "訳あり"), 0.15),
]
_DEFECTS = ("シミ", "汚れ", "ほつれ", "色褪せ", "破れ", "stain", "hole", "tear", "rip ")


def condition_norm(source: str, condition_raw: str | None, text_norm: str) -> float | None:
    if condition_raw is not None and str(condition_raw).strip():
        raw = str(condition_raw).strip().lower()
        if source.startswith("mercari_jp") and raw in MERCARI_JP_CONDITION:
            base = MERCARI_JP_CONDITION[raw]
        elif raw in MERCARI_JP_CONDITION and source.startswith("mercari"):
            base = MERCARI_JP_CONDITION[raw]
        else:
            base = None
            for words, v in _COND_TEXT:
                if any(w in raw for w in words):
                    base = v
                    break
        if base is not None:
            if any(w in text_norm for w in ("ジャンク", "for parts")):
                base = min(base, 0.15)
            return base
    for words, v in _COND_TEXT:
        if any(w in text_norm for w in words):
            return v
    return None


# ----------------------------------------------------------------------------------------------- landed cost
_NON_JP_ORIGIN = ("made in italy", "made in france", "made in china", "made in portugal", "made in usa",
                  "made in romania", "made in turkey", "made in belgium", "made in spain", "made in korea",
                  "イタリア製", "フランス製", "中国製", "ポルトガル製", "アメリカ製", "米国製", "ルーマニア製",
                  "トルコ製", "ベルギー製", "スペイン製", "韓国製", "usa製")


def landed_cost(region: str, price_usd: float, shipping_usd: float | None, weight_class: str | None,
                text_norm: str, jpy_per_usd: float, jc: dict, proxy_id: str = "buyee",
                fx_fallback: bool = False) -> dict:
    """Landed cost block for explain.cost. JP: proxy + domestic + international (by weight class) + duty.
    US: price + stated shipping. Other regions (CA, AU, EU webshops): price + flat international shipping by weight
    class + duty at the non-Japan-origin rate, no proxy fee."""
    if region not in ("JP", "US"):
        ship_tbl = jc.get("shipping_usd_by_weight_class", {}) or {}
        intl = float(shipping_usd) if shipping_usd is not None else float(ship_tbl.get(weight_class or "medium", 48))
        rate = float((jc.get("duties", {}) or {}).get("typical_rate_non_japan_origin_pct", 15))
        duty = price_usd * rate / 100.0
        return {"price_usd": round(price_usd, 2), "proxy_fee_usd": 0.0, "domestic_shipping_usd": 0.0,
                "intl_shipping_usd": round(intl, 2), "duty_usd": round(duty, 2), "duty_rate_pct": rate,
                "weight_class": weight_class or "medium", "landed_usd": round(price_usd + intl + duty, 2),
                "fx_fallback": fx_fallback}
    if region != "JP":
        ship = float(shipping_usd or 0.0)
        return {"price_usd": round(price_usd, 2), "proxy_fee_usd": 0.0, "domestic_shipping_usd": 0.0,
                "intl_shipping_usd": round(ship, 2), "duty_usd": 0.0, "landed_usd": round(price_usd + ship, 2),
                "shipping_stated": shipping_usd is not None, "fx_fallback": fx_fallback}
    proxy = next((p for p in jc.get("proxies", []) if p.get("id") == proxy_id), None) or {}
    fee_jpy = proxy.get("fee_fixed_jpy")
    fee_jpy = 500.0 if fee_jpy in (None, "UNKNOWN") else float(fee_jpy)
    pct = proxy.get("fee_pct")
    pct = 0.0 if pct in (None, "UNKNOWN") else float(pct)
    proxy_usd = fee_jpy / jpy_per_usd + price_usd * pct / 100.0
    dom_jpy = float(jc.get("domestic_shipping_jpy_default", 800))
    dom_usd = 0.0 if shipping_usd == 0 else dom_jpy / jpy_per_usd
    ship_tbl = jc.get("shipping_usd_by_weight_class", {}) or {}
    intl = float(ship_tbl.get(weight_class or "medium", ship_tbl.get("medium", 48)))
    duties = jc.get("duties", {}) or {}
    jp_rate = float(duties.get("typical_rate_apparel_pct", 12.5))
    other_rate = float(duties.get("typical_rate_non_japan_origin_pct", 15))
    non_jp = any(w in text_norm for w in _NON_JP_ORIGIN)
    rate = other_rate if non_jp else jp_rate
    duty = price_usd * rate / 100.0
    landed = price_usd + proxy_usd + dom_usd + intl + duty
    return {"price_usd": round(price_usd, 2), "proxy_fee_usd": round(proxy_usd, 2),
            "domestic_shipping_usd": round(dom_usd, 2), "intl_shipping_usd": round(intl, 2),
            "duty_usd": round(duty, 2), "duty_rate_pct": rate, "duty_origin": "non_japan" if non_jp else "japan",
            "weight_class": weight_class or "medium", "proxy": proxy_id,
            "landed_usd": round(landed, 2), "fx_fallback": fx_fallback}


# ----------------------------------------------------------------------------------------------- dedupe
_SIZE_TOKENS = re.compile(r"(?<![0-9a-z])(\d{1,2}(\.\d)?|xxs|xs|s|m|l|xl|xxl)(?![0-9a-z])")


def _dedupe_key(title_norm: str) -> str:
    return _WS.sub(" ", title_norm).strip()


def find_crossposts(rows: list[dict], candidates: set[str] | None = None) -> dict[str, str]:
    """Return {listing_id: canonical_id} for cross-posts / relists.

    rows: dicts with id, source, seller_id, title, price_usd, first_seen_at, size_norm (optional).
    Rules: (a) same seller + title similarity >= 95 + same parsed size + price within 10%;
           (b) different source + title similarity >= 95 + price within 2%.
    The canonical row is the earliest seen (ties: smallest id). Only ids in `candidates` (if given) are mapped.
    """
    from rapidfuzz import fuzz

    for r in rows:
        r["_k"] = _dedupe_key(norm_text(r.get("title")))
    out: dict[str, str] = {}

    def earlier(a, b):
        return (a.get("first_seen_at") or 0, a["id"]) < (b.get("first_seen_at") or 0, b["id"])

    def link(a, b):
        ca, cb = (a, b) if earlier(a, b) else (b, a)
        if candidates is None or cb["id"] in candidates:
            prev = out.get(cb["id"])
            if prev is None or (prev != ca["id"] and earlier(ca, next(x for x in rows if x["id"] == prev))):
                out[cb["id"]] = ca["id"]

    by_seller: dict[str, list[dict]] = {}
    for r in rows:
        s = r.get("seller_id")
        if s and not s.endswith(":0") and not s.endswith(":"):
            by_seller.setdefault(s, []).append(r)
    for group in by_seller.values():
        if len(group) < 2:
            continue
        for x in range(len(group)):
            a = group[x]
            if candidates is not None and a["id"] not in candidates and all(
                    g["id"] not in candidates for g in group):
                break
            for y in range(x + 1, len(group)):
                b = group[y]
                if candidates is not None and a["id"] not in candidates and b["id"] not in candidates:
                    continue
                if (a.get("size_norm") or None) != (b.get("size_norm") or None):
                    continue
                pa, pb = float(a["price_usd"] or 0), float(b["price_usd"] or 0)
                if max(pa, pb) <= 0 or abs(pa - pb) / max(pa, pb) > 0.10:
                    continue
                if fuzz.ratio(a["_k"], b["_k"]) >= 95:
                    link(a, b)
    # cross-source: bucket by log price (2% buckets) and compare neighbours
    buckets: dict[int, list[dict]] = {}
    for r in rows:
        p = float(r.get("price_usd") or 0)
        if p > 0:
            buckets.setdefault(int(math.log(p) / 0.02), []).append(r)
    for k, group in buckets.items():
        pool = group + buckets.get(k + 1, [])
        for a in group:
            for b in pool:
                if a is b or a["source"] == b["source"] or a["id"] >= b["id"] and b in group:
                    continue
                if candidates is not None and a["id"] not in candidates and b["id"] not in candidates:
                    continue
                pa, pb = float(a["price_usd"]), float(b["price_usd"])
                if abs(pa - pb) / max(pa, pb) > 0.02:
                    continue
                if fuzz.ratio(a["_k"], b["_k"]) >= 95:
                    link(a, b)
    for r in rows:
        r.pop("_k", None)
    # resolve chains a -> b -> c to the root
    for k in list(out):
        seen = {k}
        v = out[k]
        while v in out and v not in seen:
            seen.add(v)
            v = out[v]
        out[k] = v
    return {k: v for k, v in out.items() if k != v}
