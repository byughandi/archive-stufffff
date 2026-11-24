<script lang="ts">
  import { onMount } from 'svelte';
  import Art from '../../lib/Art.svelte';
  import Switch from '../../lib/Switch.svelte';
  import { api, qs } from '../../lib/api';
  import { ensureTaxonomy, loadHealth, loadProfile } from '../../lib/data';
  import { REGION_NAMES, ago, sourceName, usd } from '../../lib/format';
  import { archetypeName, brandName, eraName } from '../../lib/names';
  import { ref, say } from '../../lib/state.svelte';
  import type { Rule, SavedSearch, SizeProfile } from '../../lib/types';

  type Delivery = { channel?: string; configured?: boolean; last_sent_at?: number | null };
  let delivery = $state<Delivery | null>(null);
  let searches = $state<SavedSearch[]>([]);
  let loading = $state(true);
  let error = $state('');

  async function load() {
    try {
      const r = await api<{ searches: SavedSearch[]; delivery?: Delivery | null }>('/api/searches');
      delivery = r.delivery ?? null;
      searches = r.searches;
      error = '';
    } catch (e) {
      error = (e as Error).message;
    }
    loading = false;
  }
  onMount(() => {
    ensureTaxonomy();
    loadHealth();
    loadProfile().then(() => {
      if (ref.profile) profile = structuredClone($state.snapshot(ref.profile)) as SizeProfile;
    });
    load();
  });

  const builtIn = $derived(searches.find((s) => s.is_global));
  const mine = $derived(searches.filter((s) => !s.is_global));

  async function setEnabled(s: SavedSearch, on: boolean) {
    const before = s.enabled;
    s.enabled = on ? 1 : 0;
    try {
      await api(`/api/searches/${s.id}`, { method: 'PUT', json: { enabled: on } });
    } catch {
      s.enabled = before;
      say('Could not change that alert. Try again.');
    }
  }

  let confirming = $state<number | null>(null);
  let confirmTimer: ReturnType<typeof setTimeout> | undefined;
  async function remove(s: SavedSearch) {
    if (confirming !== s.id) {
      confirming = s.id;
      clearTimeout(confirmTimer);
      confirmTimer = setTimeout(() => (confirming = null), 4000);
      return;
    }
    confirming = null;
    const before = searches;
    searches = searches.filter((x) => x.id !== s.id);
    try {
      await api(`/api/searches/${s.id}`, { method: 'DELETE' });
    } catch {
      searches = before;
      say('Could not delete that saved search. Try again.');
    }
  }

  // ---------------------------------------------------------------- reading a rule back as words
  const TIERS = ['S', 'A', 'B', 'C'];
  function describe(r: Rule): string {
    const parts: string[] = [];
    if (r.q) parts.push(`Title contains “${r.q}”`);
    if (r.brand) parts.push(brandName(r.brand));
    if (r.era) parts.push(eraName(r.era));
    if (r.archetype) parts.push(archetypeName(r.archetype));
    if (r.sizes?.length) parts.push(`Size ${r.sizes.join(', ')}`);
    if (r.max_landed_usd) parts.push(`Up to ${usd(r.max_landed_usd)} landed`);
    if (r.min_tier) parts.push(r.min_tier === 'S' ? 'S tier only' : `Tier ${r.min_tier} or better`);
    if (r.labels?.length) parts.push(`Labelled ${r.labels.map(cap).join(' or ')}`);
    if (r.sources?.length) parts.push(`From ${r.sources.map(sourceName).join(', ')}`);
    if (r.region) parts.push(REGION_NAMES[r.region] ?? r.region);
    return parts.length ? parts.join('. ') + '.' : 'Every listing.';
  }
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  function feedLink(r: Rule): string {
    return (
      '/' +
      qs({
        q: r.q,
        brand: r.brand,
        era: r.era,
        archetype: r.archetype,
        size: r.sizes?.join(','),
        max_price: r.max_landed_usd,
        tier: r.min_tier ? TIERS.slice(0, TIERS.indexOf(r.min_tier) + 1).join(',') : '',
        label: r.labels?.join(','),
        source: r.sources?.join(','),
        region: r.region
      })
    );
  }

  // ---------------------------------------------------------------- the form
  const SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '44', '46', '48', '50', '52', '54', 'W28', 'W30', 'W32', 'W34', 'EU41', 'EU42', 'EU43', 'EU44', 'EU45'];
  let name = $state('');
  let fq = $state('');
  let fbrand = $state('');
  let fera = $state('');
  let farch = $state('');
  let fsizes = $state<string[]>([]);
  let fmax = $state('');
  let ftier = $state('');
  let flabels = $state<string[]>([]);
  let fsources = $state<string[]>([]);
  let fregion = $state('');
  let formError = $state('');
  let saving = $state(false);

  const brands = $derived([...(ref.taxonomy?.brands ?? [])].sort((a, b) => a.name.localeCompare(b.name)));
  const eras = $derived((ref.taxonomy?.eras ?? []).filter((e) => !fbrand || e.parent === fbrand));
  const pieces = $derived([...(ref.taxonomy?.archetypes ?? [])].sort((a, b) => a.name.localeCompare(b.name)));
  const sourceIds = $derived((ref.health?.sources ?? []).map((s) => s.source));
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function save(e: Event) {
    e.preventDefault();
    const rule: Rule = {};
    if (fq.trim()) rule.q = fq.trim();
    if (fbrand) rule.brand = fbrand;
    if (fera) rule.era = fera;
    if (farch) rule.archetype = farch;
    if (fsizes.length) rule.sizes = fsizes;
    if (fmax && Number(fmax) > 0) rule.max_landed_usd = Number(fmax);
    if (ftier) rule.min_tier = ftier;
    if (flabels.length) rule.labels = flabels;
    if (fsources.length) rule.sources = fsources;
    if (fregion) rule.region = fregion;
    if (!name.trim() || !Object.keys(rule).length) {
      formError = 'Give the search a name and at least one rule, such as a brand or a size.';
      return;
    }
    formError = '';
    saving = true;
    try {
      await api('/api/searches', { method: 'POST', json: { name: name.trim(), rule } });
      name = fq = fbrand = fera = farch = fmax = ftier = fregion = '';
      fsizes = flabels = fsources = [];
      await load();
      say('Saved. You will be alerted when a new listing matches.');
    } catch (err) {
      formError = (err as Error).message;
    }
    saving = false;
  }

  // ---------------------------------------------------------------- size profile
  const PROFILE_GROUPS: { key: keyof SizeProfile; label: string; options: string[] }[] = [
    { key: 'tops', label: 'Tops and outerwear', options: ['XS', 'S', 'M', 'L', 'XL', 'XXL'] },
    { key: 'tailoring', label: 'Tailoring and numbered sizes', options: ['44', '46', '48', '50', '52', '54'] },
    { key: 'bottoms', label: 'Bottoms', options: ['W28', 'W29', 'W30', 'W31', 'W32', 'W33', 'W34', 'W36'] },
    { key: 'shoes', label: 'Shoes', options: ['EU40', 'EU41', 'EU42', 'EU43', 'EU44', 'EU45', 'EU46'] }
  ];
  let profile = $state<SizeProfile>({ tops: [], bottoms: [], shoes: [], tailoring: [] });
  let custom = $state<Record<string, string>>({});
  let profileSaving = $state(false);
  let profileSaved = $state(false);

  function toggleSize(key: keyof SizeProfile, v: string) {
    profile[key] = toggle(profile[key], v);
    profileSaved = false;
  }
  function addCustom(key: keyof SizeProfile) {
    const v = (custom[key] ?? '').trim().toUpperCase();
    if (v && !profile[key].includes(v)) profile[key] = [...profile[key], v];
    custom[key] = '';
    profileSaved = false;
  }
  async function saveProfile() {
    profileSaving = true;
    try {
      const r = await api<{ size_profile: SizeProfile }>('/api/profile', { method: 'PUT', json: { size_profile: $state.snapshot(profile) } });
      ref.profile = r.size_profile;
      profile = structuredClone(r.size_profile);
      profileSaved = true;
    } catch (e) {
      say('Could not save your sizes. Try again.');
    }
    profileSaving = false;
  }
