<script lang="ts">
  /** A labelled 0 to 1 bar: confidence, desirability factors, deal factors. */
  interface Props {
    value: number;
    label: string;
    /** Text shown at the right, default is the percentage. */
    text?: string;
    note?: string;
  }
  let { value, label, text, note }: Props = $props();
  const v = $derived(Math.max(0, Math.min(1, value)));
</script>

<div class="bar">
  <div class="row">
    <span class="l">{label}</span>
    <span class="t tabnum">{text ?? `${Math.round(v * 100)}%`}</span>
  </div>
  <div class="track" role="meter" aria-label={label} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(v * 100)} aria-valuetext={text}>
    <div class="fill" style:width="{v * 100}%"></div>
  </div>
  {#if note}<p class="note">{note}</p>{/if}
</div>

<style>
  .bar {
    padding: var(--s-2) 0;
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: var(--s-3);
    font-size: var(--t-meta);
  }
  .t {
    color: var(--thread);
    white-space: nowrap;
  }
  .track {
    height: 6px;
    margin-top: var(--s-1);
    background: var(--label);
    border: var(--rule-w) solid var(--rule);
  }
  .fill {
    height: 100%;
    background: var(--ink);
  }
  .note {
    font-size: var(--t-small);
    color: var(--thread);
    margin-top: var(--s-1);
  }
</style>
