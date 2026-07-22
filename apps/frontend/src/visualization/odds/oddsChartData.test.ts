import { describe, expect, it } from 'vitest';
import type { OddsMovementPoint } from '../../core/types';
import { buildOddsHeatmap, buildOddsLineSeries, isDenseOddsPlay } from './oddsChartData';

const POINTS: OddsMovementPoint[] = [
  {
    snapshot_id: 3,
    snapshot_time: '2026-07-14T18:00:00+08:00',
    play_type: 'spf',
    option_code: 'h',
    option_name: '主胜',
    sp_value: 1.82,
    handicap: null,
    implied_probability: 0.55,
    prev_sp_value: 1.8,
  },
  {
    snapshot_id: 1,
    snapshot_time: '2026-07-14T17:30:00+08:00',
    play_type: 'spf',
    option_code: 'h',
    option_name: '主胜',
    sp_value: 1.8,
    handicap: null,
    implied_probability: 0.56,
    prev_sp_value: null,
  },
  {
    snapshot_id: 2,
    snapshot_time: '2026-07-14T17:30:00+08:00',
    play_type: 'spf',
    option_code: 'd',
    option_name: '平',
    sp_value: 3.2,
    handicap: null,
    implied_probability: 0.31,
    prev_sp_value: null,
  },
];

describe('oddsChartData', () => {
  it('将普通玩法整理为按时间排序的多折线数据', () => {
    const series = buildOddsLineSeries(POINTS);

    expect(series).toHaveLength(2);
    expect(series[0]).toMatchObject({ id: 'h', name: '主胜' });
    expect(series[0].data.map((point) => point.value)).toEqual([1.8, 1.82]);
    expect(Number(series[0].data[0].time)).toBeLessThan(Number(series[0].data[1].time));
  });

  it('将密集玩法整理为时间与选项的热力矩阵', () => {
    const heatmap = buildOddsHeatmap(POINTS);

    expect(heatmap.times).toEqual([
      '2026-07-14T17:30:00+08:00',
      '2026-07-14T18:00:00+08:00',
    ]);
    expect(heatmap.options).toEqual(['主胜', '平']);
    expect(heatmap.cells).toContainEqual([0, 0, 1.8]);
    expect(heatmap.cells).toContainEqual([1, 0, 1.82]);
    expect(heatmap.min).toBe(1.8);
    expect(heatmap.max).toBe(3.2);
  });

  it('仅将比分和半全场视为默认密集玩法', () => {
    expect(isDenseOddsPlay('bf')).toBe(true);
    expect(isDenseOddsPlay('bqc')).toBe(true);
    expect(isDenseOddsPlay('zjq')).toBe(false);
    expect(isDenseOddsPlay('spf')).toBe(false);
  });
});
