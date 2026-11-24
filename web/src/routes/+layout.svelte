<script lang="ts">
  import '@fontsource-variable/archivo/standard.css';
  import '../styles/tokens.css';
  import '../styles/base.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import Art from '../lib/Art.svelte';
  import Drawer from '../lib/Drawer.svelte';
  import FilterSheet from '../lib/FilterSheet.svelte';
  import { auth, seed, toast, ui } from '../lib/state.svelte';
  import { ensureTaxonomy, FILTER_KEYS, filtersFrom, loadHealth, type Filters } from '../lib/data';
  import { closeListing, drawerGone, setParams } from '../lib/nav';

  let { children } = $props();

  const NAV = [
    { href: '/', label: 'Feed' },
    { href: '/trends', label: 'Trends' },
    { href: '/comps', label: 'Comps' },
    { href: '/alerts', label: 'Alerts' },
    { href: '/sources', label: 'Sources' }
  ];
  const path = $derived(page.url.pathname.replace(/\/+$/, '') || '/');
  const current = (href: string) => path === href;
  const isFeed = $derived(path === '/');
  const listingId = $derived(page.url.searchParams.get('l'));

  $effect(() => {
    if (!listingId) drawerGone();
  });

  onMount(() => {
    ensureTaxonomy();
    loadHealth();
  });

  // The sheets live out here, beside #app, so they can make everything else inert while open.
  const feedTab = $derived(page.url.searchParams.get('tab') || 'feed');
  const feedFilters = $derived(filtersFrom(page.url.searchParams));
  function applyFilters(f: Filters) {
    const changes: Record<string, string | undefined> = {};
    for (const k of FILTER_KEYS) if (k !== 'q') changes[k] = f[k];
    ui.filterOpen = false;
    setParams(changes);
  }

  const filtersActive = $derived(
    ['brand', 'era', 'archetype', 'size', 'min_price', 'max_price', 'source', 'region', 'min_conf', 'hide_suspicious', 'sort'].filter((k) =>
      page.url.searchParams.get(k)
    ).length
  );
</script>

<svelte:head>
  <title>Grail Radar</title>
</svelte:head>

