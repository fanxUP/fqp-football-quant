import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ModelPerformanceCharts from './ModelPerformanceCharts';
import { ThemeProvider } from '../app/ThemeContext';

vi.mock('./timeseries/LightweightLineChart', () => ({
  default: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}));

describe('ModelPerformanceCharts', () => {
  it('渲染综合视图、五种玩法和可读模型排名', () => {
    render(
      <ThemeProvider>
        <ModelPerformanceCharts
          points={[
            { date: '2026-07-11', play_type: 'all', model_name: 'elo_rating', hit_rate: 0.45, sample_size: 10 },
            { date: '2026-07-12', play_type: 'all', model_name: 'elo_rating', hit_rate: 0.55, sample_size: 20 },
            { date: '2026-07-12', play_type: 'spf', model_name: 'elo_rating', hit_rate: 0.5, sample_size: 12 },
          ]}
          window={20}
        />
      </ThemeProvider>,
    );

    expect(screen.getByText('综合表现 · 模型对比')).toBeInTheDocument();
    expect(screen.getByText('Elo 实力评分')).toBeInTheDocument();
    expect(screen.getByText('55.0%')).toBeInTheDocument();
    expect(screen.getAllByText('样本日期不足')).toHaveLength(2);
    expect(screen.getAllByText(/· 模型对比$/)).toHaveLength(6);
    expect(screen.getByRole('img', { name: '胜平负模型滚动命中率对比' })).toBeInTheDocument();
  });
});
