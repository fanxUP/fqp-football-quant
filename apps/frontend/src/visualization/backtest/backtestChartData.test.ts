import { describe, expect, it } from 'vitest';
import type { BacktestResult, DashboardBacktestEquityItem } from '../../core/types';
import { buildBacktestMetricRows, buildBacktestWindowTrends } from './backtestChartData';

const equityRows: DashboardBacktestEquityItem[] = [
  {
    run_id: 19,
    run_name: '测试回测',
    run_status: 'completed',
    window_index: 1,
    test_start_date: '2026-06-01',
    test_end_date: '2026-06-30',
    window_bets: 100,
    model_name: 'elo_rating',
    n_bets: 30,
    n_wins: 12,
    hit_rate: 0.4,
    roi: 0.125,
    total_profit: 3.75,
    max_drawdown: 4,
    max_drawdown_pct: 8.5,
    sharpe_ratio: 1.2,
    profit_factor: 1.1,
  },
  {
    run_id: 19,
    run_name: '测试回测',
    run_status: 'completed',
    window_index: 0,
    test_start_date: '2026-05-01',
    test_end_date: '2026-05-31',
    window_bets: 100,
    model_name: 'elo_rating',
    n_bets: 30,
    n_wins: 10,
    hit_rate: 0.333,
    roi: -0.05,
    total_profit: -1.5,
    max_drawdown: 5,
    max_drawdown_pct: 10,
    sharpe_ratio: -0.4,
    profit_factor: 0.8,
  },
  {
    run_id: 19,
    run_name: '测试回测',
    run_status: 'completed',
    window_index: 0,
    test_start_date: '2026-05-01',
    test_end_date: '2026-05-31',
    window_bets: 100,
    model_name: 'market_baseline',
    n_bets: 25,
    n_wins: 9,
    hit_rate: 0.36,
    roi: 0.02,
    total_profit: 0.5,
    max_drawdown: 3,
    max_drawdown_pct: 6,
    sharpe_ratio: 0.2,
    profit_factor: 1.02,
  },
];

function result(modelName: string, roi: number, drawdown: number): BacktestResult {
  return {
    window_index: null,
    model_name: modelName,
    n_bets: 100,
    n_wins: 40,
    hit_rate: 0.4,
    roi,
    total_profit: 10,
    avg_odds: 2,
    brier_score: 0.2,
    log_loss: 0.6,
    clv: 0.01,
    max_drawdown: 8,
    max_drawdown_pct: drawdown,
    longest_losing_streak: 4,
    sharpe_ratio: 0.8,
    profit_factor: 1.2,
    equity_curve: null,
  };
}

describe('backtestChartData', () => {
  it('按模型和真实测试结束日期生成 ROI 与回撤趋势', () => {
    const trends = buildBacktestWindowTrends(equityRows);

    expect(trends.dateCount).toBe(2);
    expect(trends.roiSeries.map((item) => item.id)).toEqual(['elo_rating', 'market_baseline']);
    expect(trends.roiSeries[0].name).toBe('Elo 实力评分');
    expect(trends.roiSeries[0].data.map((point) => point.value)).toEqual([-5, 12.5]);
    expect(trends.roiSeries[0].data[0].time).toBe('2026-05-31');
    expect(trends.drawdownSeries[0].data.map((point) => point.value)).toEqual([-10, -8.5]);
    expect(trends.drawdownRange).toEqual([-11, 0]);
  });

  it('为聚合对比统一百分比口径并按业务优劣排序', () => {
    const results = [
      result('market_baseline', -0.1, 16),
      result('elo_rating', 0.08, 7),
    ];

    expect(buildBacktestMetricRows(results, 'roi')).toEqual([
      { modelName: 'elo_rating', label: 'Elo 实力评分', value: 8 },
      { modelName: 'market_baseline', label: '市场赔率基准', value: -10 },
    ]);
    expect(buildBacktestMetricRows(results, 'drawdown')).toEqual([
      { modelName: 'elo_rating', label: 'Elo 实力评分', value: 7 },
      { modelName: 'market_baseline', label: '市场赔率基准', value: 16 },
    ]);
  });
});
