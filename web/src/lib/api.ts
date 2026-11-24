import { auth } from './state.svelte';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Plain fetch against the same origin. 401 and 503 mean Cloudflare Access is not letting us in. */
export async function api<T>(path: string, init: RequestInit & { json?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const { json, ...rest } = init;
  const headers: Record<string, string> = { accept: 'application/json' };
  if (json !== undefined) {
    headers['content-type'] = 'application/json';
    rest.body = JSON.stringify(json);
  }
  let res: Response;
  try {
    res = await fetch(path, { ...rest, headers: { ...headers, ...(rest.headers as Record<string, string>) } });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError(0, 'Could not reach Grail Radar. Check your connection and try again.');
  }
  if (res.status === 401 || res.status === 503) {
    auth.signedOut = true;
    throw new ApiError(res.status, 'You are signed out. Reload to sign in.');
  }
  // Cloudflare Access can answer an expired session with an HTML login page.
  const type = res.headers.get('content-type') || '';
  if (!type.includes('json')) {
    if (res.redirected || res.type === 'opaqueredirect') {
      auth.signedOut = true;
      throw new ApiError(401, 'You are signed out. Reload to sign in.');
    }
    throw new ApiError(res.status, 'The server sent something unexpected. Try again.');
  }
  const body = await res.json();
  if (!res.ok) throw new ApiError(res.status, plainError(res.status, body?.error));
  return body as T;
}

export function plainError(status: number, serverMessage?: string): string {
  if (status >= 500) return 'Could not read the database. Try again.';
  if (status === 404) return serverMessage || 'That item was not found.';
  return serverMessage || 'That did not work. Try again.';
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '' || v === false) continue;
    u.set(k, v === true ? '1' : String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : '';
}
