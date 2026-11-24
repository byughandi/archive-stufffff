import { FLAG_FALLBACK } from './format';
import type { FeedItem } from './types';

export const STAMP_ART: Record<string, { art: string; label: string }> = {
  steal: { art: 'stamp-steal', label: 'Steal' },
  great: { art: 'stamp-great', label: 'Great' },
  good: { art: 'stamp-good', label: 'Good' },
  fair: { art: 'stamp-fair', label: 'Fair' },
  overpriced: { art: 'stamp-overpriced', label: 'Overpriced' },
  suspicious: { art: 'stamp-suspicious', label: 'Suspicious' },
  unknown: { art: 'stamp-unknown', label: 'No comps' }
};

export function stampOf(item: Pick<FeedItem, 'deal_label' | 'tier'>) {
  if (item.tier === 'X') return null;
  return STAMP_ART[item.deal_label ?? 'unknown'] ?? STAMP_ART.unknown;
}

export const TIER_ART: Record<string, { art: string; label: string }> = {
  S: { art: 'tier-s', label: 'S tier: grail' },
  A: { art: 'tier-a', label: 'A tier: strong' },
  B: { art: 'tier-b', label: 'B tier: decent' },
  C: { art: 'tier-c', label: 'C tier: filler' },
  X: { art: 'tier-x', label: 'Rejected' }
};

function sentence(id: string): string {
  const s = id.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1) + '.';
}

/** Flag lines for a card. The feed only carries flag ids, so the wording lives here. */
export function flagLines(item: Pick<FeedItem, 'flags' | 'reject_reason' | 'tier'>): string[] {
  if (item.tier === 'X') return item.reject_reason ? [item.reject_reason] : [];
  return (item.flags ?? []).map((id) => FLAG_FALLBACK[id] ?? sentence(id));
}

/** The old price, put on the same footing as "landed": same fees and shipping, earlier item price. */
export function prevLanded(item: Pick<FeedItem, 'prev_price_usd' | 'price_usd' | 'landed_usd'>): number | null {
  if (!item.prev_price_usd || item.prev_price_usd <= item.price_usd) return null;
  return item.prev_price_usd + (item.landed_usd - item.price_usd);
}

export function sizeText(size: string | null | undefined): string {
  return size ? `Size ${size}.` : '';
}