</script>

<svelte:head><title>Grail Radar: Alerts</title></svelte:head>

<main class="page">
  <h1>Alerts</h1>
  <p class="lede">
    Alerts are pushed to your phone with ntfy, once per listing for each rule that matches. Tapping an alert opens that listing here.
    {#if delivery && delivery.configured === false}
      No ntfy topic is set yet, so nothing is being sent. Add the NTFY_TOPIC secret in GitHub.
    {:else if delivery?.last_sent_at}
      Last alert sent {ago(delivery.last_sent_at)}.
    {/if}
  </p>

  {#if loading}
    <div class="state" role="status"><Art name="loading-sweep" h="64px" label="Loading" /><p>Loading alerts.</p></div>
  {:else if error}
    <div class="state error">
      <p><span class="hatch" aria-hidden="true"></span><span>{error}</span></p>
      <button type="button" class="btn" onclick={() => { loading = true; load(); }}>Try again</button>
    </div>
  {:else}
    <h2>Built-in rule</h2>
    {#if builtIn}
      <div class="rule">
        <Art name="icon-alert" h="32px" decorative />
        <div class="rt">
          <h3>S tier or Steal</h3>
          <p class="quiet">Alerts for every S tier listing and every Steal. Never for suspicious listings.</p>
        </div>
        <Switch checked={!!builtIn.enabled} label="Built-in rule, S tier or Steal" onchange={(on) => setEnabled(builtIn, on)} />
      </div>
    {:else}
      <p class="quiet">The built-in rule has not been created yet. It appears after the first scoring run.</p>
    {/if}

    <h2>Your saved searches</h2>
    {#if mine.length}
      <ul class="searches">
        {#each mine as s (s.id)}
          <li>
            <div class="rt">
              <h3>{s.name}</h3>
              <p class="quiet">{describe(s.rule)}</p>
              <p class="acts">
                <a href={feedLink(s.rule)}>Show matches</a>
                <button type="button" class="link-btn" onclick={() => remove(s)}>{confirming === s.id ? 'Tap again to delete' : 'Delete'}<span class="sr-only"> {s.name}</span></button>
              </p>
            </div>
            <Switch checked={!!s.enabled} label={`Alerts for ${s.name}`} onchange={(on) => setEnabled(s, on)} />
          </li>
        {/each}
      </ul>
    {:else}
      <p class="quiet">No saved searches yet. Add one below.</p>
    {/if}

    <h2>Add a saved search</h2>
    <form class="form" onsubmit={save}>
      <div class="field">
        <label for="a-name">Name</label>
        <input id="a-name" type="text" bind:value={name} maxlength="60" placeholder="Hedi leather, my size" autocomplete="off" />
      </div>
      <div class="field">
        <label for="a-q">Title contains</label>
        <input id="a-q" type="text" bind:value={fq} maxlength="60" placeholder="L01" autocomplete="off" />
      </div>
      <div class="three">
        <div class="field">
          <label for="a-brand">Brand</label>
          <select id="a-brand" bind:value={fbrand} onchange={() => { if (fera && ref.taxonomy?.eras.find((e) => e.id === fera)?.parent !== fbrand) fera = ''; }}>
            <option value="">Any brand</option>
            {#each brands as b (b.id)}<option value={b.id}>{b.name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="a-era">Era</label>
          <select id="a-era" bind:value={fera}>
            <option value="">Any era</option>
            {#each eras as e (e.id)}<option value={e.id}>{fbrand ? (e.label ?? e.name) : `${brandName(e.parent)}, ${e.label ?? e.name}`}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="a-piece">Piece type</label>
          <select id="a-piece" bind:value={farch}>
            <option value="">Any piece</option>
            {#each pieces as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
          </select>
        </div>
      </div>
      <fieldset class="field">
        <legend>Sizes</legend>
        <div class="chips">
          <button type="button" class="chip" disabled={!ref.profile || ![...(ref.profile?.tops ?? []), ...(ref.profile?.bottoms ?? []), ...(ref.profile?.shoes ?? []), ...(ref.profile?.tailoring ?? [])].length} onclick={() => ref.profile && (fsizes = [...new Set([...ref.profile.tops, ...ref.profile.bottoms, ...ref.profile.shoes, ...ref.profile.tailoring])])}>Use my sizes</button>
          {#each SIZES as s (s)}
            <button type="button" class="chip" aria-pressed={fsizes.includes(s)} onclick={() => (fsizes = toggle(fsizes, s))}>{s}</button>
          {/each}
        </div>
      </fieldset>
      <div class="three">
        <div class="field">
          <label for="a-max">Highest landed price in USD</label>
          <input id="a-max" type="number" inputmode="numeric" min="0" step="50" bind:value={fmax} placeholder="1500" />
        </div>
        <div class="field">
          <label for="a-tier">Lowest tier</label>
          <select id="a-tier" bind:value={ftier}>
            <option value="">Any tier</option>
            <option value="S">S only</option>
            <option value="A">A or better</option>
            <option value="B">B or better</option>
          </select>
        </div>
        <div class="field">
          <label for="a-region">Region</label>
          <select id="a-region" bind:value={fregion}>
            <option value="">Anywhere</option>
            {#each Object.entries(REGION_NAMES) as [code, nm] (code)}<option value={code}>{nm}</option>{/each}
          </select>
        </div>
      </div>
      <fieldset class="field">
        <legend>Deal labels</legend>
        <div class="chips">
          {#each ['steal', 'great', 'good'] as l (l)}
            <button type="button" class="chip" aria-pressed={flabels.includes(l)} onclick={() => (flabels = toggle(flabels, l))}>{cap(l)}</button>
          {/each}
        </div>
      </fieldset>
      {#if sourceIds.length}
        <fieldset class="field">
          <legend>Sources</legend>
          <div class="chips">
            {#each sourceIds as s (s)}
              <button type="button" class="chip" aria-pressed={fsources.includes(s)} onclick={() => (fsources = toggle(fsources, s))}>{sourceName(s)}</button>
            {/each}
          </div>
        </fieldset>
      {/if}
      {#if formError}<p class="err" role="alert"><span class="hatch" aria-hidden="true"></span>{formError}</p>{/if}
      <div><button type="submit" class="btn solid" disabled={saving}>{saving ? 'Saving' : 'Save search'}</button></div>
    </form>

    <h2 id="sizes">Your sizes</h2>
    <p class="lede">Saved once, used by “Use my sizes” in Filter and when you add a search.</p>
    <div class="form">
      {#each PROFILE_GROUPS as g (g.key)}
        <fieldset class="field">
          <legend>{g.label}</legend>
          <div class="chips">
            {#each [...g.options, ...profile[g.key].filter((s) => !g.options.includes(s))] as s (s)}
              <button type="button" class="chip" aria-pressed={profile[g.key].includes(s)} onclick={() => toggleSize(g.key, s)}>{s}</button>
            {/each}
          </div>
          <div class="addrow">
            <label for="cs-{g.key}" class="sr-only">Add another {g.label.toLowerCase()} size</label>
            <input
              id="cs-{g.key}"
              type="text"
              placeholder="Another size"
              maxlength="8"
              value={custom[g.key] ?? ''}
              oninput={(e) => (custom[g.key] = e.currentTarget.value)}
              onkeydown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addCustom(g.key);
                }
              }}
            />
            <button type="button" class="btn" onclick={() => addCustom(g.key)}>Add</button>
          </div>
        </fieldset>
      {/each}
      <div class="saverow">
        <button type="button" class="btn solid" disabled={profileSaving} onclick={saveProfile}>{profileSaving ? 'Saving' : 'Save sizes'}</button>
        {#if profileSaved}<span role="status" class="quiet">Sizes saved.</span>{/if}
      </div>
    </div>
  {/if}
</main>

<style>
  .rule,
  .searches li {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    padding: var(--s-3) 0;
    border-bottom: var(--rule-w) solid var(--rule);
  }
  .rt {
    flex: 1;
    min-width: 0;
  }
  .rt h3 {
    font-stretch: var(--w-condensed);
    font-weight: 800;
    font-size: var(--t-lead);
  }
  .quiet {
    color: var(--thread);
    font-size: var(--t-meta);
  }
  .acts {
    display: flex;
    gap: var(--s-4);
    font-size: var(--t-meta);
    margin-top: var(--s-1);
  }
  .acts a {
    display: inline-flex;
    align-items: center;
    min-height: var(--tap);
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--s-4);
    max-width: 40rem;
  }
  .three {
    display: grid;
    gap: var(--s-3);
    grid-template-columns: 1fr;
  }
  @media (min-width: 700px) {
    .three {
      grid-template-columns: repeat(3, 1fr);
    }
  }
  .err {
    display: flex;
    gap: var(--s-2);
    align-items: flex-start;
    font-size: var(--t-meta);
  }
  .addrow {
    display: flex;
    gap: var(--s-2);
    max-width: 18rem;
  }
  .addrow .btn {
    font-size: var(--t-body);
  }
  .saverow {
    display: flex;
    align-items: center;
    gap: var(--s-3);
  }
</style>
