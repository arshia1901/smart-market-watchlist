import { Injectable, signal } from '@angular/core';
import { Payload, QuoteFeed } from './domain/models';

const BASE = '/api';

/**
 * Session state lives in localStorage, not memory (spec 4.3). In memory, F5 would mint
 * a new session and wipe every highlight; sessionStorage dies with the tab.
 */
const TOKEN_KEY = 'watchlist.session';

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
  /** A 5xx or a network failure is the SERVER's problem; say so, never 'login failed'. */
  get serverDown(): boolean { return this.status === 0 || this.status >= 500; }
}

async function check(res: Response, what: string): Promise<Response> {
  if (res.ok) return res;
  let detail = '';
  try { detail = (await res.json()).detail ?? ''; } catch { /* not JSON - a gateway page */ }
  if (res.status >= 500) throw new ApiError(res.status, `${what}: server unavailable (${res.status})`);
  throw new ApiError(res.status, detail || `${what} failed (${res.status})`);
}

async function call(input: string, init?: RequestInit, what = 'request'): Promise<Response> {
  let res: Response;
  try { res = await fetch(input, init); }
  catch (e) { throw new ApiError(0, `${what}: network unreachable`); }
  return check(res, what);
}

export interface FeedResult { feed: QuoteFeed; fresh: boolean; cacheStatus: string; }

@Injectable({ providedIn: 'root' })
export class ApiService {
  readonly user = signal<string | null>(null);

  private stored(): { user: string; token: string } | null {
    try { const raw = localStorage.getItem(TOKEN_KEY); return raw ? JSON.parse(raw) : null; }
    catch { return null; }
  }
  private remember(user: string, token: string): void {
    try { localStorage.setItem(TOKEN_KEY, JSON.stringify({ user, token })); } catch { /* ignore */ }
  }
  forget(): void {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
    this.user.set(null);
  }

  /**
   * Held session -> refresh path (never advances). Otherwise: nothing. Sessions start
   * ONLY at the Sign in button. `?user=` used to log in implicitly, which is how a
   * second session was opened by accident and every baseline silently re-anchored.
   */
  async bootstrap(requested: string | null): Promise<Payload | null> {
    const held = this.stored();
    if (held && (!requested || requested === held.user)) {
      try {
        const p = await this.refresh(held.user);
        this.user.set(held.user);
        return p;
      } catch (e) {
        // The server closed this session (a reset, or a sign-out elsewhere). The held
        // token is dead: forget it and show the Sign in card - do not error.
        if (e instanceof ApiError && e.status === 401) { this.forget(); return null; }
        throw e;
      }
    }
    return null;
  }

  heldUser(): string | null { return this.stored()?.user ?? null; }

  /** Sign out ends the session on the server. Baselines are untouched; the next Sign in moves them. */
  async logout(): Promise<void> {
    const held = this.stored();
    this.forget();
    if (!held) return;
    try {
      await call(`${BASE}/session/logout`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: held.token }),
      }, 'sign out');
    } catch (e) {
      // The token is already gone locally; if the server disagreed the user will hear
      // about it at the next Sign in (409), which is the right place.
    }
  }

  async login(username: string, password: string | null): Promise<Payload> {
    const res = await call(`${BASE}/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }, 'sign in');
    const payload: Payload = await res.json();
    this.user.set(payload.user);
    this.remember(payload.user, payload.token!);
    return payload;
  }

  /** Current state WITHOUT advancing baselines - the refresh path. */
  async refresh(user: string): Promise<Payload> {
    return (await call(`${BASE}/watchlist?user=${encodeURIComponent(user)}`, undefined, 'load watchlist')).json();
  }

  /**
   * Shared feed. nginx keeps a 2-second cache and, when an entry expires, serves the
   * old copy while refreshing in the background - status UPDATING. That is NORMAL and
   * happens every couple of seconds on a healthy system. STALE/UPDATING on ONE response
   * means nothing; an earlier build treated it as an outage and the banner flickered
   * on and off all evening. What matters is whether a FRESH answer has arrived recently,
   * which the caller judges over time - this method only reports what it saw.
   */
  async quotes(): Promise<FeedResult> {
    const res = await call(`${BASE}/quotes`, undefined, 'quote feed');
    const cacheStatus = (res.headers.get('X-Cache-Status') ?? 'NONE').toUpperCase();
    const fresh = cacheStatus !== 'STALE' && cacheStatus !== 'UPDATING';
    return { feed: await res.json(), fresh, cacheStatus };
  }

  async status(): Promise<unknown> {
    return (await call(`${BASE}/status`, undefined, 'status')).json();
  }

  async search(q: string): Promise<{ symbol: string; name: string; band_limit: string }[]> {
    return (await (await call(`${BASE}/instruments?q=${encodeURIComponent(q)}&limit=12`, undefined, 'search')).json()).results;
  }

  async add(user: string, symbol: string): Promise<void> {
    await call(`${BASE}/watchlist?user=${encodeURIComponent(user)}&symbol=${symbol}`, { method: 'POST' }, `add ${symbol}`);
  }

  async remove(user: string, symbol: string): Promise<void> {
    await call(`${BASE}/watchlist?user=${encodeURIComponent(user)}&symbol=${symbol}`, { method: 'DELETE' }, `remove ${symbol}`);
  }
}
