import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  bindings: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    predictions: apiMocks.predictions,
    modelProviders: { bindings: apiMocks.bindings },
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
    apiMocks.bindings.mockResolvedValue({ bindings: [] });
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
    fireEvent.click(screen.getByRole('button', { name: '加载全量预测统计' }));
    expect(await screen.findByText('4187')).toBeInTheDocument();
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

  it('拒绝重复预测身份并在刷新失败时保留研究证据', async () => {
    render(<ModelsPage />);
    await screen.findByRole('button', { name: /Elo 实力评分 · #1/ });
    const data = await apiMocks.predictions.mock.results[0].value;
    apiMocks.predictions.mockResolvedValueOnce({ ...data, predictions: [data.predictions[0], data.predictions[0]] });
    fireEvent.click(screen.getByRole('button', { name: '刷新预测记录' }));
    await screen.findAllByText(/预测记录身份、范围或指标格式不正确/);
    expect(screen.getByRole('button', { name: /Elo 实力评分 · #1/ })).toBeInTheDocument();
    expect(screen.getByText(/读取失败，保留上次成功证据/)).toBeInTheDocument();
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
  it('自动读取有界记录，全部统计按需加载且未知值不显示为零', async () => {
    render(<ModelsPage />);
    await screen.findByRole('button', { name: /Elo 实力评分 · #1/ });
    expect(apiMocks.predictions).toHaveBeenCalledExactlyOnceWith({ limit: 200, include_summary: false });
    const overview = screen.getByLabelText('预测概览');
    expect(within(overview).getAllByText('—').length).toBeGreaterThanOrEqual(4);
    expect(within(overview).queryByText('0')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '加载全量预测统计' }));
    await screen.findByText('4187');
    expect(apiMocks.predictions).toHaveBeenLastCalledWith({ summary_only: true });
  });

  it('全量统计失败不挡住研究记录，重试空统计保留真实零', async () => {
    render(<ModelsPage />);
    await screen.findByRole('button', { name: /Elo 实力评分 · #1/ });
    apiMocks.predictions.mockRejectedValueOnce(new Error('slow aggregate'));
    fireEvent.click(screen.getByRole('button', { name: '加载全量预测统计' }));
    await screen.findByText(/全量预测统计读取失败/);
    expect(screen.getByRole('button', { name: /Elo 实力评分 · #1/ })).toBeInTheDocument();
    apiMocks.predictions.mockResolvedValueOnce({ predictions: [], total: 0, summary: { total: 0, positive_ev_count: 0, model_count: 0, avg_confidence: null, latest_predict_time: null } });
    fireEvent.click(screen.getByRole('button', { name: '加载全量预测统计' }));
    await waitFor(() => expect(within(screen.getByLabelText('预测概览')).getAllByText('0')).toHaveLength(3));
  });

  it('统计重读失败保留全量口径，记录刷新不会覆盖统计', async () => {
    render(<ModelsPage />);
    await screen.findByRole('button', { name: /Elo 实力评分 · #1/ });
    fireEvent.click(screen.getByRole('button', { name: '加载全量预测统计' }));
    await screen.findByText('4187');
    apiMocks.predictions.mockRejectedValueOnce(new Error('timeout'));
    fireEvent.click(screen.getByRole('button', { name: '加载全量预测统计' }));
    await screen.findByText(/全量预测统计读取失败/);
    expect(screen.getByText('4187')).toBeInTheDocument();
    apiMocks.predictions.mockResolvedValueOnce({ predictions: [], total: null, summary: null });
    fireEvent.click(screen.getByRole('button', { name: '刷新预测记录' }));
    await screen.findByText('暂无预测记录');
    expect(screen.getByText('4187')).toBeInTheDocument();
  });

  it('拒绝错口径统计，并保留最近研究记录', async () => {
    render(<ModelsPage />);
    await screen.findByRole('button', { name: /Elo 实力评分 · #1/ });
    apiMocks.predictions.mockResolvedValueOnce({ predictions: [], total: 0, summary: { total: 1, positive_ev_count: 0, model_count: 1, avg_confidence: null, latest_predict_time: null } });
    fireEvent.click(screen.getByRole('button', { name: '加载全量预测统计' }));
    await screen.findByText(/全量统计格式或口径不正确/);
    expect(within(screen.getByLabelText('预测概览')).queryByText('0')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Elo 实力评分 · #1/ })).toBeInTheDocument();
  });

  it('统计请求未完成时不重复读取，也不影响刷新研究记录', async () => {
    render(<ModelsPage />);
    await screen.findByRole('button', { name: /Elo 实力评分 · #1/ });
    let complete!: (data: unknown) => void;
    apiMocks.predictions.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    const button = screen.getByRole('button', { name: '加载全量预测统计' });
    fireEvent.click(button); fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(apiMocks.predictions.mock.calls.filter(([params]) => params.summary_only === true)).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: '刷新预测记录' }));
    await waitFor(() => expect(apiMocks.predictions).toHaveBeenLastCalledWith({ limit: 200, include_summary: false }));
    complete({ predictions: [], total: 0, summary: { total: 0, positive_ev_count: 0, model_count: 0, avg_confidence: 0, latest_predict_time: null } });
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(within(screen.getByLabelText('预测概览')).getByText('0.0%')).toBeInTheDocument();
  });

});
