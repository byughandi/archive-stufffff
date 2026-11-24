import json
import random

from pipeline.ranker import FEATURES, Ranker, fit, retrain, training_rows
from pipeline_util import make_db


def test_formula_monotonic():
    r = Ranker()
    base = {k: 0.5 for k in FEATURES}
    hi = dict(base, junk=0.0, risk=0.0, brand_w=1.0)
    lo = dict(base, junk=0.9, risk=0.8, brand_w=0.2)
    assert r.name == "formula-v1"
    assert r.prob(hi) > r.prob(lo)


def test_fit_and_numpy_inference_match_sklearn():
    random.seed(0)
    X, y = [], []
    for _ in range(300):
        f = {k: random.random() for k in FEATURES}
        X.append(f)
        y.append(1 if f["brand_w"] + f["piece_w"] - f["junk"] + random.gauss(0, 0.2) > 0.5 else 0)
    m = fit(X, y)
    r = Ranker(m)
    assert r.prob(dict(X[0])) == r.prob(X[0])
    good = {k: 0.5 for k in FEATURES} | {"brand_w": 1.0, "piece_w": 1.0, "junk": 0.0}
    bad = {k: 0.5 for k in FEATURES} | {"brand_w": 0.0, "piece_w": 0.0, "junk": 1.0}
    assert r.prob(good) > 0.8 > 0.2 > r.prob(bad)


def _seed_feedback(db, n, off=0):
    rows = []
    for i in range(off, off + n):
        pos = i % 2 == 0
        f = {k: 0.5 for k in FEATURES} | {"brand_w": 0.9 if pos else 0.2, "junk": 0.1 if pos else 0.8}
        rows.append(("INSERT INTO feedback (listing_id, kind, features, created_at) VALUES (?,?,?,?)",
                     (f"l{i}", "up" if pos else "down", json.dumps(f), 1000 + i)))
    rows.append(("INSERT INTO feedback (listing_id, kind, features, created_at) VALUES (?,?,?,?)",
                 ("lx", "wrong_era", json.dumps({}), 5000)))
    db.batch(rows)


def test_retrain_needs_labels_and_refuses_worse(tmp_path, monkeypatch):
    db = make_db(tmp_path, monkeypatch)
    _seed_feedback(db, 50)
    out = retrain(db, lambda rk: 1.0, 200)
    assert out["promoted"] is False and out["reason"] == "not_enough_labels"
    _seed_feedback(db, 250, off=50)
    X, y = training_rows(db)
    assert len(y) == 300 and set(y) == {0, 1}            # wrong_era is neutral
    out = retrain(db, lambda rk: 0.9 if rk.name == "formula-v1" else 0.8, 200)
    assert out["promoted"] is False and out["reason"] == "candidate_worse_on_eval"
    out = retrain(db, lambda rk: 0.9, 200)
    assert out["promoted"] is True and db.kv_get("ranker_model")
