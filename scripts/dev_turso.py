"""Dev-only stand-in for a Turso database: serves the libSQL "Hrana over HTTP" pipeline API
(/v2/pipeline and /v3/pipeline, JSON) on top of a local SQLite file.

Why it exists: the Worker (official @libsql/client) and the Python jobs (core/db.py) can both be
run end to end on a laptop or in CI without a Turso account.

Usage: python scripts/dev_turso.py data/dev/dev.db [port]
Then:  TURSO_DATABASE_URL=http://127.0.0.1:8080  (no auth token)
"""
import base64, json, sqlite3, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
CONN: sqlite3.Connection
SQL_STORE: dict = {}


def dec(a):
    t = a.get("type")
    if t == "null": return None
    if t == "integer": return int(a["value"])
    if t == "float": return float(a["value"])
    if t == "blob":
        b = a.get("base64", ""); return base64.b64decode(b + "=" * (-len(b) % 4))
    return a.get("value")


def enc(v):
    if v is None: return {"type": "null"}
    if isinstance(v, bool): return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int): return {"type": "integer", "value": str(v)}
    if isinstance(v, float): return {"type": "float", "value": v}
    if isinstance(v, (bytes, memoryview)): return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode().rstrip("=")}
    return {"type": "text", "value": str(v)}


def run_stmt(stmt):
    sql = stmt.get("sql") or SQL_STORE.get(stmt.get("sql_id")) or ""
    named = {a["name"].lstrip(":@$"): dec(a["value"]) for a in stmt.get("named_args") or []}
    args = named if named else [dec(a) for a in stmt.get("args") or []]
    cur = CONN.execute(sql, args)
    cols = [{"name": d[0], "decltype": None} for d in (cur.description or [])]
    rows = [[enc(v) for v in r] for r in cur.fetchall()] if cur.description else []
    return {"cols": cols, "rows": rows, "affected_row_count": max(cur.rowcount, 0),
            "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid is not None else None,
            "replication_index": None, "rows_read": len(rows), "rows_written": max(cur.rowcount, 0), "query_duration_ms": 0.0}


def cond_ok(c, results, errors):
    if c is None: return True
    t = c.get("type")
    if t == "ok": return results[c["step"]] is not None
    if t == "error": return errors[c["step"]] is not None
    if t == "not": return not cond_ok(c["cond"], results, errors)
    if t == "and": return all(cond_ok(x, results, errors) for x in c["conds"])
    if t == "or": return any(cond_ok(x, results, errors) for x in c["conds"])
    if t == "is_autocommit": return not CONN.in_transaction
    return False


def handle(req):
    t = req.get("type")
    if t == "execute":
        return {"type": "execute", "result": run_stmt(req["stmt"])}
    if t == "batch":
        results, errors = [], []
        for step in req["batch"]["steps"]:
            if not cond_ok(step.get("condition"), results, errors):
                results.append(None); errors.append(None); continue
            try:
                results.append(run_stmt(step["stmt"])); errors.append(None)
            except sqlite3.Error as e:
                results.append(None); errors.append({"message": str(e), "code": "SQLITE_ERROR"})
        return {"type": "batch", "result": {"step_results": results, "step_errors": errors}}
    if t == "sequence":
        CONN.executescript(req.get("sql") or ""); return {"type": "sequence"}
    if t == "get_autocommit":
        return {"type": "get_autocommit", "is_autocommit": not CONN.in_transaction}
    if t == "store_sql":
        SQL_STORE[req["sql_id"]] = req["sql"]; return {"type": t}
    if t == "close_sql":
        SQL_STORE.pop(req.get("sql_id"), None); return {"type": t}
    if t == "close":
        return {"type": t}
    raise ValueError(f"unsupported request type {t}")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        self._send(200 if self.path.rstrip("/") in ("/v2", "/v3", "/health", "") else 404, {})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        if self.path.rstrip("/") not in ("/v2/pipeline", "/v3/pipeline"):
            self.rfile.read(n); return self._send(404, {"error": "not found"})
        body = json.loads(self.rfile.read(n) or b"{}")
        out = []
        with LOCK:
            for r in body.get("requests", []):
                try:
                    out.append({"type": "ok", "response": handle(r)})
                except Exception as e:  # report per-request, like the real server
                    out.append({"type": "error", "error": {"message": str(e), "code": "SQLITE_ERROR"}})
            if CONN.in_transaction:  # a pipeline is one stream here: never leave a transaction open
                CONN.rollback()
        self._send(200, {"baton": None, "base_url": None, "results": out})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "local.db"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    CONN = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    CONN.execute("PRAGMA journal_mode=WAL")
    print(f"dev libSQL server on http://127.0.0.1:{port} -> {path}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
