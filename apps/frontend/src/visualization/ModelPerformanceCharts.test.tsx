import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ModelPerformanceCharts from './ModelPerformanceCharts';
import { ThemeProvider } from '../app/ThemeContext';

vi.mock('./timeseries/LightweightLineChart', () => ({
  default: ({ ariaLabel, height }: { ariaLabel: string; height: number }) => (
    <div role="img" aria-label={ariaLabel} data-height={height} />
  ),
}));

describe('ModelPerformanceCharts', () => {
  it('用横向标签在单张加高图表中切换六种视图', () => {
    const onPlayTypeChange = vi.fn();
    render(
      <ThemeProvider>
        <ModelPerformanceCharts
          points={[
            { date: '2026-07-11', play_type: 'all', model_name: 'elo_rating', hit_rate: 0.45, sample_size: 10 },
            { date: '2026-07-12', play_type: 'all', model_name: 'elo_rating', hit_rate: 0.55, sample_size: 20 },
            { date: '2026-07-12', play_type: 'spf', model_name: 'elo_rating', hit_rate: 0.5, sample_size: 12 },
          ]}
          samples={[
            {
              play_type: 'all', model_name: 'elo_rating', total_samples: 20,
              settled_dates: 2, first_date: '2026-07-11', last_date: '2026-07-12',
            },
          ]}
          days={365}
          modelNames={['elo_rating']}
          selectedModels={['elo_rating']}
          playType="spf"
          window={20}
          onPlayTypeChange={onPlayTypeChange}
        />
      </ThemeProvider>,
    );

    expect(screen.getByText('胜平负 · 模型对比')).toBeInTheDocument();
    expect(screen.getByText('命中率仅作辅助趋势；正式结论以 Brier、Log Loss 与校准表现为主。')).toBeInTheDocument();
    expect(screen.getAllByText('Elo 实力评分').length).toBeGreaterThan(0);
    expect(screen.getByText('样本日期不足')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '胜平负 · 模型对比滚动命中率对比' })).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('data-height', '500');
    expect(screen.getAllByRole('img')).toHaveLength(1);
    const tabs = screen.getByRole('tablist', { name: '模型表现图表' });
    expect(tabs).toHaveTextContent('跨玩法概览');
    expect(tabs).toHaveTextContent('胜平负');
    expect(tabs).toHaveTextContent('让球胜平负');
    expect(tabs).toHaveTextContent('比分');
    expect(tabs).toHaveTextContent('总进球数');
    expect(tabs).toHaveTextContent('半全场');
    expect(screen.getByRole('tab', { name: '胜平负' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: '比分' }));
    expect(onPlayTypeChange).toHaveBeenCalledWith('bf');
    expect(screen.getByText('查看图表数据')).toBeInTheDocument();
  });
});
