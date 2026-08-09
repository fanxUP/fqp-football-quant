import { describe, expect, it } from 'vitest';
import { buildProfitLossSeries } from './profitLossSeries';

describe('buildProfitLossSeries', () => {
  it('按日期生成日盈亏与累计盈亏两条时间序列', () => {
    const series = buildProfitLossSeries([
      { review_date: '2026-08-02', real_profit_loss: -10 },
      { review_date: '2026-08-01', real_profit_loss: 25 },
    ]);

    expect(series).toEqual([
      {
        id: 'daily-profit-loss',
        name: '日盈亏',
        data: [
          { time: '2026-08-01', value: 25 },
          { time: '2026-08-02', value: -10 },
        ],
      },
      {
        id: 'cumulative-profit-loss',
        name: '累计盈亏',
        data: [
          { time: '2026-08-01', value: 25 },
          { time: '2026-08-02', value: 15 },
        ],
      },
    ]);
  });
});
