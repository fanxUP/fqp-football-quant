import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { BacktestResult, DashboardBacktestEquityItem } from '../../core/types';
import BacktestPerformanceCharts from './BacktestPerformanceCharts';

vi.mock('../timeseries/LightweightLineChart', () => ({
  default: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}));

vi.mock('../../app/ThemeContext', () => ({
  useTheme: () => ({ theme: 'redline-quant' }),
}));

vi.mock('./BacktestMetricBarChart', () => ({
  default: ({ title }: { title: string }) => <div role="img" aria-label={title} />,
}));

const result = {
  model_name: 'elo_rating',
  roi: 0.1,
  max_drawdown_pct: 8,
} as BacktestResult;

function equity(date: string, windowIndex: number): DashboardBacktestEquityItem {
  return {
    model_name: 'elo_rating',
    test_end_date: date,
    window_index: windowIndex,
    roi: 0.1,
    max_drawdown_pct: 8,
  } as DashboardBacktestEquityItem;
}

describe('BacktestPerformanceCharts', () => {
  it('始终展示聚合模型对比，单窗口时用诚实的趋势空状态', () => {
    render(<BacktestPerformanceCharts results={[result]} windowRows={[equity('2026-07-09', 0)]} />);

    expect(screen.getByRole('img', { name: '模型 ROI 对比' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '模型最大回撤对比' })).toBeInTheDocument();
    expect(screen.getAllByText('当前仅 1 个测试窗口，无法形成时间趋势').length).toBe(2);
    expect(screen.queryByRole('img', { name: '各模型窗口 ROI 时间趋势' })).not.toBeInTheDocument();
  });

  it('至少两个测试窗口时展示真实时间轴趋势', () => {
    render(<BacktestPerformanceCharts
      results={[result]}
      windowRows={[equity('2026-06-30', 0), equity('2026-07-09', 1)]}
    />);

    expect(screen.getByRole('img', { name: '各模型窗口 ROI 时间趋势' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '各模型窗口最大回撤时间趋势' })).toBeInTheDocument();
  });
});
