"""Stage 3: semantic similarity to the taste exemplars (exemplars.yaml) and image hashing.

Backends behind one interface (`Embedder.similarities`):
- `fastembed:<model>`: small multilingual sentence model (ONNX, CPU). Used when the weights are in the model
  cache (`GR_MODEL_DIR`, default ./models) or when `GR_EMBED=fastembed` (which allows a download).
- `tfidf-char+concepts`: character 2-4-gram TF-IDF cosine. Titles are augmented with canonical taxonomy ids
  (brand/era/season/archetype found by classify.py) so a Japanese title and an English exemplar about the same
  piece still share features. Used when the model is unavailable or `GR_EMBED=off`.
Every scored row records which backend produced its similarity.

Images: perceptual hash (imagehash.phash) of thumbnails for duplicate / stock-photo detection on a capped number
of top candidates per run. `visual_grail_match` stays None; `GR_CLIP=1` is a hook for a future CLIP backend.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from core.config import ROOT
from core.taxonomy import load_taxonomy

from .normalize import norm_text

log = logging.getLogger(__name__)
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TOPK = 3


def model_dir() -> Path:
    d = os.environ.get("GR_MODEL_DIR") or "models"
    p = Path(d)
    return p if p.is_absolute() else ROOT / p


def exemplar_texts() -> tuple[list[str], list[str]]:
    ex = load_taxonomy().exemplars or {}
    grail = [str(t) for g in ex.get("grail", []) or [] for t in g.get("texts") or []]
    junk = [str(t) for g in ex.get("junk", []) or [] for t in g.get("texts") or []]
    return grail, junk


def _concept_text(text: str, concepts: list[str] | None) -> str:
    c = " ".join(f"§{x}§" for x in (concepts or []))
    return f"{norm_text(text)} {c} {c}".strip()


def _analyzer(s: str) -> list[str]:
    feats: list[str] = []
    words = s.split()
    plain = " ".join(w for w in words if not w.startswith("§"))
    feats += [w for w in words if w.startswith("§")]
    p = f" {plain} "
    for n in (2, 3, 4):
        feats += [p[i:i + n] for i in range(len(p) - n + 1)]
    return feats


class Embedder:
    def __init__(self, mode: str | None = None):
        self.mode = (mode or os.environ.get("GR_EMBED", "auto")).lower()
        self.backend = "none"
        self._model = None
        self._grail_v = self._junk_v = None
        self._tfidf = None
        grail, junk = exemplar_texts()
        self.grail_texts, self.junk_texts = grail, junk
        if self.mode != "off":
            self._try_fastembed()
        if self._model is None:
            self._init_tfidf()

    # ------------------------------------------------------------------ backends
    def _model_cached(self) -> bool:
        d = model_dir() / "fastembed"
        return any(d.glob("models--*paraphrase-multilingual-MiniLM-L12-v2*/snapshots/*/*.onnx")) if d.exists() else False

    def _try_fastembed(self) -> None:
        if self.mode == "auto" and not self._model_cached():
            return
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(MODEL_NAME, cache_dir=str(model_dir() / "fastembed"),
                                        threads=os.cpu_count() or 4)
            self.backend = f"fastembed:{MODEL_NAME.split('/')[-1]}"
            self._grail_v = self._cached_vectors("grail", self.grail_texts)
            self._junk_v = self._cached_vectors("junk", self.junk_texts)
        except Exception as e:  # weights missing / CDN blocked / onnxruntime problem: degrade
            log.warning("fastembed unavailable (%s); using TF-IDF fallback", e)
            self._model = None

    def _embed(self, texts: list[str]) -> np.ndarray:
        v = np.asarray(list(self._model.embed(texts, batch_size=128)), dtype=np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        return v

    def _cached_vectors(self, name: str, texts: list[str]) -> np.ndarray:
        h = hashlib.sha1(("\n".join(texts) + MODEL_NAME).encode()).hexdigest()[:12]
        p = model_dir() / f"exemplars_{name}_{h}.npy"
        if p.exists():
            return np.load(p)
        v = self._embed(texts) if texts else np.zeros((0, 384), np.float32)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            np.save(p, v)
        except OSError:
            pass
        return v

    def _init_tfidf(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        from .classify import get_matcher

        m = get_matcher()

        def prep(texts):
            out = []
            for t in texts:
                e = m.classify(t)
                out.append(_concept_text(t, e.concepts))
            return out

        g, j = prep(self.grail_texts), prep(self.junk_texts)
        self._tfidf = TfidfVectorizer(analyzer=_analyzer, sublinear_tf=True, min_df=1)
        self._tfidf.fit(g + j)
        self._grail_v = self._tfidf.transform(g)
        self._junk_v = self._tfidf.transform(j)
        self.backend = "tfidf-char+concepts"

    # ------------------------------------------------------------------ public
    def similarities(self, texts: list[str], concepts: list[list[str]] | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Return (taste_sim, junk_sim) per text: mean cosine of the top-3 grail / junk exemplars."""
        if not texts:
            return np.zeros(0), np.zeros(0)
        if self._model is not None:
            v = self._embed([norm_text(t) for t in texts])
            g = v @ self._grail_v.T
            j = v @ self._junk_v.T
        else:
            cs = concepts or [[] for _ in texts]
            x = self._tfidf.transform([_concept_text(t, c) for t, c in zip(texts, cs)])
            g = (x @ self._grail_v.T).toarray()
            j = (x @ self._junk_v.T).toarray()
        return _topk_mean(g), _topk_mean(j)


def _topk_mean(m: np.ndarray) -> np.ndarray:
    if m.shape[1] == 0:
        return np.zeros(m.shape[0])
    k = min(TOPK, m.shape[1])
    part = np.partition(m, -k, axis=1)[:, -k:]
    return np.clip(part.mean(axis=1), 0.0, 1.0)


_EMBEDDER: Embedder | None = None


def get_embedder() -> Embedder:
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = Embedder()
    return _EMBEDDER


# ---------------------------------------------------------------------------------------------- images
def phash_urls(urls: list[str], timeout: float = 6.0, threads: int = 16) -> dict[str, str]:
    """Perceptual hashes (hex) for thumbnail URLs. Failures are skipped silently."""
    if not urls:
        return {}
    try:
        import httpx
        import imagehash
        from PIL import Image
    except ImportError:  # optional extra not installed
        return {}

    client = httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"user-agent": "Mozilla/5.0 (grail-radar thumbnail hasher)"})

    def one(u: str):
        try:
            r = client.get(u)
            if r.status_code != 200:
                return u, None
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            return u, str(imagehash.phash(im))
        except Exception:
            return u, None

    try:
        with ThreadPoolExecutor(max_workers=threads) as ex:
            res = dict(ex.map(one, list(dict.fromkeys(urls))))
    finally:
        client.close()
    return {k: v for k, v in res.items() if v}


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def visual_grail_match(image_url: str | None) -> float | None:
    """Similarity of a thumbnail to reference grail images. Stays None until reference image embeddings exist.

    Hook: with GR_CLIP=1 a CLIP image backend (e.g. fastembed's Qdrant/clip-ViT-B-32-vision) would be loaded here
    and compared with reference vectors stored per season; not built yet by design.
    """
    if os.environ.get("GR_CLIP") != "1":
        return None
    return None
