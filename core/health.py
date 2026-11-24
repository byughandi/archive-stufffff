"""Per-source health and circuit breaker, stored in the `source_health` table.

Rules
- `allowed()` is False while `breaker_until` lies in the future (status `paused`).
- Three consecutive *blocked* runs (403/429/challenge page) open the breaker for 6 hours.
  After it expires one run is let through (half-open): a success resets everything, another
  block re-opens it immediately because the failure streak is still at its threshold.
- Plain errors (bugs, timeouts, parse failures) are counted in `consecutive_failures` but only
  trip the breaker after `ERROR_THRESHOLD` of them, so one flaky run never silences a source.
- `items_today` / `items_day` / `items_total` count items stored by successful runs.
"""
from __future__ import annotations

import datetime as dt

from .db import Database, now

BLOCK_THRESHOLD = 3
ERROR_THRESHOLD = 6
BREAKER_SECONDS = 6 * 3600


def _day(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def get(db: Database, source: str) -> dict | None:
    return db.one("SELECT * FROM source_health WHERE source = ?", (source,))


def allowed(db: Database, source: str, at: int | None = None) -> bool:
    row = get(db, source)
    if not row or not row.get("breaker_until"):
        return True
    return int(row["breaker_until"]) <= (at if at is not None else now())


def breaker_remaining(db: Database, source: str, at: int | None = None) -> int:
    row = get(db, source)
    t = at if at is not None else now()
    return max(0, int(row["breaker_until"] or 0) - t) if row else 0


def record_ok(db: Database, source: str, items: int, rung: str | None = None, at: int | None = None) -> None:
    """A run finished without being blocked. `items` = rows stored (new listings + comps)."""
    t = at if at is not None else now()
    day = _day(t)
    row = get(db, source)
    status = "ok" if items > 0 else "empty"
    if row is None:
        db.execute(
            "INSERT INTO source_health (source, last_run_at, last_ok_at, last_status, last_error,"
            " consecutive_failures, breaker_until, rung, items_day, items_today, items_total)"
            " VALUES (?,?,?,?,NULL,0,NULL,?,?,?,?)",
            (source, t, t, status, rung, day, items, items),
        )
        return
    today = int(row["items_today"] or 0) + items if row["items_day"] == day else items
    db.execute(
        "UPDATE source_health SET last_run_at=?, last_ok_at=?, last_status=?, last_error=NULL,"
        " consecutive_failures=0, breaker_until=NULL, rung=COALESCE(?, rung), items_day=?, items_today=?,"
        " items_total=items_total+? WHERE source=?",
        (t, t, status, rung, day, today, items, source),
    )


def record_failure(db: Database, source: str, blocked: bool, error: str = "", at: int | None = None) -> bool:
    """Returns True when this failure opened the circuit breaker."""
    t = at if at is not None else now()
    row = get(db, source)
    fails = (int(row["consecutive_failures"] or 0) if row else 0) + 1
    threshold = BLOCK_THRESHOLD if blocked else ERROR_THRESHOLD
    tripped = fails >= threshold
    breaker = t + BREAKER_SECONDS if tripped else (row or {}).get("breaker_until")
    status = "paused" if tripped else ("blocked" if blocked else "error")
    err = (error or "")[:500]
    if row is None:
        db.execute(
            "INSERT INTO source_health (source, last_run_at, last_status, last_error, consecutive_failures,"
            " breaker_until, items_day, items_today, items_total) VALUES (?,?,?,?,?,?,?,0,0)",
            (source, t, status, err, fails, breaker, _day(t)),
        )
    else:
        db.execute(
            "UPDATE source_health SET last_run_at=?, last_status=?, last_error=?, consecutive_failures=?,"
            " breaker_until=? WHERE source=?",
            (t, status, err, fails, breaker, source),
        )
    return tripped
