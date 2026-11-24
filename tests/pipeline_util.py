"""Shared helpers for the pipeline tests (kept out of conftest.py, which belongs to the scraper tests)."""
import json
import os
import time

os.environ.setdefault("GR_EMBED", "off")   # tests never download a model


def make_db(tmp_path, monkeypatch):
    monkeypatch.setenv("GR_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    from core.db import connect
    d = connect()
    d.migrate()
    d.kv_set("fx_rates", json.dumps({"per_usd": {"USD": 1.0, "JPY": 150.0, "CAD": 1.38, "AUD": 1.52},
                                     "fetched_at": int(time.time())}))
    return d


def classify(title, **kw):
    from pipeline.classify import get_matcher
    return get_matcher().classify(title, **kw)


def run_one(title, **kw):
    from pipeline.score import score_items
    return score_items([dict(title=title, **kw)])[0]
