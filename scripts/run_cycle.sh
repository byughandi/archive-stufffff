#!/usr/bin/env bash
# One scheduled cycle of Grail Radar: scrape, score, alert. Meant to be run every few hours by any
# scheduler that can run a shell command (a Claude Code scheduled task, cron on a VM, a CI job).
#
# Needs: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN (database), optionally APIFY_TOKEN (Grailed fallback and
# weekly Instagram trends). The ntfy topic is read from the database (kv `ntfy_topic`) when NTFY_TOPIC is unset.
#
# Every step is allowed to fail on its own: a blocked source or a hiccup never stops scoring and alerts.
# Once a day it also pulls sold prices, rebuilds fair values, rescores everything and prunes; once a week
# it pulls Instagram trends. The last line printed is a one-line JSON summary.
set -u
cd "$(dirname "$0")/.."

if [ -z "${TURSO_DATABASE_URL:-}" ]; then
  echo '{"cycle": "refused", "reason": "TURSO_DATABASE_URL is not set"}'
  exit 2
fi
if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv -q .venv && uv pip install -q --python .venv/bin/python -e . pillow imagehash
  else
    python3 -m venv .venv && .venv/bin/pip install -q -e . pillow imagehash
  fi
fi
. .venv/bin/activate
export GR_RAW=0 PYTHONUNBUFFERED=1
unset GR_DB_PATH

FAILED=""
step() {
  echo "== $*"
  timeout 900 "$@" 2>&1 | tail -n 6
  [ "${PIPESTATUS[0]}" -eq 0 ] || FAILED="$FAILED [$*]"
}
due() {   # due <name> <hours>: exit 0 when the named extra has not run for that long
  python - "$1" "$2" <<'PY'
import sys
from core.db import connect, now
last = connect().kv_get(f"last:cycle_{sys.argv[1]}")
sys.exit(0 if not last or now() - int(last) >= float(sys.argv[2]) * 3600 else 1)
PY
}
mark() { python -c "import sys; from core.db import connect, now; connect().kv_set('last:cycle_' + sys.argv[1], str(now()))" "$1"; }

step python -m scrapers.run slow
step python -m scrapers.run fast
step python -m scrapers.run recheck --max-queries "${GR_RECHECK:-15}"   # 15 tracked listings per source per cycle

if due daily 20; then
  step python -m scrapers.run comps
  step python -m pipeline.run comps
  step python -m pipeline.run rescore
  step python -m pipeline.run prune
  mark daily
else
  step python -m pipeline.run score
fi

if [ -n "${APIFY_TOKEN:-}" ] && due trends 160; then
  step python -m scrapers.run trends
  step python -m pipeline.run trends
  mark trends
fi

step python -m pipeline.run alerts

python - "$FAILED" <<'PY'
import json, sys
from core.db import connect, now
db = connect()
out = {
    "cycle": "done", "at": now(), "failed_steps": sys.argv[1].strip(),
    "listings_active": db.scalar("SELECT COUNT(*) FROM feed WHERE status = 'active' AND tier_rank < 9"),
    "new_last_3h": db.scalar("SELECT COUNT(*) FROM listings WHERE first_seen_at >= ?", (now() - 3 * 3600,)),
    "comps": db.scalar("SELECT COUNT(*) FROM comps_sold"),
    "steals": db.scalar("SELECT COUNT(*) FROM feed WHERE status = 'active' AND deal_label = 'steal'"),
    "apify_month_usd": round(float(db.scalar("SELECT COALESCE(SUM(usd), 0) FROM spend_ledger WHERE vendor = 'apify'"
                                             " AND at >= strftime('%s', 'now', 'start of month')") or 0), 3),
    "sources": {r["source"]: r["last_status"] for r in db.query("SELECT source, last_status FROM source_health")},
}
db.kv_set("run_stats:cycle", json.dumps(out))
print(json.dumps(out))
PY
