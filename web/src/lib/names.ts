import { ref } from './state.svelte';
import type { FeedItem, TaxEntity } from './types';

function humanize(id: string): string {
  const last = id.split('__').pop() || id;
  return last.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
function find(list: TaxEntity[] | undefined, id: string | null | undefined): TaxEntity | undefined {
  if (!id || !list) return undefined;
  return list.find((e) => e.id === id);
}
export function brandName(id: string | null | undefined): string {
  if (!id) return 'Unknown brand';
  return find(ref.taxonomy?.brands, id)?.name ?? humanize(id);
}
export function eraName(id: string | null | undefined): string {
  if (!id) return '';
  return find(ref.taxonomy?.eras, id)?.name ?? humanize(id);
}
export function archetypeName(id: string | null | undefined): string {
  if (!id) return '';
  return find(ref.taxonomy?.archetypes, id)?.name ?? humanize(id);
}
/** Season name from the taxonomy ("AW07 Navigate"); falls back to the code inside the id ("AW13"). */
export function seasonName(id: string | null | undefined): string {
  if (!id) return '';
  const hit = find(ref.taxonomy?.seasons, id);
  if (hit) return hit.name;
  const code = id.split('__').pop() || id;
  return /^(aw|ss|fw)\d\d/i.test(code) ? code.toUpperCase() : humanize(id);
}
/** "Brand, Designer" for places where an era is shown by itself. */
export function eraWithBrand(id: string): string {
  const e = find(ref.taxonomy?.eras, id);
  if (!e) return humanize(id);
  const b = brandName(e.parent);
  const label = e.label || e.name;
  return e.name === b ? b : `${b}, ${label}`;
}
const lcfirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** "Hedi Slimane, AW13, biker / moto jacket" */
export function eraLine(item: Pick<FeedItem, 'era' | 'season' | 'archetype'> & { brand?: string | null }): string {
  const era = item.era ? eraName(item.era) : 'Era unconfirmed';
  // Some eras carry the brand's own name; saying it twice adds nothing.
  const parts = item.era && item.brand && era === brandName(item.brand) ? [] : [era];
  if (item.season) parts.push(seasonCode(item.season));
  if (item.archetype) parts.push(lcfirst(archetypeName(item.archetype)));
  return parts.join(', ') || era;
}

/** Era with its years, for menus where two eras of one brand must be told apart. */
export function eraLabel(id: string | null | undefined): string {
  if (!id) return '';
  const e = find(ref.taxonomy?.eras, id);
  return e ? e.label || e.name : humanize(id);
}

/** Just the season code ("AW07") for tight spaces; the full name belongs in the drawer. */
export function seasonCode(id: string | null | undefined): string {
  if (!id) return '';
  const hit = find(ref.taxonomy?.seasons, id);
  if (hit?.code) return hit.code;
  const code = id.split('__').pop() || id;
  return /^(aw|ss|fw)\d\d/i.test(code) ? code.toUpperCase() : seasonName(id);
}
