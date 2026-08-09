import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PredictionModelOverviewPanel from './PredictionModelOverviewPanel';

const apiMocks = vi.hoisted(() => ({ modelOverview: vi.fn() }));

vi.mock('../core/apiClient', () => ({
  api: { modelOverview: apiMocks.modelOverview },
}));

describe('PredictionModelOverviewPanel', () => {
  beforeEach(() => {
    apiMocks.modelOverview.mockResolvedValue({
      total: 4,
      models: [
        {
          code: 'market_baseline', isActive: true, version: '1.0.0',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: null,
          trainingEndDate: null, validPredictionMatchCount: 18,
          latestPredictionAt: '2026-08-09T06:30:00',
        },
        {
          code: 'elo_rating', isActive: false, version: null,
          versionCreatedAt: null, trainingStartDate: null, trainingEndDate: null,
          validPredictionMatchCount: 0, latestPredictionAt: null,
        },
        {
          code: 'maher_poisson', isActive: true, version: 'mle-1',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: '2024-01-01',
          trainingEndDate: '2026-08-01', validPredictionMatchCount: 12,
          latestPredictionAt: '2026-08-09T06:30:00',
        },
        {
          code: 'dixon_coles', isActive: true, version: 'mle-1',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: '2024-01-01',
          trainingEndDate: '2026-08-01', validPredictionMatchCount: 12,
          latestPredictionAt: '2026-08-09T06:30:00',
        },
      ],
    });
  });

  it('说明四个预测模型，并呈现运行状态和推荐边界', async () => {
    render(<PredictionModelOverviewPanel />);

    expect(await screen.findByRole('heading', { name: '预测模型说明' })).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(4);
    expect(screen.getByText('市场赔率基准')).toBeInTheDocument();
    expect(screen.getAllByText('已启用')[0]).toHaveAttribute('data-status', 'enabled');
    expect(screen.getByText('未启用')).toHaveAttribute('data-status', 'disabled');
    expect(screen.getByText(/单一模型不会直接生成投注推荐/)).toBeInTheDocument();
  });
});
