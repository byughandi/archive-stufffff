"""Test-ladder helpers: remember (in kv) that a rung was blocked so we do not hammer it every run."""
from __future__ import annotations

from core.db import Database, now

COOLDOWN = 6 * 3600


def _key(source: str, rung: str) -> str:
    return f"rung_blocked:{source}:{rung}"


def on_cooldown(db: Database, source: str, rung: str, at: int | None = None) -> bool:
    v = db.kv_get(_key(source, rung))
    return bool(v) and int(v) > (at if at is not None else now())


def block(db: Database, source: str, rung: str, seconds: int = COOLDOWN, at: int | None = None) -> None:
    db.kv_set(_key(source, rung), str((at if at is not None else now()) + seconds))


def clear(db: Database, source: str, rung: str) -> None:
    db.execute("DELETE FROM kv WHERE k = ?", (_key(source, rung),))


def interval_due(db: Database, key: str, min_seconds: int, at: int | None = None) -> bool:
    """True when `key` has not been marked within `min_seconds` (used to throttle paid fallbacks)."""
    v = db.kv_get(f"last:{key}")
    return not v or (at if at is not None else now()) - int(v) >= min_seconds


def mark(db: Database, key: str, at: int | None = None) -> None:
    db.kv_set(f"last:{key}", str(at if at is not None else now()))
