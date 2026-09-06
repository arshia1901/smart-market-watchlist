import { describe, expect, it } from 'vitest';
import { atCircuit, band, isCorporateAction, magnitude } from './magnitude';
import { applyOrder, evaluate, order } from './rank';
import { Quote, WatchRow } from './models';

const BPD = 375;   // buckets in a trading day, 1-minute grid

describe('the thesis', () => {
  it('reproduces the worked example from the design document', () => {
    // Section 3.3. Both stocks moved +2.7% since the user last looked, one trading
    // day ago. Identical raw moves; one is news, one is Tuesday.
    const large = magnitude(100, 102.7, 0.00069, BPD)!;
    const small = magnitude(100, 102.7, 0.00207, BPD)!;

    expect(large).toBeCloseTo(2.02, 2);
    expect(small).toBeCloseTo(0.67, 2);
    expect(band(large, { hasBaseline: true, hasSigma: true })).toBe('notable');
    expect(band(small, { hasBaseline: true, hasSigma: true })).toBe('noise');
  });

  it('matches the Python reference exactly', () => {
    // Section 6.3 splits the formula across a language boundary. This golden case is
    // the only thing preventing the two halves from drifting apart.
    expect(magnitude(100, 102.7, 0.00069, BPD)!.toFixed(6)).toBe('2.020687');
  });

  it('ranks by how unusual a move is, not how big it is', () => {
    const rows: WatchRow[] = [
      { symbol: 'CALM', name: 'Calm', baseline: 100, sigma: 0.00069,
        observations: 750, band_limit: 'No Band', added_at: '' },
      { symbol: 'JUMPY', name: 'Jumpy', baseline: 100, sigma: 0.00207,
        observations: 750, band_limit: 'No Band', added_at: '' },
    ];
    const quotes = new Map<string, Quote>([
      ['CALM',  { symbol: 'CALM',  price: 102.7, as_of: '', source: '', freshness: 'live' }],
      ['JUMPY', { symbol: 'JUMPY', price: 103.1, as_of: '', source: '', freshness: 'live' }],
    ]);
    const ranked = evaluate(rows, quotes, BPD);
    const jumpy = ranked.find((r) => r.row.symbol === 'JUMPY')!;
    const calm = ranked.find((r) => r.row.symbol === 'CALM')!;

    expect(jumpy.changePct!).toBeGreaterThan(calm.changePct!);   // bigger raw move...
    expect(order(ranked)[0]).toBe('CALM');                       // ...ranked below
  });
});

describe('N cannot reorder the list', () => {
  it('holds for every N, because sqrt(N) is a common factor', () => {
    // Section 3.5, machine-checked. This is why an imperfect market calendar cannot
    // corrupt the ranking - only the band labels drift.
    let seed = 1234;
    const rand = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;

    for (let trial = 0; trial < 200; trial++) {
      const rows = Array.from({ length: 10 }, (_, i) => ({
        symbol: `S${i}`, name: '', baseline: 100,
        sigma: 1e-5 + rand() * 5e-3, observations: 750,
        band_limit: 'No Band', added_at: '',
      }));
      const quotes = new Map(rows.map((r) => [r.symbol, {
        symbol: r.symbol, price: 100 * (1 + (rand() - 0.5) * 0.4),
        as_of: '', source: '', freshness: 'live',
      }]));
      const reference = order(evaluate(rows, quotes, 375));
      for (const n of [1, 7, 60, 750, 99999]) {
        expect(order(evaluate(rows, quotes, n))).toEqual(reference);
      }
    }
  });
});

