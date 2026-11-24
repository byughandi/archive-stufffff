import { api } from './api';
import { mine, ref, say, feedbackOf, watchedOf } from './state.svelte';
import type { FeedItem, Health, SizeProfile, Taxonomy } from './types';

let taxPromise: Promise<void> | null = null;
export function ensureTaxonomy(): Promise<void> {
  taxPromise ??= api<Taxonomy>('/api/taxonomy')
    .then((t) => {
      ref.taxonomy = t;
    })
    .catch(() => {
      taxPromise = null; // try again next time; names fall back to readable forms of the ids
    });
  return taxPromise;
}

export async function loadHealth(): Promise<Health | null> {
  try {
    const h = await api<Health>('/api/health');
    ref.health = h;
    return h;
  } catch {
    return null;
  }
}

export async function loadProfile(): Promise<SizeProfile | null> {
  try {
    const r = await api<{ size_profile: SizeProfile }>('/api/profile');
    ref.profile = { ...r.size_profile };
    return ref.profile;
  } catch {
    return null;
  }
}

/** Yes and No cancel each other out. */
const EXCLUSIVE: Record<string, string> = { up: 'down', down: 'up' };

/**
 * One tap on a feedback cell. The UI changes first; if the server says no, it changes back and
 * says so in plain words.
 */
export async function tapFeedback(item: Pick<FeedItem, 'listing_id' | 'my_feedback'>, kind: string) {
  const id = item.listing_id;
  const before = [...feedbackOf(item)];
  const on = before.includes(kind);
  let after = on ? before.filter((k) => k !== kind) : [...before, kind];
  const other = EXCLUSIVE[kind];
  const dropOther = !on && other && before.includes(other);
  if (dropOther) after = after.filter((k) => k !== other);
  mine[id] = { ...mine[id], fb: after };
  try {
    await api('/api/feedback', { method: 'POST', json: on ? { listing_id: id, kind, undo: true } : { listing_id: id, kind } });
  } catch (e) {
    mine[id] = { ...mine[id], fb: before };
    if ((e as { status?: number }).status === 401 || (e as { status?: number }).status === 503) return;
    say('Could not save that. Your answer was not recorded. Try again.');
  }
}

export async function toggleWatch(item: Pick<FeedItem, 'listing_id' | 'watched'>) {
  const id = item.listing_id;
  const before = watchedOf(item);
  mine[id] = { ...mine[id], watched: !before };
  try {
    await api(`/api/watchlist/${encodeURIComponent(id)}`, { method: before ? 'DELETE' : 'PUT' });
  } catch (e) {
    mine[id] = { ...mine[id], watched: before };
    if ((e as { status?: number }).status === 401 || (e as { status?: number }).status === 503) return;
    say(before ? 'Could not remove it from your watchlist. Try again.' : 'Could not add it to your watchlist. Try again.');
  }
}

/** Query-string for the feed, shared by the page, the filter sheet's count and saved-search links. */
export const FILTER_KEYS = [
  'brand',
  'era',
  'archetype',
  'size',
  'min_price',
  'max_price',
  'source',
  'region',
  'min_conf',
  'hide_suspicious',
  'sort',
  'q',
  'tier',
  'label'
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Partial<Record<FilterKey, string>>;

export function filtersFrom(params: { get(name: string): string | null }): Filters {
  const f: Filters = {};
  for (const k of FILTER_KEYS) {
    const v = params.get(k);
    if (v) f[k] = v;
  }
  return f;
}
