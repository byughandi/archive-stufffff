<script lang="ts">
  import { onMount } from 'svelte';
  import Art from '../../lib/Art.svelte';
  import Bar from '../../lib/Bar.svelte';
  import Sparkline from '../../lib/Sparkline.svelte';
  import { api } from '../../lib/api';
  import { ensureTaxonomy } from '../../lib/data';
  import { archetypeName, brandName, eraWithBrand, seasonName } from '../../lib/names';
  import { ref } from '../../lib/state.svelte';
  import type { Trends, TrendSeries } from '../../lib/types';

  let data = $state<Trends | null>(null);
  let error = $state('');
  let loading = $state(true);

  async function load() {
    loading = true;
    error = '';
    try {
      data = await api<Trends>('/api/trends');
    } catch (e) {
      error = (e as Error).message;
    }
    loading = false;
  }
  onMount(() => {
    ensureTaxonomy();
    load();
  });

  function nameOf(kind: string, id: string): string {
    void ref.taxonomy; // re-run when names arrive
    if (kind === 'brand') return brandName(id);
    if (kind === 'era') return eraWithBrand(id);
    if (kind === 'archetype') return archetypeName(id);
    if (kind === 'season') return seasonName(id);
    return id;
  }
  const seriesMap = $derived(new Map((data?.series ?? []).map((s) => [`${s.kind}:${s.id}`, s] as [string, TrendSeries])));
  const weekly = (kind: string, id: string) => seriesMap.get(`${kind}:${id}`)?.points ?? [];
  const hasIg = $derived((data?.series.length ?? 0) > 0);
  const heat = $derived([...(data?.heat ?? [])].sort((a, b) => b.trend_prior - a.trend_prior));
</script>

<svelte:head><title>Grail Radar: Trends</title></svelte:head>

<main class="page">
  <h1>Trends</h1>
  {#if loading}
    <div class="state" role="status"><Art name="loading-sweep" h="64px" label="Loading" /><p>Loading trends.</p></div>
  {:else if error}
    <div class="state error">
      <p><span class="hatch" aria-hidden="true"></span><span>{error}</span></p>
      <button type="button" class="btn" onclick={load}>Try again</button>
    </div>
  {:else if data}
    {#if !hasIg}
      <p class="lede">
        No Instagram data yet, so there are no weekly scores. This page shows the research priors only: how hot each brand and era looked in the
        sources read so far.
      </p>
    {/if}

    <h2>Rising this week</h2>
    {#if data.rising.length}
      <ol class="rows">
        {#each data.rising as r (r.kind + r.id)}
          {@const pts = weekly(r.kind, r.id)}
          <li>
            <span class="n">{nameOf(r.kind, r.id)}</span>
            <Sparkline values={pts.map((p) => p.score)} label={`Weekly score for ${nameOf(r.kind, r.id)}, last ${pts.length} weeks`} />
            <span class="d tabnum">+{Math.round(r.delta * 100)} {Math.round(r.delta * 100) === 1 ? 'point' : 'points'}</span>
          </li>
        {/each}
      </ol>
    {:else}
      <p class="quiet">{hasIg ? 'Nothing gained score since last week.' : 'Nothing to show until weekly scores exist. It needs two weeks of Instagram data.'}</p>
    {/if}

    <h2>Heat list</h2>
    {#if heat.length}
      <ol class="rows heat">
        {#each heat as h, i (h.kind + h.id + i)}
          {@const pts = weekly(h.kind, h.id)}
          <li>
            <span class="rank tabnum" aria-hidden="true">{i + 1}</span>
            <span class="n">{nameOf(h.kind, h.id)}</span>
            <span class="spark">
              {#if pts.length >= 2}
                <Sparkline values={pts.map((p) => p.score)} label={`Weekly score for ${nameOf(h.kind, h.id)}, last ${pts.length} weeks, now ${Math.round(pts[pts.length - 1].score * 100)}`} />
              {:else}
                <span class="quiet small">No weekly data</span>
              {/if}
            </span>
            <span class="prior"><Bar value={h.trend_prior} label="Research prior" /></span>
          </li>
        {/each}
      </ol>
    {:else}
      <p class="quiet">No research priors are loaded.</p>
    {/if}
  {/if}
</main>

<style>
  .rows {
    max-width: 56rem;
  }
  .rows li {
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: center;
    gap: var(--s-3);
    min-height: var(--tap);
    padding: var(--s-2) 0;
    border-bottom: var(--rule-w) solid var(--rule);
  }
  .rows .n {
    font-weight: 700;
    min-width: 0;
  }
  .d {
    font-size: var(--t-meta);
    color: var(--thread);
    text-align: right;
    min-width: 6rem;
  }
  .rows.heat li {
    grid-template-columns: 1.75rem 1fr 5.5rem;
    grid-template-areas:
      'r n s'
      'r p p';
    row-gap: 0;
  }
  .rank {
    grid-area: r;
    font-stretch: var(--w-condensed);
    font-weight: 800;
    color: var(--thread);
    align-self: start;
    padding-top: 2px;
  }
  .heat .n {
    grid-area: n;
  }
  .spark {
    grid-area: s;
    justify-self: end;
  }
  .prior {
    grid-area: p;
    max-width: 22rem;
  }
  .small {
    font-size: var(--t-small);
  }
  .quiet {
    color: var(--thread);
  }
  @media (min-width: 900px) {
    .rows.heat li {
      grid-template-columns: 2rem 1fr 6rem 16rem;
      grid-template-areas: 'r n s p';
    }
  }
</style>
