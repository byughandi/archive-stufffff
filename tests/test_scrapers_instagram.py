import httpx

from scrapers import instagram_trends
from tests.conftest import polite

ITEMS = [
    {"id": "111", "ownerUsername": "Glam_Archive", "caption": "Hedi era #diorhomme #hedislimane", "likesCount": 1200,
     "commentsCount": 30, "displayUrl": "https://cdn.ig/1.jpg", "timestamp": "2026-11-20T10:00:00.000Z"},
    {"id": "112", "ownerUsername": "junki_ichikawa", "caption": "AW05 #rickowens", "hashtags": ["rickowens"], "likesCount": -1,
     "commentsCount": 2, "displayUrl": "https://cdn.ig/2.jpg", "timestamp": 1795400000},
    {"caption": "no id"},
]


def test_posts_written_once_with_hashtags_and_no_images(ctx, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    seen = []

    def handler(req):
        import json
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=ITEMS)

    c, _ = polite(handler)
    r = instagram_trends.run(ctx, client=c)
    assert r.inserted == 2 and r.rung == "apify"
    body = seen[0]
    assert 4 <= body["resultsLimit"] <= 12 and body["resultsType"] == "posts" and len(body["directUrls"]) <= 25
    row = ctx.db.one("SELECT * FROM ig_posts WHERE id='ig:111'")
    assert row["handle"] == "glam_archive" and row["likes"] == 1200 and row["image_url"] == "https://cdn.ig/1.jpg"
    assert '"diorhomme"' in row["hashtags"] and row["posted_at"] > 1_700_000_000
    assert ctx.db.one("SELECT likes FROM ig_posts WHERE id='ig:112'")["likes"] is None
    instagram_trends.run(ctx, client=c)                           # re-run updates, no duplicates
    assert ctx.db.scalar("SELECT COUNT(*) FROM ig_posts") == 2
    assert ctx.db.scalar("SELECT COUNT(*) FROM spend_ledger WHERE note='source:instagram'") >= 2


def test_run_is_sized_to_the_monthly_budget():
    from scrapers.instagram_trends import RUNS_PER_MONTH, posts_per_account
    n = posts_per_account(42, 2.3, 3.5)
    assert 4 <= n <= 12
    assert 42 * n * RUNS_PER_MONTH * 2.3 / 1000 <= 3.5          # a month of weekly runs fits the source cap
    assert posts_per_account(10, 1.5, 3.5) == 12                # small lists get the full 12 posts
    assert posts_per_account(400, 2.3, 3.5) == 4                # never below the floor