<div id="app">
  {#if auth.signedOut}
    <main class="signed-out">
      <Art name="empty-quiet" h="120px" decorative />
      <h1>Grail Radar</h1>
      <p>You are signed out. Reload to sign in.</p>
      <button type="button" class="btn solid" onclick={() => location.reload()}>Reload</button>
    </main>
  {:else}
    <header class="top">
      <div class="bar">
        <a href="/" class="mark" aria-label="Grail Radar, feed"><Art name="logo-wordmark" h="26px" decorative /></a>
        <nav class="dnav" aria-label="Sections">
          {#each NAV as n (n.href)}
            <a href={n.href} aria-current={current(n.href) ? 'page' : undefined}>{n.label}</a>
          {/each}
        </nav>
        {#if isFeed}
          <div class="acts">
            <button type="button" aria-expanded={ui.searchOpen} aria-controls="search-form" onclick={() => (ui.searchOpen = !ui.searchOpen)}>Search</button>
            <button type="button" aria-haspopup="dialog" onclick={() => (ui.filterOpen = true)}>
              Filter{#if filtersActive}<sup aria-hidden="true">{filtersActive}</sup><span class="sr-only">, {filtersActive} active</span>{/if}
            </button>
          </div>
        {/if}
      </div>
    </header>

    <div class="content">
      {@render children()}
    </div>

    <nav class="bnav" aria-label="Sections">
      {#each NAV as n (n.href)}
        <a href={n.href} aria-current={current(n.href) ? 'page' : undefined}>{n.label}</a>
      {/each}
    </nav>
  {/if}
</div>

{#if !auth.signedOut}
  <Drawer id={listingId} seed={seed.item} onclose={closeListing} />
  {#if isFeed}
    <FilterSheet open={ui.filterOpen} tab={feedTab} filters={feedFilters} onapply={applyFilters} onclose={() => (ui.filterOpen = false)} />
  {/if}
{/if}

<div class="toast" role="status" aria-live="polite">
  {#if toast.message}<p><span class="hatch" aria-hidden="true"></span>{toast.message}</p>{/if}
</div>

<style>
  :global(:root) {
    --bar-h: 3.25rem;
    --bnav-h: 3.25rem;
  }
  .top {
    position: sticky;
    top: 0;
    z-index: 10;
    background: var(--paper);
    border-bottom: var(--rule-w) solid var(--ink);
    padding-top: env(safe-area-inset-top);
  }
  .bar {
    height: var(--bar-h);
    max-width: var(--page-max);
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-6);
    padding: 0 var(--gutter);
  }
  .mark {
    display: inline-flex;
    align-items: center;
    min-height: var(--tap);
  }
  .acts {
    display: flex;
    gap: var(--s-1);
    font-stretch: var(--w-condensed);
    font-weight: 700;
    font-size: var(--t-lead);
    margin-left: auto;
  }
  .acts button {
    min-height: var(--tap);
    padding: 0 var(--s-2);
  }
  .acts button[aria-expanded='true'] {
    text-decoration: underline;
    text-underline-offset: 6px;
    text-decoration-thickness: 3px;
  }
  .acts sup {
    font-size: var(--t-micro);
    margin-left: 2px;
  }
  .dnav {
    display: none;
  }
  .content {
    padding-bottom: calc(var(--bnav-h) + env(safe-area-inset-bottom));
  }
  .bnav {
    position: fixed;
    z-index: 20;
    left: 0;
    right: 0;
    bottom: 0;
    height: calc(var(--bnav-h) + env(safe-area-inset-bottom));
    padding-bottom: env(safe-area-inset-bottom);
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    background: var(--paper);
    border-top: var(--rule-w) solid var(--ink);
  }
  .bnav a,
  .dnav a {
    display: flex;
    align-items: center;
    justify-content: center;
    text-decoration: none;
    font-stretch: var(--w-condensed);
    font-weight: 700;
    font-size: var(--t-lead);
    color: var(--thread);
  }
  .bnav a[aria-current='page'],
  .dnav a[aria-current='page'] {
    color: var(--ink);
  }
  .bnav a {
    position: relative;
  }
  .bnav a[aria-current='page']::after {
    content: '';
    position: absolute;
    left: 25%;
    right: 25%;
    bottom: 8px;
    height: 3px;
    background: var(--ink);
  }

  @media (min-width: 900px) {
    .bnav {
      display: none;
    }
    .content {
      padding-bottom: 0;
    }
    .dnav {
      display: flex;
      gap: var(--s-6);
      margin-right: auto;
      margin-left: var(--s-2);
    }
    .dnav a {
      min-height: var(--tap);
      border-bottom: 3px solid transparent;
      padding-top: 3px;
    }
    .dnav a[aria-current='page'] {
      border-bottom-color: var(--ink);
    }
  }

  .signed-out {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--s-4);
    text-align: center;
    padding: var(--s-8) var(--gutter);
  }
  .signed-out h1 {
    font-stretch: var(--w-condensed);
    font-weight: 900;
    font-size: var(--t-head);
  }

  .toast {
    position: fixed;
    z-index: 60;
    left: var(--gutter);
    right: var(--gutter);
    bottom: calc(var(--bnav-h) + env(safe-area-inset-bottom) + var(--s-3));
    display: flex;
    justify-content: center;
    pointer-events: none;
  }
  .toast p {
    display: flex;
    gap: var(--s-2);
    align-items: center;
    background: var(--ink);
    color: var(--paper);
    padding: var(--s-3) var(--s-4);
    font-size: var(--t-meta);
    max-width: 28rem;
    border: var(--rule-w) solid var(--paper);
  }
  .toast .hatch {
    border-color: var(--paper);
    background: repeating-linear-gradient(-45deg, var(--paper) 0 2px, var(--ink) 2px 5px);
  }
  @media (min-width: 900px) {
    .toast {
      bottom: var(--s-6);
    }
  }
</style>
