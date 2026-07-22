import { describe, expect, it } from 'vitest';
import { calculateSettledProfitRate } from './AiPoolDashboard';

describe('Agent pool financial metrics', () => {
  it('uses settled stake instead of newly committed stake for realized profit rate', () => {
    expect(calculateSettledProfitRate(20, 40)).toBe(0.5);
    expect(calculateSettledProfitRate(20, 0)).toBe(0);
  });
});
