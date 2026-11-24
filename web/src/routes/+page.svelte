<script lang="ts">
  import { page } from '$app/state';
  import { onMount, untrack } from 'svelte';
  import Art from '../lib/Art.svelte';
  import Card from '../lib/Card.svelte';
  import { api, qs } from '../lib/api';
  import { FILTER_KEYS, filtersFrom, loadHealth } from '../lib/data';
  import { ago, sourceName, weekdayTime } from '../lib/format';
  import { openListing, setParams } from '../lib/nav';
  import { auth, clock, prefs, ref, setDensity, ui } from '../lib/state.svelte';
  import type { FeedItem, FeedResponse } from '../lib/types';

  const TABS = [
    { key: 'feed', label: 'Best' },
    { key: 'steals', label: 'Steals' },
    { key: 'grails', label: 'Grails' },
    { key: 'heat', label: 'Heat' },
    { key: 'new', label: 'New' },
    { key: 'japan', label: 'Japan' },
    { key: 'ending', label: 'Ending soon' },
    { key: 'watchlist', label: 'Watchlist' },
    { key: 'rejected', label: 'Rejected' }
  ];

  const tab = $derived.by(() => {
    const t = page.url.searchParams.get('tab') || 'feed';
    return TABS.some((x) => x.key === t) ? t : 'feed';
  });
  const filters = $derived(filtersFrom(page.url.searchParams));
  const hasFilters = $derived(Object.keys(filters).length > 0);
  const queryKey = $derived(`${tab}|${JSON.stringify(filters)}`);

  let items = $state<FeedItem[]>([]);
  let cursor = $state<string | null>(null);
  let loading = $state(true);
  let loadingMore = $state(false);
  let error = $state('');
  let moreError = $state('');
  let ctl: AbortController | undefined;
  let first = true;
  let reload = $state(0);

  function paramsFor(c: string | null) {
    return qs({ ...filters, tab: tab === 'feed' ? '' : tab, limit: 30, cursor: c });
  }

  $effect(() => {
    queryKey;
    reload;
    untrack(() => {
      ctl?.abort();
      ctl = new AbortController();
      const mine = ctl;
      items = [];
      cursor = null;
      error = '';
      moreError = '';
      loading = true;
      if (!first) window.scrollTo({ top: 0 });
      first = false;
      api<FeedResponse>(`/api/feed${paramsFor(null)}`, { signal: mine.signal })
        .then((r) => {
          items = r.items;
          cursor = r.next_cursor;
          loading = false;
          queueMicrotask(maybeMore);
        })
        .catch((e: Error) => {
          if (e.name === 'AbortError') return;
          error = e.message;
          loading = false;
        });
    });
    return () => ctl?.abort();
  });

  async function more() {
    if (!cursor || loading || loadingMore) return;
    const mine = ctl;
    loadingMore = true;
    moreError = '';
    try {
      const r = await api<FeedResponse>(`/api/feed${paramsFor(cursor)}`, { signal: mine?.signal });
      if (mine !== ctl) return;
      const seen = new Set(items.map((i) => i.listing_id));
      items = [...items, ...r.items.filter((i) => !seen.has(i.listing_id))];
      cursor = r.next_cursor;
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      moreError = (e as Error).message;
    } finally {
      loadingMore = false;
      if (mine === ctl) requestAnimationFrame(maybeMore);
    }
  }

  let sentinel = $state<HTMLElement>();
  function maybeMore() {
    if (!sentinel || !cursor || loading || loadingMore || moreError) return;
    if (sentinel.getBoundingClientRect().top < window.innerHeight + 900) more();
  }
  $effect(() => {
    if (!sentinel) return;
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && more(), { rootMargin: '900px 0px' });
    io.observe(sentinel);
    return () => io.disconnect();
  });

  // ---------------------------------------------------------------- header furniture
  let stealCount = $state<string | null>(null);
  async function loadStealCount() {
    try {
      const r = await api<FeedResponse>('/api/feed?tab=steals&limit=60');
      stealCount = r.items.length ? `${r.items.length}${r.next_cursor ? '+' : ''}` : null;
    } catch {
      stealCount = null;
    }
  }
  onMount(() => {
    loadStealCount();
    const t = setInterval(() => {
      loadHealth();
      loadStealCount();
    }, 120_000);
    return () => clearInterval(t);
  });

  const lastScan = $derived.by(() => {
    const ok = (ref.health?.sources ?? []).map((s) => s.last_ok_at ?? 0);
    return ok.length ? Math.max(...ok) : 0;
  });
  const downSource = $derived(
    (ref.health?.sources ?? []).find((s) => ['blocked', 'error', 'paused'].includes(s.last_status ?? '') || (s.breaker_until ?? 0) > clock.now)
  );
  const downText = $derived(
    downSource
      ? downSource.last_ok_at
        ? `No scan has succeeded for ${sourceName(downSource.source)} since ${weekdayTime(downSource.last_ok_at)}.`
        : `No scan has succeeded for ${sourceName(downSource.source)} yet.`
      : ''
  );
  const status = $derived(
    ref.health ? `${(ref.health.counts.active ?? 0).toLocaleString('en-US')} live listings.${lastScan ? ` Last scan ${ago(lastScan)}.` : ' No scan has finished yet.'}` : ''
  );

  function tabHref(key: string) {
    const u = new URL(page.url.href);
    u.searchParams.delete('l');
    if (key === 'feed') u.searchParams.delete('tab');
    else u.searchParams.set('tab', key);
    return u.pathname + u.search;
  }
  function tabKeys(e: KeyboardEvent) {
    const i = TABS.findIndex((t) => t.key === tab);
    let n = -1;
    if (e.key === 'ArrowRight') n = (i + 1) % TABS.length;
    else if (e.key === 'ArrowLeft') n = (i - 1 + TABS.length) % TABS.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = TABS.length - 1;
    if (n < 0) return;
    e.preventDefault();
    setParams({ tab: TABS[n].key === 'feed' ? undefined : TABS[n].key, l: undefined }, { replace: true });
    queueMicrotask(() => document.getElementById(`tab-${TABS[n].key}`)?.focus());
  }
  $effect(() => {
    tab;
    document.getElementById(`tab-${tab}`)?.scrollIntoView({ inline: 'center', block: 'nearest' });
  });

  // ---------------------------------------------------------------- search and filters
  let q = $state('');
  $effect(() => {
    q = page.url.searchParams.get('q') ?? '';
  });
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  function onSearch(v: string) {
    q = v;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setParams({ q: v.trim() || undefined }, { replace: true }), 350);
  }
  let searchInput = $state<HTMLInputElement>();
  $effect(() => {
    if (ui.searchOpen) queueMicrotask(() => searchInput?.focus());
  });
  $effect(() => {
    if (page.url.searchParams.get('q')) ui.searchOpen = true;
  });

  function clearFilters() {
    const changes: Record<string, string | undefined> = {};
    for (const k of FILTER_KEYS) changes[k] = undefined;
    setParams(changes);
  }

  const emptyKind = $derived.by(() => {
    if (hasFilters) return 'filters';
    if (tab === 'watchlist') return 'watchlist';
    if (downText && (tab === 'feed' || tab === 'japan' || tab === 'new')) return 'quiet';
    return 'plain';
  });
  const PLAIN_EMPTY: Record<string, string> = {
    feed: 'Nothing is live right now.',
    steals: 'No steals right now. Check Best.',
    grails: 'No S tier listings right now.',
    heat: 'No A tier listings right now.',
    new: 'Nothing new in the last hour.',
    japan: 'Nothing from Japan right now.',
    ending: 'No auctions end in the next 24 hours.',
    watchlist: 'Nothing watched yet. Tap Watch on a listing to keep it here.',
    rejected: 'Nothing was rejected.'
  };
