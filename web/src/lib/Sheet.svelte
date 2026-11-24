<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    open: boolean;
    /** Accessible name of the dialog. */
    label: string;
    /** Visible heading in the sheet's header, if any. */
    title?: string;
    onclose: () => void;
    tall?: boolean;
    children: Snippet;
    footer?: Snippet;
  }
  let { open, label, title, onclose, tall = false, children, footer }: Props = $props();

  let mounted = $state(false);
  let closing = $state(false);
  let dialog = $state<HTMLElement>();
  let opener: HTMLElement | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function sheetMs(): number {
    const raw = getComputedStyle(document.documentElement).getPropertyValue('--t-sheet').trim();
    const n = parseFloat(raw);
    return Number.isFinite(n) ? n : 280;
  }
  const appRoot = () => document.getElementById('app');

  function lock() {
    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    const root = appRoot();
    if (root) {
      root.setAttribute('inert', '');
      root.setAttribute('aria-hidden', 'true');
    }
  }
  function unlock() {
    document.documentElement.style.overflow = '';
    document.body.style.overflow = '';
    const root = appRoot();
    if (root) {
      root.removeAttribute('inert');
      root.removeAttribute('aria-hidden');
    }
  }

  $effect(() => {
    if (open) {
      clearTimeout(timer);
      if (!mounted) {
        opener = document.activeElement as HTMLElement | null;
        lock();
      }
      mounted = true;
      closing = false;
    } else if (mounted) {
      closing = true;
      unlock();
      const back = opener;
      timer = setTimeout(() => {
        mounted = false;
        closing = false;
        // Return focus to what opened the sheet, if it is still on the page.
        if (back && document.contains(back)) back.focus({ preventScroll: true });
      }, sheetMs());
    }
  });

  $effect(() => {
    if (mounted && dialog && open) {
      const target = dialog.querySelector<HTMLElement>('[data-autofocus]') ?? dialog.querySelector<HTMLElement>('.close') ?? dialog;
      target.focus({ preventScroll: true });
    }
  });

  $effect(() => () => {
    clearTimeout(timer);
    unlock();
  });

  const FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onclose();
      return;
    }
    if (e.key !== 'Tab' || !dialog) return;
    const items = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!items.length) {
      e.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === dialog)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

{#if mounted}
  <div class="scrim" class:closing role="presentation" onclick={onclose}></div>
  <div
    class="sheet"
    class:tall
    class:closing
    role="dialog"
    aria-modal="true"
    aria-label={label}
    tabindex="-1"
    bind:this={dialog}
    {onkeydown}
  >
    <header class="sh">
      {#if title}<h2 class="sh-title">{title}</h2>{:else}<span></span>{/if}
      <button type="button" class="close" onclick={onclose}>Close</button>
    </header>
    <div class="body">{@render children()}</div>
    {#if footer}<div class="foot">{@render footer()}</div>{/if}
  </div>
{/if}

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.45);
    z-index: 40;
    animation: fade var(--t-sheet) var(--ease) both;
  }
  .scrim.closing {
    animation: fade-out var(--t-sheet) var(--ease) both;
  }
  .sheet {
    position: fixed;
    z-index: 41;
    left: 0;
    right: 0;
    bottom: 0;
    max-height: 92dvh;
    display: flex;
    flex-direction: column;
    background: var(--paper);
    color: var(--ink);
    border-top: 2px solid var(--ink);
    animation: rise var(--t-sheet) var(--ease) both;
    outline: none;
  }
  .sheet.tall {
    height: 92dvh;
  }
  .sheet.closing {
    animation: drop var(--t-sheet) var(--ease) both;
  }
  .sh {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-3);
    padding: 0 0 0 var(--gutter);
    border-bottom: var(--rule-w) solid var(--rule);
    flex: none;
  }
  .sh-title {
    font-stretch: var(--w-condensed);
    font-weight: 900;
    font-size: var(--t-head);
    line-height: 1;
  }
  .close {
    min-height: var(--tap);
    min-width: var(--tap);
    padding: 0 var(--gutter);
    margin-left: auto;
    font-stretch: var(--w-condensed);
    font-weight: 700;
    font-size: var(--t-lead);
  }
  .body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
  }
  .foot {
    flex: none;
    border-top: var(--rule-w) solid var(--ink);
    background: var(--paper);
    padding-bottom: env(safe-area-inset-bottom);
  }

  @media (min-width: 900px) {
    .sheet,
    .sheet.tall {
      left: auto;
      top: 0;
      bottom: 0;
      height: auto;
      max-height: none;
      width: var(--sheet-max);
      border-top: 0;
      border-left: 2px solid var(--ink);
      animation-name: slide-in;
    }
    .sheet.closing {
      animation-name: slide-out;
    }
  }

  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  @keyframes fade-out {
    to {
      opacity: 0;
    }
  }
  @keyframes rise {
    from {
      transform: translateY(100%);
    }
  }
  @keyframes drop {
    to {
      transform: translateY(100%);
    }
  }
  @keyframes slide-in {
    from {
      transform: translateX(100%);
    }
  }
  @keyframes slide-out {
    to {
      transform: translateX(100%);
    }
  }
</style>
