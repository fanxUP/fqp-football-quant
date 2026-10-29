import { fireEvent, render, screen } from '@testing-library/react';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildRadarOption, FeatureImportanceTab, ModelCompareTab, ShapExplainTab } from './AnalysisPage';
import type { ModelCompareItem } from '../core/types';
import ModelDiagnosticsPanel from './models/ModelDiagnosticsPanel';

const mocks = vi.hoisted(() => ({ compare: vi.fn(), importance: vi.fn(), modelInfo: vi.fn(), shap: vi.fn() }));
vi.mock('../core/apiClient', () => ({ api: { analysis: {
  modelCompare: mocks.compare,
  featureImportance: mocks.importance,
  featureModelInfo: mocks.modelInfo,
  shapExplanation: mocks.shap,
  recommendations: async () => ({ recommendations: [] }),
  calibration: async () => ({ bins: [], ece: 0, mce: 0, n_predictions: 0 }),
} } }));
vi.mock('../shared/components/ChartCard', () => ({ default: ({ emptyReason, title }: { emptyReason?: string; title?: string }) => <div>{title}{emptyReason}</div> }));
vi.mock('./RecommendationsPage', () => ({ default: () => null }));
vi.mock('../features/analysis/FeatureSnapshotPanel', () => ({ default: () => null }));
vi.mock('./agent-workspace/BusinessInterpretationPanel', () => ({ default: () => null }));

function model(name: string, changes: Partial<ModelCompareItem> = {}): ModelCompareItem {
  return { name, n_predictions: 20, brier: 0.4, log_loss: 0.8, rps: 0.2,
    market_probability_move: null, closing_edge: null, odds_clv: null, flb_score: null,
    roi: 0.1, sharpe: 1, hit_rate: 0.5, profit_factor: 1.1, ...changes };
}