describe('bands', () => {
  const k = { hasBaseline: true, hasSigma: true };
  it('uses half-open intervals so boundaries are unambiguous', () => {
    expect(band(0.999, k)).toBe('noise');
    expect(band(1, k)).toBe('mild');
    expect(band(1.999, k)).toBe('mild');
    expect(band(2, k)).toBe('notable');
    expect(band(2.999, k)).toBe('notable');
    expect(band(3, k)).toBe('extreme');
  });

  it('flags a 1:10 split rather than ranking it first', () => {
    const m = magnitude(1000, 100, 0.0007, BPD)!;
    expect(band(m, { ...k, r: -0.9 })).toBe('corporate_action');
  });

  it('does not let the corporate-action flag move with N', () => {
    // The defect this test exists for: keyed off magnitude, an ordinary +2.7% move
    // read as a corporate action whenever N was small - i.e. two quick logins.
    for (const n of [1, 7, 60, 375, 750]) {
      const m = magnitude(100, 102.7, 0.00069, n);
      expect(band(m, { ...k, r: 0.027 })).not.toBe('corporate_action');
    }
  });

  it('never divides when a baseline or sigma is missing', () => {
    expect(magnitude(null, 102.7, 0.0007, BPD)).toBeNull();
    expect(magnitude(100, 102.7, null, BPD)).toBeNull();
    expect(magnitude(100, null, 0.0007, BPD)).toBeNull();     // added mid-session
    expect(magnitude(100, 102.7, 0.0007, 0)).toBeNull();      // two logins in a row
    expect(band(null, { hasBaseline: false, hasSigma: true })).toBe('new');
    expect(band(null, { hasBaseline: true, hasSigma: false })).toBe('unrated');
  });
});

describe('circuit limits', () => {
  it('detects a price pinned at its official band', () => {
    expect(atCircuit('20%', 100, 120)).toBe(true);
    expect(atCircuit('20%', 100, 105)).toBe(false);
  });
  it('is inert for the F&O stocks, which have no fixed band', () => {
    expect(atCircuit('No Band', 100, 200)).toBe(false);
  });
});

describe('the sort holds still while the reader is reading', () => {
  it('updates values live but does not reorder until refresh', () => {
    // Section 4.5. A list that reorders under the reader's eyes feels broken even
    // when it is correct.
    const rows: WatchRow[] = [
      { symbol: 'AAA', name: '', baseline: 100, sigma: 0.0007, observations: 750,
        band_limit: 'No Band', added_at: '' },
      { symbol: 'BBB', name: '', baseline: 100, sigma: 0.0007, observations: 750,
        band_limit: 'No Band', added_at: '' },
    ];
    const q = (a: number, b: number) => new Map<string, Quote>([
      ['AAA', { symbol: 'AAA', price: a, as_of: '', source: '', freshness: 'live' }],
      ['BBB', { symbol: 'BBB', price: b, as_of: '', source: '', freshness: 'live' }],
    ]);

    const fixed = order(evaluate(rows, q(105, 101), BPD));
    expect(fixed[0]).toBe('AAA');

    // BBB now moves far more - the displayed value must change, the order must not.
    const later = applyOrder(evaluate(rows, q(105, 130), BPD), fixed);
    expect(later.map((r) => r.row.symbol)).toEqual(['AAA', 'BBB']);
    expect(later[1].magnitude!).toBeGreaterThan(later[0].magnitude!);
  });

  it('puts unrankable rows below the ranked ones', () => {
    const rows: WatchRow[] = [
      { symbol: 'NEW', name: '', baseline: null, sigma: 0.0007, observations: 750,
        band_limit: 'No Band', added_at: '' },
      { symbol: 'RATED', name: '', baseline: 100, sigma: 0.0007, observations: 750,
        band_limit: 'No Band', added_at: '' },
    ];
    const quotes = new Map<string, Quote>([
      ['NEW',   { symbol: 'NEW',   price: 999, as_of: '', source: '', freshness: 'live' }],
      ['RATED', { symbol: 'RATED', price: 101, as_of: '', source: '', freshness: 'live' }],
    ]);
    expect(order(evaluate(rows, quotes, BPD))).toEqual(['RATED', 'NEW']);
  });
});
