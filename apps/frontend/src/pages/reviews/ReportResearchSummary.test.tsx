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
        schemaVersion: 2,
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
    expect(screen.getByText('Poisson')).toBeInTheDocument();
    expect(apiMocks.snapshot).toHaveBeenCalledWith('post_daily', '2026-08-09');
  });

  it('clearly reports that an older report has no research metrics', async () => {
    apiMocks.snapshot.mockResolvedValueOnce({ report: { schemaVersion: 1, researchMetrics: null } });
    render(<ReportResearchSummary sourceType="post_monthly" sourceRef="2026-07" />);

    await waitFor(() => expect(apiMocks.snapshot).toHaveBeenCalled());
    expect(screen.getByText('该历史报告未包含量化指标。')).toBeInTheDocument();
  });
});
