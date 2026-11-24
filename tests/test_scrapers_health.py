import httpx

from core import health
from core.fx import Fx
from scrapers import run as runner
from scrapers import yahoo_jp
from scrapers.common.http import PoliteClient


def test_breaker_trips_after_three_blocked_runs_and_resets_on_success(db):
    t = 1_000_000
    assert health.allowed(db, "grailed", t)
    assert not health.record_failure(db, "grailed", True, "403", at=t)
    assert not health.record_failure(db, "grailed", True, "429", at=t + 60)
    assert health.allowed(db, "grailed", t + 120)
    assert health.record_failure(db, "grailed", True, "challenge", at=t + 120)
    row = health.get(db, "grailed")
    assert row["last_status"] == "paused" and row["breaker_until"] == t + 120 + 6 * 3600
    assert not health.allowed(db, "grailed", t + 3600)
    assert health.allowed(db, "grailed", t + 120 + 6 * 3600)          # half-open after 6 h
    assert health.record_failure(db, "grailed", True, "still blocked", at=t + 7 * 3600)  # re-opens at once
    assert not health.allowed(db, "grailed", t + 7 * 3600 + 10)
    health.record_ok(db, "grailed", 5, "apify", at=t + 20 * 3600)
    row = health.get(db, "grailed")
    assert row["consecutive_failures"] == 0 and row["breaker_until"] is None and row["rung"] == "apify"


def test_plain_errors_do_not_trip_quickly(db):
    for i in range(5):
        assert not health.record_failure(db, "yahoo_jp", False, "boom", at=100 + i)
    assert health.allowed(db, "yahoo_jp", 200)
    assert health.record_failure(db, "yahoo_jp", False, "boom", at=300)


def test_item_counters_roll_over_by_day(db):
    day1, day2 = 1_700_000_000, 1_700_000_000 + 86400
    health.record_ok(db, "mercari_jp", 4, "library", at=day1)
    health.record_ok(db, "mercari_jp", 3, "library", at=day1 + 10)
    row = health.get(db, "mercari_jp")
    assert (row["items_today"], row["items_total"], row["last_status"]) == (7, 7, "ok")
    health.record_ok(db, "mercari_jp", 0, "library", at=day2)
    row = health.get(db, "mercari_jp")
    assert (row["items_today"], row["items_total"], row["last_status"]) == (0, 7, "empty")


def test_simulated_429s_trip_breaker_and_block_next_run(tmp_path, monkeypatch, capsys, fx):
    """End to end through the CLI: three runs that only see 429 open the breaker, the fourth is not even attempted."""
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("GR_RAW", "0")
    monkeypatch.setattr(runner, "load_fx", lambda db: fx)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(429, headers={"retry-after": "0"}, text="slow down")

    class P(PoliteClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, transport=httpx.MockTransport(handler), sleep=lambda s: None,
                             max_retries=1, **{k: v for k, v in kw.items() if k not in ("transport", "sleep", "max_retries")})

    monkeypatch.setattr(yahoo_jp, "PoliteClient", P)

    for i in range(3):
        code = runner.main(["slow", "--source", "yahoo_jp", "--max-queries", "1"])
        out = capsys.readouterr().out.strip().splitlines()
        assert code == 0, out                      # blocked is handled, not a failed job
        assert '"status": "blocked"' in out[-1] or '"status": "paused"' in out[-1]
    assert '"status": "paused"' in out[-1]         # third block opened the breaker
    n = len(calls)
    code = runner.main(["slow", "--source", "yahoo_jp", "--max-queries", "1"])
    out = capsys.readouterr().out
    assert '"status": "paused"' in out and len(calls) == n    # no request made while the breaker is open
    assert code == 0                                          # nothing attempted -> not a failed job


def test_parked_rung_does_not_count_toward_the_breaker(tmp_path, monkeypatch, capsys):
    """A run that makes no request because its rung is on cooldown is not another block."""
    import json
    from core.db import connect
    from scrapers import run as runner
    from scrapers.common import ladder
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("GR_RAW", "0")
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    db = connect(); db.migrate()
    db.kv_set("fx_rates", json.dumps({"per_usd": {"USD": 1.0, "JPY": 150.0}, "fetched_at": __import__("time").time().__int__()}))
    ladder.block(db, "grailed", "direct")
    for _ in range(4):
        assert runner.main(["fast", "--source", "grailed"]) == 0
        assert '"status": "parked"' in capsys.readouterr().out
    row = db.one("SELECT consecutive_failures, breaker_until FROM source_health WHERE source = 'grailed'")
    assert row is None or (row["consecutive_failures"] == 0 and row["breaker_until"] is None)
