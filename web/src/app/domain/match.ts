/**
 * Splitting a label around the matched substring, so the typeahead can show *why*
 * a result matched. Pure, so it is tested like everything else in domain/.
 */
export interface Segment { text: string; hit: boolean; }

export function segments(text: string, query: string): Segment[] {
  const q = query.trim();
  if (!q) return [{ text, hit: false }];

  const at = text.toLowerCase().indexOf(q.toLowerCase());
  if (at < 0) return [{ text, hit: false }];

  const out: Segment[] = [];
  if (at > 0) out.push({ text: text.slice(0, at), hit: false });
  out.push({ text: text.slice(at, at + q.length), hit: true });
  if (at + q.length < text.length) out.push({ text: text.slice(at + q.length), hit: false });
  return out;
}

/** Wrap-around movement, so the keyboard never lands on nothing. */
export function step(index: number, delta: number, length: number): number {
  if (length === 0) return -1;
  return (index + delta + length) % length;
}
