<script lang="ts">
  import Sheet from './Sheet.svelte';
  import { api, qs } from './api';
  import { ensureTaxonomy, loadHealth, loadProfile, type Filters } from './data';
  import { ref } from './state.svelte';
  import { brandName, eraName } from './names';
  import { REGION_NAMES, sourceName, SORT_OPTIONS } from './format';
  import type { FeedResponse } from './types';

  interface Props {
    open: boolean;
    tab: string;
    filters: Filters;
    onapply: (f: Filters) => void;
    onclose: () => void;
  }
  let { open, tab, filters, onapply, onclose }: Props = $props();

  const SIZE_GROUPS: { label: string; sizes: string[] }[] = [
    { label: 'Letter sizes', sizes: ['XS', 'S', 'M', 'L', 'XL', 'XXL'] },
    { label: 'Numbered sizes', sizes: ['44', '46', '48', '50', '52', '54'] },
    { label: 'Waist sizes', sizes: ['W28', 'W30', 'W31', 'W32', 'W34'] },
    { label: 'Shoe sizes', sizes: ['EU41', 'EU42', 'EU43', 'EU44', 'EU45'] }
  ];
  const CONF_OPTIONS = [
    { value: '', label: 'Any' },
    { value: 'low', label: 'Low or better' },
    { value: 'med', label: 'Medium or better' },
    { value: 'high', label: 'High only' }
  ];

  let draft = $state<Filters>({});
  let sizes = $state<string[]>([]);
  let sources = $state<string[]>([]);
  let count = $state<number | null>(null);
  let countPlus = $state(false);
  let wasOpen = false;

  // Start from what is applied each time the sheet opens.
  $effect(() => {
    if (open && !wasOpen) {
      draft = { ...filters };
      sizes = filters.size ? filters.size.split(',') : [];
      sources = filters.source ? filters.source.split(',') : [];
      ensureTaxonomy();
      if (!ref.health) loadHealth();
      if (!ref.profile) loadProfile();
    }
    wasOpen = open;
  });

  const tax = $derived(ref.taxonomy);
  const brands = $derived([...(tax?.brands ?? [])].sort((a, b) => a.name.localeCompare(b.name)));
  const eras = $derived.by(() => {
    const all = tax?.eras ?? [];
    const list = draft.brand ? all.filter((e) => e.parent === draft.brand) : all;
    return [...list].sort((a, b) => (a.parent ?? '').localeCompare(b.parent ?? '') || a.name.localeCompare(b.name));
  });
  const pieces = $derived([...(tax?.archetypes ?? [])].sort((a, b) => a.name.localeCompare(b.name)));
  const sourceIds = $derived((ref.health?.sources ?? []).map((s) => s.source));
  const mySizes = $derived(ref.profile ? [...new Set([...ref.profile.tops, ...ref.profile.bottoms, ...ref.profile.shoes, ...ref.profile.tailoring])] : []);
  const extraSizes = $derived(sizes.filter((s) => !SIZE_GROUPS.some((g) => g.sizes.includes(s))));

  function setBrand(v: string) {
    draft.brand = v || undefined;
    if (draft.era && v && tax?.eras.find((e) => e.id === draft.era)?.parent !== v) draft.era = undefined;
  }
  function toggle(list: string[], v: string): string[] {
    return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
  }

  const built = $derived.by((): Filters => {
    const f: Filters = { ...draft };
    if (sizes.length) f.size = sizes.join(',');
    else delete f.size;
    if (sources.length) f.source = sources.join(',');
    else delete f.source;
    for (const k of Object.keys(f) as (keyof Filters)[]) if (!f[k]) delete f[k];
    return f;
  });

  // How many listings the draft would show: one capped count from the API.
  $effect(() => {
    if (!open) return;
    const params = { ...built, tab: tab === 'feed' ? '' : tab };
    const ctl = new AbortController();
    count = null;
    const t = setTimeout(async () => {
      try {
        const r = await api<{ count: number; capped: boolean }>(`/api/feed${qs({ ...params, count: 1 })}`, { signal: ctl.signal });
        countPlus = r.capped;
        count = r.count;
      } catch {
        /* the button keeps its generic label */
      }
    }, 280);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  });

  const confirmLabel = $derived(count === null ? 'Show listings' : `Show ${count}${countPlus ? '+' : ''} ${count === 1 && !countPlus ? 'listing' : 'listings'}`);

  function clear() {
    draft = { q: draft.q };
    sizes = [];
    sources = [];
  }
  function apply() {
    onapply(built);
  }
</script>

