"""Stage 4: relevance ranker.

Below `ranker_min_labels` feedback labels the hand-weighted `formula-v1` is used. Above it, `retrain` fits a
regularised logistic regression (scikit-learn) on the `feedback` table, stores coefficients + feature names +
scaler in kv `ranker_model`, and inference runs in plain numpy. A new model is promoted only if it does not score
worse than the current one on the eval set.

Label mapping (docs/CONTRACTS.md): positive = up, cop, bought; negative = down, fake, wrong_brand;
wrong_era is neutral for relevance.
"""
from __future__ import annotations

import json
import math
import time

import numpy as np

FEATURES = ["has_brand", "brand_w", "era_resolved", "era_w", "era_conf", "unwanted_era", "season", "piece_w",
            "trend", "taste", "junk", "risk", "stuffing", "archetype_known", "below_floor", "rarity"]

FORMULA_V1 = {
    "_bias": -3.2, "has_brand": 2.0, "brand_w": 1.6, "era_resolved": 0.3, "era_w": 1.2, "era_conf": 0.3,
    "unwanted_era": -1.6, "season": 0.6, "piece_w": 1.0, "trend": 0.8, "taste": 1.2, "junk": -1.5,
    "risk": -2.0, "stuffing": -1.2, "archetype_known": 0.3, "below_floor": -0.4, "rarity": 0.2,
}
POSITIVE = {"up", "cop", "bought"}
NEGATIVE = {"down", "fake", "wrong_brand"}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def feature_vector(f: dict) -> list[float]:
    return [float(f.get(k, 0.0) or 0.0) for k in FEATURES]


class Ranker:
    def __init__(self, model: dict | None = None):
        self.model = model
        if model:
            self.name = model.get("version", "logreg")
            names = model["features"]
            self._idx = [names.index(k) if k in names else -1 for k in FEATURES]
            self._coef = np.asarray(model["coef"], float)
            self._mean = np.asarray(model["mean"], float)
            self._scale = np.asarray(model["scale"], float)
            self._names = names
        else:
            self.name = "formula-v1"

    def prob(self, f: dict) -> float:
        if not self.model:
            z = FORMULA_V1["_bias"] + sum(FORMULA_V1[k] * float(f.get(k, 0.0) or 0.0) for k in FEATURES)
            return sigmoid(z)
        x = np.asarray([float(f.get(k, 0.0) or 0.0) for k in self._names], float)
        xs = (x - self._mean) / np.where(self._scale == 0, 1, self._scale)
        return sigmoid(float(xs @ self._coef + self.model["intercept"]))


def load_ranker(db) -> Ranker:
    if db is None:
        return Ranker()
    raw = db.kv_get("ranker_model")
    if not raw:
        return Ranker()
    try:
        return Ranker(json.loads(raw))
    except Exception:
        return Ranker()


def training_rows(db) -> tuple[list[dict], list[int]]:
    """One row per listing: the latest relevance feedback, features from the tap snapshot or the stored explain."""
    fb = db.query("SELECT listing_id, kind, features, created_at FROM feedback ORDER BY created_at")
    latest: dict[str, tuple[str, str | None]] = {}
    for r in fb:
        if r["kind"] in POSITIVE or r["kind"] in NEGATIVE:
            latest[r["listing_id"]] = (r["kind"], r["features"])
    X, y = [], []
    missing = [lid for lid, (_, f) in latest.items() if not f]
    stored: dict[str, dict] = {}
    for i in range(0, len(missing), 300):
        chunk = missing[i:i + 300]
        for r in db.query(f"SELECT listing_id, explain FROM scores WHERE listing_id IN ({','.join('?' * len(chunk))})", chunk):
            try:
                stored[r["listing_id"]] = (json.loads(r["explain"] or "{}").get("ranker") or {}).get("features") or {}
            except Exception:
                pass
    for lid, (kind, f) in latest.items():
        feats = None
        if f:
            try:
                feats = json.loads(f)
            except Exception:
                feats = None
        feats = feats or stored.get(lid)
        if not feats:
            continue
        X.append(feats)
        y.append(1 if kind in POSITIVE else 0)
    return X, y


def fit(X: list[dict], y: list[int], C: float = 0.5) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    A = np.asarray([feature_vector(f) for f in X], float)
    sc = StandardScaler().fit(A)
    lr = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(A), np.asarray(y))
    return {"version": f"logreg-{time.strftime('%Y%m%d')}", "features": FEATURES, "coef": lr.coef_[0].tolist(),
            "intercept": float(lr.intercept_[0]), "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
            "n": len(y), "positives": int(sum(y)), "trained_at": int(time.time())}


def retrain(db, eval_metric, min_labels: int) -> dict:
    """Fit on feedback; promote only if eval precision@50 of the candidate >= the current ranker's."""
    X, y = training_rows(db)
    out = {"labels": len(y), "min_labels": min_labels, "promoted": False}
    if len(y) < min_labels or len(set(y)) < 2:
        out["reason"] = "not_enough_labels"
        out["model"] = load_ranker(db).name
        return out
    cand = fit(X, y)
    cur = load_ranker(db)
    m_cur = eval_metric(cur)
    m_new = eval_metric(Ranker(cand))
    out.update({"current": cur.name, "current_p50": m_cur, "candidate": cand["version"], "candidate_p50": m_new})
    if m_new >= m_cur:
        cand["eval_p50"] = m_new
        db.kv_set("ranker_model", json.dumps(cand))
        out["promoted"] = True
        out["model"] = cand["version"]
    else:
        out["reason"] = "candidate_worse_on_eval"
        out["model"] = cur.name
    return out
