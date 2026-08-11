import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ModelsPage from './ModelsPage';
import { LanguageProvider } from '../app/LanguageContext';
import { LANGUAGE_STORAGE_KEY } from '../app/language';

const apiMocks = vi.hoisted(() => ({
  predictions: vi.fn(),
  evaluationSummary: vi.fn(),
  performanceHistory: vi.fn(),
  modelOverview: vi.fn(),
  calibrationProfiles: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    predictions: apiMocks.predictions,
    modelOverview: apiMocks.modelOverview,
    calibrationProfiles: apiMocks.calibrationProfiles,
    analysis: {
      evaluationSummary: apiMocks.evaluationSummary,
      performanceHistory: apiMocks.performanceHistory,
    },
  },
}));

vi.mock('../visualization/ModelPerformanceCharts', () => ({
  default: () => <div>五种玩法模型曲线</div>,
}));
vi.mock('./models/ModelDiagnosticsPanel', () => ({ default: () => <div>模型诊断面板</div> }));

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
        {
          id: 2,
          match_id: 102,
          predict_time: '2026-07-14T12:05:00',
          model_name: 'market_baseline',
          play_type: 'spf',
          option_code: '1',
          raw_model_probability: 0.31,
          model_probability: 0.31,
          feature_adjusted: false,
          market_probability: 0.33,
          fair_odds: 3.22,
          ev: -0.02,
          confidence: 0.6,
          home_team: '法国',
          away_team: '西班牙',
        },
      ],
      total: 4187,
      summary: {
        total: 4187, positive_ev_count: 1632, avg_confidence: 0.714,
        model_count: 19, latest_predict_time: '2026-07-14T12:05:00',
      },
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
          avg_market_probability_move: 0.01,
          avg_closing_edge: 0.02,
          avg_odds_clv: null,
          paired_market_samples: 10,
          brier_improvement_vs_market: -0.01,
          brier_improvement_ci_low: -0.04,
          brier_improvement_ci_high: 0.02,
          sample_status: 'monitoring',
          is_publishable: false,
        },
      ],
      overall: {
        total_evaluated: 10,
        overall_brier: 0.2,
        overall_logloss: 0.5,
        publication_min_samples: 100,
        publishable_models: 0,
      },
    });
    apiMocks.performanceHistory.mockResolvedValue({
      status: 'ok',
      metric: 'rolling_hit_rate',
      window: 20,
      days: 365,
      points: [],
      samples: [],
    });
    apiMocks.modelOverview.mockResolvedValue({ total: 0, models: [] });
    apiMocks.calibrationProfiles.mockResolvedValue({
      profiles: [], trends: [],
      policy: { sampleThreshold: 300, improvementThreshold: 0.005, affectsDecisionPath: false },
    });
  });

  it('将模型内部代码统一显示为易懂的中文名称', async () => {
    render(<ModelsPage />);

    expect((await screen.findAllByText('Elo 实力评分')).length).toBeGreaterThan(0);
    expect(screen.getByText('主胜')).toBeInTheDocument();
    expect(screen.getAllByText('原始概率').length).toBeGreaterThan(0);
    expect(screen.getAllByText('最终概率').length).toBeGreaterThan(0);
    expect(screen.getByText('特征已修正')).toBeInTheDocument();
    expect(screen.queryByText('elo_rating')).not.toBeInTheDocument();
    expect(screen.getByText('五种玩法模型曲线')).toBeInTheDocument();
    expect(screen.getByText(/每个模型名称与比赛只计一次/)).toBeInTheDocument();
    expect(screen.getByText(/市场概率变化、模型收盘优势与赔率 CLV 分开呈现/)).toBeInTheDocument();
    expect(screen.getByText('目前没有达到正式评估门槛的模型')).toBeInTheDocument();
    expect(screen.getByText('仅观察')).toBeInTheDocument();
    expect(screen.getByText('4187')).toBeInTheDocument();
  });

  it('将预测按模型折叠分组，便于分别查看每个模型的明细', async () => {
    const { container } = render(<ModelsPage />);

    expect(await screen.findByText('Elo 实力评分（1 条）')).toBeInTheDocument();
    expect(screen.getByText('市场赔率基准（1 条）')).toBeInTheDocument();
    expect(screen.getAllByText('展开预测明细')).toHaveLength(2);
    const groups = container.querySelectorAll<HTMLDetailsElement>('.model-prediction-group');
    expect(groups).toHaveLength(2);
    expect(groups[0].open).toBe(false);

    fireEvent.click(groups[0].querySelector('summary')!);
    expect(groups[0].open).toBe(true);
  });

  it('评估指标接口失败时明确显示错误，而不是误报需要结算数据', async () => {
    apiMocks.evaluationSummary.mockRejectedValue(new Error('服务暂不可用'));

    render(<ModelsPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('评估指标加载失败，请稍后重试');
    expect(screen.queryByText('暂无已结算评估数据')).not.toBeInTheDocument();
  });

  it('切换为 English 后翻译完整页面的核心内容', async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
    render(<LanguageProvider><ModelsPage /></LanguageProvider>);
    expect(await screen.findByRole('heading', { name: 'Model performance' })).toBeInTheDocument();
    expect(screen.getByText('Independent-sample evaluation')).toBeInTheDocument();
    expect(screen.getByText(/Each model name and match is counted once/)).toBeInTheDocument();
    expect(screen.getAllByText('Elo strength rating').length).toBeGreaterThan(0);
    expect(screen.queryByText('独立样本评估')).not.toBeInTheDocument();
    localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  });
});
