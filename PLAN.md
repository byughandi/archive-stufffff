# Grail Radar — build plan

Source of truth: `GRAIL_RADAR_PROMPT.md` (the master prompt). Part 1 is mirrored in
`research/TASTE_PROFILE.md` so research agents have it on disk.

## Phases

| # | Phase | Owner (model) | Output | Done when |
|---|---|---|---|---|
| 1 | Plan | Orchestrator | `PLAN.md`, `research/INDEX.md`, `.claude/agents/*.md` | files exist |
| 2 | Research | R1–R4 (sonnet), in parallel, once | `research/R*.md`, `data/taxonomy/*.yaml`, `config/*.yaml` | every template field filled or `UNKNOWN` |
| 2b | Synthesis | Orchestrator | `research/SYNTHESIS.md`, reviewed YAML | conflicts resolved, low-confidence noise pruned |
| 3 | Architecture | Architect (opus) | `docs/ARCHITECTURE.md`, schema, layout | limits checked against current docs |
| 4 | Scrapers + storage | Scraper engineer (sonnet) | `scrapers/*`, workflows | each source ingests real rows, second run inserts ~0 |
| 5 | Scoring | Scoring engineer (opus) | `pipeline/*`, eval set | Part 8 eval targets pass |
| 6 | Design + site | Illustrator (fable) → Frontend (sonnet) | `design/DIRECTION.md`, `web/*`, `worker/*` | site runs against real scored rows |
| 7 | Alerts + scheduling | Scraper engineer / Orchestrator | crons, keepalive, retrain, comps, trends, brain refresh | workflows valid, alert delivered |
| 8 | Verify | Verifier (sonnet, fresh context) | `docs/VERIFICATION.md` | all checks pass or are honestly marked blocked |

Order inside phase 4: Grailed → Mercari US (test ladder) → Mercari JP → Yahoo! Auctions JP →
independent Shopify webshops → weekly IG trends job.

## Assumptions (defaults picked without asking)

1. **Build environment is a cloud container, not the user's PC.** Outbound network is limited
   to package registries and GitHub's API. Every marketplace host is refused by the network
   policy until the user approves an allowlist. Live scraper tests depend on that approval.
2. **No account credentials exist in this session** (GitHub token invalid; no Cloudflare,
   Turso or Apify login). Everything up to deploy is built and verified locally against a
   local libSQL/SQLite file, which is the same engine Turso runs. Deploy needs the user.
3. **Orchestrator model** is whatever the session runs; subagents use the models in Part 3.
4. **Language split:** Python 3.12 for scrapers + pipeline (runs on Actions runners),
   TypeScript for the Worker, a static SvelteKit app for the site.
5. **Database:** Turso (libSQL). Local dev and tests use a SQLite file with the same schema.
6. **Embeddings:** small ONNX sentence model on CPU; CLIP image embeddings are optional per
   run and skipped when the run would exceed the ~5 minute budget.
7. **LLM fallback off** (`MAX_LLM_ITEMS_PER_DAY=0`). Apify spend tracked in `spend_ledger`,
   hard stop at 90% of $5.
8. **Alerts:** ntfy.sh topic (random, unguessable name stored as a secret).
9. **R3 writes `trend_priors.yaml`** rather than editing R2's files; merged at synthesis.
10. **No Depop, no Vinted**, ever.

## Open questions for the user (kept to the minimum)

1. Public vs. private GitHub repo (public = unlimited free Actions minutes, code and scraped
   data visible; private = slower schedule or a VM).
2. Account connections for deploy: GitHub, Cloudflare, Turso, Apify.

## Status log

- Plan: done.
- Research R1–R4 + synthesis: done. Page fetching was blocked for every research agent, so
  findings rest on search snippets and background knowledge and are flagged accordingly.
- Architecture: done by the Orchestrator directly (same judgment tier as the Architect role).
  One deviation: a single Cloudflare Worker with static assets instead of Pages + Worker.
- Scrapers: Mercari JP, Yahoo! Auctions JP and Shopify webshops verified live. Grailed,
  Mercari US, Apify and the Instagram job are mock-tested only (unreachable from the build
  machine). Rakuma, 2nd Street, RagTag, Kindal, Treasure Factory, eBay and the optional
  sources are not built.
- Scoring: cascade, comps engine, eval gate (287 labelled rows) done; calibrated against
  ~3,650 real listings by the Orchestrator.
- Design + site: Direction A "Selvedge"; site and Worker API built and run locally on real
  pipeline output.
- Workflows: written, never executed (no repository).
- Verification: fresh-context verifier, see `docs/VERIFICATION.md`.
- Deploy: blocked on the user's GitHub, Turso, Cloudflare, Apify and ntfy accounts
  (`docs/SETUP.md`). The weekly brain-refresh scheduled task cannot be created until the
  repository exists.
