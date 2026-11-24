"""One small database interface with two backends.

- Local file (tests, dev):   GR_DB_PATH=./local.db            -> stdlib sqlite3
- Turso (production, CI):    TURSO_DATABASE_URL + TURSO_AUTH_TOKEN -> libSQL "Hrana over HTTP"

The remote backend batches many statements into one HTTP round trip (`/v2/pipeline`), which is
what a cron job needs: a scrape run writes a few hundred rows in two or three requests.
"""
from __future__ import annotations

import base64
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
Stmt = tuple[str, Sequence[Any]]
# (table, column, declaration) for columns added to db/schema.sql after the first release.
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("feed", "base_key", "REAL NOT NULL DEFAULT 0"),
]


def now() -> int:
    return int(time.time())


def split_sql(script: str) -> list[str]:
    """Split a schema script into statements (no triggers/BEGIN..END blocks are used)."""
    lines = [ln.split("--", 1)[0] for ln in script.splitlines()]  # schema never has "--" inside a string
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


class Database:
    """Common interface. Rows come back as plain dicts."""

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        raise NotImplementedError

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run one statement, return affected row count."""
        raise NotImplementedError

    def batch(self, stmts: Iterable[Stmt]) -> int:
        """Run many statements atomically. Returns total affected rows."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    # ---- shared helpers -------------------------------------------------
    def one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def migrate(self) -> None:
        """Create anything missing. `CREATE ... IF NOT EXISTS` never alters an existing table, so columns
        added after a database was first created are listed in ADDED_COLUMNS and added here."""
        self.batch((s, ()) for s in split_sql(SCHEMA_PATH.read_text()))
        for table, column, decl in ADDED_COLUMNS:
            have = {r["name"] for r in self.query(f"PRAGMA table_info({table})")}
            if column not in have:
                self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        v = self.scalar("SELECT v FROM kv WHERE k = ?", (key,))
        return default if v is None else v

    def kv_set(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO kv (k, v, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at",
            (key, value, now()),
        )


class SqliteDatabase(Database):
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=OFF")

    def query(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cur.rowcount

    def batch(self, stmts):
        total = 0
        try:
            for sql, params in stmts:
                total += max(self.conn.execute(sql, tuple(params)).rowcount, 0)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return total

    def close(self):
        self.conn.close()


class DatabaseError(RuntimeError):
    pass


def _encode(v: Any) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode().rstrip("=")}
    return {"type": "text", "value": str(v)}


def _decode(cell: dict) -> Any:
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        b = cell.get("base64", "")
        return base64.b64decode(b + "=" * (-len(b) % 4))
    return cell.get("value")


class TursoDatabase(Database):
    """libSQL remote protocol (Hrana v2 over HTTP, JSON)."""

    CHUNK = 150  # statements per HTTP request

    def __init__(self, url: str, token: str | None, timeout: float = 30.0):
        url = url.strip().rstrip("/")
        for scheme in ("libsql://", "wss://"):
            if url.startswith(scheme):
                url = "https://" + url[len(scheme):]
        if url.startswith("ws://"):
            url = "http://" + url[len("ws://"):]
        self.url = url + "/v2/pipeline"
        headers = {"content-type": "application/json"}
        # Forgive the usual paste slips in a secret: surrounding spaces, quotes, a "Bearer " prefix, a trailing dot.
        token = (token or "").strip().strip("\"'").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        token = token.rstrip(".")
        self.token_shape = f"length {len(token)}, {token.count('.') + 1 if token else 0} parts, starts with eyJ: {token.startswith('eyJ')}"
        if token:
            headers["authorization"] = f"Bearer {token}"
        self.http = httpx.Client(headers=headers, timeout=timeout)

    def _post(self, reqs: list[dict]) -> list[dict]:
        last: Exception | None = None
        for attempt in range(4):
            try:
                resp = self.http.post(self.url, json={"requests": reqs})
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise DatabaseError(f"turso http {resp.status_code}: {resp.text[:200]}")
                break
            except (httpx.TransportError, DatabaseError) as e:  # retry transient failures
                last = e
                time.sleep(1.5 * (attempt + 1))
        else:
            raise DatabaseError(f"turso unreachable: {last}")
        if resp.status_code >= 400:
            hint = f" (token as received: {self.token_shape}; a valid one has 3 parts and starts with eyJ)" if resp.status_code in (400, 401) else ""
            raise DatabaseError(f"turso http {resp.status_code}: {resp.text[:300]}{hint}")
        results = resp.json().get("results", [])
        for r in results:
            if r.get("type") == "error":
                raise DatabaseError(r.get("error", {}).get("message", "unknown database error"))
        return results

    @staticmethod
    def _stmt(sql: str, params: Sequence[Any]) -> dict:
        return {"sql": sql, "args": [_encode(p) for p in params]}

    def _pipeline(self, stmts: list[Stmt], transactional: bool) -> list[dict]:
        if not transactional:
            reqs = [{"type": "execute", "stmt": self._stmt(sql, params)} for sql, params in stmts]
            results = self._post(reqs + [{"type": "close"}])
            return [r.get("response", {}).get("result", {}) for r in results[:-1]]

        # Atomic batch: each step runs only if the previous one succeeded; COMMIT only if every
        # statement did; ROLLBACK otherwise. (A plain pipeline keeps executing after an error,
        # so BEGIN/.../COMMIT as separate requests would commit a half-applied batch.)
        steps: list[dict] = [{"stmt": {"sql": "BEGIN"}}]
        for i, (sql, params) in enumerate(stmts):
            steps.append({"condition": {"type": "ok", "step": i}, "stmt": self._stmt(sql, params)})
        commit = len(steps)
        steps.append({"condition": {"type": "ok", "step": commit - 1}, "stmt": {"sql": "COMMIT"}})
        steps.append({"condition": {"type": "not", "cond": {"type": "ok", "step": commit}}, "stmt": {"sql": "ROLLBACK"}})
        results = self._post([{"type": "batch", "batch": {"steps": steps}}, {"type": "close"}])
        res = results[0].get("response", {}).get("result", {})
        for err in res.get("step_errors", [])[:commit + 1]:
            if err:
                raise DatabaseError(err.get("message", "unknown database error"))
        step_results = res.get("step_results", [])
        if len(step_results) <= commit or step_results[commit] is None:
            raise DatabaseError("batch did not commit")
        return [r or {} for r in step_results[1:commit]]

    def query(self, sql, params=()):
        res = self._pipeline([(sql, params)], transactional=False)[0]
        cols = [c.get("name") for c in res.get("cols", [])]
        return [dict(zip(cols, (_decode(c) for c in row))) for row in res.get("rows", [])]

    def execute(self, sql, params=()):
        res = self._pipeline([(sql, params)], transactional=False)[0]
        return int(res.get("affected_row_count", 0))

    def batch(self, stmts):
        stmts = list(stmts)
        total = 0
        for i in range(0, len(stmts), self.CHUNK):
            for res in self._pipeline(stmts[i:i + self.CHUNK], transactional=True):
                total += int(res.get("affected_row_count", 0))
        return total

    def close(self):
        self.http.close()


def connect() -> Database:
    url = os.environ.get("TURSO_DATABASE_URL")
    if url:
        return TursoDatabase(url, os.environ.get("TURSO_AUTH_TOKEN"))
    return SqliteDatabase(os.environ.get("GR_DB_PATH", "local.db"))
