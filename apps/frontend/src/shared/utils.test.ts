import { describe, expect, it } from 'vitest';

import { formatTimestamp } from './utils';

describe('formatTimestamp', () => {
  it('treats timezone-free database timestamps as UTC and displays Beijing time', () => {
    expect(formatTimestamp('2026-07-22T10:42:27.798238')).toBe('2026-07-22 18:42:27');
  });

  it('keeps timezone-aware timestamps on the same Beijing instant', () => {
    expect(formatTimestamp('2026-07-22T18:42:27+08:00')).toBe('2026-07-22 18:42:27');
  });

  it('returns a dash for missing or invalid values', () => {
    expect(formatTimestamp(null)).toBe('—');
    expect(formatTimestamp('not-a-date')).toBe('—');
  });
});
