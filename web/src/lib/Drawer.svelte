<script lang="ts">
  import { untrack } from 'svelte';
  import Sheet from './Sheet.svelte';
  import Art from './Art.svelte';
  import Thumb from './Thumb.svelte';
  import Bar from './Bar.svelte';
  import RangeBar from './RangeBar.svelte';
  import Sparkline from './Sparkline.svelte';
  import FeedbackStrip from './FeedbackStrip.svelte';
  import { api, ApiError } from './api';
  import { brandName, eraLine } from './names';
  import { ago, bidsText, CONF_WORD, countdown, dateShort, figureOf, FLAG_FALLBACK, LEVEL_WORDS, money, pct, sourceName, usd } from './format';
  import { prevLanded, sizeText, stampOf, TIER_ART } from './deal';
  import { feedbackOf, watchedOf } from './state.svelte';
  import { tapFeedback, toggleWatch } from './data';
  import type { ExplainEntity, FeedItem, ListingDetail } from './types';

  interface Props {
    id: string | null;
    seed: FeedItem | null;
    onclose: () => void;
  }
  let { id, seed, onclose }: Props = $props();

  let detail = $state<ListingDetail | null>(null);
  let loading = $state(false);
  let error = $state('');
  let retry = $state(0);

  // The sheet stays mounted while it slides away, so keep the last id for the exit.
  let shownId = $state<string | null>(null);
  $effect(() => {
    if (id) shownId = id;
  });

  $effect(() => {
    retry;
    if (!id) return;
    const ctl = new AbortController();
    loading = true;
    error = '';
    // Read `detail` without subscribing to it: this effect also writes it, and a tracked read would make
    // every successful load trigger the next one (an endless request loop while the drawer is open).
    const current = untrack(() => detail);
    if (current && current.item.listing_id !== id) detail = null;
    api<ListingDetail>(`/api/listing/${encodeURIComponent(id)}`, { signal: ctl.signal })
      .then((d) => {
        detail = d;
        loading = false;
      })
      .catch((e: Error) => {
        if (e.name === 'AbortError') return;
        loading = false;
        error = e instanceof ApiError && e.status === 404 ? 'That listing is no longer in the feed.' : e.message;
      });
    return () => ctl.abort();
  });

  const item = $derived<FeedItem | null>(detail && detail.item.listing_id === shownId ? detail.item : seed && seed.listing_id === shownId ? seed : null);
  const ex = $derived(detail && detail.item.listing_id === shownId ? detail.explain : null);
  const fig = $derived(item ? figureOf(item) : null);
  const tier = $derived(item ? (TIER_ART[item.tier] ?? TIER_ART.C) : null);
  const stamp = $derived(item ? stampOf(item) : null);
  const old = $derived(item ? prevLanded(item) : null);
  const photos = $derived.by(() => {
    const list = detail?.images?.length ? detail.images : item?.image_url ? [item.image_url] : [];
    return list.slice(0, 4);
  });
  const dealFlag = $derived(item?.deal_label === 'steal' || item?.deal_label === 'great');
  const flags = $derived.by(() => {
    if (ex?.flags?.length) return ex.flags;
    return (item?.flags ?? []).map((f) => ({ id: f, label: FLAG_FALLBACK[f] ?? f.replace(/_/g, ' '), severity: 1 }));
  });
  const SEVERITY = ['', 'Note', 'Caution', 'Serious'];

  const ent = $derived(ex?.entities ?? null);
  const years = (e: ExplainEntity) => (e.years ? `${e.years[0]} to ${e.years[1] ?? 'now'}` : '');
  const history = $derived(detail?.snapshots ?? []);
  const priceNote = $derived.by(() => {
    if (history.length < 2) return '';
    const first = history[0];
    const last = history[history.length - 1];
    if (last.price_usd === first.price_usd) return '';
    return `Was ${usd(first.price_usd)} on ${dateShort(first.at)}, now ${usd(last.price_usd)}.`;
  });
  const shipLine = (label: string, v: number | null | undefined) => (v === null || v === undefined ? null : { label, v });
  const ledger = $derived.by(() => {
    const c = ex?.cost;
    if (!c) return [];
    return [
      { label: 'Price', v: c.price_usd },
      shipLine('Proxy fee', c.proxy_fee_usd),
      shipLine('Shipping within the seller’s country', c.domestic_shipping_usd),
      shipLine('International shipping', c.intl_shipping_usd),
      shipLine('Duty and import tax', c.duty_usd)
    ].filter((r): r is { label: string; v: number } => r !== null && r.v !== 0);
  });
  const title = $derived(item ? `${brandName(item.brand)}, ${eraLine(item)}` : 'Listing');
