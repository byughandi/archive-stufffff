# Grail Radar

A private, always-on deal finder for archive designer fashion. It scans Grailed, Mercari
(US and Japan), Yahoo! Auctions Japan and independent archive webshops, throws out the junk,
works out which designer era each piece belongs to, estimates fair value from sold listings,
and ranks what is left by how desirable it is and how far under fair value it is priced.

Read-only. It never buys, bids, offers or messages.

- **Where it runs:** GitHub Actions (scheduled jobs), Turso (database), one Cloudflare Worker
  (site + API) behind Cloudflare Access. Nothing runs on your own computer.
- **What it costs:** $0 for hosting, scraping and scoring. No paid AI calls at runtime.

| Read | For |
|---|---|
| `docs/SETUP.md` | Going live: accounts, secrets, first runs |
| `docs/RUNBOOK.md` | When a source goes quiet; running things by hand |
| `docs/ARCHITECTURE.md` | How the pieces fit, schedules, budgets |
| `docs/CONTRACTS.md` | Data shapes between scrapers, scoring and the site |
| `docs/VERIFICATION.md` | What was tested, how, and what could not be |
| `design/DIRECTION.md` | Visual direction and component spec |
| `research/SYNTHESIS.md` | What the taxonomy knows and where it is thin |

## Changing your taste
Edit the YAML in `data/taxonomy/` (or ask Claude Code to "add <brand/era/piece> to Grail
Radar" or "stop showing me <thing>"), run `python -m pytest tests -q`, push. No rebuild.

## Running locally
```bash
uv venv .venv --python 3.12 && . .venv/bin/activate && uv pip install -e ".[embed,dev]"
GR_DB_PATH=local.db python -m scrapers.run slow --max-queries 6
GR_DB_PATH=local.db python -m pipeline.run all
python scripts/dev_turso.py local.db 8080 &          # local stand-in for the database
(cd web && npm ci && npm run build) && (cd worker && npm ci && npx wrangler dev)
```
