<script lang="ts">
  interface Props {
    values: number[];
    /** Read out by screen readers in place of the picture. */
    label: string;
    width?: number;
    height?: number;
    /** Fixed scale, so two sparklines can be compared. */
    min?: number;
    max?: number;
  }
  let { values, label, width = 88, height = 28, min, max }: Props = $props();

  const pad = 3;
  const pts = $derived.by(() => {
    if (values.length < 2) return [];
    const lo = min ?? Math.min(...values);
    const hi = max ?? Math.max(...values);
    const span = hi - lo || 1;
    return values.map((v, i) => [pad + (i * (width - pad * 2)) / (values.length - 1), height - pad - ((v - lo) / span) * (height - pad * 2)]);
  });
  const d = $derived(pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(''));
</script>

<svg {width} {height} viewBox="0 0 {width} {height}" role="img" aria-label={label}>
  {#if pts.length}
    <line x1={pad} x2={width - pad} y1={height - 0.5} y2={height - 0.5} stroke="var(--rule)" stroke-width="1" />
    <path {d} fill="none" stroke="var(--ink)" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
    <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.4" fill="var(--ink)" />
  {:else}
    <line x1={pad} x2={width - pad} y1={height / 2} y2={height / 2} stroke="var(--rule)" stroke-width="1" stroke-dasharray="3 3" />
  {/if}
</svg>
