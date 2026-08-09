import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PredictionModelOverviewPanel from './PredictionModelOverviewPanel';

const apiMocks = vi.hoisted(() => ({ modelOverview: vi.fn(), calibrationProfiles: vi.fn() }));

vi.mock('../core/apiClient', () => ({
  api: { modelOverview: apiMocks.modelOverview, calibrationProfiles: apiMocks.calibrationProfiles },
}));

describe('PredictionModelOverviewPanel', () => {
  beforeEach(() => {
    apiMocks.calibrationProfiles.mockResolvedValue({
      policy: { sampleThreshold: 300, improvementThreshold: 0.005, affectsDecisionPath: false },
      trends: [{ modelCode: 'market_baseline', status: 'improving', label: '近期改善', latestLogLoss: 1.02, previousLogLoss: 1.04, logLossChange: -0.02, profileCount: 2, comparison: { status: 'comparable', label: '样本可比', sampleRatio: 1.067 }, affectsDecisionPath: false }],
      profiles: [{ modelCode: 'market_baseline', sampleCount: 320, logLossBefore: 1.04, logLossAfter: 1.02, temperature: 1.15, createdAt: '2026-08-09T23:42:00', review: { status: 'ready_for_manual_review', label: '具备人工评审基础', affectsDecisionPath: false } }],
    });
    apiMocks.modelOverview.mockResolvedValue({
      total: 9,
      models: [
        {
          code: 'market_baseline', isActive: true, version: '1.0.0',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: null,
          trainingEndDate: null, validPredictionMatchCount: 18,
          latestPredictionAt: '2026-08-09T06:30:00', calibration: {
            methodName: 'temperature_scaling_v1', sampleCount: 240,
            logLossBefore: 1.024, logLossAfter: 1.001, temperature: 1.15,
            trainingEndDate: '2026-08-08', rolloutMode: 'shadow',
          },
        },
        {
          code: 'elo_rating', isActive: false, version: null,
          versionCreatedAt: null, trainingStartDate: null, trainingEndDate: null,
          validPredictionMatchCount: 0, latestPredictionAt: null, calibration: null,
        },
        {
          code: 'maher_poisson', isActive: true, version: 'mle-1',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: '2024-01-01',
          trainingEndDate: '2026-08-01', validPredictionMatchCount: 12,
          latestPredictionAt: '2026-08-09T06:30:00', calibration: null,
        },
        {
          code: 'dixon_coles', isActive: true, version: 'mle-1',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: '2024-01-01',
          trainingEndDate: '2026-08-01', validPredictionMatchCount: 12,
          latestPredictionAt: '2026-08-09T06:30:00', calibration: null,
        },
        {
          code: 'glicko2_rating', isActive: true, version: '1.0.0',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: null,
          trainingEndDate: null, validPredictionMatchCount: 0, latestPredictionAt: null, calibration: null,
        },
        {
          code: 'bivariate_poisson', isActive: true, version: '1.0.0',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: '2024-01-01',
          trainingEndDate: '2026-08-01', validPredictionMatchCount: 0,
          latestPredictionAt: null, calibration: null,
        },
        {
          code: 'xgboost_shadow', isActive: true, version: '1.0.0',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: null,
          trainingEndDate: null, validPredictionMatchCount: 0,
          latestPredictionAt: null, calibration: null,
        },
        {
          code: 'logistic_shadow', isActive: true, version: '1.0.0',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: null,
          trainingEndDate: null, validPredictionMatchCount: 0,
          latestPredictionAt: null, calibration: null,
        },
        {
          code: 'bayesian_form', isActive: true, version: '1.0.0',
          versionCreatedAt: '2026-08-09T06:30:00', trainingStartDate: null,
          trainingEndDate: null, validPredictionMatchCount: 0,
          latestPredictionAt: null, calibration: null,
        },
      ],
    });
  });

  it('说明九个预测模型，并呈现运行状态和推荐边界', async () => {
    render(<PredictionModelOverviewPanel />);

    expect(await screen.findByRole('heading', { name: '预测模型说明' })).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(10);
    expect(screen.getByRole('heading', { name: '市场赔率基准' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Glicko-2 强度评级' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '双变量泊松进球模型' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'XGBoost 赛前特征模型' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '逻辑回归赛前特征模型' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '贝叶斯近期状态模型' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '随机森林赛前特征模型' })).toBeInTheDocument();
    expect(screen.getAllByText('已启用')[0]).toHaveAttribute('data-status', 'enabled');
    expect(screen.getByText('未启用')).toHaveAttribute('data-status', 'disabled');
    expect(screen.getByText(/概率校准：影子验证/)).toBeInTheDocument();
    expect(screen.getByText(/对数损失 1.024 → 1.001/)).toBeInTheDocument();
    expect(await screen.findByText('概率校准监测')).toBeInTheDocument();
    expect(screen.getByText('验证 320 场')).toBeInTheDocument();
    expect(screen.getByText('具备人工评审基础')).toBeInTheDocument();
    expect(screen.getByText('近期改善')).toBeInTheDocument();
    expect(screen.getByText('样本可比')).toBeInTheDocument();
    expect(screen.getByText(/还须至少两期样本可比的校准记录/)).toBeInTheDocument();
    expect(screen.getByText(/单一模型不会直接生成投注推荐/)).toBeInTheDocument();
  });
});
