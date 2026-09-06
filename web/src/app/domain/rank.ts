import { Band, Payload, Quote, Ranked, WatchRow } from './models';
import { atCircuit, band, magnitude, simpleReturn } from './magnitude';

/** Rows that cannot be scored sit below the ranked ones rather than being faked. */
const UNRANKABLE: ReadonlySet<string> = new Set(
  ['new', 'unrated', 'corporate_action', 'at_circuit', 'no_quote'],
);

export function evaluate(
  rows: WatchRow[], quotes: Map<string, Quote>, n: number,
): Ranked[] {
  return rows.map((row) => {
    const quote = quotes.get(row.symbol) ?? null;
    const price = quote ? quote.price : null;
    const circuit = atCircuit(row.band_limit, row.baseline, price);
    const r = row.baseline !== null && price !== null
      ? simpleReturn(row.baseline, price) : null;
    const m = magnitude(row.baseline, price, row.sigma, n);
    return {
      row,
      price,
      asOf: quote ? new Date(quote.as_of) : null,
      changePct: r !== null ? r * 100 : null,
      magnitude: m,
      // No quote at all is not 'stale' and not 'unrated' - it is the feed not having
      // delivered this symbol. Blaming the stock's data for an outage is a lie.
      band: (quote ? band(m, {
        hasBaseline: row.baseline !== null,
        hasSigma: row.sigma !== null,
        atCircuit: circuit,
        r,
      }) : 'no_quote') as Band,
      freshness: quote ? quote.freshness : 'no_quote',
      source: quote ? quote.source : '',
    };
  });
}

/**
 * The order, decided once.
 *
 * Section 4.5: values are live, the sort is stable. Recomputing the order on every
 * poll would make rows swap places while the reader is looking at them, which feels
 * broken even when it is correct. Section 3.5 makes this cheap to justify - order
 * depends only on |r|/sigma, so N cannot change it.
 */
export function order(ranked: Ranked[]): string[] {
  return [...ranked]
    .sort((a, b) => {
      const au = UNRANKABLE.has(a.band), bu = UNRANKABLE.has(b.band);
      if (au !== bu) return au ? 1 : -1;                      // unrankable below
      const am = a.magnitude ?? -1, bm = b.magnitude ?? -1;
      if (am !== bm) return bm - am;
      return a.row.symbol.localeCompare(b.row.symbol);        // deterministic ties
    })
    .map((r) => r.row.symbol);
}

export function applyOrder(ranked: Ranked[], symbols: string[]): Ranked[] {
  const rank = new Map(symbols.map((s, i) => [s, i]));
  return [...ranked].sort(
    (a, b) => (rank.get(a.row.symbol) ?? 1e9) - (rank.get(b.row.symbol) ?? 1e9),
  );
}
