<script lang="ts">
  import { onMount } from 'svelte';
  import Art from '../../lib/Art.svelte';
  import { api } from '../../lib/api';
  import { ago, sourceName, usd, weekdayTime } from '../../lib/format';
  import { clock, ref } from '../../lib/state.svelte';
  import type { Health, SourceHealth } from '../../lib/types';

  let data = $state<Health | null>(null);
  let error = $state('');
  let loading = $state(true);

  async function load() {
    loading = true;
    error = '';
    try {
      data = await api<Health>('/api/health');
      ref.health = data;
    } catch (e) {
      error = (e as Error).message;
    }
    loading = false;
  }
  onMount(load);

  type State = 'ok' | 'quiet' | 'paused' | 'blocked' | 'new';
  function stateOf(s: SourceHealth): State {
    if (s.last_status === 'paused' || (s.breaker_until ?? 0) > clock.now) return 'paused';
    if (s.last_status === 'blocked' || s.last_status === 'error') return 'blocked';
    if (s.last_status === 'empty') return 'quiet';
    if (s.last_status === 'ok') return 'ok';
    return 'new';
  }
  const STATE_WORDS: Record<State, string> = { ok: 'OK', quiet: 'Quiet', paused: 'Paused', blocked: 'Blocked', new: 'Not run yet' };
  const STATE_HELP: Record<State, string> = {
    ok: 'Scanning normally.',
    quiet: 'The last scan worked but found nothing new.',
    paused: 'Switched off for a while after repeated failures.',
    blocked: 'The last scan was refused or failed.',
    new: 'No scan has run for this source.'
  };
  const RUNG: Record<string, string> = { direct: 'Direct requests', library: 'Library', apify: 'Apify actor' };

  const spend = $derived(data?.spend);
  const apifyPct = $derived(spend ? Math.min(1, spend.apify_month_usd / (spend.apify_cap_usd || 5)) : 0);
  const sources = $derived(data?.sources ?? []);
  const when = (t: number | null) => (t ? `${ago(t)} (${weekdayTime(t)})` : 'never');
  const statLabel: Record<string, string> = {
    ms: 'time in ms',
    listings_seen: 'listings seen',
    new: 'new',
    scored: 'scored',
    classified: 'classified',
    sent: 'alerts sent'
  };
  function statsText(s: Record<string, unknown> | null): string {
    if (!s) return 'No details recorded.';
    return Object.entries(s)
      .map(([k, v]) => `${statLabel[k] ?? k.replace(/_/g, ' ')} ${typeof v === 'number' ? v.toLocaleString('en-US') : String(v)}`)
      .join(', ');
  }
  const JOBS: Record<string, string> = { scrape: 'Scrape', score: 'Score', comps: 'Comps', alerts: 'Alerts', trends: 'Trends' };
</script>

<svelte:head><title>Grail Radar: Sources</title></svelte:head>

