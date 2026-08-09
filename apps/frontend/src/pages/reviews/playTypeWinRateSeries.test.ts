import { describe, expect, it } from 'vitest';
import { buildPlayTypeWinRateSeries } from './playTypeWinRateSeries';

describe('buildPlayTypeWinRateSeries', () => {
  it('按玩法构建与模型对比图一致的日期时间序列', () => {
    const series = buildPlayTypeWinRateSeries([
      { settle_date: '2026-08-02', play_type: 'spf', total: 8, wins: 5, win_rate: 0.625 },
      { settle_date: '2026-08-01', play_type: 'spf', total: 4, wins: 3, win_rate: 0.75 },
      { settle_date: '2026-08-02', play_type: 'rqspf', total: 3, wins: 1, win_rate: 1 / 3 },
    ]);

    expect(series).toEqual([
      {
        id: 'rqspf',
        name: '让球胜平负',
        data: [{ time: '2026-08-02', value: 33.3 }],
      },
      {
        id: 'spf',
        name: '胜平负',
        data: [
          { time: '2026-08-01', value: 75 },
          { time: '2026-08-02', value: 62.5 },
        ],
      },
    ]);
  });
});
