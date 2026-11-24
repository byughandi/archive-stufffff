"""The contract between scrapers and the pipeline.

Scrapers produce `Listing` objects and hand them to `upsert_listings`. They never score,
classify or filter: that is the pipeline's job. `upsert_listings` owns incremental semantics:
new rows are inserted and queued for scoring, price/status changes write a snapshot and
re-queue, and unchanged rows cost no writes (apart from a once-a-day `last_seen_at` touch).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from .db import Database, now

DAY = 86400


@dataclass
class Seller:
    source: str
    source_id: str
    username: str | None = None
    rating: float | None = None        # 0..5
    review_count: int | None = None
    sales_count: int | None = None
    joined_at: int | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass
class Listing:
    source: str                         # grailed | mercari_us | mercari_jp | yahoo_jp | shop:<slug>
    source_id: str
    url: str
    title: str
    price: float
    currency: str                       # ISO code: USD, JPY, EUR...
    price_usd: float                    # converted with core.fx at scrape time
    region: str = "US"
    lang: str = "en"
    description: str | None = None
    brand_raw: str | None = None
    category_raw: str | None = None
    size_raw: str | None = None
    condition_raw: str | None = None
    shipping_usd: float | None = None
    proxy_url: str | None = None
    seller: Seller | None = None
    image_url: str | None = None
    image_urls: list[str] = field(default_factory=list)
    is_auction: bool = False
    auction_end_at: int | None = None
    bids: int | None = None
    buy_now_usd: float | None = None
    status: str = "active"              # active | sold | ended | removed
    listed_at: int | None = None
    sold_at: int | None = None
    sold_price_usd: float | None = None
    query_id: str | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass
class UpsertStats:
    seen: int = 0
    inserted: int = 0
    price_changed: int = 0
    status_changed: int = 0
    unchanged: int = 0

    def __add__(self, o: "UpsertStats") -> "UpsertStats":
        return UpsertStats(*(a + b for a, b in zip(self.as_tuple(), o.as_tuple())))

    def as_tuple(self):
        return (self.seen, self.inserted, self.price_changed, self.status_changed, self.unchanged)

    def as_dict(self):
        return dict(zip(("seen", "inserted", "price_changed", "status_changed", "unchanged"), self.as_tuple()))


def known_ids(db: Database, source: str, source_ids: Iterable[str]) -> set[str]:
    """Which of these source ids are already stored. Scrapers use this for the incremental stop."""
    ids = list(dict.fromkeys(source_ids))
    found: set[str] = set()
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        marks = ",".join("?" * len(chunk))
        rows = db.query(
            f"SELECT source_id FROM listings WHERE source = ? AND source_id IN ({marks})", (source, *chunk)
        )
        found.update(r["source_id"] for r in rows)
    return found


def upsert_listings(db: Database, listings: Iterable[Listing]) -> UpsertStats:
    items = {l.id: l for l in listings}  # de-dupe within the batch
    stats = UpsertStats(seen=len(items))
    if not items:
        return stats
    t = now()
    existing: dict[str, dict] = {}
    ids = list(items)
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        marks = ",".join("?" * len(chunk))
        for r in db.query(
            f"SELECT id, price, price_usd, status, last_seen_at, bids, auction_end_at FROM listings WHERE id IN ({marks})",
            chunk,
        ):
            existing[r["id"]] = r

    stmts: list[tuple[str, tuple]] = []
    sellers: dict[str, Seller] = {}
    for lid, l in items.items():
        if l.seller:
            sellers[l.seller.id] = l.seller
        old = existing.get(lid)
        if old is None:
            stats.inserted += 1
            stmts.append((
                "INSERT INTO listings (id, source, source_id, url, proxy_url, region, lang, title, description,"
                " brand_raw, category_raw, size_raw, condition_raw, price, currency, price_usd, shipping_usd,"
                " seller_id, image_url, image_urls, is_auction, auction_end_at, bids, buy_now_usd, status,"
                " listed_at, first_seen_at, last_seen_at, sold_at, sold_price_usd, needs_score, query_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)"
                " ON CONFLICT(id) DO NOTHING",
                (lid, l.source, l.source_id, l.url, l.proxy_url, l.region, l.lang, l.title[:500],
                 (l.description or None) and l.description[:4000], l.brand_raw, l.category_raw, l.size_raw,
                 l.condition_raw, l.price, l.currency, l.price_usd, l.shipping_usd,
                 l.seller.id if l.seller else None, l.image_url, json.dumps(l.image_urls[:4]),
                 int(l.is_auction), l.auction_end_at, l.bids, l.buy_now_usd, l.status, l.listed_at, t, t,
                 l.sold_at, l.sold_price_usd, l.query_id),
            ))
            stmts.append((
                "INSERT OR IGNORE INTO listing_snapshots (listing_id, at, price, price_usd, status) VALUES (?,?,?,?,?)",
                (lid, t, l.price, l.price_usd, l.status),
            ))
            continue

        if l.description:
            # A later fetch (item detail, recheck) can bring text the search result lacked.
            # Fills only an empty description, and re-queues the row since more text can change its class.
            stmts.append((
                "UPDATE listings SET description = ?, needs_score = 1 WHERE id = ? AND description IS NULL",
                (l.description[:4000], lid),
            ))
        price_changed = abs(float(old["price"]) - float(l.price)) > 1e-6
        status_changed = old["status"] != l.status
        if price_changed or status_changed:
            stats.price_changed += int(price_changed)
            stats.status_changed += int(status_changed and not price_changed)
            sets = ["price = ?", "price_usd = ?", "status = ?", "last_seen_at = ?", "needs_score = 1",
                    "bids = ?", "auction_end_at = COALESCE(?, auction_end_at)",
                    "sold_at = COALESCE(?, sold_at)", "sold_price_usd = COALESCE(?, sold_price_usd)"]
            args: list = [l.price, l.price_usd, l.status, t, l.bids, l.auction_end_at, l.sold_at, l.sold_price_usd]
            if price_changed:
                sets += ["prev_price_usd = ?", "price_changed_at = ?"]
                args += [old["price_usd"], t]
            stmts.append((f"UPDATE listings SET {', '.join(sets)} WHERE id = ?", (*args, lid)))
            stmts.append((
                "INSERT OR IGNORE INTO listing_snapshots (listing_id, at, price, price_usd, status) VALUES (?,?,?,?,?)",
                (lid, t, l.price, l.price_usd, l.status),
            ))
        else:
            stats.unchanged += 1
            bids_changed = l.is_auction and (l.bids != old["bids"] or l.auction_end_at != old["auction_end_at"])
            if bids_changed or t - int(old["last_seen_at"] or 0) > DAY:
                stmts.append((
                    "UPDATE listings SET last_seen_at = ?, bids = COALESCE(?, bids),"
                    " auction_end_at = COALESCE(?, auction_end_at) WHERE id = ?",
                    (t, l.bids, l.auction_end_at, lid),
                ))

    for s in sellers.values():
        stmts.append((
            "INSERT INTO sellers (id, source, username, rating, review_count, sales_count, joined_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET"
            " username = COALESCE(excluded.username, username), rating = COALESCE(excluded.rating, rating),"
            " review_count = COALESCE(excluded.review_count, review_count),"
            " sales_count = COALESCE(excluded.sales_count, sales_count),"
            " joined_at = COALESCE(excluded.joined_at, joined_at), updated_at = excluded.updated_at"
            " WHERE excluded.updated_at - sellers.updated_at > 86400"
            " OR sellers.rating IS NOT excluded.rating OR sellers.review_count IS NOT excluded.review_count",
            (s.id, s.source, s.username, s.rating, s.review_count, s.sales_count, s.joined_at, t),
        ))
    if stmts:
        db.batch(stmts)
    return stats


@dataclass
class SoldComp:
    source: str
    source_id: str
    title: str
    sold_price_usd: float
    sold_at: int
    url: str | None = None
    image_url: str | None = None
    brand_raw: str | None = None
    size_raw: str | None = None
    condition_raw: str | None = None
    description: str | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"


def upsert_comps(db: Database, comps: Iterable[SoldComp]) -> int:
    """Store raw sold comps. The pipeline classifies rows where classified = 0. Returns rows inserted."""
    t = now()
    stmts = [(
        "INSERT INTO comps_sold (id, source, url, title, image_url, sold_price_usd, sold_at, brand_raw, size_raw,"
        " condition_raw, description, classified, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)"
        " ON CONFLICT(id) DO NOTHING",
        (c.id, c.source, c.url, c.title[:500], c.image_url, c.sold_price_usd, c.sold_at, c.brand_raw, c.size_raw,
         c.condition_raw, (c.description or None) and c.description[:2000], t),
    ) for c in {c.id: c for c in comps}.values()]
    return db.batch(stmts) if stmts else 0
