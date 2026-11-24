import { goto } from '$app/navigation';
import { seed } from './state.svelte';
import type { FeedItem } from './types';

let pushed = false;

/** The drawer is the `l` query parameter, so alerts can link straight to a listing. */
export function openListing(item: FeedItem) {
  seed.item = item;
  const u = new URL(location.href);
  u.searchParams.set('l', item.listing_id);
  pushed = true;
  goto(u.pathname + u.search, { reset: false });
}

export function closeListing() {
  if (pushed) {
    pushed = false;
    history.back();
    return;
  }
  const u = new URL(location.href);
  u.searchParams.delete('l');
  goto(u.pathname + u.search, { replace: true, reset: false });
}

/** Browser Back closed the drawer on its own. */
export function drawerGone() {
  pushed = false;
}

/** Set one or more query parameters on the current page (empty values remove them). */
export function setParams(changes: Record<string, string | undefined>, opts: { replace?: boolean } = {}) {
  const u = new URL(location.href);
  for (const [k, v] of Object.entries(changes)) {
    if (v) u.searchParams.set(k, v);
    else u.searchParams.delete(k);
  }
  goto(u.pathname + u.search, { replace: opts.replace ?? false, reset: false });
}
