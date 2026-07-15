import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ModelPerformanceCharts, { buildModelPerformanceOption } from './ModelPerformanceCharts';
import { ThemeProvider } from '../app/ThemeContext';

vi.mock('../shared/components/ChartCard', () => ({
  default: ({ title }: { title: string }) => <div>{title}</div>,
}));

describe('buildModelPerformanceOption', () => {
  it('按日期对齐同一玩法下的多模型曲线，并使用中文模型名', () => {
    const option = buildModelPerformanceOption([
      { date: '2026-07-11', play_type: 'spf', model_name: 'elo_rating', hit_rate: 0.5, sample_size: 4 },
      { date: '2026-07-12', play_type: 'spf', model_name: 'elo_rating', hit_rate: 0.6, sample_size: 8 },
      { date: '2026-07-12', play_type: 'spf', model_name: 'maher_poisson', hit_rate: 0.4, sample_size: 5 },
      { date: '2026-07-12', play_type: 'bf', model_name: 'maher_poisson', hit_rate: 0.2, sample_size: 5 },
    ], 'spf');

    expect(option?.xAxis).toMatchObject({ data: ['07-11', '07-12'] });
    expect(option?.series).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'Elo 实力评分', data: [50, 60] }),
      expect.objectContaining({ name: '马赫泊松进球模型', data: [null, 40] }),
    ]));
  });

  it('没有该玩法数据时返回空配置', () => {
    expect(buildModelPerformanceOption([], 'spf')).toBeNull();
  });

  it('在五种玩法之外增加一张全模型综合视图', () => {
    render(
      <ThemeProvider>
        <ModelPerformanceCharts
          points={[
            { date: '2026-07-12', play_type: 'all', model_name: 'elo_rating', hit_rate: 0.55, sample_size: 20 },
          ]}
          window={20}
        />
      </ThemeProvider>,
    );

    expect(screen.getByText('综合表现 · 模型对比')).toBeInTheDocument();
    expect(screen.getAllByText(/· 模型对比$/)).toHaveLength(6);
  });
});
