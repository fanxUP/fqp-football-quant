import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReportResearchSummary from './ReportResearchSummary';

const apiMocks = vi.hoisted(() => ({ snapshot: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { reportAutomation: { snapshot: apiMocks.snapshot } },
}));

describe('ReportResearchSummary', () => {
  beforeEach(() => {
    apiMocks.snapshot.mockResolvedValue({
      report: {
        sourceType: 'post_daily',
        sourceRef: '2026-08-09',
        schemaVersion: 4,
        snapshotRevision: 2,
        interpretationRequiresRefresh: true,
        researchMetrics: {
          matchCount: 3,
          signalCoverageRate: 0.6667,
          evidenceCoverageRate: 1,
          averageEdge: 0.06,
          averageEv: 0.12,
        },
        dailyReview: { actualStake: 100, realPrize: 120, realProfitLoss: 20, realRoi: 0.2 },
        researchBreakdowns: {
          models: [{ key: 'Poisson', signalCount: 3, matchCount: 2, averageModelProbability: 0.65, averageMarketProbability: 0.55, averageEdge: 0.1, averageEv: 0.2 }],
          playTypes: [],
          leagues: [],
        },
        performanceMetrics: {
          sampleCount: 4,
          correctCount: 2,
          hitRate: 0.5,
          brierScore: 0.21,
          logLoss: 0.69,
          rps: 0.16,
          clvSampleCount: 4,
          averageClv: 0.03,
          averageClosingEdge: 0.04,
          averageClosingOdds: 2,
          pricedSampleCount: 4,
          unitStakeProfit: 1,
          unitStakeRoi: 0.25,
          calibrationError: 0.08,
          maximumCalibrationError: 0.12,
          maxLosingStreak: 2,
          currentStreakType: 'loss',
          currentStreakCount: 1,
          calibrationBins: [],
        },
        performanceBreakdowns: {
          models: [{ key: 'Poisson', sampleCount: 4, correctCount: 2, hitRate: 0.5, averageClv: 0.03, averageClosingEdge: 0.04, averageClosingOdds: 2, unitStakeProfit: 1, unitStakeRoi: 0.25, brierScore: 0.21, logLoss: 0.69 }],
          playTypes: [],
          leagues: [],
        },
        evidenceSummary: { evidenceCount: 2, coveredMatchCount: 1, preMatchCount: 1, postMatchCount: 1, newsEvidenceCount: 0, officialOrVerifiedCount: 2, missingMatchCount: 2 },
        errorAnalysis: { errorCount: 2, byType: [{ code: 'DRAW_UNDERESTIMATED', label: '低估平局', count: 2, suggestedAction: '复核平局先验' }] },
        strategySummary: { status: 'review_required', findings: ['主要错因是低估平局'], actions: ['复核平局先验'], safetyNotice: '只用于人工研究复盘' },
      },
    });
  });

  it('renders frozen outcome and research metrics instead of model prose', async () => {
    render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);

    expect(await screen.findByText('量化复盘指标')).toBeInTheDocument();
    expect(screen.getByText('实际盈亏')).toBeInTheDocument();
    expect(screen.getByText('+¥20.00')).toBeInTheDocument();
    expect(screen.getByText('平均 Edge')).toBeInTheDocument();
    expect(screen.getByText('6.00%')).toBeInTheDocument();
    expect(screen.getByText('模型信号分布')).toBeInTheDocument();
    expect(screen.getAllByText('Poisson').length).toBeGreaterThan(0);
    expect(screen.getByText('真实赛果评价')).toBeInTheDocument();
    expect(screen.getByText('Brier Score')).toBeInTheDocument();
    expect(screen.getByText('0.2100')).toBeInTheDocument();
    expect(screen.getByText('命中率')).toBeInTheDocument();
    expect(screen.getAllByText('50.00%').length).toBeGreaterThan(0);
    expect(screen.getByText('平均 CLV')).toBeInTheDocument();
    expect(screen.getByText('+3.00%')).toBeInTheDocument();
    expect(screen.getByText('可靠新闻证据：0 条')).toBeInTheDocument();
    expect(screen.getByText('低估平局 · 2 次')).toBeInTheDocument();
    expect(screen.getByText('只用于人工研究复盘')).toBeInTheDocument();
    expect(screen.getByText('该报告已完成第 2 次可追溯补跑；已归档的模型文字可能基于旧快照。')).toBeInTheDocument();
    expect(apiMocks.snapshot).toHaveBeenCalledWith('post_daily', '2026-08-09');
  });

  it('clearly reports that an older report has no research metrics', async () => {
    apiMocks.snapshot.mockResolvedValueOnce({ report: { schemaVersion: 1, researchMetrics: null } });
    render(<ReportResearchSummary sourceType="post_monthly" sourceRef="2026-07" />);

    await waitFor(() => expect(apiMocks.snapshot).toHaveBeenCalled());
    expect(screen.getByText('该历史报告未包含量化指标。')).toBeInTheDocument();
  });
});
