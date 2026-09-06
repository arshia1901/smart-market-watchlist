import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiError, ApiService } from '../api.service';
import { Payload, Quote, QuoteFeed, Ranked } from '../domain/models';
import { applyOrder, evaluate, order } from '../domain/rank';
import { bucketsToText } from '../domain/duration';
import { StockSearchComponent } from '../stock-search/stock-search.component';
import { BatchStatusComponent } from '../batch-status/batch-status.component';

const BAND_LABEL: Record<string, string> = {
  extreme: 'EXTREME', notable: 'NOTABLE', mild: 'MILD', noise: 'noise',
  new: 'NEW', unrated: 'UNRATED', corporate_action: 'CORP ACTION', at_circuit: 'AT CIRCUIT',
  no_quote: 'NO QUOTE',
};
const UNRANKED = new Set(['new', 'unrated', 'corporate_action', 'at_circuit', 'no_quote']);
const IST = 'Asia/Kolkata';

/** The market is IST. Every time shown for a price is IST and says so. */
function istTime(d: Date): string {
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: IST });
}
function istDay(d: Date): string {
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', timeZone: IST });
}

@Component({
  selector: 'app-watchlist-page',
  standalone: true,
  imports: [CommonModule, FormsModule, StockSearchComponent, BatchStatusComponent],
  styleUrl: './watchlist-page.component.css',
  templateUrl: './watchlist-page.component.html',
})
export class WatchlistPageComponent implements OnInit, OnDestroy {
  readonly payload = signal<Payload | null>(null);
  readonly feed = signal<QuoteFeed | null>(null);
  readonly sortOrder = signal<string[]>([]);
  readonly loading = signal(true);

  /** Sign-in problems live on the sign-in card... */
  readonly error = signal<string | null>(null);
  /** ...everything else is a notice that stays until dismissed. A failed click that
   *  says nothing is the exact defect a live browser demonstrated during an outage. */
  readonly notice = signal<string | null>(null);

  // Feed health. nginx deliberately serves last-known values when the API is down;
  // the design wants that. What it does not want is for that to be INVISIBLE.
  //
  // ONE rule, judged over time: has a FRESH answer (not a served-while-refreshing
  // copy) arrived in the last FEED_SILENCE_MS? Polls run every 2s, so a healthy system
  // produces a fresh answer at least every ~4s. Twelve seconds of nothing fresh is six
  // consecutive stale polls - an outage, not a cache tick.
  readonly feedError = signal<string | null>(null);
  readonly lastFreshAt = signal<number | null>(null);
  private static readonly FEED_SILENCE_MS = 12_000;

  // Freshness ticks. If it only updated when data arrived, stopping ingestion would
  // freeze every label on "live" forever - asserting the opposite of the truth.
  readonly tick = signal(0);

  username = '';
  password = '';
  readonly heldSymbols = computed(() => this.payload()?.rows.map((r) => r.symbol) ?? []);

  private timers: number[] = [];
  constructor(readonly api: ApiService) {}

  readonly rows = computed<Ranked[]>(() => {
    const p = this.payload(); const f = this.feed();
    if (!p) return [];
    this.tick();
    const quotes = new Map<string, Quote>((f?.quotes ?? []).map((q) => [q.symbol, q]));
    return applyOrder(evaluate(p.rows, quotes, p.n), this.sortOrder());
  });
  readonly ranked = computed(() => this.rows().filter((r) => !UNRANKED.has(r.band)));
  readonly aside = computed(() => this.rows().filter((r) => UNRANKED.has(r.band)));
  readonly anyNoQuote = computed(() => this.aside().some((r) => r.band === 'no_quote'));

  /** One sentence, or null when the feed is healthy. Rendered above the table. */
  readonly feedIssue = computed<string | null>(() => {
    this.tick();
    const err = this.feedError();
    const last = this.lastFreshAt();
    if (last === null) return err ? `Quote feed unreachable — ${err}.` : null;
    const silent = Date.now() - last;
    // The same 12-second grace for BOTH failure shapes. A single failed poll is a
    // 3-second nginx restart during a deploy, not an outage; it was flashing the banner.
    if (silent <= WatchlistPageComponent.FEED_SILENCE_MS) return null;
    const since = `for ${Math.round(silent / 1000)}s (last fresh answer ${istTime(new Date(last))} IST)`;
    if (err) return `Quote feed unreachable ${since} — ${err}. Showing last known values.`;
    return `The API has not answered a fresh request ${since}. The web tier is serving its `
         + `last good copy; prices below are not being refreshed.`;
  });

  async ngOnInit(): Promise<void> {
    const requested = new URLSearchParams(location.search).get('user');
    if (requested) this.username = requested;          // pre-select only; Sign in is a button
    try {
      const p = await this.api.bootstrap(requested);
      if (p) this.adopt(p);
    } catch (e) {
      this.error.set(this.describe(e));
    }
    this.loading.set(false);
    await this.poll();
    this.timers.push(setInterval(() => this.poll(), 2000) as unknown as number);
    this.timers.push(setInterval(() => this.tick.update((t) => t + 1), 1000) as unknown as number);
  }
  ngOnDestroy(): void { this.timers.forEach(clearInterval); }

  private describe(e: unknown): string {
    if (e instanceof ApiError) return e.message;
    return String((e as Error)?.message ?? e);
  }

  /** The sort is decided once per load. Only an explicit re-rank moves it. */
  private adopt(p: Payload): void {
    this.payload.set(p);
    const quotes = new Map<string, Quote>((this.feed()?.quotes ?? []).map((q) => [q.symbol, q]));
    this.sortOrder.set(order(evaluate(p.rows, quotes, p.n)));
  }

