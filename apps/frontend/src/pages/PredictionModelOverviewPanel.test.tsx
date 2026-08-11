import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PredictionModelOverviewPanel from './PredictionModelOverviewPanel';

const apiMocks = vi.hoisted(() => ({ modelOverview: vi.fn(), calibrationProfiles: vi.fn() }));
vi.mock('../core/apiClient', () => ({ api: { modelOverview: apiMocks.modelOverview, calibrationProfiles: apiMocks.calibrationProfiles } }));

const metadata = (title: string) => ({
  title: { 'zh-CN': title, en: title }, summary: { 'zh-CN': '模型说明', en: 'Model summary' },
  output: { 'zh-CN': '胜平负概率。', en: '1X2 probabilities.' }, cadence: { 'zh-CN': '每日更新。', en: 'Daily.' },
  condition: { 'zh-CN': '需要有效数据。', en: 'Requires valid data.' }, role: { 'zh-CN': '仅提供概率信号。', en: 'Probability signal only.' }, stage: 'shadow' as const,
});

describe('PredictionModelOverviewPanel', () => {
  beforeEach(() => {
    apiMocks.calibrationProfiles.mockResolvedValue({
      policy: { sampleThreshold: 300, improvementThreshold: 0.005, affectsDecisionPath: false },
      trends: [{ modelCode: 'market_baseline', status: 'improving', label: '近期改善', latestLogLoss: 1.02, previousLogLoss: 1.04, logLossChange: -0.02, profileCount: 2, comparison: { status: 'comparable', label: '样本可比', sampleRatio: 1.067 }, affectsDecisionPath: false }],
      profiles: [{ modelCode: 'market_baseline', playType: 'spf', methodName: 'temperature_scaling_v1', version: 'v1', sampleCount: 320, logLossBefore: 1.04, logLossAfter: 1.02, temperature: 1.15, trainingEndDate: '2026-08-08', isActive: true, createdAt: '2026-08-09T23:42:00', review: { status: 'ready_for_manual_review', label: '具备人工评审基础', affectsDecisionPath: false } }],
    });
    apiMocks.modelOverview.mockResolvedValue({
      total: 3, catalogVersion: '2026-08-12', models: [
        { code: 'market_baseline', isActive: true, version: '1.0.0', versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: null, trainingEndDate: null, validPredictionMatchCount: 18, latestPredictionAt: '2026-08-09T06:30:00', metadata: metadata('市场赔率基准'), calibration: { methodName: 'temperature_scaling_v1', sampleCount: 240, logLossBefore: 1.024, logLossAfter: 1.001, temperature: 1.15, trainingEndDate: '2026-08-08', rolloutMode: 'shadow' } },
        { code: 'elo_rating', isActive: false, version: null, versionCreatedAt: null, trainingStartDate: null, trainingEndDate: null, validPredictionMatchCount: 0, latestPredictionAt: null, metadata: metadata('Elo 实力评分'), calibration: null },
        { code: 'maher_poisson', isActive: true, version: 'mle-1', versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: '2024-01-01', trainingEndDate: '2026-08-01', validPredictionMatchCount: 12, latestPredictionAt: '2026-08-09T06:30:00', metadata: metadata('Maher Poisson 进球模型'), calibration: null },
      ],
    });
  });

  it('默认收起后端模型目录，并在展开后显示运行与校准状态', async () => {
    render(<PredictionModelOverviewPanel />);
    const summary = await screen.findByText('预测模型说明');
    const details = summary.closest('details')!;
    expect(details.open).toBe(false);
    fireEvent.click(summary.closest('summary')!);
    expect(details.open).toBe(true);
    expect(screen.getAllByRole('article')).toHaveLength(3);
    expect(screen.getByRole('heading', { name: '市场赔率基准' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Maher Poisson 进球模型' })).toBeInTheDocument();
    expect(screen.getAllByText('已启用')[0]).toHaveAttribute('data-status', 'enabled');
    expect(screen.getByText('未启用')).toHaveAttribute('data-status', 'disabled');
    expect(screen.getByText(/概率校准：影子验证/)).toBeInTheDocument();
    expect(screen.getByText(/对数损失 1.024 → 1.001/)).toBeInTheDocument();
    expect(screen.getByText('概率校准监测')).toBeInTheDocument();
    expect(screen.getByText('具备人工评审基础')).toBeInTheDocument();
  });

  it('校准接口失败时明确提示接口错误', async () => {
    apiMocks.calibrationProfiles.mockRejectedValue(new Error('offline'));
    render(<PredictionModelOverviewPanel />);
    const summary = await screen.findByText('预测模型说明');
    fireEvent.click(summary.closest('summary')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('概率校准记录加载失败');
  });
});
