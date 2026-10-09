import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReportResearchSummary from './ReportResearchSummary';

const apiMocks = vi.hoisted(() => ({ snapshot: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { reportAutomation: { snapshot: apiMocks.snapshot } },
}));

describe('ReportResearchSummary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    apiMocks.snapshot.mockResolvedValueOnce({ report: { sourceType: 'post_monthly', sourceRef: '2026-07', schemaVersion: 1, researchMetrics: null } });
    render(<ReportResearchSummary sourceType="post_monthly" sourceRef="2026-07" />);

    await waitFor(() => expect(apiMocks.snapshot).toHaveBeenCalled());
    expect(screen.getByText('该历史报告未包含量化指标。')).toBeInTheDocument();
  });
  it('offers a retry after first failure and preserves this period after refresh failure', async () => {
    apiMocks.snapshot.mockRejectedValueOnce(new Error('快照超时'));
    render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('快照超时');
    fireEvent.click(screen.getByRole('button',{name:'刷新量化复盘指标'}));
    expect(await screen.findByText('+¥20.00')).toBeInTheDocument();
    apiMocks.snapshot.mockRejectedValueOnce(new Error('暂不可读'));
    fireEvent.click(screen.getByRole('button',{name:'刷新量化复盘指标'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('保留本查询上次成功数据');
    expect(screen.getByText('+¥20.00')).toBeInTheDocument();
  });
  it('does not coerce missing, null or blank finance into zero or NaN', async () => {
    const response=await apiMocks.snapshot(); apiMocks.snapshot.mockClear();
    apiMocks.snapshot.mockResolvedValue({...response,report:{...response.report,dailyReview:{actualStake:null,realPrize:'',realProfitLoss:null,realRoi:null}}});
    render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('量化复盘指标');
    for(const label of ['实际投入','实际返还','实际盈亏','实际 ROI']) expect(screen.getByText(label).nextElementSibling).toHaveTextContent('—');
    expect(screen.queryByText('¥0.00')).not.toBeInTheDocument(); expect(screen.queryByText('NaN%')).not.toBeInTheDocument();
  });
  it('shows real zero and negative profit with its own sign class', async () => {
    const response=await apiMocks.snapshot(); apiMocks.snapshot.mockClear();
    apiMocks.snapshot.mockResolvedValue({...response,report:{...response.report,dailyReview:{actualStake:0,realPrize:0,realProfitLoss:-20,realRoi:0}}});
    render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('量化复盘指标');
    expect(screen.getByText('实际 ROI').nextElementSibling).toHaveTextContent('0.00%');
    expect(screen.getByText('¥-20.00')).toHaveClass('automatic-report-profit-negative');
  });
  it('isolates periods and ignores a late previous snapshot', async () => {
    let resolve!: (v:unknown)=>void; apiMocks.snapshot.mockReturnValueOnce(new Promise(r=>{resolve=r;}));
    const {rerender}=render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-08" />);
    rerender(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('+¥20.00');
    resolve({report:{sourceType:'post_daily',sourceRef:'2026-08-08',researchMetrics:null}});
    await waitFor(()=>expect(screen.getByText('+¥20.00')).toBeInTheDocument());
  });
  it('clears previous-period metrics even when the next period fails', async () => {
    const {rerender}=render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('+¥20.00'); apiMocks.snapshot.mockRejectedValueOnce(new Error('新期间失败'));
    rerender(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-10" />);
    await screen.findByRole('alert'); expect(screen.queryByText('+¥20.00')).not.toBeInTheDocument();
  });
  it('rejects mismatched report source and clears a valid empty snapshot', async () => {
    const {rerender}=render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-10" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('复盘快照与所选期间不一致');
    rerender(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);
    await screen.findByText('+¥20.00'); apiMocks.snapshot.mockResolvedValueOnce({report:null});
    fireEvent.click(screen.getByRole('button',{name:'刷新量化复盘指标'}));
    expect(await screen.findByText('本期暂无冻结复盘快照')).toBeInTheDocument(); expect(screen.queryByText('+¥20.00')).not.toBeInTheDocument();
  });
  it('non-finite research and outcome percentages display as missing', async () => {
    const response=await apiMocks.snapshot(); apiMocks.snapshot.mockClear();
    response.report.researchMetrics.averageEdge=NaN; response.report.performanceMetrics.brierScore=Infinity;
    apiMocks.snapshot.mockResolvedValue(response);
    render(<ReportResearchSummary sourceType="post_daily" sourceRef="2026-08-09" />);
    const region=await screen.findByRole('region',{name:'真实赛果评价'});
    expect(within(region).getByText('Brier Score').nextElementSibling).toHaveTextContent('—');
    expect(screen.getByText('平均 Edge').nextElementSibling).toHaveTextContent('—');
  });

});
