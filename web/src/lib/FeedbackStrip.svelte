<script lang="ts">
  import { feedbackOf, FEEDBACK_CELLS } from './state.svelte';
  import { tapFeedback } from './data';
  import type { FeedItem } from './types';

  let { item }: { item: Pick<FeedItem, 'listing_id' | 'my_feedback'> } = $props();
  const pressed = $derived(feedbackOf(item));
</script>

<div class="fb" role="group" aria-label="Your verdict on this listing">
  {#each FEEDBACK_CELLS as cell (cell.kind)}
    <button type="button" aria-pressed={pressed.includes(cell.kind)} onclick={() => tapFeedback(item, cell.kind)}>
      {cell.label}
    </button>
  {/each}
</div>

<style>
  .fb {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    border-top: var(--rule-w) solid var(--rule);
  }
  button {
    min-height: var(--tap);
    font-stretch: var(--w-narrow);
    font-size: var(--t-small);
    font-weight: 600;
    border-right: var(--rule-w) solid var(--rule);
    line-height: 1.1;
    padding: 0 2px;
    transition: background var(--t-fast), color var(--t-fast);
  }
  button:last-child {
    border-right: 0;
  }
  button[aria-pressed='true'] {
    background: var(--ink);
    color: var(--paper);
  }
  @media (max-width: 380px) {
    button {
      font-size: var(--t-micro);
    }
  }
</style>
