<script lang="ts">
  interface Props {
    src: string | null | undefined;
    alt?: string;
    /** CSS aspect-ratio, default 4 / 5 from the tokens. */
    ratio?: string;
    eager?: boolean;
    class?: string;
  }
  let { src, alt = '', ratio = 'var(--photo-ratio)', eager = false, class: cls = '' }: Props = $props();

  // Listing photos are hotlinked from the marketplace. If one will not load, the halftone stays.
  let failed = $state(false);
  $effect(() => {
    src;
    failed = false;
  });
</script>

<div class="thumb {cls}" style:aspect-ratio={ratio}>
  {#if src && !failed}
    <img
      {src}
      {alt}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      referrerpolicy="no-referrer"
      onerror={() => (failed = true)}
    />
  {/if}
</div>

<style>
  .thumb {
    position: relative;
    overflow: hidden;
    background: var(--label);
  }
  .thumb::before {
    content: '';
    position: absolute;
    inset: 0;
    background: var(--label) url('/art/halftone.svg');
  }
  img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  @media (prefers-color-scheme: dark) {
    .thumb::before {
      filter: invert(1);
    }
  }
</style>
