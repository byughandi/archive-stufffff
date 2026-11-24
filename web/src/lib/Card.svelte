<script lang="ts">
  import Art from './Art.svelte';
  import Thumb from './Thumb.svelte';
  import FeedbackStrip from './FeedbackStrip.svelte';
  import { archetypeName, brandName, eraLine } from './names';
  import { ago, bidsText, countdown, figureOf, sourceName, usd } from './format';
  import { flagLines, prevLanded, sizeText, stampOf, TIER_ART } from './deal';
  import type { FeedItem } from './types';

  interface Props {
    item: FeedItem;
    density: 'list' | 'grid';
    onopen: (item: FeedItem, opener: HTMLElement) => void;
  }
  let { item, density, onopen }: Props = $props();

  const stamp = $derived(stampOf(item));
  const tier = $derived(TIER_ART[item.tier] ?? TIER_ART.C);
  const fig = $derived(figureOf(item));
  const flags = $derived(flagLines(item));
  const old = $derived(prevLanded(item));
  const steal = $derived(item.deal_label === 'steal' && item.tier !== 'X');
  const suspicious = $derived(item.deal_label === 'suspicious');
  const when = $derived(
    item.is_auction && item.auction_end_at
      ? `${countdown(item.auction_end_at)}, ${bidsText(item.bids)}.`
      : `${ago(item.listed_at)}.`
  );
  const fair = $derived(
    item.fair_value_usd
      ? `Fair ${usd(item.fair_value_usd)} from ${item.comp_count ?? 0} sold${item.value_conf === 'low' ? ', low confidence' : ''}.`
      : item.tier === 'X'
        ? ''
        : 'No sold comps to price it from.'
  );

  // The deal stamp presses in once, the first time the card scrolls into view.
  let seen = $state(false);
  function inview(node: HTMLElement) {
    if (typeof IntersectionObserver === 'undefined') {
      seen = true;
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          seen = true;
          io.disconnect();
        }
      },
      { threshold: 0.4 }
    );
    io.observe(node);
    return { destroy: () => io.disconnect() };
  }
</script>

