import { clock } from './state.svelte';
import type { FeedItem } from './types';

const MINUS = '−';

/** USD with no cents from $100 up. */
export function usd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '';
  const abs = Math.abs(n);
  const s =
    abs >= 100
      ? Math.round(abs).toLocaleString('en-US')
      : abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? MINUS : ''}$${s}`;
}

/** Local currency for the original price ("¥70,500"). */
export function money(n: number, currency: string): string {
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      maximumFractionDigits: currency === 'JPY' ? 0 : 2
    }).format(n);
  } catch {
    return `${Math.round(n).toLocaleString('en-US')} ${currency}`;
  }
}

export function pct(f: number | null | undefined): string {
  return f === null || f === undefined ? '' : `${Math.round(f * 100)}%`;
}

/** "12 min ago", "3 h ago", "2 d ago", then a date. */
export function ago(at: number | null | undefined, now = clock.now): string {
  if (!at) return '';
  const s = Math.max(0, now - at);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return dateShort(at, now);
}

export function dateShort(at: number, now = clock.now): string {
  const d = new Date(at * 1000);
  const sameYear = d.getFullYear() === new Date(now * 1000).getFullYear();
  return d.toLocaleDateString(
    'en-US',
    sameYear ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' }
  );
}

/** "Tuesday 14:10" */
export function weekdayTime(at: number): string {
  const d = new Date(at * 1000);
  const day = d.toLocaleDateString('en-US', { weekday: 'long' });
  const t = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${day} ${t}`;
}

/** "ends in 3 h 12 min" */
export function countdown(end: number | null | undefined, now = clock.now): string {
  if (!end) return '';
  const s = end - now;
  if (s <= 0) return 'ended';
  if (s < 60) return 'ends in under a minute';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `ends in ${d} d${h ? ` ${h} h` : ''}`;
  if (h > 0) return `ends in ${h} h${m ? ` ${m} min` : ''}`;
  return `ends in ${m} min`;
}

export function bidsText(bids: number | null | undefined): string {
  if (!bids) return 'no bids';
  return bids === 1 ? '1 bid' : `${bids} bids`;
}

/** The figure on a card. Discount positive means under fair value. */
export interface Figure {
  text: string;
  caption: string[];
  tone: 'deal' | 'plain' | 'over' | 'landed';
}
export function figureOf(item: FeedItem): Figure {
  const d = item.discount;
  if (item.fair_value_usd && d !== null && d !== undefined) {
    const n = Math.round(Math.abs(d) * 100);
    if (d < 0) return { text: `+${n}%`, caption: ['over', 'fair value'], tone: 'over' };
    const deal = item.deal_label === 'steal' || item.deal_label === 'great';
    return { text: `${n === 0 ? '' : MINUS}${n}%`, caption: ['under', 'fair value'], tone: deal ? 'deal' : 'plain' };
  }
  return { text: usd(item.landed_usd), caption: ['landed,', 'no fair value yet'], tone: 'landed' };
}

export const SOURCE_NAMES: Record<string, string> = {
  grailed: 'Grailed',
  mercari_us: 'Mercari US',
  mercari_jp: 'Mercari Japan',
  yahoo_jp: 'Yahoo Auctions Japan',
  ebay: 'eBay',
  vestiaire: 'Vestiaire Collective'
};
export function sourceName(id: string): string {
  if (SOURCE_NAMES[id]) return SOURCE_NAMES[id];
  if (id.startsWith('shop:')) {
    const slug = id.slice(5).replace(/[-_]+/g, ' ');
    return slug.charAt(0).toUpperCase() + slug.slice(1);
  }
  return id.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}
export const REGION_NAMES: Record<string, string> = { US: 'United States', JP: 'Japan', EU: 'Europe' };

export const FLAG_FALLBACK: Record<string, string> = {
  needs_tag_pics: 'Era unconfirmed. Ask for tag photos.',
  size_unknown: 'Size not stated. Ask the seller.',
  condition_vague: 'Condition is vague. Ask for close-ups.',
  new_seller: 'Seller has few sales.',
  price_below_floor: 'Price is far below the floor for this piece. Check authenticity.',
  stock_photos: 'Photos look copied from elsewhere.',
  fx_fallback: 'Exchange rate is a fallback. Price may be off by a few percent.'
};

export const CONF_WORD: Record<string, string> = { high: 'High', med: 'Medium', low: 'Low', none: 'No' };
export const LEVEL_WORDS: Record<string, string> = {
  season: 'Same season',
  era_archetype: 'Same era and piece type',
  brand_archetype: 'Same brand and piece type',
  brand: 'Same brand only',
  price_band: 'Typical price for this kind of piece',
  none: 'No match'
};
export const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Best first' },
  { value: 'newest', label: 'Newest' },
  { value: 'discount', label: 'Biggest discount' },
  { value: 'price_asc', label: 'Price, low to high' },
  { value: 'price_desc', label: 'Price, high to low' },
  { value: 'ending', label: 'Ending soonest' }
];
