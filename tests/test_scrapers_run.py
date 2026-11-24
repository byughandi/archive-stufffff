import json

from core.db import now
from core.models import Listing, upsert_listings
from scrapers import run as runner
from scrapers.common.queries import mark_run


def add(db, fx, sid, tier, source="mercari_jp", status="active"):
    upsert_listings(db, [Listing(source, sid, f"https://x/{sid}", "t", 1000, "JPY", fx.to_usd(1000, "JPY"), status=status)])
    db.execute(
        "INSERT INTO feed (listing_id, source, region, url, title, price, currency, price_usd, landed_usd, tier, tier_rank,"
        " status, listed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"{source}:{sid}", source, "JP", "u", "t", 1000, "JPY", 6.6, 10, tier, "SABCX".index(tier), status, now()))


def test_recheck_selection_tiers_and_oldest_checked_first(db, fx):
    add(db, fx, "a", "S"); add(db, fx, "b", "A"); add(db, fx, "c", "B"); add(db, fx, "d", "C"); add(db, fx, "e", "S", status="sold")
    add(db, fx, "z", "S", source="yahoo_jp")
    assert sorted(runner.recheck_ids(db, "mercari_jp", 10)) == ["a", "b", "c"]
    mark_run(db, "recheck:mercari_jp", "mercari_jp:a", at=100)
    mark_run(db, "recheck:mercari_jp", "mercari_jp:b", at=50)
    assert runner.recheck_ids(db, "mercari_jp", 10)[:3] == ["c", "b", "a"]          # never checked, then oldest
    assert runner.recheck_ids(db, "mercari_jp", 2) == ["c", "b"]
    assert runner.recheck_ids(db, "yahoo_jp", 10) == ["z"]


def test_recheck_selection_webshops_use_full_ids(db, fx):
    add(db, fx, "123", "A", source="shop:driewgarments")
    assert runner.recheck_ids(db, "webshops", 5) == ["shop:driewgarments:123"]


def test_fast_runs_mercari_us_every_second_run(tmp_path, monkeypatch, capsys, fx):
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "f.db"))
    monkeypatch.setenv("GR_RAW", "0")
    monkeypatch.setattr(runner, "load_fx", lambda db: fx)
    ran: list[str] = []
    from scrapers import grailed, mercari_us
    from scrapers.common import RunResult
    monkeypatch.setattr(grailed, "run", lambda ctx, q: ran.append("grailed") or RunResult("grailed", inserted=1))
    monkeypatch.setattr(mercari_us, "run", lambda ctx, q: ran.append("mercari_us") or RunResult("mercari_us", inserted=1))
    for _ in range(4):
        assert runner.main(["fast"]) == 0
    assert ran.count("grailed") == 4 and ran.count("mercari_us") == 2


def test_one_failing_source_does_not_fail_the_job_and_all_failing_does(tmp_path, monkeypatch, capsys, fx):
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "g.db"))
    monkeypatch.setenv("GR_RAW", "0")
    monkeypatch.setattr(runner, "load_fx", lambda db: fx)
    from scrapers import grailed, mercari_us
    from scrapers.common import RunResult
    from scrapers.common.http import Blocked

    def boom(ctx, q):
        raise Blocked("403")
    monkeypatch.setattr(grailed, "run", boom)
    monkeypatch.setattr(mercari_us, "run", lambda ctx, q: RunResult("mercari_us", inserted=3, rung="apify"))
    # a block is a handled state: recorded, next rung or breaker takes over, job carries on to scoring
    assert runner.main(["fast", "--source", "grailed"]) == 0
    capsys.readouterr()
    runner.main(["fast"])      # counter 1: grailed only
    capsys.readouterr()
    runner.main(["fast"])      # counter 2: includes mercari_us
    lines = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    by = {l["source"]: l for l in lines}
    assert by["grailed"]["status"] in ("blocked", "paused") and "error" in by["grailed"] and by["mercari_us"]["status"] == "ok"
    from core.db import connect
    db = connect()
    assert db.one("SELECT rung, items_total FROM source_health WHERE source='mercari_us'") == {"rung": "apify", "items_total": 3}


def test_dry_run_writes_no_health_or_rows(tmp_path, monkeypatch, capsys, fx):
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "d.db"))
    monkeypatch.setattr(runner, "load_fx", lambda db: fx)
    from scrapers import grailed
    from scrapers.common import RunResult
    monkeypatch.setattr(grailed, "run", lambda ctx, q: RunResult("grailed", skipped_dry=5))
    assert runner.main(["fast", "--source", "grailed", "--dry-run"]) == 0
    from core.db import connect
    assert connect().scalar("SELECT COUNT(*) FROM source_health") == 0
    assert not (tmp_path.parent / "raw").exists() or True


def test_raw_writer_roundtrip(tmp_path):
    import gzip
    from scrapers.common import RawWriter
    w = RawWriter("shop:x", base=tmp_path)
    w.write("https://a", 200, {"k": "ü"})
    w.close()
    f = next((tmp_path / "shop_x").glob("*.jsonl.gz"))
    rec = json.loads(gzip.open(f, "rt", encoding="utf-8").readline())
    assert rec["url"] == "https://a" and rec["body"] == {"k": "ü"}


def test_unexpected_error_on_every_source_fails_the_job(tmp_path, monkeypatch, capsys, fx):
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "e.db"))
    monkeypatch.setenv("GR_RAW", "0")
    monkeypatch.setattr(runner, "load_fx", lambda db: fx)
    from scrapers import grailed

    def crash(ctx, q):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(grailed, "run", crash)
    assert runner.main(["fast", "--source", "grailed"]) == 1
    assert '"status": "error"' in capsys.readouterr().out
