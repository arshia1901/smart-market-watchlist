export interface WatchRow {
  symbol: string;
  name: string;
  baseline: number | null;   // null = new (spec 4.7)
  baseline_source?: 'added' | 'previous_session' | null;
  sigma: number | null;      // null = unrated (spec 4.7)
  sigma_provisional?: boolean; // back-filled from one real session; not yet organic
  observations: number;
  band_limit: string;        // official NSE price band, e.g. "20%" or "No Band"
  added_at: string;
}

export interface Payload {
  user: string;
  n: number;                 // ONE number for the whole payload (spec 3.2)
  trading_minutes_elapsed?: number;   // the truth behind n; 0 on a weekend
  grid_seconds: number;
  n_source: string;
  last_login: string | null;
  session_started?: string | null;   // when the baselines last moved
  server_time: string;
  rows: WatchRow[];
  token?: string;
}

export interface Quote {
  symbol: string;
  price: number;
  as_of: string;
  source: string;
  freshness: string;
}

export interface QuoteFeed {
  as_of: string;
  served_by: string;
  clock: string;
  data_source: string;
  market_open: boolean;
  quotes: Quote[];
}

export type Band =
  | 'noise' | 'mild' | 'notable' | 'extreme'
  | 'new' | 'unrated' | 'corporate_action' | 'at_circuit' | 'no_quote';

export interface Ranked {
  row: WatchRow;
  price: number | null;
  asOf: Date | null;
  changePct: number | null;
  magnitude: number | null;
  band: Band;
  freshness: string;
  source: string;   // which venue quoted it - BSE prices differ from NSE by a normal spread
}