</script>

<Sheet open={!!id} label={`Why this score: ${title}`} {onclose} tall>
  {#if !item}
    {#if error}
      <div class="state error">
        <p><span class="hatch" aria-hidden="true"></span>{error}</p>
        <button type="button" class="btn" onclick={() => (retry += 1)}>Try again</button>
      </div>
    {:else}
      <div class="state" role="status">
        <Art name="loading-sweep" h="64px" label="Loading" />
        <p>Loading the listing.</p>
      </div>
    {/if}
  {:else}
    <div class="strip" aria-label="Photos">
      {#each photos as p, i (p)}
        <div class="slot"><Thumb src={p} alt={`Photo ${i + 1} of ${photos.length}`} eager={i === 0} /></div>
      {:else}
        <div class="slot"><Thumb src={null} /></div>
      {/each}
    </div>

    <div class="pad">
      <div class="marks">
        {#if tier}<Art name={tier.art} label={tier.label} h="32px" />{/if}
        {#if stamp}<span class="stamp"><Art name={stamp.art} label={stamp.label} h="26px" /></span>{/if}
        {#if item.region === 'JP'}<span class="jp-pill">日本</span>{/if}
      </div>
      <h3 class="brand">{brandName(item.brand)}</h3>
      <p class="era">{eraLine(item)}</p>
      <p class="orig">{item.title}</p>
      <p class="src">
        {sourceName(item.source)},
        {#if item.is_auction && item.auction_end_at}{countdown(item.auction_end_at)}, {bidsText(item.bids)}.{:else}{ago(item.listed_at)}.{/if}
        {sizeText(item.size_norm)}
      </p>

      {#if fig}
        <div class="big tone-{fig.tone}">
          <b class="figure">{fig.text}</b>
          <span>{fig.caption[0]}<br />{fig.caption[1]}</span>
        </div>
      {/if}
      {#if item.tier !== 'X'}
        <p class="price">
          {usd(item.landed_usd)} landed{#if old}<s><span class="sr-only">was </span>{usd(old)}</s>{/if}{#if item.fair_value_usd},
            fair value {usd(item.fair_value_usd)}{/if}
        </p>
      {/if}
      {#if item.tier === 'X' && item.reject_reason}
        <p class="flag"><span class="hatch" aria-hidden="true"></span>{item.reject_reason}</p>
      {/if}

      <div class="actions">
        <a class="btn solid" href={item.url} target="_blank" rel="noopener noreferrer">Open listing<span class="sr-only"> (opens in a new tab)</span></a>
        {#if item.region === 'JP' && item.proxy_url}
          <a class="btn" href={item.proxy_url} target="_blank" rel="noopener noreferrer">Buy via Buyee<span class="sr-only"> (opens in a new tab)</span></a>
        {/if}
      </div>
      {#if loading && !detail}<p class="inline-note" role="status">Loading the score breakdown.</p>{/if}
      {#if error && !detail}<p class="inline-note">{error}</p>{/if}
    </div>

    <section class="sec" aria-labelledby="s-what">
      <h3 id="s-what">What it is</h3>
      {#if ent}
        <dl class="ents">
          <div>
            <dt>Brand</dt>
            <dd>
              {#if ent.brand}
                <span class="name">{ent.brand.name}</span>
                {#if ent.brand.conf !== undefined}<Bar value={ent.brand.conf} label="Brand confidence" />{/if}
                {#if ent.brand.matched?.length}<p class="cues">Matched on {ent.brand.matched.join(', ')}</p>{/if}
              {:else}<span class="quiet">Not identified.</span>{/if}
            </dd>
          </div>
          <div>
            <dt>Era</dt>
            <dd>
              {#if ent.era}
                <span class="name">{ent.era.name}</span>{#if ent.era.years}<span class="quiet">, {years(ent.era)}</span>{/if}
                {#if ent.era.conf !== undefined}<Bar value={ent.era.conf} label="Era confidence" />{/if}
                {#if ent.era.cues?.length}<p class="cues">Evidence: {ent.era.cues.join(', ')}</p>{/if}
                {#if ent.era.anti_cues?.length}<p class="cues">Against: {ent.era.anti_cues.join(', ')}</p>{/if}
              {:else}<span class="quiet">Era unconfirmed.</span>{/if}
            </dd>
          </div>
          <div>
            <dt>Season</dt>
            <dd>
              {#if ent.season}
                <span class="name">{ent.season.name}</span>
                {#if ent.season.conf !== undefined}<Bar value={ent.season.conf} label="Season confidence" />{/if}
                {#if ent.season.matched?.length}<p class="cues">Matched on {ent.season.matched.join(', ')}</p>{/if}
              {:else}<span class="quiet">Not identified.</span>{/if}
            </dd>
          </div>
          <div>
            <dt>Piece</dt>
            <dd>
              {#if ent.archetype}
                <span class="name">{ent.archetype.name}</span>
                {#if ent.archetype.matched?.length}<p class="cues">Matched on {ent.archetype.matched.join(', ')}</p>{/if}
              {:else}<span class="quiet">Not identified.</span>{/if}
            </dd>
          </div>
        </dl>
      {:else}
        <p class="quiet">{loading ? 'Loading.' : 'No identification details for this listing yet.'}</p>
      {/if}
      {#if detail?.seller?.username}
        <p class="seller">
          Seller {detail.seller.username}{#if detail.seller.review_count}, rated {detail.seller.rating ?? 'n/a'} from {detail.seller.review_count} reviews{/if}{#if detail.seller.sales_count}, {detail.seller.sales_count} sales{/if}.
        </p>
      {/if}
    </section>

    <section class="sec" aria-labelledby="s-worth">
      <h3 id="s-worth">What it’s worth</h3>
      {#if ex?.value?.fair_value_usd}
        {@const v = ex.value}
        <p class="lead">
          <b class="figure fair">{usd(v.fair_value_usd)}</b>
          <span>fair value</span>
        </p>
        <p class="quiet">
          {CONF_WORD[v.conf] ?? v.conf} confidence. {LEVEL_WORDS[v.level] ?? ''}. From {v.comp_count} sold{v.market ? ` in the ${v.market === 'JP' ? 'Japanese' : v.market === 'US' ? 'US' : v.market} market` : ''}.
        </p>
        {#if v.range_usd}
          <div class="rangewrap">
            <RangeBar p25={v.range_usd[0]} p75={v.range_usd[1]} median={v.fair_value_usd ?? 0} landed={item.landed_usd} deal={dealFlag} />
          </div>
        {/if}
        {#if v.comps?.length}
          <h4>Sold comps</h4>
          <ul class="comps">
            {#each v.comps as c (c.id)}
              <li>
                <span class="cp tabnum">{usd(c.price_usd)}</span>
                <span class="cd">{dateShort(c.sold_at)}</span>
                {#if c.url}
                  <a href={c.url} target="_blank" rel="noopener noreferrer" class="ct">{c.title}<span class="sr-only"> (opens in a new tab)</span></a>
                {:else}<span class="ct">{c.title}</span>{/if}
              </li>
            {/each}
          </ul>
        {/if}
      {:else if item.fair_value_usd}
        <p class="lead"><b class="figure fair">{usd(item.fair_value_usd)}</b><span>fair value</span></p>
        <p class="quiet">From {item.comp_count ?? 0} sold. Details are not available for this listing.</p>
      {:else}
        <p>No fair value yet. There are not enough sold comps for this piece to price it.</p>
      {/if}
    </section>

    <section class="sec" aria-labelledby="s-costs">
      <h3 id="s-costs">What it costs</h3>
      {#if ledger.length}
        <dl class="ledger">
          {#each ledger as row (row.label)}
            <div><dt>{row.label}</dt><dd class="tabnum">{usd(row.v)}</dd></div>
          {/each}
          <div class="total"><dt>Landed</dt><dd class="tabnum">{usd(ex?.cost?.landed_usd ?? item.landed_usd)}</dd></div>
        </dl>
        {#if item.currency !== 'USD'}<p class="inline-note">Listed at {money(item.price, item.currency)}.</p>{/if}
        {#if ex?.cost?.fx_fallback}<p class="inline-note">The exchange rate is a fallback, so these figures may be off by a few percent.</p>{/if}
      {:else}
        <p class="quiet">No cost breakdown for this listing. Landed price is {usd(item.landed_usd)}.</p>
      {/if}
      {#if history.length >= 2}
        <div class="hist">
          <Sparkline values={history.map((h) => h.price_usd)} label={`Price history, ${history.length} changes`} width={120} height={32} />
          <p>{priceNote || 'Price has not changed.'}</p>
        </div>
      {/if}
    </section>

    <section class="sec" aria-labelledby="s-rank">
      <h3 id="s-rank">Why this rank</h3>
      {#if ex?.desirability}
        <p class="rankhead">
          Desirability <b class="tabnum">{Math.round(ex.desirability.score)}</b> of 100, tier {ex.desirability.tier}.
          {#if ex.desirability.ceiling_reason}<span class="quiet">{ex.desirability.ceiling_reason}</span>{/if}
        </p>
        {#if ex.desirability.factors?.length}
          <h4>What makes it desirable</h4>
          {#each ex.desirability.factors as f (f.k)}
            <Bar value={f.v} label={f.label} text={f.w !== undefined ? `${pct(f.v)}, weight ${pct(f.w)}` : pct(f.v)} />
          {/each}
        {/if}
      {:else}
        <p class="quiet">No desirability score for this listing.</p>
      {/if}
      {#if ex?.deal}
        <h4>What makes it a deal</h4>
        <p class="quiet">
          {ex.deal.discount !== null && ex.deal.discount !== undefined
            ? ex.deal.discount >= 0
              ? `${pct(ex.deal.discount)} under fair value.`
              : `${pct(-ex.deal.discount)} over fair value.`
            : ''}
          {#if ex.deal.risk !== null && ex.deal.risk !== undefined}Risk {pct(ex.deal.risk)}.{/if}
        </p>
        {#each ex.deal.factors ?? [] as f (f.k)}
          <Bar value={f.v} label={f.label} />
        {/each}
      {/if}
      {#if ex?.similarity && (ex.similarity.taste !== null || ex.similarity.junk !== null)}
        <h4>Likeness to what you have judged</h4>
        {#if ex.similarity.taste !== null && ex.similarity.taste !== undefined}<Bar value={ex.similarity.taste} label="Like listings you said Yes to" />{/if}
        {#if ex.similarity.junk !== null && ex.similarity.junk !== undefined}<Bar value={ex.similarity.junk} label="Like listings you said No to" />{/if}
      {/if}
      {#if ex?.ranker?.prob !== null && ex?.ranker?.prob !== undefined}
        <p class="inline-note">Ranker says {pct(ex.ranker.prob)} likely to interest you ({ex.ranker.model}).</p>
      {/if}
      {#if flags.length}
        <h4>Flags</h4>
        <ul class="flags">
          {#each flags as f (f.id)}
            <li><span class="hatch" aria-hidden="true"></span><span><b>{SEVERITY[f.severity] ?? 'Note'}.</b> {f.label}</span></li>
          {/each}
        </ul>
      {/if}
      {#if detail?.description}
        <details class="desc">
          <summary>Seller’s description</summary>
          <p>{detail.description}</p>
        </details>
      {/if}
    </section>
  {/if}

  {#snippet footer()}
    {#if item}
      <div class="acts">
        <button type="button" class="watch" aria-pressed={watchedOf(item)} onclick={() => toggleWatch(item)}>
          {watchedOf(item) ? 'Watching' : 'Watch'}
        </button>
        <button type="button" class="watch" aria-pressed={feedbackOf(item).includes('bought')} onclick={() => tapFeedback(item, 'bought')}>
          {feedbackOf(item).includes('bought') ? 'Bought' : 'I bought this'}
        </button>
      </div>
      <FeedbackStrip {item} />
    {/if}
  {/snippet}
</Sheet>

<style>
  .strip {
    display: flex;
    gap: 1px;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    background: var(--label);
    border-bottom: var(--rule-w) solid var(--ink);
    scrollbar-width: thin;
  }
  .slot {
    flex: 0 0 min(16rem, 72%);
    scroll-snap-align: start;
  }
  .pad {
    padding: var(--s-3) var(--gutter) var(--s-4);
  }
  .marks {
    display: flex;
    align-items: center;
    gap: var(--s-2);
    margin-bottom: var(--s-2);
  }
  .stamp {
    display: inline-flex;
    transform: rotate(-3deg);
  }
  .jp-pill {
    margin-left: auto;
    background: var(--ink);
    color: var(--paper);
    font-size: var(--t-small);
    font-weight: 700;
    padding: 3px var(--s-2);
    letter-spacing: 0.12em;
  }
  .brand {
    font-size: var(--t-lead);
    font-weight: 700;
    line-height: var(--lh-snug);
  }
  .era {
    font-size: var(--t-meta);
    color: var(--thread);
  }
  .orig {
    font-size: var(--t-small);
    margin-top: var(--s-2);
    overflow-wrap: anywhere;
  }
  .src {
    font-size: var(--t-small);
    color: var(--thread);
  }
  .big {
    display: flex;
    align-items: baseline;
    gap: var(--s-3);
    margin-top: var(--s-3);
  }
  .big b {
    font-size: var(--t-poster);
    white-space: nowrap;
  }
  .big span {
    font-size: var(--t-meta);
    color: var(--thread);
    line-height: 1.15;
  }
  .tone-deal b {
    color: var(--selvedge);
  }
  .tone-over b {
    color: var(--thread);
  }
  .price {
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .price s {
    font-weight: 400;
    color: var(--thread);
    margin-left: var(--s-2);
  }
  .flag {
    display: flex;
    gap: var(--s-2);
    font-size: var(--t-small);
    margin-top: var(--s-2);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-2);
    margin-top: var(--s-4);
  }
  .actions .btn {
    flex: 1 1 9rem;
  }

  .sec {
    padding: var(--s-4) var(--gutter) var(--s-6);
    border-top: var(--rule-w) solid var(--ink);
  }
  .sec h3 {
    font-stretch: var(--w-condensed);
    font-weight: 900;
    font-size: var(--t-head);
    line-height: var(--lh-snug);
    margin-bottom: var(--s-2);
  }
  .sec h4 {
    font-stretch: var(--w-condensed);
    font-weight: 700;
    font-size: var(--t-lead);
    margin: var(--s-4) 0 var(--s-1);
  }
  .ents > div {
    display: grid;
    grid-template-columns: 4.5rem 1fr;
    gap: var(--s-3);
    padding: var(--s-2) 0;
    border-bottom: var(--rule-w) solid var(--rule);
  }
  .ents dt {
    font-size: var(--t-small);
    color: var(--thread);
    padding-top: 2px;
  }
  .ents .name {
    font-weight: 700;
  }
  .cues {
    font-size: var(--t-small);
    color: var(--thread);
  }
  .quiet {
    color: var(--thread);
  }
  .seller {
    font-size: var(--t-small);
    color: var(--thread);
    margin-top: var(--s-3);
  }
  .lead {
    display: flex;
    align-items: baseline;
    gap: var(--s-2);
  }
  .lead .fair {
    font-size: 2.5rem;
  }
  .rangewrap {
    margin-top: var(--s-3);
  }
  .comps li {
    display: grid;
    grid-template-columns: 4.5rem 4.5rem 1fr;
    gap: var(--s-2);
    align-items: baseline;
    padding: var(--s-2) 0;
    border-bottom: var(--rule-w) solid var(--rule);
    font-size: var(--t-small);
  }
  .cp {
    font-weight: 700;
    font-size: var(--t-body);
  }
  .cd {
    color: var(--thread);
  }
  .ct {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .ledger > div {
    display: flex;
    justify-content: space-between;
    gap: var(--s-4);
    padding: var(--s-2) 0;
    border-bottom: var(--rule-w) solid var(--rule);
  }
  .ledger dd {
    font-variant-numeric: tabular-nums;
  }
  .ledger .total {
    font-weight: 800;
    border-bottom: 0;
    border-top: 2px solid var(--ink);
    margin-top: var(--s-1);
  }
  .hist {
    display: flex;
    align-items: center;
    gap: var(--s-3);
    margin-top: var(--s-3);
    font-size: var(--t-small);
    color: var(--thread);
  }
  .rankhead b {
    font-size: var(--t-lead);
  }
  .flags li {
    display: flex;
    gap: var(--s-2);
    padding: var(--s-1) 0;
    font-size: var(--t-meta);
  }
  .flags .hatch {
    margin-top: 3px;
  }
  .desc {
    margin-top: var(--s-4);
    font-size: var(--t-small);
  }
  .desc summary {
    min-height: var(--tap);
    display: flex;
    align-items: center;
    cursor: pointer;
    font-weight: 700;
  }
  .desc p {
    white-space: pre-wrap;
    color: var(--thread);
  }
  .acts {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .acts .watch + .watch {
    border-left: var(--rule-w) solid var(--rule);
  }
  .watch {
    display: block;
    width: 100%;
    min-height: var(--tap);
    font-stretch: var(--w-condensed);
    font-weight: 800;
    font-size: var(--t-lead);
    transition: background var(--t-fast), color var(--t-fast);
  }
  .watch[aria-pressed='true'] {
    background: var(--ink);
    color: var(--paper);
  }
</style>
