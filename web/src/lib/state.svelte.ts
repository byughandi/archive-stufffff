import type { FeedItem, FeedbackKind, Health, SizeProfile, Taxonomy } from './types';

/** Set by api() when the API answers 401 or 503. */
export const auth = $state({ signedOut: false });

/** One shared clock so relative times and countdowns re-render without a timer per card. */
export const clock = $state({ now: Math.floor(Date.now() / 1000) });
if (typeof window !== 'undefined') {
  setInterval(() => (clock.now = Math.floor(Date.now() / 1000)), 20_000);
}

export const toast = $state({ message: '' });
let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function say(message: string) {
  toast.message = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.message = ''), 5000);
}

// ---------------------------------------------------------------- density
export type Density = 'list' | 'grid';
const DENSITY_KEY = 'grail-radar:density';
function readDensity(): Density {
  try {
    return localStorage.getItem(DENSITY_KEY) === 'grid' ? 'grid' : 'list';
  } catch {
    return 'list';
  }
}
export const prefs = $state({ density: readDensity() });
export function setDensity(d: Density) {
  prefs.density = d;
  try {
    localStorage.setItem(DENSITY_KEY, d);
  } catch {
    /* private mode: keep it for this visit */
  }
}

// ---------------------------------------------------------------- shared reference data
export const ref = $state<{
  taxonomy: Taxonomy | null;
  health: Health | null;
  profile: SizeProfile | null;
}>({ taxonomy: null, health: null, profile: null });

/** Per-listing answers the user has just given. They win over what the feed said when it loaded. */
export const mine = $state<Record<string, { fb?: string[]; watched?: boolean }>>({});

export function feedbackOf(item: Pick<FeedItem, 'listing_id' | 'my_feedback'>): string[] {
  return mine[item.listing_id]?.fb ?? item.my_feedback ?? [];
}
export function watchedOf(item: Pick<FeedItem, 'listing_id' | 'watched'>): boolean {
  return mine[item.listing_id]?.watched ?? item.watched ?? false;
}

export const FEEDBACK_CELLS: { kind: FeedbackKind; label: string }[] = [
  { kind: 'up', label: 'Yes' },
  { kind: 'down', label: 'No' },
  { kind: 'cop', label: 'Would cop' },
  { kind: 'fake', label: 'Fake' },
  { kind: 'wrong_era', label: 'Wrong era' },
  { kind: 'wrong_brand', label: 'Wrong brand' }
];

// ---------------------------------------------------------------- shared UI state
/** The header's Search and Filter buttons live in the layout; the feed page answers them. */
export const ui = $state({ filterOpen: false, searchOpen: false });

/** The feed row a drawer was opened from, so it can show something before its own fetch returns. */
export const seed = $state<{ item: FeedItem | null }>({ item: null });