<Sheet {open} label="Filter listings" title="Filter" {onclose}>
  <form
    class="form"
    id="filter-form"
    onsubmit={(e) => {
      e.preventDefault();
      apply();
    }}
  >
    <div class="field">
      <label for="f-brand">Brand</label>
      <select id="f-brand" value={draft.brand ?? ''} onchange={(e) => setBrand(e.currentTarget.value)}>
        <option value="">Any brand</option>
        {#each brands as b (b.id)}<option value={b.id}>{b.name}{b.active ? ` (${b.active})` : ''}</option>{/each}
      </select>
    </div>
    <div class="field">
      <label for="f-era">Era</label>
      <select id="f-era" value={draft.era ?? ''} onchange={(e) => (draft.era = e.currentTarget.value || undefined)}>
        <option value="">{draft.brand ? `Any ${brandName(draft.brand)} era` : 'Any era'}</option>
        {#each eras as e (e.id)}<option value={e.id}>{draft.brand ? (e.label ?? e.name) : `${brandName(e.parent)}, ${e.label ?? e.name}`}</option>{/each}
      </select>
    </div>
    <div class="field">
      <label for="f-piece">Piece type</label>
      <select id="f-piece" value={draft.archetype ?? ''} onchange={(e) => (draft.archetype = e.currentTarget.value || undefined)}>
        <option value="">Any piece</option>
        {#each pieces as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
      </select>
    </div>

    <fieldset class="field">
      <legend>Size</legend>
      <div class="chips" role="group" aria-label="Sizes">
        <button type="button" class="chip" disabled={!mySizes.length} onclick={() => (sizes = [...mySizes])}>Use my sizes</button>
        {#if sizes.length}<button type="button" class="chip" onclick={() => (sizes = [])}>Any size</button>{/if}
      </div>
      {#if ref.profile && !mySizes.length}
        <p class="inline-note">No sizes saved yet. <a href="/alerts#sizes">Add your sizes</a>.</p>
      {/if}
      {#each SIZE_GROUPS as g (g.label)}
        <div class="chips" role="group" aria-label={g.label}>
          {#each g.sizes as s (s)}
            <button type="button" class="chip" aria-pressed={sizes.includes(s)} onclick={() => (sizes = toggle(sizes, s))}>{s}</button>
          {/each}
        </div>
      {/each}
      {#if extraSizes.length}
        <div class="chips" role="group" aria-label="Other sizes">
          {#each extraSizes as s (s)}
            <button type="button" class="chip" aria-pressed="true" onclick={() => (sizes = toggle(sizes, s))}>{s}</button>
          {/each}
        </div>
      {/if}
    </fieldset>

    <fieldset class="field">
      <legend>Landed price in USD</legend>
      <div class="two">
        <div class="field">
          <label for="f-min" class="sr-only">Lowest price</label>
          <input id="f-min" type="number" inputmode="numeric" min="0" step="10" placeholder="Lowest" value={draft.min_price ?? ''} oninput={(e) => (draft.min_price = e.currentTarget.value || undefined)} />
        </div>
        <div class="field">
          <label for="f-max" class="sr-only">Highest price</label>
          <input id="f-max" type="number" inputmode="numeric" min="0" step="10" placeholder="Highest" value={draft.max_price ?? ''} oninput={(e) => (draft.max_price = e.currentTarget.value || undefined)} />
        </div>
      </div>
    </fieldset>

    <fieldset class="field">
      <legend>Source</legend>
      <div class="chips" role="group" aria-label="Sources">
        {#each sourceIds as s (s)}
          <button type="button" class="chip" aria-pressed={sources.includes(s)} onclick={() => (sources = toggle(sources, s))}>{sourceName(s)}</button>
        {:else}
          <span class="inline-note">Sources load from the status page.</span>
        {/each}
      </div>
    </fieldset>

    <fieldset class="field">
      <legend>Region</legend>
      <div class="chips" role="group" aria-label="Region">
        <button type="button" class="chip" aria-pressed={!draft.region} onclick={() => (draft.region = undefined)}>Anywhere</button>
        {#each Object.entries(REGION_NAMES) as [code, name] (code)}
          <button type="button" class="chip" aria-pressed={draft.region === code} onclick={() => (draft.region = code)}>{name}</button>
        {/each}
      </div>
    </fieldset>

    <fieldset class="field">
      <legend>Minimum value confidence</legend>
      <div class="chips" role="group" aria-label="Minimum value confidence">
        {#each CONF_OPTIONS as o (o.value)}
          <button type="button" class="chip" aria-pressed={(draft.min_conf ?? '') === o.value} onclick={() => (draft.min_conf = o.value || undefined)}>{o.label}</button>
        {/each}
      </div>
    </fieldset>

    <label class="check">
      <input type="checkbox" checked={draft.hide_suspicious === '1'} onchange={(e) => (draft.hide_suspicious = e.currentTarget.checked ? '1' : undefined)} />
      <span>Hide suspicious listings</span>
    </label>

    <div class="field">
      <label for="f-sort">Sort</label>
      <select id="f-sort" value={draft.sort ?? ''} onchange={(e) => (draft.sort = e.currentTarget.value || undefined)}>
        {#each SORT_OPTIONS as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
      </select>
    </div>
    {#if draft.q}<p class="inline-note">Search text “{draft.q}” stays applied.</p>{/if}
  </form>

  {#snippet footer()}
    <div class="foot">
      <button type="button" class="btn" onclick={clear}>Clear filters</button>
      <button type="submit" form="filter-form" class="btn solid">{confirmLabel}</button>
    </div>
  {/snippet}
</Sheet>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--s-4);
    padding: var(--s-4) var(--gutter) var(--s-6);
  }
  .two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--s-2);
  }
  fieldset.field {
    gap: var(--s-2);
  }
  .check {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    min-height: var(--tap);
  }
  .check input {
    width: 22px;
    height: 22px;
    accent-color: var(--ink);
    margin: 0;
  }
  .foot {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--s-2);
    padding: var(--s-2) var(--gutter);
  }
</style>
