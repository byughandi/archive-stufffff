<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import Art from '../../lib/Art.svelte';
  import RangeBar from '../../lib/RangeBar.svelte';
  import Thumb from '../../lib/Thumb.svelte';
  import { api, qs } from '../../lib/api';
  import { ensureTaxonomy } from '../../lib/data';
  import { dateShort, sourceName, usd } from '../../lib/format';
  import { brandName } from '../../lib/names';
  import { setParams } from '../../lib/nav';
  import { ref } from '../../lib/state.svelte';
  import type { CompsResponse } from '../../lib/types';

  const brand = $derived(page.url.searchParams.get('brand') ?? '');
  const era = $derived(page.url.searchParams.get('era') ?? '');
  const archetype = $derived(page.url.searchParams.get('archetype') ?? '');

  onMount(ensureTaxonomy);
  const brands = $derived([...(ref.taxonomy?.brands ?? [])].sort((a, b) => a.name.localeCompare(b.name)));
  const eras = $derived((ref.taxonomy?.eras ?? []).filter((e) => !brand || e.parent === brand));
  const pieces = $derived([...(ref.taxonomy?.archetypes ?? [])].sort((a, b) => a.name.localeCompare(b.name)));

  let data = $state<CompsResponse | null>(null);
  let loading = $state(false);
  let error = $state('');
  let retry = $state(0);

  $effect(() => {
    retry;
    if (!brand && !era && !archetype) {
      data = null;
      error = '';
      return;
    }
    const ctl = new AbortController();
    loading = true;
    error = '';
    api<CompsResponse>(`/api/comps${qs({ brand, era, archetype })}`, { signal: ctl.signal })
      .then((r) => {
        data = r;
        loading = false;
      })
      .catch((e: Error) => {
        if (e.name === 'AbortError') return;
        error = e.message;
        loading = false;
      });
    return () => ctl.abort();
  });

  function pickBrand(v: string) {
    const eraBrand = ref.taxonomy?.eras.find((e) => e.id === era)?.parent;
    setParams({ brand: v || undefined, era: v && eraBrand && eraBrand !== v ? undefined : era || undefined }, { replace: true });
  }

  const stats = $derived(data?.stats);
  const months = $derived(data?.by_month ?? []);

  // Month-by-month median chart, hand-built.
  const CH = { w: 640, h: 190, l: 8, r: 8, t: 22, b: 36 };
  const maxMedian = $derived(Math.max(1, ...months.map((m) => m.median ?? 0)));
  const bw = $derived(months.length ? (CH.w - CH.l - CH.r) / months.length : 0);
  function monthLabel(m: string, i: number) {
    const d = new Date(`${m}-01T00:00:00Z`);
    const mon = d.toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' });
    return i === 0 || m.endsWith('-01') ? `${mon} ${String(d.getUTCFullYear()).slice(2)}` : mon;
  }
  const chartLabel = $derived(
    months.length ? `Median sold price by month, ${months.length} months, from ${usd(months[0].median)} in ${monthLabel(months[0].month, 0)} to ${usd(months[months.length - 1].median)} in ${monthLabel(months[months.length - 1].month, 1)}.` : ''
  );
  const subject = $derived([brand ? brandName(brand) : '', era ? ref.taxonomy?.eras.find((e) => e.id === era)?.name : '', archetype ? ref.taxonomy?.archetypes.find((a) => a.id === archetype)?.name : ''].filter(Boolean).join(', '));
</script>

<svelte:head><title>Grail Radar: Comps</title></svelte:head>