<main class="page">
  <h1>Sources</h1>
  {#if loading && !data}
    <div class="state" role="status"><Art name="loading-sweep" h="64px" label="Loading" /><p>Loading source status.</p></div>
  {:else if error && !data}
    <div class="state error">
      <p><span class="hatch" aria-hidden="true"></span><span>{error}</span></p>
      <button type="button" class="btn" onclick={load}>Try again</button>
    </div>
  {:else if data}
    <h2>Source health</h2>
    {#if sources.length}
      <ul class="srcs">
        {#each sources as s (s.source)}
          {@const st = stateOf(s)}
          <li>
            <div class="head">
              <h3>{sourceName(s.source)}</h3>
              <p class="state-tag {st}"><span class="dot {st}" aria-hidden="true"></span>{STATE_WORDS[st]}</p>
            </div>
            <p class="help">{STATE_HELP[st]}</p>
            <dl>
              <div><dt>Last successful scan</dt><dd>{when(s.last_ok_at)}</dd></div>
              <div><dt>Listings today</dt><dd class="tabnum">{s.items_today.toLocaleString('en-US')}</dd></div>
              <div><dt>Listings in total</dt><dd class="tabnum">{s.items_total.toLocaleString('en-US')}</dd></div>
              <div><dt>Access path</dt><dd>{s.rung ? (RUNG[s.rung] ?? s.rung) : 'Not set'}</dd></div>
              {#if s.consecutive_failures}<div><dt>Failures in a row</dt><dd class="tabnum">{s.consecutive_failures}</dd></div>{/if}
              {#if s.breaker_until && s.breaker_until > clock.now}<div><dt>Paused until</dt><dd>{weekdayTime(s.breaker_until)}</dd></div>{/if}
            </dl>
            {#if s.last_error && (st === 'blocked' || st === 'paused')}
              <p class="err"><span class="hatch" aria-hidden="true"></span>{s.last_error}</p>
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      <div class="state">
        <Art name="empty-quiet" h="110px" decorative />
        <p>No source has reported yet.</p>
      </div>
    {/if}

    <h2>Spend this month</h2>
    {#if spend}
      <div class="spend">
        <p class="amount"><b class="figure">{usd(spend.apify_month_usd)}</b> <span>of {usd(spend.apify_cap_usd)} Apify cap</span></p>
        <div class="track" role="meter" aria-label="Apify spend against the cap" aria-valuemin="0" aria-valuemax={spend.apify_cap_usd} aria-valuenow={spend.apify_month_usd} aria-valuetext="{usd(spend.apify_month_usd)} of {usd(spend.apify_cap_usd)}">
          <div class="fill" style:width="{apifyPct * 100}%"></div>
        </div>
        <p class="help">
          {apifyPct >= 1 ? 'The cap is reached. Apify jobs stop until next month.' : `${usd(spend.apify_cap_usd - spend.apify_month_usd)} left before Apify jobs stop.`}
        </p>
        <p class="help">Language model fallback: {usd(spend.llm_month_usd)} this month.</p>
      </div>
    {/if}

    <h2>Job run log</h2>
    {#if data.runs.length}
      <ul class="runs">
        {#each [...data.runs].sort((a, b) => b.at - a.at) as r (r.job)}
          <li>
            <h3>{JOBS[r.job] ?? r.job}</h3>
            <p class="when">{ago(r.at)}</p>
            <p class="stats">{statsText(r.stats)}</p>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="quiet">No job has recorded a run yet.</p>
    {/if}
  {/if}
</main>

<style>
  .srcs {
    display: grid;
    gap: 0;
    grid-template-columns: minmax(0, 1fr);
  }
  .srcs li {
    padding: var(--s-4) 0;
    border-bottom: var(--rule-w) solid var(--rule);
  }
  @media (min-width: 900px) {
    .srcs {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      column-gap: var(--s-8);
    }
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--s-3);
  }
  h3 {
    font-stretch: var(--w-condensed);
    font-weight: 800;
    font-size: var(--t-lead);
  }
  .state-tag {
    display: flex;
    align-items: center;
    gap: var(--s-2);
    font-stretch: var(--w-condensed);
    font-weight: 800;
    font-size: var(--t-lead);
  }
  .dot {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid var(--ink);
  }
  .dot.ok {
    background: var(--ink);
  }
  .dot.quiet,
  .dot.new {
    background: var(--paper);
  }
  .dot.paused {
    background: linear-gradient(90deg, var(--ink) 50%, var(--paper) 50%);
  }
  .dot.blocked {
    background: repeating-linear-gradient(-45deg, var(--ink) 0 2px, var(--paper) 2px 5px);
  }
  .help,
  .when {
    font-size: var(--t-small);
    color: var(--thread);
  }
  dl {
    margin-top: var(--s-2);
  }
  dl div {
    display: flex;
    justify-content: space-between;
    gap: var(--s-4);
    padding: var(--s-1) 0;
    font-size: var(--t-meta);
  }
  dt {
    color: var(--thread);
  }
  dd {
    text-align: right;
  }
  .err {
    display: flex;
    gap: var(--s-2);
    align-items: flex-start;
    font-size: var(--t-small);
    margin-top: var(--s-2);
  }
  .spend {
    max-width: 30rem;
  }
  .amount {
    display: flex;
    align-items: baseline;
    gap: var(--s-2);
    flex-wrap: wrap;
  }
  .amount b {
    font-size: 2.5rem;
  }
  .track {
    height: 14px;
    margin: var(--s-2) 0;
    border: var(--rule-w) solid var(--ink);
    background: var(--paper);
  }
  .fill {
    height: 100%;
    background: var(--ink);
  }
  .runs li {
    display: grid;
    grid-template-columns: 6rem 1fr;
    gap: 0 var(--s-3);
    padding: var(--s-3) 0;
    border-bottom: var(--rule-w) solid var(--rule);
  }
  .runs h3 {
    grid-row: span 2;
  }
  .runs .stats {
    font-size: var(--t-meta);
  }
  .quiet {
    color: var(--thread);
  }
</style>