<article class="card {density}" class:steal class:suspicious class:seen class:rejected={item.tier === 'X'} use:inview>
  {#if density === 'list'}
    <div class="top">
      <div class="photo">
        <Thumb src={item.image_url} />
        {#if item.region === 'JP'}<span class="jp" aria-hidden="true">日本</span>{/if}
      </div>
      <div class="cap">
        <div class="marks">
          <Art name={tier.art} label={tier.label} h="30px" />
          {#if stamp}<span class="stamp"><Art name={stamp.art} label={stamp.label} h="24px" /></span>{/if}
        </div>
        <h3 class="brand">
          <button type="button" class="open" onclick={(e) => onopen(item, e.currentTarget)}>
            {brandName(item.brand)}<span class="sr-only">, {item.region === 'JP' ? 'listed in Japan, ' : ''}open details</span>
          </button>
        </h3>
        <p class="era">{eraLine(item)}</p>
        {#each flags.slice(0, 2) as f (f)}
          <p class="flag"><span class="hatch" aria-hidden="true"></span>{f}</p>
        {/each}
        <div class="disc tone-{fig.tone}">
          <b class="figure">{fig.text}</b>
          <span>{fig.caption[0]}<br />{fig.caption[1]}</span>
        </div>
        {#if item.tier !== 'X'}
          <p class="price">{usd(item.landed_usd)} landed{#if old}<s><span class="sr-only">was </span>{usd(old)}</s>{/if}</p>
        {/if}
        <p class="fair">{fair} {sizeText(item.size_norm)}</p>
      </div>
      <p class="title"><small>{sourceName(item.source)}, {when}</small> {item.title}</p>
    </div>
    <FeedbackStrip {item} />
  {:else}
    <div class="gtop">
      <div class="photo">
        <Thumb src={item.image_url} />
        {#if item.region === 'JP'}<span class="jp" aria-hidden="true">日本</span>{/if}
        <div class="marks">
          <Art name={tier.art} label={tier.label} h="28px" />
          {#if stamp}<span class="stamp"><Art name={stamp.art} label={stamp.label} h="22px" /></span>{/if}
        </div>
      </div>
      <div class="cap">
        <h3 class="brand">
          <button type="button" class="open" onclick={(e) => onopen(item, e.currentTarget)}>
            {brandName(item.brand)}<span class="sr-only">, {archetypeName(item.archetype)}, open details</span>
          </button>
        </h3>
        <div class="disc tone-{fig.tone}">
          <b class="figure">{fig.text}</b>
        </div>
        <p class="price">
          {#if fig.tone === 'landed'}no fair value yet{:else}{usd(item.landed_usd)} landed{/if}{#if old}<s><span class="sr-only">was </span>{usd(old)}</s>{/if}
        </p>
      </div>
    </div>
  {/if}
</article>

<style>
  .card {
    position: relative;
    border-bottom: var(--rule-w) solid var(--ink);
    background: var(--paper);
    content-visibility: auto;
    contain-intrinsic-size: auto 520px;
  }
  .card.steal {
    border-left: var(--selvedge-w) solid var(--selvedge);
  }

  /* ---------------------------------------------------------------- list */
  .top {
    position: relative;
    display: grid;
    grid-template-columns: 42% 1fr;
  }
  .photo {
    position: relative;
    min-width: 0;
  }
  .jp {
    position: absolute;
    top: 0;
    right: 0;
    writing-mode: vertical-rl;
    background: var(--ink);
    color: var(--paper);
    font-size: var(--t-small);
    font-weight: 700;
    padding: var(--s-2) 5px;
    letter-spacing: 0.12em;
    line-height: 1;
    white-space: nowrap;
    overflow-wrap: normal;
  }
  .cap {
    padding: var(--s-2) var(--gutter);
    display: flex;
    flex-direction: column;
    min-width: 0;
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
  .seen .stamp {
    animation: press var(--t-press) var(--ease) both;
  }
  @keyframes press {
    from {
      transform: rotate(-3deg) scale(1.12);
    }
    to {
      transform: rotate(-3deg) scale(1);
    }
  }
  .brand {
    font-size: var(--t-lead);
    font-weight: 700;
    line-height: var(--lh-snug);
  }
  /* The whole photo and caption area is one tap target. The feedback strip stays separate. */
  .open {
    text-align: left;
    font: inherit;
    color: inherit;
  }
  .open::after {
    content: '';
    position: absolute;
    inset: 0;
  }
  .open:focus-visible {
    outline: none;
  }
  .open:focus-visible::after {
    outline: 3px solid var(--ink);
    outline-offset: -3px;
  }
  .era {
    font-size: var(--t-meta);
    color: var(--thread);
    line-height: var(--lh-snug);
    margin-top: 2px;
  }
  .flag {
    display: flex;
    gap: var(--s-2);
    align-items: flex-start;
    font-size: var(--t-small);
    line-height: var(--lh-snug);
    margin-top: var(--s-1);
  }
  .flag .hatch {
    margin-top: 1px;
  }
  .disc {
    display: flex;
    align-items: baseline;
    gap: var(--s-2);
    margin-top: auto;
    padding-top: var(--s-2);
  }
  .disc b {
    font-size: var(--t-figure);
    white-space: nowrap;
  }
  .disc span {
    font-size: var(--t-small);
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
    font-size: var(--t-body);
    font-weight: 700;
    margin-top: var(--s-1);
    font-variant-numeric: tabular-nums;
  }
  .price s {
    font-weight: 400;
    color: var(--thread);
    margin-left: var(--s-2);
  }
  .fair {
    font-size: var(--t-small);
    color: var(--thread);
  }
  .title {
    grid-column: 1 / -1;
    font-size: var(--t-small);
    padding: var(--s-2) var(--gutter);
    border-top: var(--rule-w) solid var(--rule);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .title small {
    color: var(--thread);
    font-size: inherit;
  }

  /* ---------------------------------------------------------------- grid */
  .card.grid {
    border-right: var(--rule-w) solid var(--rule);
  }
  .gtop {
    position: relative;
    display: flex;
    flex-direction: column;
  }
  .grid .photo {
    overflow: visible;
  }
  .grid .photo :global(.thumb) {
    overflow: hidden;
  }
  .grid .marks {
    position: absolute;
    left: var(--s-2);
    bottom: 0;
    margin: 0;
    transform: translateY(50%);
    z-index: 1;
    pointer-events: none;
  }
  .grid .cap {
    padding: calc(var(--s-3) + 8px) var(--s-2) var(--s-3);
  }
  .grid .disc {
    padding-top: var(--s-1);
    margin-top: 0;
  }
  .grid .disc b {
    font-size: var(--t-figure);
  }
  .grid .brand {
    font-size: var(--t-body);
  }
  .grid .price {
    font-size: var(--t-small);
    margin-top: 0;
  }
  .grid .open::after {
    inset: 0 0 0 0;
  }
</style>
