import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { buildRadarOption, ModelCompareTab } from './AnalysisPage';
import type { ModelCompareItem } from '../core/types';
import ModelDiagnosticsPanel from './models/ModelDiagnosticsPanel';

const mocks = vi.hoisted(() => ({ compare: vi.fn() }));
vi.mock('../core/apiClient', () => ({ api: { analysis: {
  modelCompare: mocks.compare,
  recommendations: async () => ({ recommendations: [] }),
  calibration: async () => ({ bins: [], ece: 0, mce: 0, n_predictions: 0 }),
} } }));
vi.mock('../shared/components/ChartCard', () => ({ default: ({ emptyReason }: { emptyReason?: string }) => <div>{emptyReason}</div> }));
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
