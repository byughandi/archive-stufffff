"""Weekly Instagram pull for trend detection: latest 12 posts for each handle in
`weekly_scrape_list` (data/taxonomy/sellers.yaml), via an Apify Instagram actor.

Only text + counts + the hotlinked image URL are stored (`ig_posts`); no image is downloaded.
Trend scoring is the pipeline's job. Mock-tested only: api.apify.com is unreachable from the
build machine and the actor's output field names are from memory (see `_post_from_item`).
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from core.db import now
from core.taxonomy import Taxonomy, load_taxonomy
from scrapers import apify
from scrapers.common import Ctx, RunResult
from scrapers.common.http import PoliteClient

SOURCE = "instagram"
POSTS_PER_ACCOUNT = 12           # upper bound; the run is sized down to fit the monthly budget
MIN_POSTS_PER_ACCOUNT = 4
RUNS_PER_MONTH = 4.4             # weekly


def posts_per_account(n_accounts: int, price_per_1k: float, monthly_cap_usd: float) -> int:
    """Largest per-account post count that keeps a month of weekly runs inside the source's budget."""
    if n_accounts <= 0 or price_per_1k <= 0:
        return POSTS_PER_ACCOUNT
    per_run_posts = monthly_cap_usd / RUNS_PER_MONTH / price_per_1k * 1000.0
    return max(MIN_POSTS_PER_ACCOUNT, min(POSTS_PER_ACCOUNT, int(per_run_posts // n_accounts)))
BATCH = 25                       # accounts per actor run (keeps each run well under the timeout)
_TAG = re.compile(r"#([\wÀ-￿]+)", re.U)


def _ts(v) -> int | None:
    if isinstance(v, (int, float)):
        return int(v)
    if not v:
        return None
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def post_from_item(item: dict) -> dict | None:
    """One actor dataset item -> an ig_posts row dict. Field names: CONFIRM against a real run."""
    handle = item.get("ownerUsername") or (item.get("owner") or {}).get("username") or item.get("username")
    pid = item.get("id") or item.get("shortCode") or item.get("shortcode")
    if not handle or not pid:
        return None
    caption = item.get("caption") or ""
    tags = item.get("hashtags")
    if not isinstance(tags, list):
        tags = _TAG.findall(caption)
    imgs = item.get("images") or []
    image = item.get("displayUrl") or item.get("imageUrl") or (imgs[0] if imgs else None)
    likes = item.get("likesCount", item.get("likes"))
    return {
        "id": f"ig:{pid}", "handle": str(handle).lower(), "posted_at": _ts(item.get("timestamp") or item.get("takenAt")),
        "caption": caption[:2000], "hashtags": json.dumps([str(t).lower().lstrip("#") for t in tags][:30], ensure_ascii=False),
        "likes": likes if isinstance(likes, int) and likes >= 0 else None,
        "comments": item.get("commentsCount", item.get("comments")), "image_url": image,
    }


def run(ctx: Ctx, tax: Taxonomy | None = None, client: PoliteClient | None = None) -> RunResult:
    tax = tax or load_taxonomy()
    handles = [h for h in tax.sellers.get("weekly_scrape_list") or [] if h]
    res = RunResult(SOURCE, "trends", rung="apify")
    actor = apify.actor_for("INSTAGRAM")
    posts: dict[str, dict] = {}
    per_account = posts_per_account(len(handles), actor.price_per_1k, apify.source_cap("instagram"))
    for i in range(0, len(handles), BATCH):
        batch = handles[i:i + BATCH]
        items = apify.run_actor(ctx.db, actor, apify.instagram_input(actor, batch, per_account),
                                max_items=len(batch) * per_account, source="instagram", client=client)
        ctx.rawlog("apify:" + actor.id, 200, items)
        res.queries += 1
        for it in items:
            p = post_from_item(it)
            if p:
                posts[p["id"]] = p
    res.seen = len(posts)
    if ctx.dry_run or not posts:
        res.skipped_dry = len(posts) if ctx.dry_run else 0
        return res
    t = now()
    stmts = [(
        "INSERT INTO ig_posts (id, handle, posted_at, caption, hashtags, likes, comments, image_url, ingested_at)"
        " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET likes = excluded.likes,"
        " comments = excluded.comments, caption = excluded.caption, image_url = excluded.image_url",
        (p["id"], p["handle"], p["posted_at"], p["caption"], p["hashtags"], p["likes"], p["comments"],
         p["image_url"], t)) for p in posts.values()]
    ctx.db.batch(stmts)
    res.inserted = len(stmts)
    return res
