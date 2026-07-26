import { describe, expect, it } from 'vitest';
import { buildModelPerformanceOverview, buildModelPerformanceSeries } from './modelPerformanceData';

const points = [
  { date: '2026-07-11', play_type: 'all', model_name: 'elo_rating', hit_rate: 0.4, sample_size: 5 },
  { date: '2026-07-12', play_type: 'all', model_name: 'elo_rating', hit_rate: 0.55, sample_size: 20 },
  { date: '2026-07-11', play_type: 'all', model_name: 'market_baseline', hit_rate: 0.5, sample_size: 6 },
  { date: '2026-07-12', play_type: 'all', model_name: 'market_baseline', hit_rate: 0.6, sample_size: 20 },
  { date: '2026-07-12', play_type: 'spf', model_name: 'market_baseline', hit_rate: 0.5455, sample_size: 11 },
  { date: '2026-07-11', play_type: 'spf', model_name: 'elo_rating', hit_rate: 0.3333, sample_size: 3 },
  { date: '2026-07-12', play_type: 'spf', model_name: 'elo_rating', hit_rate: 0.5, sample_size: 12 },
];

describe('buildModelPerformanceSeries', () => {
  it('按固定模型顺序生成真实日期轴和百分比数据', () => {
    const series = buildModelPerformanceSeries(points, 'spf');

    expect(series.map((item) => item.id)).toEqual(['elo_rating', 'market_baseline']);
    expect(series[0].data).toEqual([
      { time: '2026-07-11', value: 33.3 },
      { time: '2026-07-12', value: 50 },
    ]);
    expect(series[0]).toMatchObject({ latestSampleSize: 12, dateCount: 2 });
  });

  it('忽略非目标玩法和非法数值', () => {
    expect(buildModelPerformanceSeries([
      ...points,
      { date: '2026-07-13', play_type: 'spf', model_name: 'elo_rating', hit_rate: Number.NaN, sample_size: 13 },
    ], 'bf')).toEqual([]);
  });
});

describe('buildModelPerformanceOverview', () => {
  it('按最新综合命中率排名并计算相对上一期变化', () => {
    const overview = buildModelPerformanceOverview(points);

    expect(overview.map((item) => item.modelName)).toEqual(['market_baseline', 'elo_rating']);
    expect(overview[0]).toMatchObject({
      rank: 1,
      latestHitRate: 60,
      latestSampleSize: 20,
      changePercentagePoints: 10,
      dateCount: 2,
      insufficientHistory: true,
    });
    expect(overview[1].changePercentagePoints).toBe(15);
  });
});
