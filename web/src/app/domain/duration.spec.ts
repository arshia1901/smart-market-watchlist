import { describe, expect, it } from 'vitest';
import { bucketsToText } from './duration';

describe('rendering N as time', () => {
  it('converts a full trading session', () => {
    expect(bucketsToText(375, 60)).toBe('1 trading day');
  });
  it('converts partial sessions', () => {
    expect(bucketsToText(60, 60)).toBe('1h');
    expect(bucketsToText(18, 60)).toBe('18m');
    expect(bucketsToText(246, 60)).toBe('4h 6m');
    expect(bucketsToText(90, 60)).toBe('1h 30m');
  });
  it('rolls over into whole trading days, not 24-hour days', () => {
    // 750 buckets is the sigma window: two sessions, not "12h 30m" of wall clock.
    expect(bucketsToText(750, 60)).toBe('2 trading days');
    expect(bucketsToText(400, 60)).toBe('1 trading day 25m');
  });
  it('degrades sensibly at the edges', () => {
    expect(bucketsToText(0, 60)).toBe('under a minute');
    expect(bucketsToText(1, 60)).toBe('1m');
  });
});
