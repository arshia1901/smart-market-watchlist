/**
 * Buckets are a unit of the engine, not of a person's day. N = 375 means nothing to
 * a reader; "6h 15m of trading" is the same fact in a form they already hold.
 *
 * Note "of trading" is load-bearing: 375 buckets can span a weekend and still be
 * 6h 15m, because closed hours contribute none.
 */
export function bucketsToText(buckets: number, gridSeconds: number): string {
  const minutes = Math.round((buckets * gridSeconds) / 60);
  if (minutes < 1) return 'under a minute';
  const days = Math.floor(minutes / 375);          // 375 minutes = one trading session
  const rest = minutes - days * 375;
  const h = Math.floor(rest / 60);
  const m = rest % 60;

  const parts: string[] = [];
  if (days) parts.push(`${days} trading day${days > 1 ? 's' : ''}`);
  if (h) parts.push(`${h}h`);
  if (m || (!days && !h)) parts.push(`${m}m`);
  return parts.join(' ');
}
