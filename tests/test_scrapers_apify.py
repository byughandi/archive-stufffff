import httpx
import pytest

from core.db import now
from scrapers import apify
from tests.conftest import polite


def ledger(db, usd, at=None):
    db.execute("INSERT INTO spend_ledger (at, vendor, kind, units, usd, note) VALUES (?,?,?,?,?,?)",
               (at or now(), "apify", "x", 1, usd, "source:grailed"))


def actor():
    return apify.Actor("GRAILED", "owner/some-actor", 1.0)


def test_limit_is_90_percent_of_credit():
    assert abs(apify.credit_limit() - 4.5) < 1e-9


def test_refuses_when_run_would_pass_90_percent(db, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    ledger(db, 4.40)
    c, rec = polite(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(apify.SpendGuard):
        apify.run_actor(db, actor(), {}, max_items=200, source="instagram", client=c)     # est 0.20 -> 4.60 > 4.50
    assert rec.requests == []                                                           # nothing was sent


def test_allows_run_below_limit_and_writes_ledger(db, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    ledger(db, 4.00)
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["q"] = str(req.url), req.headers.get("authorization"), dict(req.url.params)
        return httpx.Response(200, json=[{"a": 1}] * 50)

    c, _ = polite(handler)
    items = apify.run_actor(db, actor(), {"x": 1}, max_items=100, source="instagram", client=c)
    assert len(items) == 50 and "owner~some-actor/run-sync-get-dataset-items" in seen["url"]
    assert seen["auth"] == "Bearer t" and "token" not in seen["q"]
    row = db.one("SELECT * FROM spend_ledger ORDER BY id DESC LIMIT 1")
    assert row["vendor"] == "apify" and abs(row["usd"] - 0.05) < 1e-9 and row["units"] == 50
    assert abs(apify.month_total(db) - 4.05) < 1e-9


def test_previous_month_does_not_count(db, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    ledger(db, 4.9, at=apify.month_start() - 86400)
    apify.check_budget(db, 1.0)                  # fine: last month's spend is not this month's


def test_per_source_cap(db, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    ledger(db, 2.74)
    with pytest.raises(apify.SpendGuard):
        apify.check_budget(db, 0.05, "grailed")  # cap 2.75
    apify.check_budget(db, 0.05, "mercari_us")   # other sources unaffected
    # the three per-source caps together never exceed the overall stop (90% of the free credit)
    assert sum(apify.DEFAULT_CAPS.values()) <= apify.credit_limit() + 1e-9


def test_missing_token(db, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    with pytest.raises(apify.ApifyUnavailable):
        apify.run_actor(db, actor(), {}, max_items=1, source="grailed")


def test_actor_config_from_sources_yaml_and_env(monkeypatch):
    a = apify.actor_for("GRAILED")
    assert a.id == "piotrv1001/grailed-listings-scraper" and a.price_per_1k == 3.0
    monkeypatch.setenv("APIFY_ACTOR_GRAILED", "me/other")
    monkeypatch.setenv("APIFY_PRICE_GRAILED", "2.5")
    a = apify.actor_for("GRAILED")
    assert (a.id, a.price_per_1k) == ("me/other", 2.5)
