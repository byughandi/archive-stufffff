# Weekly brain refresh (instructions for the scheduled Claude Code session)

You are running as a weekly scheduled task in the Grail Radar repository. Your job is to keep
the taxonomy current without any API spend. Budget: at most 10 web searches. Produce one pull
request, or nothing if there is nothing worth changing.

## Inputs
1. Run `python -m pipeline.run refresh-report` (needs `TURSO_DATABASE_URL` and
   `TURSO_AUTH_TOKEN` in the environment). It prints JSON with:
   - `trend_scores`: the past week's movers;
   - `unmatched_terms`: frequent words and phrases in listing titles and Instagram captions
     that no taxonomy alias matched;
   - `feedback`: the week's taps, grouped by kind, with the listings marked `wrong_era`,
     `wrong_brand` and `fake`;
   - `rejected_but_liked`: listings the filter rejected that the user marked Yes;
   - `top_unresolved_eras`: brands whose listings most often come out era-unresolved.
   If the database is unreachable, say so in the task result and stop.
2. `data/taxonomy/*.yaml`, `research/SCHEMAS.md` (file formats), `research/SYNTHESIS.md`
   (known gaps).

## What to do
1. A **Sonnet** subagent reads the report and picks the gaps worth closing: a brand, season,
   piece, alias or Japanese spelling that keeps appearing unmatched; an era cue that keeps
   producing `wrong_era`; a junk pattern that keeps getting through; an entry still marked
   `verify: true` that listings now confirm or contradict.
2. It researches only those gaps (≤ 10 searches), then edits `data/taxonomy/*.yaml` and
   `exemplars.yaml`. Every new or changed entity carries a source URL and a confidence. Never
   invent season names, tag codes or handles. Remove `verify: true` only with a source.
3. Run `python -m pytest tests -q` and `python -m pipeline.run eval`. Both must pass. If the
   eval gate fails, fix the taxonomy change or drop it; never edit `data/eval/` to make a
   change pass.
4. An **Opus** subagent reviews the diff for false positives: aliases that are common words,
   aliases that collide with another brand, blocklist phrases that would reject real pieces.
   It can veto individual changes.
5. Open a pull request titled `Brain refresh <YYYY-MM-DD>` with: what changed, why (the
   report rows that motivated it), sources, and the eval numbers before and after. Do not
   merge it. Do not push to `main`.

## Hard limits
- No Depop, no Vinted, in any file.
- No changes outside `data/taxonomy/` and, when a new junk pattern needs a regression case,
  new rows appended to `data/eval/labeled_listings.jsonl`.
- No secrets in the repository. No paid API calls.