  private async poll(): Promise<void> {
    try {
      const { feed, fresh } = await this.api.quotes();
      this.feed.set(feed);
      this.feedError.set(null);
      // A served-while-refreshing copy is still a successful poll; it just does not
      // reset the freshness clock. Six of those in a row is what the banner reacts to.
      if (fresh || this.lastFreshAt() === null) this.lastFreshAt.set(Date.now());
      if (this.sortOrder().length === 0 && this.payload()) this.adopt(this.payload()!);
    } catch (e) {
      this.feedError.set(this.describe(e));     // last known values stay; the banner says so
    }
  }

  async doLogin(): Promise<void> {
    this.error.set(null);
    try { this.adopt(await this.api.login(this.username.trim().toLowerCase(), this.password || null)); }
    catch (e) { this.error.set(this.describe(e)); }
  }
  async logout(): Promise<void> {
    await this.api.logout();
    this.payload.set(null);
    this.sortOrder.set([]);
    this.notice.set(null);
  }
  reRank(): void { const p = this.payload(); if (p) this.adopt(p); }

  // Two steps, two messages. "Could not add INFY" when the add went through and only
  // the reload failed is a false statement - and it happened, during a redeploy.
  async add(symbol: string): Promise<void> {
    const user = this.api.user(); if (!user) return;
    try { await this.api.add(user, symbol); }
    catch (e) { this.notice.set(`Could not add ${symbol} — ${this.describe(e)}`); return; }
    try { this.payload.set(await this.api.refresh(user)); this.notice.set(null); }
    catch (e) { this.notice.set(`${symbol} was added, but the list could not be reloaded — ${this.describe(e)}. It will appear on the next refresh.`); }
  }

  async remove(symbol: string): Promise<void> {
    const user = this.api.user(); if (!user) return;
    try { await this.api.remove(user, symbol); }
    catch (e) { this.notice.set(`Could not remove ${symbol} — it is still on your list. ${this.describe(e)}`); return; }
    try { this.adopt(await this.api.refresh(user)); this.notice.set(null); }
    catch (e) { this.notice.set(`${symbol} was removed, but the list could not be reloaded — ${this.describe(e)}. Refresh to see the change.`); }
  }

  label(band: string): string { return BAND_LABEL[band] ?? band; }

  /** N in a unit a reader already holds - and the truth when none has elapsed. */
  gap(): string {
    const p = this.payload(); if (!p) return '';
    const elapsed = p.trading_minutes_elapsed ?? p.n;
    return elapsed <= 0 ? 'no market time yet' : bucketsToText(p.n, p.grid_seconds ?? 60);
  }
  /** For the footer: reads as a sentence whether or not any market time has passed. */
  gapFooter(): string {
    const p = this.payload(); if (!p) return 'N = trading minutes since your last visit';
    const elapsed = p.trading_minutes_elapsed ?? p.n;
    return elapsed <= 0 ? 'N: no market time has passed since your last visit'
                        : `N = ${bucketsToText(p.n, p.grid_seconds ?? 60)} of trading`;
  }

  private utc(iso: string): string { return `${new Date(iso).toISOString().slice(11, 16)} UTC`; }

  /** When the baselines last moved. Always shown, so a re-anchor is never a surprise. */
  sessionStarted(): string {
    const p = this.payload();
    return p?.session_started ? `session started ${istTime(new Date(p.session_started))} IST` : '';
  }

  /**
   * What the baselines are anchored to. On the sign-in response that is the previous
   * visit; after a refresh the anchor IS this session's start (baselines advanced at
   * sign-in). Say which - the old label called both "your last visit".
   */
  comparedTo(): string {
    const p = this.payload(); if (!p) return '';
    if (!p.last_login) return 'the price when you added each stock — this is your first visit';
    if (p.session_started && new Date(p.last_login).getTime() >= new Date(p.session_started).getTime() - 1000) {
      return `the start of this session (${this.utc(p.last_login)})`;
    }
    return `your previous visit at ${this.utc(p.last_login)}`;
  }

  /** Header clock, in the market's zone and labelled as such. */
  clockIst(): string {
    const f = this.feed(); return f ? `${istTime(new Date(f.as_of))} IST` : '';
  }

  /**
   * Open market: a relative age that ticks against the wall clock, so a dead feed shows
   * as growing age rather than a frozen number. Closed market: the absolute last trade -
   * "31h ago" is true and reads as a fault; "Fri 04 Sep 16:00 IST" is the same fact.
   */
  age(r: Ranked): string {
    this.tick();
    if (!r.asOf) return '--';
    if (r.freshness === 'market_closed') return `${istDay(r.asOf)} ${istTime(r.asOf)} IST`;
    const secs = Math.max(0, Math.round((Date.now() - r.asOf.getTime()) / 1000));
    if (secs < 90) return `${secs}s ago`;
    if (secs < 5400) return `${Math.round(secs / 60)}m ago`;
    return `${Math.round(secs / 3600)}h ago`;
  }

  freshLabel(r: Ranked): string {
    if (r.freshness === 'market_closed') return 'last trade · market closed';
    if (r.freshness === 'no_quote') return 'no quote received';
    return r.freshness;
  }

  fmt(v: number | null, digits = 2): string {
    return v === null || !Number.isFinite(v) ? '--' : v.toFixed(digits);
  }
  signed(v: number | null): string {
    return v === null ? '--' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  }
}