</script>

<svelte:head>
  <title>Grail Radar: {TABS.find((t) => t.key === tab)?.label}</title>
</svelte:head>

<h1 class="sr-only">Grail Radar feed</h1>
<div class="chrome">
  <nav class="tabs" aria-label="Feed views">
    <div role="tablist" aria-label="Feed views" tabindex="-1">
      {#each TABS as t (t.key)}
        <a
          role="tab"
          id="tab-{t.key}"
          href={tabHref(t.key)}
          aria-selected={tab === t.key}
          aria-controls="feed-panel"
          tabindex={tab === t.key ? 0 : -1}
          onkeydown={tabKeys}
          >{t.label}{#if t.key === 'steals' && stealCount}<sup>{stealCount}</sup><span class="sr-only"> steals</span>{/if}</a
        >
      {/each}
    </div>
  </nav>
  {#if ui.searchOpen}
    <form
      id="search-form"
      class="search"
      role="search"
      onsubmit={(e) => {
        e.preventDefault();
        clearTimeout(searchTimer);
        setParams({ q: q.trim() || undefined }, { replace: true });
      }}
    >
      <label for="q" class="sr-only">Search titles</label>
      <input
        id="q"
        type="search"
        enterkeyhint="search"
        placeholder="Search titles, such as L01 or 07AW"
        autocomplete="off"
        bind:this={searchInput}
        value={q}
        oninput={(e) => onSearch(e.currentTarget.value)}
        onkeydown={(e) => {
          if (e.key === 'Escape') {
            ui.searchOpen = false;
            onSearch('');
          }
        }}
      />
      {#if q}<button type="button" class="btn" onclick={() => { onSearch(''); searchInput?.focus(); }}>Clear</button>{/if}
    </form>
  {/if}
</div>

<div class="statusrow">
  <p class="status">
    {status}
    {#if downText}<span> {downText} <a href="/sources">See Sources.</a></span>{/if}
  </p>
  <div class="density" role="group" aria-label="Layout">
    <button type="button" aria-pressed={prefs.density === 'list'} onclick={() => setDensity('list')}>List</button>
    <button type="button" aria-pressed={prefs.density === 'grid'} onclick={() => setDensity('grid')}>Grid</button>
  </div>
</div>

<div role="tabpanel" id="feed-panel" aria-labelledby="tab-{tab}" aria-busy={loading}>
  <h2 class="sr-only">Listings, {TABS.find((t) => t.key === tab)?.label}</h2>
  {#if error && !items.length}
    <div class="state error">
      <p><span class="hatch" aria-hidden="true"></span><span>{error}</span></p>
      {#if !auth.signedOut}<button type="button" class="btn" onclick={() => (reload += 1)}>Try again</button>{/if}
    </div>
  {:else if loading}
    <div class="state" role="status">
      <Art name="loading-sweep" h="64px" label="Loading" />
      <p>Loading listings.</p>
    </div>
  {:else if !items.length}
    <div class="state">
      {#if emptyKind === 'filters'}
        <Art name="empty-rack" h="124px" decorative />
        <p>Nothing matches these filters.</p>
        <button type="button" class="btn solid" onclick={clearFilters}>Clear filters</button>
      {:else if emptyKind === 'watchlist'}
        <Art name="empty-watchlist" h="110px" decorative />
        <p>{PLAIN_EMPTY.watchlist}</p>
      {:else if emptyKind === 'quiet'}
        <Art name="empty-quiet" h="124px" decorative />
        <p>{downText} <a href="/sources">See Sources.</a></p>
      {:else}
        <Art name="empty-rack" h="124px" decorative />
        <p>{PLAIN_EMPTY[tab]}</p>
      {/if}
    </div>
  {:else}
    <div class="list" class:grid={prefs.density === 'grid'}>
      {#each items as item (item.listing_id)}
        <Card {item} density={prefs.density} onopen={(it) => openListing(it)} />
      {/each}
    </div>
    <div bind:this={sentinel} class="sentinel">
      {#if loadingMore}
        <div class="state" role="status"><Art name="loading-sweep" h="44px" label="Loading more" /></div>
      {:else if moreError}
        <div class="state error">
          <p><span class="hatch" aria-hidden="true"></span><span>{moreError}</span></p>
          <button type="button" class="btn" onclick={() => { moreError = ''; more(); }}>Try again</button>
        </div>
      {:else if !cursor}
        <p class="end">{items.length} {items.length === 1 ? 'listing' : 'listings'}. That is all of them.</p>
      {/if}
    </div>
  {/if}
</div>

<style>
  .chrome {
    position: sticky;
    top: calc(var(--bar-h) + env(safe-area-inset-top) + var(--rule-w));
    z-index: 9;
    background: var(--paper);
    border-bottom: var(--rule-w) solid var(--ink);
  }
  .tabs {
    max-width: var(--page-max);
    margin: 0 auto;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .tabs::-webkit-scrollbar {
    display: none;
  }
  [role='tablist'] {
    display: flex;
    gap: var(--s-4);
    padding: 0 var(--gutter);
    white-space: nowrap;
    width: max-content;
    min-width: 100%;
  }
  [role='tab'] {
    display: flex;
    align-items: center;
    min-height: var(--tap);
    color: var(--thread);
    text-decoration: none;
    font-stretch: var(--w-condensed);
    font-weight: 700;
    font-size: 1.25rem;
    border-bottom: 3px solid transparent;
    padding-top: 3px;
  }
  [role='tab'][aria-selected='true'] {
    color: var(--ink);
    border-bottom-color: var(--ink);
  }
  [role='tab'] sup {
    font-size: var(--t-micro);
    color: var(--selvedge);
    margin-left: 2px;
    align-self: flex-start;
    margin-top: 6px;
  }
  .search {
    display: flex;
    gap: var(--s-2);
    padding: var(--s-2) var(--gutter);
    border-top: var(--rule-w) solid var(--rule);
    max-width: var(--page-max);
    margin: 0 auto;
  }
  .statusrow {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--s-3);
    max-width: var(--page-max);
    margin: 0 auto;
    padding: 0 var(--gutter);
    border-bottom: var(--rule-w) solid var(--rule);
  }
  .status {
    padding: var(--s-2) 0;
    font-size: var(--t-small);
    color: var(--thread);
  }
  .status a {
    color: var(--ink);
  }
  .density {
    display: flex;
    flex: none;
  }
  .density button {
    min-height: var(--tap);
    padding: 0 var(--s-3);
    font-stretch: var(--w-condensed);
    font-weight: 700;
    font-size: var(--t-body);
    color: var(--thread);
  }
  .density button[aria-pressed='true'] {
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 6px;
    text-decoration-thickness: 3px;
  }
  [role='tabpanel'] {
    max-width: var(--page-max);
    margin: 0 auto;
  }
  .list {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }
  .list.grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .end {
    text-align: center;
    color: var(--thread);
    font-size: var(--t-small);
    padding: var(--s-6) var(--gutter);
  }
  @media (min-width: 640px) {
    .list.grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }
  @media (min-width: 900px) {
    .list {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .list :global(.card.list) {
      border-right: var(--rule-w) solid var(--ink);
    }
    .list.grid {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
  }
  @media (min-width: 1200px) {
    .list.grid {
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }
  }
  @media (min-width: 1400px) {
    .list {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .list.grid {
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }
  }
  @media (min-width: 1700px) {
    .list.grid {
      grid-template-columns: repeat(6, minmax(0, 1fr));
    }
  }
</style>
