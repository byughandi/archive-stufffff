<script lang="ts">
  interface Props {
    checked: boolean;
    label: string;
    onchange: (next: boolean) => void;
    disabled?: boolean;
  }
  let { checked, label, onchange, disabled = false }: Props = $props();
</script>

<button type="button" role="switch" class="sw" aria-checked={checked} aria-label={label} {disabled} onclick={() => onchange(!checked)}>
  <span class="track" aria-hidden="true"><span class="knob"></span></span>
  <span class="word" aria-hidden="true">{checked ? 'On' : 'Off'}</span>
</button>

<style>
  .sw {
    display: inline-flex;
    align-items: center;
    gap: var(--s-2);
    min-height: var(--tap);
    min-width: var(--tap);
    font-stretch: var(--w-condensed);
    font-weight: 700;
    font-size: var(--t-lead);
  }
  .track {
    position: relative;
    width: 3rem;
    height: 1.625rem;
    border: 2px solid var(--ink);
    background: var(--paper);
    transition: background var(--t-fast);
  }
  .knob {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 1.125rem;
    height: 1.125rem;
    background: var(--ink);
    transition: transform var(--t-fast), background var(--t-fast);
  }
  [aria-checked='true'] .track {
    background: var(--ink);
  }
  [aria-checked='true'] .knob {
    transform: translateX(1.375rem);
    background: var(--paper);
  }
  .word {
    min-width: 1.75rem;
  }
  .sw:disabled {
    opacity: 0.5;
  }
</style>
