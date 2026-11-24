"""Dev-only: seed a local SQLite file with real Mercari JP listings and sold comps.

Not part of the production pipeline (scrapers/ does this properly). It exists so scoring can be
developed against real data from a machine where only the Japanese sources are reachable.
Usage: GR_DB_PATH=data/dev/dev.db python scripts/dev_seed.py [max_queries]
"""
import asyncio, random, sys

from mercapi import Mercapi
from mercapi.requests import SearchRequestData

from core.db import connect
from core.fx import load_fx
from core.models import Listing, Seller, SoldComp, upsert_comps, upsert_listings
from core.taxonomy import load_taxonomy


def ts(v):
    try:
        return int(v.timestamp())
    except Exception:
        return None


async def main(max_q: int):
    db = connect(); db.migrate(); fx = load_fx(db); tax = load_taxonomy()
    queries = tax.ja.get("search_queries", [])[:max_q]
    m = Mercapi(); n_l = n_c = 0
    for i, q in enumerate(queries):
        for status, sold in ((SearchRequestData.Status.STATUS_ON_SALE, False), (SearchRequestData.Status.STATUS_SOLD_OUT, True)):
            try:
                r = await m.search(q["query"], status=[status],
                                   sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
                                   sort_order=SearchRequestData.SortOrder.ORDER_DESC)
            except Exception as e:
                print("ERR", q["query"], e); await asyncio.sleep(5); continue
            if sold:
                comps = [SoldComp("mercari_jp", it.id_, it.name or "", fx.to_usd(it.price, "JPY"), ts(it.updated) or 0,
                                  url=f"https://jp.mercari.com/item/{it.id_}",
                                  image_url=(it.thumbnails or [None])[0]) for it in r.items if it.price]
                n_c += upsert_comps(db, comps)
            else:
                ls = [Listing("mercari_jp", it.id_, f"https://jp.mercari.com/item/{it.id_}", it.name or "", float(it.price), "JPY",
                              fx.to_usd(it.price, "JPY"), region="JP", lang="ja",
                              proxy_url=f"https://buyee.jp/mercari/item/{it.id_}",
                              seller=Seller("mercari_jp", str(it.seller_id)) if it.seller_id else None,
                              image_url=(it.thumbnails or [None])[0], image_urls=list(it.thumbnails or [])[:4],
                              condition_raw=str(it.item_condition_id) if it.item_condition_id else None,
                              listed_at=ts(it.created), query_id=f"ja:{q['query']}") for it in r.items if it.price]
                n_l += upsert_listings(db, ls).inserted
            await asyncio.sleep(random.uniform(1.0, 2.2))
        print(f"{i+1}/{len(queries)} {q['query']}  listings={n_l} comps={n_c}", flush=True)


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 60))
