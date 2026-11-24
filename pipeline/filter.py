"""Stage 1: hard rejects, risk flags and tier ceilings from blocklist.yaml, brands.yaml and aliases_ja.yaml.

A rejected listing gets tier X with a `reject_reason` (`<rule>:<what fired>`) and stays reviewable. Everything that
is a risk rather than a certainty (below price floor, no tag photos, stock photos, no returns, Chanel base rate...)
becomes a flag with a severity and adds to `risk`; it never makes a listing trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from core.taxonomy import Taxonomy, load_taxonomy

from . import cfg
from .classify import Entities
from .normalize import PhraseIndex, Token, norm_text, tok_strings, tokenize

SEVERITY_LABEL = {1: "info", 2: "caution", 3: "serious"}

FLAG_LABELS = {
    "needs_tag_pics": "Era unconfirmed. Ask for tag photos.",
    "below_floor": "Price below the plausible floor for this brand and piece.",
    "too_good": "Price implausibly low for a piece of this tier.",
    "no_tag": "Tag missing or cut: era and authenticity cannot be checked.",
    "no_tag_photos": "Seller shows or offers no tag photos.",
    "stock_photo": "Stock or borrowed photos.",
    "dup_photo": "Same photo seen on another listing.",
    "no_returns": "No returns.",
    "junk_condition": "Sold as junk / for parts.",
    "condition_issue": "Seller mentions stains, holes or fading.",
    "repaired": "Restored, re-sewn or refurbished.",
    "keyword_stuffing": "Title lists several unrelated designers.",
    "multi_brand": "Two designers named without a collab marker.",
    "reference_brand": "A designer is named only as a reference (style / 風 / 好き).",
    "era_conflict": "Era cues contradict each other.",
    "unwanted_era": "Era this buyer does not chase.",
    "bundle": "Bundle / lot: price is not per item.",
    "new_seller": "Seller has no ratings yet.",
    "fx_fallback": "Converted with fallback FX rates.",
    "sample": "Sample piece: verify provenance.",
    "made_in_mismatch": "Country of origin unusual for this brand and era.",
    "chanel_fake_rate": "Chanel: fakes are rampant, verify hardware and codes.",
    "reissue": "Reissue / re-release of an archive design, not the original season.",
    "womens": "Women's piece.",
    "type_stuffing": "Title lists many piece types: a keyword list, not one piece.",
    "stale_listing": "Listed a long time ago and still unsold.",
    "auction_in_progress": "Auction in progress: current bid, not a final price.",
    "ending_soon": "Auction ends within 2 hours.",
    "current_retail": "Current-season retail stock, not archive.",
    "diffusion_line": "Diffusion line, not the mainline.",
    "era_leans_unwanted": "Era unconfirmed, but the evidence points to an era this buyer does not chase.",
}

_REJECT_CONDITIONAL = {"custom", "bootleg", "tribute", "replica", "レプリカ", "fake", "copy", "reworked", "handmade",
                       "baby", "kids", "toddler", "costume", "toy", "poster"}
_FLAG_CONDITIONAL = {"no tag": "no_tag", "no tags": "no_tag", "tag cut": "no_tag", "tags removed": "no_tag",
                     "label removed": "no_tag", "label cut": "no_tag", "restored": "repaired",
                     "re-sewn": "repaired", "refurbished": "repaired", "sample": "sample"}
_JA_REJECT = {"偽物": "fake_language", "コピー品": "fake_language", "ノーブランド": "no_brand_language",
              "オマージュ": "lookalike_language", "リメイク": "remake", "ハンドメイド": "handmade"}
_JA_FLAG = {"ジャンク": "junk_condition", "訳あり": "condition_issue", "難あり": "condition_issue",
            "タグなし": "no_tag", "タグ無し": "no_tag", "タグ切り": "no_tag", "色褪せ": "condition_issue",
            "ほつれ": "condition_issue", "シミ": "condition_issue", "穴あき": "condition_issue", "破れ": "condition_issue"}
_NO_RETURNS = ["no returns", "no return", "all sales final", "final sale", "返品不可", "ノークレームノーリターン",
               "ノークレーム", "返品返金不可", "nc nr", "ncnr"]
_REISSUE = ["復刻", "復刻版", "リイシュー", "reissue", "re-issue", "re issue", "re-release", "rerelease", "re-edition",
            "retro release", "anniversary reissue"]
_WOMENS = ["レディース", "womens", "women's", "women", "wmns", "ladies", "ワンピース", "スカート", "ドレス", "skirt",
           "dress", "ミニドレス", "パンプス", "pumps", "camisole", "キャミソール", "キャミ", "チビt", "baby tee", "handbag",
           "ハンドバッグ", "blouse", "ブラウス", "レギンス", "leggings"]
_BUNDLE = ["まとめ売り", "まとめ", "点セット", "セット売り", "lot of", "bundle", "bulk lot", "wholesale"]
_JA_ITEM_SUFFIX = set("付有込同柄期")
# object categories that are a design detail when the title is clearly a garment ("monster hoodie with plush")
_OBJECT_CATS = {"ぬいぐるみ", "plush", "toy", "おもちゃ", "フィギュア", "figurine", "キーチェーン", "sticker", "ステッカー"}
_STRONG_LOOKALIKE = {"似", "風", "っぽい", "ぽい", "ライク", "テイスト", "inspired", "esque", "dupe", "lookalike", "-style"}
_HARDWARE_BRANDS = {"chrome_hearts"}
_HARDWARE_CATS = {"keychain", "key chain", "keyring", "key ring", "key holder", "lighter", "キーチェーン", "キーホルダー", "キーリング", "ライター"}
_GARMENTS = {"leather_jacket", "biker_jacket", "varsity_jacket", "blazer", "coat", "denim", "pants", "hoodie", "knit",
             "shirt", "graphic_tee", "boots", "sneakers"}
_NON_ORIGIN = ["made in china", "made in turkey", "made in vietnam", "made in bangladesh", "made in indonesia",
               "made in cambodia", "made in pakistan", "中国製", "ベトナム製", "バングラデシュ製", "トルコ製"]
_GENERIC_FIELD = {"", "other", "others", "vintage", "designer", "japanese brand", "japanese", "streetwear", "archive",
                  "unknown", "none", "n/a", "na", "custom", "handmade", "no brand", "unbranded", "brand", "italian brand",
                  "french brand", "luxury", "other designer", "その他", "ノーブランド", "ブランド", "ヴィンテージ"}
_LUXURY_GROUPS = {"core", "eu_archive", "jp_archive", "rapper_staple"}


def flag(fid: str, severity: int, detail: str | None = None) -> dict:
    d = {"id": fid, "label": FLAG_LABELS.get(fid, fid.replace("_", " ")), "severity": severity}
    if detail:
        d["detail"] = detail
    return d


@dataclass
class FilterResult:
    reject_reason: str | None = None
    flags: list[dict] = field(default_factory=list)
    risk: float = 0.0
    ceiling: str | None = None
    ceiling_reason: str | None = None
    fired: list[str] = field(default_factory=list)

    def add(self, f: dict, risk: float = 0.0):
        if not any(x["id"] == f["id"] for x in self.flags):
            self.flags.append(f)
            self.risk += risk

    def cap(self, tier: str, reason: str):
        order = "SABCX"
        if self.ceiling is None or order.index(tier) > order.index(self.ceiling):
            self.ceiling, self.ceiling_reason = tier, reason


class Filter:
    def __init__(self, tax: Taxonomy):
        self.tax = tax
        bl = tax.blocklist or {}
        self.reject_title = PhraseIndex()
        self.reject_any = PhraseIndex()
        for r in bl.get("reject_phrases") or []:
            (self.reject_title if r.get("scope") == "title" else self.reject_any).add(r["phrase"], r["phrase"])
        self.cond = PhraseIndex()
        self.cond_allow: dict[str, PhraseIndex] = {}
        for r in bl.get("conditional_phrases") or []:
            self.cond.add(r["phrase"], r["phrase"])
            ai = PhraseIndex()
            ai.add_many(r.get("allow_when") or [], True)
            self.cond_allow[r["phrase"]] = ai
        self.other = PhraseIndex()
        self.other.add_many(bl.get("other_brands") or [], "other")
        self.mall = PhraseIndex()
        self.mall.add_many(bl.get("mall_brands") or [], "mall")
        self.category = PhraseIndex(plural=True)
        for c in bl.get("category_exclusions") or []:
            if str(c) not in self.cond_allow:
                self.category.add(str(c), str(c))
        self.collisions = PhraseIndex()
        for c in bl.get("brand_collisions") or []:
            for p in c.get("phrases") or []:
                self.collisions.add(p, str(c["brand"]))
        self.neg: dict[str, PhraseIndex] = {}
        for bid, b in tax.brands.items():
            pi = PhraseIndex()
            pi.add_many([p.strip() for p in b.get("negative_context") or [] if p.strip()], bid)
            self.neg[bid] = pi
        self.fake = PhraseIndex()
        self.qualityreps = PhraseIndex()
        for f in bl.get("fake_red_flags") or []:
            if f.get("id") == "qualityreps_pattern_note":
                self.qualityreps.add_many(f.get("listing_signals") or [], f["id"])
            elif f.get("id") in ("implausibly_low_price", "chanel_high_fake_prevalence", "made_in_country_mismatch"):
                continue
            else:
                for s in f.get("listing_signals") or []:
                    self.fake.add(s, f)
        self.made_in_brands = set()
        for f in bl.get("fake_red_flags") or []:
            if f.get("id") == "made_in_country_mismatch":
                self.made_in_brands = {str(b) for b in f.get("brands") or []}
        self.ja_reject = PhraseIndex()
        for k, v in _JA_REJECT.items():
            self.ja_reject.add(k, v)
        self.ja_flag = PhraseIndex()
        for k, v in _JA_FLAG.items():
            self.ja_flag.add(k, v)
        self.no_returns = PhraseIndex()
        self.no_returns.add_many(_NO_RETURNS, True)
        self.bundle = PhraseIndex()
        self.bundle.add_many(_BUNDLE, True)
        self.reissue = PhraseIndex()
        self.reissue.add_many(_REISSUE, True)
        # distinctive words per piece type (EN + JA), for spotting titles that name every type at once
        self.type_words: dict[str, list[str]] = {}
        ja_arch = tax.ja.get("archetypes") or {}
        for aid, a in tax.archetypes.items():
            words = [norm_text(w) for w in list(a.get("aliases") or [])[:6] + list(ja_arch.get(aid) or [])[:6]]
            self.type_words[aid] = [w for w in words if len(w) >= 3]
        self.womens = PhraseIndex()
        self.womens.add_many(_WOMENS, True)
        self.non_origin = PhraseIndex()
        self.non_origin.add_many(_NON_ORIGIN, True)

    @staticmethod
    def _hits(idx: PhraseIndex, toks: list[Token]):
        return idx.find(toks) if toks else []

    def apply(self, listing: dict, ent: Entities, tnorm: str, toks: list[Token], dtoks: list[Token]) -> FilterResult:
        res = FilterResult()
        tax = self.tax
        both = toks + dtoks
        brand = ent.brand

        def reject(reason: str):
            if res.reject_reason is None:
                res.reject_reason = reason

        # --- explicit fake / lookalike language
        for m in self._hits(self.qualityreps, toks):
            reject(f"fake_language:{m.phrase}")
        for m in self._hits(self.reject_title, toks) + self._hits(self.reject_any, both):
            if m.phrase == "ua":
                if brand and tax.brands[brand].get("group") in _LUXURY_GROUPS:
                    reject("fake_language:ua")
                continue
            reject(f"blocklist:{m.phrase}")
        for m in self._hits(self.ja_reject, toks):
            reject(f"{m.payload}:{m.phrase}")
        for m in self._hits(self.cond, toks + dtoks):
            ph = m.payload
            allowed = bool(self.cond_allow[ph].find(both))
            in_title = m.j <= len(toks)
            if ph in _FLAG_CONDITIONAL:
                if not allowed:
                    res.add(flag(_FLAG_CONDITIONAL[ph], 2, ph), 0.1)
            elif ph in _REJECT_CONDITIONAL and in_title and not allowed:
                if ph in _OBJECT_CATS and ent.archetype in _GARMENTS and brand:
                    continue
                if ph in ("replica", "レプリカ") and brand == "margiela":
                    continue
                reject(f"conditional:{ph}")
        # --- titles that list every garment type are keyword lists, not a piece
        named_types = {aid for aid, words in self.type_words.items() if any(w in tnorm for w in words)}
        if len(named_types) >= 5:
            res.add(flag("type_stuffing", 2, f"{len(named_types)} piece types named"), 0.2)
            res.cap("C", "title lists many piece types")
        # --- placeholder listings: sellers park sold items at 999,999 yen or retitle them "sold out"
        # A real 1.5 million yen Hedi leather exists, so the size of the price alone proves nothing. What marks
        # a placeholder is the shape of the number: every digit the same (999,999 / 8,888,888), or absurd.
        price_native = float(listing.get("price") or 0)
        digits = str(int(price_native)) if price_native else ""
        if (len(digits) >= 6 and len(set(digits)) == 1) or float(listing.get("price_usd") or 0) >= 60_000:
            reject("placeholder_price")
        if any(k in tnorm for k in ("売り切れ", "売切れ", "sold out", "soldout")):
            reject("marked_sold")
        # --- mall brands / category exclusions / collisions
        for m in self._hits(self.mall, toks) + self._hits(self.mall, tokenize(norm_text(listing.get("brand_raw")))):
            reject(f"mall_brand:{m.phrase}")
        for m in self._hits(self.other, toks):
            reject(f"other_brand:{m.phrase}")   # another label's piece, naming a wanted brand only as a comparison
        for m in self._hits(self.category, toks):
            if m.phrase == "cd" and ("dior" in tnorm or brand == "dior_homme"):
                continue
            if m.j < len(toks) and toks[m.j].t in _JA_ITEM_SUFFIX and not m.phrase.isascii():
                continue   # "紙袋付き" = comes with a paper bag, not the item
            if m.phrase in _OBJECT_CATS and ent.archetype in _GARMENTS and brand:
                continue
            if brand in _HARDWARE_BRANDS and m.phrase in _HARDWARE_CATS:
                continue   # a Chrome Hearts keychain is a Chrome Hearts piece, not merch
            reject(f"category:{m.phrase}")
        for m in self._hits(self.collisions, toks):
            reject(f"collision:{m.payload}:{m.phrase}")
        for bid in dict.fromkeys(([brand] if brand else []) + ent.brands_all + ent.reference_brands):
            for m in self._hits(self.neg.get(bid), toks):
                reject(f"negative_context:{bid}:{m.phrase}")
                break

        # --- brand presence, references, stuffing, brand field
        independent = [b for b in ent.brands_all if b != brand and b not in ent.collab_brands]
        if ent.reference_matches:
            res.add(flag("reference_brand", 1, ", ".join(ent.reference_matches[:3])))
        braw = norm_text(listing.get("brand_raw"))
        field_brand = None
        from .classify import get_matcher  # local import avoids a cycle at module load
        if braw and braw not in _GENERIC_FIELD:
            field_brand = get_matcher().resolve_brand_field(braw)
        if len(independent) >= 2:
            if braw and braw not in _GENERIC_FIELD and field_brand != brand:
                reject("keyword_stuffing:brand_field_disagrees")
            res.add(flag("keyword_stuffing", 3, ", ".join([brand] + independent)), 0.3)
            res.cap("C", "keyword_stuffing")
        elif len(independent) == 1:
            res.add(flag("multi_brand", 1, f"{brand} + {independent[0]}"), 0.05)
            res.cap("B", "multi_brand")
        if brand and braw and braw not in _GENERIC_FIELD:
            if field_brand is None:
                reject(f"brand_field_mismatch:{braw}")
            elif field_brand != brand and field_brand not in ent.brands_all:
                reject(f"brand_field_mismatch:{braw}")
        # "Rick Owens似 ジオバスケット": the brand is named (a model name even confirms it), but the seller says
        # outright that the item only resembles it.
        for ref in getattr(ent, "brand_refs", None) or []:
            if ref.rsplit("+", 1)[-1] in _STRONG_LOOKALIKE:
                reject(f"lookalike:{ref}")
        if brand is None:
            if ent.reference_brands:
                reject(f"lookalike:{ent.reference_matches[0] if ent.reference_matches else ent.reference_brands[0]}")
            reject("no_brand")

        # --- risk flags (never rejects)
        for m in self._hits(self.ja_flag, both):
            fid = m.payload
            if fid == "junk_condition":
                res.add(flag(fid, 2, m.phrase), 0.1)
                res.cap("B", "junk_condition")
            else:
                res.add(flag(fid, 2 if fid == "no_tag" else 1, m.phrase), 0.1 if fid == "no_tag" else 0.0)
        for m in self._hits(self.fake, both):
            f = m.payload
            fb = [str(b) for b in f.get("brands") or []]
            if fb and brand not in fb:
                continue
            fid = {"stock_or_borrowed_photos": "stock_photo", "no_tag_or_label_photos": "no_tag_photos"}.get(f["id"], f["id"])
            sev = int(f.get("severity", 2))
            res.add(flag(fid, sev, m.phrase), 0.08 * sev)
        if self._hits(self.no_returns, both):
            res.add(flag("no_returns", 1), 0.04)
        if self._hits(self.bundle, toks):
            res.add(flag("bundle", 2), 0.0)
        if brand in self.made_in_brands and self._hits(self.non_origin, both):
            res.add(flag("made_in_mismatch", 3), 0.25)
        if self._hits(self.reissue, both):
            res.add(flag("reissue", 1), 0.0)
            res.cap("B", "reissue")
        mens_marked = any(k in tnorm for k in ("メンズ", "mens", "men's", "紳士", " homme", "オム"))
        wm = [m for m in self._hits(self.womens, toks)
              if not (m.phrase in ("ドレス", "dress") and any(k in tnorm for k in ("ドレスシャツ", "dress shirt", "ドレスシューズ", "dress shoes", "ドレスパンツ", "dress pants")))]
        if brand and brand != "chanel" and wm and not mens_marked:
            res.add(flag("womens", 1), 0.0)
            res.cap("C", "womens piece")   # menswear buyer; Chanel/glam womenswear is the exception
        if ent.line and "diffusion" in str(next((l.get("name") for l in tax.brands[brand].get("lines") or []
                                                  if l.get("id") == ent.line), "")).lower():
            res.add(flag("diffusion_line", 1, ent.line), 0.0)
            res.cap("C", "diffusion line")
        if brand == "chanel":
            res.add(flag("chanel_fake_rate", 2), 0.12)
        if ent.era_conflict and ent.era_conf >= 0.3:
            res.add(flag("era_conflict", 1), 0.03)
        # price floor (needs archetype)
        if brand and ent.archetype:
            floor = (tax.brands[brand].get("price_floor_usd") or {}).get(ent.archetype)
            price = float(listing.get("price_usd") or 0)
            if isinstance(floor, (int, float)) and (listing.get("region") == "JP"):
                floor = round(floor * float(cfg("jp_floor_factor")))
            if isinstance(floor, (int, float)) and price > 0 and price < floor:
                res.add(flag("below_floor", 2, f"${price:.0f} < floor ${floor}"), 0.15 + 0.25 * (1 - price / floor))
        res.risk = round(min(res.risk, 1.0), 3)
        return res


@lru_cache(maxsize=1)
def get_filter() -> Filter:
    return Filter(load_taxonomy())
