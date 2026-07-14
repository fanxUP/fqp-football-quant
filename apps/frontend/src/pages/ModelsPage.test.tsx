import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ModelsPage from './ModelsPage';

const apiMocks = vi.hoisted(() => ({
  predictions: vi.fn(),
  evaluationSummary: vi.fn(),
  performanceHistory: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    predictions: apiMocks.predictions,
    analysis: {
      evaluationSummary: apiMocks.evaluationSummary,
      performanceHistory: apiMocks.performanceHistory,
    },
  },
}));

vi.mock('../visualization/ModelPerformanceCharts', () => ({
  default: () => <div>五种玩法模型曲线</div>,
}));

describe('ModelsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.predictions.mockResolvedValue({
      predictions: [
        {
          id: 1,
          match_id: 101,
          predict_time: '2026-07-14T12:00:00',
          model_name: 'elo_rating',
          play_type: 'spf',
          option_code: '3',
          raw_model_probability: 0.48,
          model_probability: 0.52,
          feature_adjusted: true,
          market_probability: 0.5,
          fair_odds: 1.92,
          ev: 0.04,
          confidence: 0.8,
          home_team: '英格兰',
          away_team: '阿根廷',
        },
      ],
      total: 1,
    });
    apiMocks.evaluationSummary.mockResolvedValue({
      status: 'ok',
      models: [
        {
          model_name: 'elo_rating',
          n: 10,
          avg_brier: 0.2,
          avg_logloss: 0.5,
          avg_rps: 0.1,
          avg_clv: 0.01,
        },
      ],
      overall: { total_evaluated: 10, overall_brier: 0.2, overall_logloss: 0.5 },
    });
    apiMocks.performanceHistory.mockResolvedValue({
      status: 'ok',
      metric: 'rolling_hit_rate',
      window: 20,
      points: [],
    });
  });

  it('将模型内部代码统一显示为易懂的中文名称', async () => {
    render(<ModelsPage />);

    expect(await screen.findAllByText('Elo 实力评分')).toHaveLength(3);
    expect(screen.getByText('主胜')).toBeInTheDocument();
    expect(screen.getByText('原始概率')).toBeInTheDocument();
    expect(screen.getByText('最终概率')).toBeInTheDocument();
    expect(screen.getByText('特征已修正')).toBeInTheDocument();
    expect(screen.queryByText('elo_rating')).not.toBeInTheDocument();
    expect(screen.getByText('五种玩法模型曲线')).toBeInTheDocument();
  });
});
