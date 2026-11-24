"""Independent webshops from data/taxonomy/sellers.yaml (`webshops`): Shopify and BigCartel.

Shopify: GET <shop>/products.json?limit=100&page=N (public). Verified live 2026-11-24 on
driewgarments.com (CA, ~2000 products, default order newest-published first) and marais.com.au.
Currency and country come from <shop>/meta.json (cached in kv). One Listing per product; only
available variants count (size_raw lists them, price is the cheapest available variant).

Incremental: pages are walked newest-first and we stop at the first page with only known ids.
A per-shop `updated_at` watermark (kv `shop_wm:<slug>`) skips re-emitting unchanged known
products. Sold detection for tracked products happens in `recheck` (/products/<handle>.json).
BigCartel support is untested (no BigCartel shop in sellers.yaml yet).
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from core.db import now
from core.models import Listing, Seller, known_ids, upsert_listings
from core.taxonomy import Taxonomy, load_taxonomy
from scrapers.common import Ctx, RunResult
from scrapers.common.http import FetchError, NotFound, PoliteClient
from scrapers.common.queries import mark_run
from scrapers.yahoo_jp import _ts

LIMIT = 100
MAX_PAGES = 5
DEEP_PAGES = 25
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
      "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}


def slug_for(shop: dict) -> str:
    host = urlsplit(shop["url"]).netloc.lower().removeprefix("www.")
    return host.split(".")[0] if host.endswith(("bigcartel.com",)) else re.sub(r"[^a-z0-9]+", "", host.split(".")[0])


def region_for(country: str | None) -> str:
    c = (country or "US").upper()
    return "EU" if c in EU else c


def strip_html(html: str | None, limit: int = 1500) -> str | None:
    if not html:
        return None
    text = HTMLParser(html).text(separator="\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit] or None


def focus_terms(shop: dict, tax: Taxonomy) -> list[str]:
    terms: set[str] = set()
    for bid in shop.get("brands_focus") or []:
        b = tax.brands.get(bid)
        if b:
            terms |= {b["name"].lower(), *(a.lower() for a in b.get("aliases", []) if len(a) > 3)}
    return sorted(terms)


def shopify_listing(p: dict, base: str, slug: str, shop_name: str, currency: str, region: str, fx) -> Listing | None:
    variants = p.get("variants") or []
    avail = [v for v in variants if v.get("available")]
    if not variants:
        return None
    use = avail or variants
    price = min(float(v["price"]) for v in use if v.get("price") is not None)
    opt_names = [o.get("name", "").lower() for o in p.get("options") or []]
    size_idx = next((i for i, n in enumerate(opt_names) if "size" in n), 0)
    sizes: list[str] = []
    for v in avail:
        sz = v.get(f"option{size_idx + 1}")
        if sz and sz not in sizes and sz.lower() not in ("default title", "os"):
            sizes.append(sz)
    images = [i["src"] for i in p.get("images") or [] if i.get("src")]
    pid = str(p["id"])
    return Listing(
        source=f"shop:{slug}", source_id=pid, url=f"{base}/products/{p['handle']}", title=p.get("title") or "",
        price=price, currency=currency, price_usd=fx.to_usd(price, currency), region=region, lang="en",
        description=strip_html(p.get("body_html")), brand_raw=p.get("vendor") or None,
        category_raw=p.get("product_type") or None, size_raw=", ".join(sizes) or None,
        seller=Seller(f"shop:{slug}", slug, username=shop_name),
        image_url=images[0] if images else None, image_urls=images[:4],
        status="active" if avail else "sold", listed_at=_ts(p.get("published_at") or p.get("created_at")),
    )


def bigcartel_listing(p: dict, base: str, slug: str, shop_name: str, currency: str, region: str, fx) -> Listing | None:
    """BigCartel public `products.json` (field names from memory; untested live)."""
    if p.get("price") is None:
        return None
    opts = p.get("options") or []
    avail = [o for o in opts if not o.get("sold_out")] if opts else []
    sold = p.get("status") in ("sold-out", "sold_out") or (bool(opts) and not avail)
    imgs = [i.get("url") for i in p.get("images") or [] if i.get("url")]
    price = float(p["price"])
    return Listing(
        source=f"shop:{slug}", source_id=str(p["id"]), url=p.get("url") or f"{base}/product/{p.get('permalink', '')}",
        title=p.get("name") or "", price=price, currency=p.get("currency") or currency,
        price_usd=fx.to_usd(price, p.get("currency") or currency), region=region, lang="en",
        description=strip_html(p.get("description")), size_raw=", ".join(o.get("name", "") for o in avail) or None,
        seller=Seller(f"shop:{slug}", slug, username=shop_name), image_url=imgs[0] if imgs else None,
        image_urls=imgs[:4], status="sold" if sold else "active", listed_at=_ts(p.get("created_at")),
    )


def js_to_json(p: dict) -> dict:
    """`/products/<handle>.js` (has per-variant `available`; prices in cents) -> products.json shape."""
    def img(u: str) -> str:
        return "https:" + u if u.startswith("//") else u
    return {
        "id": p["id"], "title": p.get("title"), "handle": p.get("handle"), "body_html": p.get("description"),
        "vendor": p.get("vendor"), "product_type": p.get("type"), "tags": p.get("tags") or [],
        "published_at": p.get("published_at"), "created_at": p.get("created_at"),
        "options": [o if isinstance(o, dict) else {"name": o} for o in p.get("options") or []],
        "images": [{"src": img(u)} for u in p.get("images") or []],
        "variants": [{**v, "price": f"{(v.get('price') or 0) / 100:.2f}"} for v in p.get("variants") or []],
    }


class Webshops:
    def __init__(self, ctx: Ctx, client: PoliteClient | None = None, tax: Taxonomy | None = None):
        self.ctx = ctx
        self.tax = tax or load_taxonomy()
        self.http = client or PoliteClient(
            min_delay=1.5, max_delay=3.0, on_response=lambda r: ctx.rawlog(str(r.url), r.status_code,
                                                                          r.text if r.status_code != 200 or len(r.text) < 20000 else f"<{len(r.text)} bytes>"))

    # ---- shop metadata ------------------------------------------------------------------
    def _meta(self, base: str, slug: str) -> tuple[str, str]:
        key = f"shop_meta:{slug}"
        cached = self.ctx.db.kv_get(key)
        if cached:
            m = json.loads(cached)
            return m["currency"], m["region"]
        try:
            d = self.http.get_json(f"{base}/meta.json")
            cur, region = (d.get("currency") or "USD").upper(), region_for(d.get("country"))
        except (FetchError, NotFound):
            return "USD", "US"
        if not self.ctx.dry_run:
            self.ctx.db.kv_set(key, json.dumps({"currency": cur, "region": region}))
        return cur, region

    def shops(self) -> list[dict]:
        return list(self.tax.sellers.get("webshops") or [])

    # ---- one shop -----------------------------------------------------------------------
    def scrape_shop(self, shop: dict) -> RunResult:
        slug = slug_for(shop)
        source = f"shop:{slug}"
        res = RunResult(source, "scrape", rung="direct")
        parts = urlsplit(shop["url"])
        base = f"{parts.scheme}://{parts.netloc}"
        platform = (shop.get("platform") or "shopify").lower()
        cur, region = self._meta(base, slug) if platform == "shopify" else ("USD", "US")
        terms: list[str] = []
        prefix = ""
        coll = re.search(r"/collections/([^/?#]+)", parts.path)
        fallback = False
        if coll:  # a named collection is the intended scope; if it is gone, fall back to a brand-filtered crawl
            prefix = f"/collections/{coll.group(1)}"
        pages = DEEP_PAGES if self.ctx.deep else MAX_PAGES
        wm_key = f"shop_wm:{slug}"
        wm = int(self.ctx.db.kv_get(wm_key) or 0)
        pub_key = f"shop_pub:{slug}"
        pub_wm = int(self.ctx.db.kv_get(pub_key) or 0)
        max_updated, max_pub = wm, pub_wm
        collected: dict[str, Listing] = {}
        new_count = 0
        seen_any = False
        for page in range(1, pages + 1):
            url = (f"{base}{prefix}/products.json?limit={LIMIT}&page={page}" if platform == "shopify"
                   else f"{base}/products.json?page={page}")
            try:
                data = self.http.get_json(url)
            except NotFound:
                data = {"products": []}
            products = data.get("products") if isinstance(data, dict) else data
            products = products or []
            if page == 1 and prefix and not products:
                prefix, fallback = "", True
                terms = focus_terms(shop, self.tax)
                res.note = f"collection {coll.group(1)} empty or gone; crawling store filtered to brands_focus"
                data = self.http.get_json(f"{base}/products.json?limit={LIMIT}&page=1")
                products = data.get("products") or []
            if not products:
                break
            seen_any = True
            known = known_ids(self.ctx.db, source, [str(p["id"]) for p in products])
            page_new = 0
            page_pub = max((_ts(p.get("published_at")) or 0) for p in products)
            max_pub = max(max_pub, page_pub)
            for p in products:
                upd = _ts(p.get("updated_at")) or 0
                max_updated = max(max_updated, upd)
                pid = str(p["id"])
                if terms and not any(t in f"{p.get('vendor','')} {p.get('title','')} {' '.join(p.get('tags') or [])}".lower() for t in terms):
                    continue
                is_new = pid not in known
                if not is_new and upd <= wm:
                    continue
                mk = shopify_listing if platform == "shopify" else bigcartel_listing
                l = mk(p, base, slug, shop.get("name", slug), cur, region, self.ctx.fx)
                if not l:
                    continue
                if is_new and l.status == "sold":
                    continue          # never seen and already sold out: nothing to track
                collected[l.id] = l
                page_new += int(is_new)
            new_count += page_new
            # products.json is newest-published first: once a page holds nothing newer than the previous
            # run's newest publish time, everything beyond it was already seen.
            if page_pub <= pub_wm or len(products) < LIMIT:
                break
        res.seen = len(collected)
        res.queries = 1
        if self.ctx.dry_run:
            res.skipped_dry = new_count
        elif seen_any:
            stats = upsert_listings(self.ctx.db, collected.values())
            res.inserted, res.updated = stats.inserted, stats.price_changed + stats.status_changed
            self.ctx.db.kv_set(wm_key, str(max_updated))
            self.ctx.db.kv_set(pub_key, str(max_pub))
            mark_run(self.ctx.db, source, f"shop:{slug}", hits=len(collected), kept=stats.inserted)
        res.requests = sum(self.http.requests.values())
        return res

    # ---- recheck ------------------------------------------------------------------------
    def recheck(self, ids: list[str]) -> RunResult:
        """`ids` are full listing ids `shop:<slug>:<product id>` or `(source, source_id)` pairs."""
        res = RunResult("webshops", "recheck", rung="direct")
        shops = {slug_for(s): s for s in self.shops()}
        for lid in ids:
            source, sid = lid.rsplit(":", 1)
            slug = source.removeprefix("shop:")
            shop = shops.get(slug)
            old = self.ctx.db.one("SELECT url, price, price_usd, currency, title, status, region FROM listings WHERE id = ?", (lid,))
            if not shop or not old:
                continue
            base = "{0.scheme}://{0.netloc}".format(urlsplit(shop["url"]))
            res.seen += 1
            try:
                p = js_to_json(self.http.get_json(old["url"].split("?")[0] + ".js"))
                cur, region = old["currency"], old["region"]
                l = shopify_listing(p, base, slug, shop.get("name", slug), cur, region, self.ctx.fx)
            except NotFound:
                l = None
            if l is None:
                l = Listing(source, sid, old["url"], old["title"], old["price"], old["currency"], old["price_usd"],
                            region=old["region"], status="removed")
            if self.ctx.dry_run:
                res.skipped_dry += int(l.status != old["status"] or abs(l.price - old["price"]) > 1e-6)
                continue
            stats = upsert_listings(self.ctx.db, [l])
            res.updated += stats.price_changed + stats.status_changed
            mark_run(self.ctx.db, "recheck:webshops", lid)
        res.requests = sum(self.http.requests.values())
        return res
