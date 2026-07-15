import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BacktestMetricBarChart from './BacktestMetricBarChart';

const { chartCardSpy } = vi.hoisted(() => ({ chartCardSpy: vi.fn() }));

vi.mock('../../app/ThemeContext', () => ({
  useTheme: () => ({ theme: 'redline-quant' }),
}));

vi.mock('../../shared/components/ChartCard', () => ({
  default: (props: Record<string, unknown>) => {
    chartCardSpy(props);
    return <div role="img" aria-label={String(props.title)} />;
  },
}));

describe('BacktestMetricBarChart', () => {
  it('ROI 使用零基准的横向模型排名并保留正负号', () => {
    render(<BacktestMetricBarChart
      title="模型 ROI 对比"
      metric="roi"
      rows={[
        { modelName: 'elo_rating', label: 'Elo 实力评分', value: 8 },
        { modelName: 'market_baseline', label: '市场赔率基准', value: -10 },
      ]}
    />);

    expect(screen.getByRole('img', { name: '模型 ROI 对比' })).toBeInTheDocument();
    const props = chartCardSpy.mock.lastCall?.[0] as { option: Record<string, unknown> };
    const option = props.option as {
      legend: { show: boolean };
      yAxis: { type: string; data: string[] };
      series: Array<{ data: number[]; label: { formatter: (params: { value: number }) => string } }>;
    };
    expect(option.yAxis).toMatchObject({ type: 'category', data: ['Elo 实力评分', '市场赔率基准'] });
    expect(option.legend.show).toBe(false);
    expect(option.series[0].data).toEqual([8, -10]);
    expect(option.series[0].label.formatter({ value: 8 })).toBe('+8.0%');
    expect(option.series[0].label.formatter({ value: -10 })).toBe('-10.0%');
  });
});
