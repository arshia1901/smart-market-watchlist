import { describe, expect, it } from 'vitest';
import { segments, step } from './match';

describe('showing why a result matched', () => {
  it('splits around the match', () => {
    expect(segments('RELIANCE', 'lia')).toEqual([
      { text: 'RE', hit: false }, { text: 'LIA', hit: true }, { text: 'NCE', hit: false },
    ]);
  });
  it('is case-insensitive but preserves the original casing', () => {
    // The match is at index 0, so there is no leading segment.
    expect(segments('Reliance Industries', 'RELI')[0]).toEqual({ text: 'Reli', hit: true });
    expect(segments('Hindustan Unilever', 'unil')[1]).toEqual({ text: 'Unil', hit: true });
  });
  it('handles a match at either end', () => {
    expect(segments('TCS', 'TCS')).toEqual([{ text: 'TCS', hit: true }]);
    expect(segments('INFY', 'IN')[0]).toEqual({ text: 'IN', hit: true });
  });
  it('returns the whole label when there is no match or no query', () => {
    expect(segments('ITC', '')).toEqual([{ text: 'ITC', hit: false }]);
    expect(segments('ITC', 'zzz')).toEqual([{ text: 'ITC', hit: false }]);
  });
});

describe('keyboard movement', () => {
  it('wraps in both directions so focus never falls off the list', () => {
    expect(step(0, 1, 3)).toBe(1);
    expect(step(2, 1, 3)).toBe(0);
    expect(step(0, -1, 3)).toBe(2);
  });
  it('reports nothing selectable for an empty list', () => {
    expect(step(0, 1, 0)).toBe(-1);
  });
});