describe('模型对比的未知指标', () => {
  it('不将缺失或非有限指标当成低损失高分，比较仅使用共同已知维度', () => {
    const missing = model('未知', { brier: null, sharpe: Number.NaN });
    const option = buildRadarOption([missing, model('已知')]);
    expect(option.radar.indicator.map((axis) => axis.name)).not.toContain('布里尔分数 ↓');
    expect(option.radar.indicator.map((axis) => axis.name)).not.toContain('夏普');
    expect(option.series[0].data.every((entry) => entry.value.length === 4)).toBe(true);
    expect(option.series[0].data.flatMap((entry) => entry.value).every(Number.isFinite)).toBe(true);
  });

  it('保留已知零值的真实比较语义', () => {
    const option = buildRadarOption([model('零损失', { brier: 0 }), model('有损失')]);
    expect(option.series[0].data[0].value[0]).toBe(1);
    expect(option.series[0].data[1].value[0]).toBe(0);
  });

  it('缺指标时表格正常显示未知，并说明雷达图采用共同维度', async () => {
    mocks.compare.mockResolvedValue({ status: 'ok', models: [model('缺失模型', {
      brier: null, log_loss: null,
      roi: null, hit_rate: null,
    })] });
    render(<ModelCompareTab />);
    expect(await screen.findByText('缺失模型')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByText(/共同已知/).length).toBeGreaterThan(0);
  });

  it('模型诊断的共享对比表格也能读取未知损失', async () => {
    mocks.compare.mockResolvedValue({ status: 'ok', models: [model('未知诊断模型', {
      brier: null, log_loss: null,
    })] });
    render(<ModelDiagnosticsPanel modelNames={['未知诊断模型']} />);
    await screen.findByText('样本不足，暂不能生成可靠校准曲线');
    fireEvent.click(screen.getByRole('tab', { name: '模型对比' }));
    expect(await screen.findByText('未知诊断模型')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });
});

function readyImportance(nSamples = 150, warning: string | null = null) {
  return { status: 'ok', method: 'permutation', rankings: [
    { feature: 'home_rest_days', label: '主队休息天数', importance: 0.1 },
  ], model_accuracy: 0.6, n_features: 1, model_info: {
    status: 'ok', n_samples: nSamples, n_features: 1, train_accuracy: 0.6,
    trained_at: '2026-10-29T00:00:00+00:00', artifact_id: 'fixture', warning,
  } };
}

describe('解释模型工件读取', () => {
  beforeEach(() => {
    mocks.importance.mockReset();
    mocks.modelInfo.mockReset();
    mocks.shap.mockReset();
  });

  it('一次读取排名和同版本信息，加载时不再声称训练', async () => {
    mocks.importance.mockResolvedValue(readyImportance());
    render(<FeatureImportanceTab />);
    expect(screen.getByText('读取特征重要性...')).toBeInTheDocument();
    expect(await screen.findByText('150')).toBeInTheDocument();
    expect(screen.getByText('特征重要性排名（排列重要性）')).toBeInTheDocument();
    expect(mocks.importance).toHaveBeenCalledTimes(1);
    expect(mocks.modelInfo).not.toHaveBeenCalled();
    expect(screen.queryByText(/至少50条/)).not.toBeInTheDocument();
  });

  it('保留后台真实未就绪原因，重试只重新读取', async () => {
    mocks.importance.mockResolvedValueOnce({ status: 'error', error: '训练数据不足（需要至少100场独立已结算比赛）' })
      .mockResolvedValueOnce(readyImportance());
    render(<FeatureImportanceTab />);
    expect(await screen.findByText(/需要至少100场独立已结算比赛/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('150')).toBeInTheDocument();
    expect(mocks.importance).toHaveBeenCalledTimes(2);
    expect(mocks.modelInfo).not.toHaveBeenCalled();
  });

  it('更新失败继续显示旧有效结果及告警，新结果到达后清除告警', async () => {
    mocks.importance.mockResolvedValueOnce(readyImportance(150, '训练任务未成功'))
      .mockResolvedValueOnce(readyImportance(180));
    render(<FeatureImportanceTab />);
    expect(await screen.findByRole('status')).toHaveTextContent('当前显示上一份有效结果：训练任务未成功');
    expect(screen.getByText('150')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '增益重要性' }));
    expect(await screen.findByText('180')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(mocks.importance).toHaveBeenLastCalledWith({ method: 'gain', top_n: 20 });
  });

  it('切换方法后，较慢的旧请求不能覆盖新排名和模型信息', async () => {
    let finishOld!: (result: ReturnType<typeof readyImportance>) => void;
    mocks.importance.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce(readyImportance(240));
    render(<FeatureImportanceTab />);
    fireEvent.click(screen.getByRole('button', { name: '增益重要性' }));
    expect(await screen.findByText('240')).toBeInTheDocument();
    await act(async () => { finishOld(readyImportance(120)); });
    expect(screen.getByText('240')).toBeInTheDocument();
    expect(screen.queryByText('120')).not.toBeInTheDocument();
  });

  it('网络读取失败明确显示错误并允许重试', async () => {
    mocks.importance.mockRejectedValueOnce(new Error('network fixture')).mockResolvedValueOnce(readyImportance());
    render(<FeatureImportanceTab />);
    expect(await screen.findByRole('button', { name: '重试' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('150')).toBeInTheDocument();
  });

  it('SHAP 页面显示同一后台未就绪原因', async () => {
    mocks.shap.mockResolvedValue({ status: 'error', error: '解释模型尚未就绪，等待后台训练任务生成结果' });
    render(<ShapExplainTab initialMatchId={88} />);
    expect(await screen.findByText('解释模型尚未就绪，等待后台训练任务生成结果')).toBeInTheDocument();
  });

  it('SHAP 读取上一份有效工件时保留更新失败提示', async () => {
    mocks.shap.mockResolvedValue({ status: 'ok', match_id: 88, home_team: '主队', away_team: '客队',
      predicted_probs: { home: 0.5, draw: 0.3, away: 0.2 }, shap_values: [], base_values: [],
      warning: '后台训练失败' });
    render(<ShapExplainTab initialMatchId={88} />);
    expect(await screen.findByRole('status')).toHaveTextContent('后台训练失败');
    expect(screen.getByText('50.0%')).toBeInTheDocument();
  });

  it('SHAP 原始分数基准不被显示成百分比', async () => {
    mocks.shap.mockResolvedValue({ status: 'ok', match_id: 88, home_team: '主队', away_team: '客队',
      predicted_probs: { home: 0.5, draw: 0.3, away: 0.2 }, shap_values: [], base_values: [0.2, 0.3, 0.4] });
    render(<ShapExplainTab initialMatchId={88} />);
    expect(await screen.findByText('0.4000 / 0.3000 / 0.2000')).toBeInTheDocument();
    expect(screen.getByText('基准值（原始分数）')).toBeInTheDocument();
    expect(screen.queryByText('40.0% / 30.0% / 20.0%')).not.toBeInTheDocument();
    expect(screen.getByText('50.0%')).toBeInTheDocument();
  });
});
