<script lang="ts" module>
  let counter = 0;
</script>

<script lang="ts">
  import { ART } from './art.generated';

  interface Props {
    name: string;
    /** Replaces the label baked into the art. */
    label?: string;
    /** Decorative art is hidden from screen readers. */
    decorative?: boolean;
    class?: string;
    /** CSS height, e.g. "24px". Width follows the art's aspect ratio. */
    h?: string;
  }
  let { name, label, decorative = false, class: cls = '', h }: Props = $props();

  // Each instance gets its own filter and pattern ids, so stamps never borrow each other's.
  const uid = ++counter;
  const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  const svg = $derived.by(() => {
    let s = (ART[name] ?? '').replaceAll('__ID__', String(uid));
    if (reduced) s = s.replace(/<animate(Transform)?\b[^>]*\/>/g, '');
    if (decorative) {
      s = s.replace(/ role="img" aria-label="[^"]*"/, ' aria-hidden="true" focusable="false"').replace(/<title>.*?<\/title>/, '');
    } else if (label) {
      s = s.replace(/aria-label="[^"]*"/, `aria-label="${label}"`).replace(/<title>.*?<\/title>/, `<title>${label}</title>`);
    }
    return s;
  });
</script>

<span class="art {cls}" style:height={h}>{@html svg}</span>

<style>
  .art {
    display: inline-block;
    line-height: 0;
    flex: none;
  }
  .art :global(svg) {
    display: block;
    height: 100%;
    width: auto;
    max-width: 100%;
  }
</style>