<main class="page">
  <h1>Comps</h1>
  <p class="lede">What similar pieces actually sold for. Pick a brand, then narrow by era and piece type.</p>

  <div class="pickers">
    <div class="field">
      <label for="c-brand">Brand</label>
      <select id="c-brand" value={brand} onchange={(e) => pickBrand(e.currentTarget.value)}>
        <option value="">Pick a brand</option>
        {#each brands as b (b.id)}<option value={b.id}>{b.name}</option>{/each}
      </select>
    </div>
    <div class="field">
      <label for="c-era">Era</label>
      <select id="c-era" value={era} onchange={(e) => setParams({ era: e.currentTarget.value || undefined }, { replace: true })}>
        <option value="">{brand ? `Any ${brandName(brand)} era` : 'Any era'}</option>
        {#each eras as e (e.id)}<option value={e.id}>{brand ? (e.label ?? e.name) : `${brandName(e.parent)}, ${e.label ?? e.name}`}</option>{/each}
      </select>
    </div>
    <div class="field">
      <label for="c-piece">Piece type</label>
      <select id="c-piece" value={archetype} onchange={(e) => setParams({ archetype: e.currentTarget.value || undefined }, { replace: true })}>
        <option value="">Any piece</option>
        {#each pieces as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
      </select>
    </div>
  </div>

  {#if !brand && !era && !archetype}
    <div class="state">
      <Art name="empty-rack" h="110px" decorative />
      <p>Pick a brand to see what it sold for.</p>
    </div>
  {:else if error}
    <div class="state error">
      <p><span class="hatch" aria-hidden="true"></span><span>{error}</span></p>
      <button type="button" class="btn" onclick={() => (retry += 1)}>Try again</button>
    </div>
  {:else if loading && !data}
    <div class="state" role="status"><Art name="loading-sweep" h="64px" label="Loading" /><p>Loading sold comps.</p></div>
  {:else if data && stats}
    {#if stats.count === 0}
      <div class="state">
        <Art name="empty-quiet" h="110px" decorative />
        <p>No sold comps for {subject || 'this selection'} in the last 18 months. Try a wider selection.</p>
      </div>
    {:else}
      <section aria-label="Summary for {subject}" class="summary" aria-busy={loading}>
        <dl class="stats">
          <div><dt>Sold comps</dt><dd class="figure">{stats.count}</dd></div>
          <div><dt>Median</dt><dd class="figure">{usd(stats.median)}</dd></div>
          <div><dt>Middle half</dt><dd class="figure">{usd(stats.p25)} to {usd(stats.p75)}</dd></div>
        </dl>
        {#if stats.p25 !== null && stats.p75 !== null && stats.median !== null}
          <div class="rb"><RangeBar p25={stats.p25} p75={stats.p75} median={stats.median} /></div>
        {/if}
      </section>

      <h2>Median by month</h2>
      {#if months.length}
        <svg viewBox="0 0 {CH.w} {CH.h}" class="chart" role="img" aria-label={chartLabel}>
          <line x1={CH.l} x2={CH.w - CH.r} y1={CH.h - CH.b} y2={CH.h - CH.b} stroke="var(--ink)" stroke-width="1" />
          {#each months as m, i (m.month)}
            {@const h = ((m.median ?? 0) / maxMedian) * (CH.h - CH.t - CH.b)}
            {@const x = CH.l + i * bw}
            <rect x={x + bw * 0.14} y={CH.h - CH.b - h} width={bw * 0.72} height={Math.max(1, h)} fill="var(--ink)" />
            {#if bw > 34}
              <text x={x + bw / 2} y={CH.h - CH.b - h - 5} text-anchor="middle" class="v">{usd(m.median)}</text>
            {/if}
            <text x={x + bw / 2} y={CH.h - CH.b + 14} text-anchor="middle" class="m">{monthLabel(m.month, i)}</text>
            <text x={x + bw / 2} y={CH.h - CH.b + 27} text-anchor="middle" class="c">{m.count} sold</text>
          {/each}
        </svg>
      {/if}

      <h2>Sold listings</h2>
      <p class="inline-note">{data.comps.length < stats.count ? `The ${data.comps.length} most recent of ${stats.count}.` : `All ${stats.count}.`} Newest first.</p>
      <ul class="sold">
        {#each data.comps as c (c.id)}
          <li>
            <div class="ph"><Thumb src={c.image_url} /></div>
            <div class="t">
              {#if c.url}
                <a href={c.url} target="_blank" rel="noopener noreferrer">{c.title}<span class="sr-only"> (opens in a new tab)</span></a>
              {:else}{c.title}{/if}
              <p class="meta">{sourceName(c.source)}, sold {dateShort(c.sold_at)}.{c.size_norm ? ` Size ${c.size_norm}.` : ''}</p>
            </div>
            <b class="p tabnum">{usd(c.sold_price_usd)}</b>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</main>

<style>
  .pickers {
    display: grid;
    gap: var(--s-3);
    grid-template-columns: 1fr;
    margin-bottom: var(--s-4);
  }
  @media (min-width: 700px) {
    .pickers {
      grid-template-columns: repeat(3, 1fr);
      max-width: 52rem;
    }
  }
  .stats {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s-3);
    margin-bottom: var(--s-3);
  }
  .stats div:last-child {
    grid-column: 1 / -1;
  }
  .stats dt {
    font-size: var(--t-small);
    color: var(--thread);
  }
  .stats dd {
    font-size: 2.25rem;
  }
  @media (min-width: 700px) {
    .stats {
      grid-template-columns: auto auto 1fr;
      gap: var(--s-8);
    }
    .stats div:last-child {
      grid-column: auto;
    }
  }
  .rb {
    max-width: 28rem;
  }
  .chart {
    width: 100%;
    max-width: 44rem;
    height: auto;
    font-family: var(--font);
  }
  .chart .v {
    font-size: 11px;
    font-weight: 700;
    fill: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .chart .m {
    font-size: 11px;
    fill: var(--ink);
  }
  .chart .c {
    font-size: 10px;
    fill: var(--thread);
  }
  .sold li {
    display: grid;
    grid-template-columns: 4rem 1fr auto;
    gap: var(--s-3);
    align-items: start;
    padding: var(--s-3) 0;
    border-bottom: var(--rule-w) solid var(--rule);
  }
  .sold .ph {
    width: 4rem;
  }
  .sold .t {
    font-size: var(--t-meta);
    min-width: 0;
  }
  .sold .t a {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .meta {
    font-size: var(--t-small);
    color: var(--thread);
    margin-top: 2px;
  }
  .p {
    font-size: var(--t-lead);
    font-variant-numeric: tabular-nums;
  }
  @media (min-width: 900px) {
    .sold {
      columns: 2;
      column-gap: var(--s-8);
    }
    .sold li {
      break-inside: avoid;
    }
  }
</style>
