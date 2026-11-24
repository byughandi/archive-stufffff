<script lang="ts">
  import { usd } from './format';

  interface Props {
    p25: number;
    p75: number;
    median: number;
    /** This listing's landed price, when there is one. */
    landed?: number | null;
    /** Landed marker is red only when the price is under fair value in a way worth a stamp. */
    deal?: boolean;
  }
  let { p25, p75, median, landed = null, deal = false }: Props = $props();

  const W = 320;
  const padX = 14;
  const lo = $derived(Math.min(p25, landed ?? p25, median) * 0.82);
  const hi = $derived(Math.max(p75, landed ?? p75, median) * 1.12);
  const x = (v: number) => padX + ((v - lo) / (hi - lo || 1)) * (W - padX * 2);
  const landedX = $derived(landed !== null ? x(landed) : 0);
  const summary = $derived(
    `Sold comps: middle half from ${usd(p25)} to ${usd(p75)}, median ${usd(median)}.` + (landed !== null ? ` This listing lands at ${usd(landed)}.` : '')
  );
</script>

<svg viewBox="0 0 {W} 78" class="range" role="img" aria-label={summary}>
  <line x1={padX} x2={W - padX} y1="40" y2="40" stroke="var(--rule)" stroke-width="1" />
  <rect x={x(p25)} y="30" width={Math.max(2, x(p75) - x(p25))} height="20" fill="var(--label)" stroke="var(--ink)" stroke-width="1" />
  <line x1={x(median)} x2={x(median)} y1="24" y2="56" stroke="var(--ink)" stroke-width="2.5" />
  <text x={x(p25)} y="70" text-anchor="middle" class="t">{usd(p25)}</text>
  <text x={x(p75)} y="70" text-anchor="middle" class="t">{usd(p75)}</text>
  <text x={x(median)} y="16" text-anchor="middle" class="t b">Median {usd(median)}</text>
  {#if landed !== null}
    <path d="M{landedX} 52 l-6 11 h12 z" fill={deal ? 'var(--selvedge)' : 'var(--ink)'} />
    <line x1={landedX} x2={landedX} y1="26" y2="52" stroke={deal ? 'var(--selvedge)' : 'var(--ink)'} stroke-width="1.5" stroke-dasharray="2 2" />
  {/if}
</svg>
<p class="legend">
  <span><i class="k band"></i>Middle half of sold prices</span>
  <span><i class="k tick"></i>Median</span>
  {#if landed !== null}<span><i class="k mark" class:deal></i>This listing, landed {usd(landed)}</span>{/if}
</p>

<style>
  .range {
    display: block;
    width: 100%;
    max-width: 28rem;
    height: auto;
    font-family: var(--font);
  }
  .t {
    font-size: 11px;
    fill: var(--thread);
    font-variant-numeric: tabular-nums;
  }
  .t.b {
    fill: var(--ink);
    font-weight: 700;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-1) var(--s-4);
    font-size: var(--t-small);
    color: var(--thread);
    margin-top: var(--s-1);
  }
  .k {
    display: inline-block;
    vertical-align: -2px;
    margin-right: var(--s-1);
  }
  .band {
    width: 14px;
    height: 10px;
    background: var(--label);
    border: 1px solid var(--ink);
  }
  .tick {
    width: 3px;
    height: 12px;
    background: var(--ink);
  }
  .mark {
    width: 0;
    height: 0;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 10px solid var(--ink);
  }
  .mark.deal {
    border-bottom-color: var(--selvedge);
  }
</style>
