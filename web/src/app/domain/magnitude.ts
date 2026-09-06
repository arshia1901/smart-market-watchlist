/**
 * magnitude = |r| / (sigma * sqrt(N))        - design document, section 3.2
 *
 * This is the compute layer, not the view layer: the server performs no per-user
 * arithmetic at all (section 6.3), so this file is where the product's thesis
 * actually executes. It is pure, imports nothing from Angular, and is pinned to the
 * same worked example as the Python reference so the two cannot drift.
 */

export const BAND_EDGES = { mild: 1, notable: 2, extreme: 3 };
/**
 * Keyed off the RETURN, not the magnitude. Magnitude scales with sqrt(N), so a
 * magnitude threshold made banding depend on N - an ordinary +2.7% move read as a
 * corporate action whenever a user logged in twice within a few minutes, which also
 * contradicted section 3.5. A 1:10 split is -90%, a 1:2 split is -50%, and an NSE
 * circuit band caps a real session move at 20%.
 */
export const CORPORATE_ACTION_RETURN = 0.4;

export function isCorporateAction(r: number | null): boolean {
  return r !== null && Math.abs(r) >= CORPORATE_ACTION_RETURN;
}

export function simpleReturn(baseline: number, observed: number): number {
  return (observed - baseline) / baseline;
}

export function magnitude(
  baseline: number | null,
  observed: number | null,
  sigma: number | null,
  n: number,
): number | null {
  // None whenever the inputs cannot support a ranking - never a faked default.
  if (baseline === null || observed === null || sigma === null) return null;
  if (baseline <= 0 || sigma <= 0 || n <= 0) return null;
  const value = Math.abs(simpleReturn(baseline, observed)) / (sigma * Math.sqrt(n));
  return Number.isFinite(value) ? value : null;
}

/**
 * Half-open intervals, so every boundary value lands in exactly one band.
 * A magnitude of exactly 2 is `notable`, never ambiguous.
 */
export function band(
  m: number | null,
  opts: { hasBaseline: boolean; hasSigma: boolean; atCircuit?: boolean; r?: number | null },
): string {
  if (!opts.hasBaseline) return 'new';
  if (isCorporateAction(opts.r ?? null)) return 'corporate_action';
  if (opts.atCircuit) return 'at_circuit';
  if (!opts.hasSigma || m === null) return 'unrated';
  if (m >= BAND_EDGES.extreme) return 'extreme';
  if (m >= BAND_EDGES.notable) return 'notable';
  if (m >= BAND_EDGES.mild) return 'mild';
  return 'noise';
}

/**
 * Is the price pinned at its official circuit band?
 *
 * The band is published against the previous close; we compare against the session
 * baseline, which is the closest thing the client holds. Good to within a day's
 * drift, and the approximation is stated rather than hidden.
 */
export function atCircuit(
  bandLimit: string, baseline: number | null, price: number | null,
): boolean {
  if (baseline === null || price === null) return false;
  const match = /^(\d+(?:\.\d+)?)%$/.exec(bandLimit.trim());
  if (!match) return false;                       // "No Band" - every F&O stock
  const limit = parseFloat(match[1]) / 100;
  return Math.abs(simpleReturn(baseline, price)) >= limit * 0.99;
}
