import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReviewsPage from './ReviewsPage';

const apiMocks = vi.hoisted(() => ({
  daily: vi.fn(),
  playTypeWinRate: vi.fn(),
  weekly: vi.fn(),
  monthly: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    reviews: apiMocks,
    settlements: { list: vi.fn() },
  },
}));

vi.mock('../shared/components/DataTable', () => ({
  default: ({ rows, onRowClick }: { rows: Array<{ review_date?: string; id?: number }>; onRowClick?: (row: { review_date?: string; id?: number }) => void }) => (
    <div>{rows.map((row) => <button key={row.review_date ?? row.id} onClick={() => onRowClick?.(row)}>{row.review_date ?? row.id}</button>)}</div>
  ),
}));
vi.mock('../shared/components/ChartCard', () => ({ default: () => <div /> }));
vi.mock('../shared/components/Card', () => ({ default: ({ children }: { children: React.ReactNode }) => <section>{children}</section> }));
vi.mock('./reviews/PlayTypeWinRateChart', () => ({ default: () => <div /> }));
vi.mock('./reviews/RealProfitLossChart', () => ({ default: () => <div /> }));
vi.mock('./reviews/MatchReviewCards', () => ({ default: () => <div>单场复盘</div> }));
vi.mock('./reviews/ReportAutomationPanel', () => ({ default: () => <div /> }));
vi.mock('./reviews/AutomaticReportArchivePanel', () => ({ default: () => <div>自动赛后报告</div> }));
vi.mock('./reviews/ReportResearchSummary', () => ({ default: () => <div>量化复盘指标</div> }));

describe('ReviewsPage', () => {
  beforeEach(() => {
    apiMocks.daily.mockResolvedValue({ reviews: [{
      review_date: '2026-08-09', official_match_count: 1, analyzable_match_count: 1,
      simulation_ticket_count: 0, real_ticket_count: 0, real_profit_loss: 0,
      summary_text: '旧日报摘要，不应再展示', suggested_stake: 0, actual_stake: 0,
      budget_usage_rate: 0, max_single_ticket_loss: 0,
    }] });
    apiMocks.playTypeWinRate.mockResolvedValue({ data: [] });
    apiMocks.weekly.mockResolvedValue({ reviews: [] });
    apiMocks.monthly.mockResolvedValue({ reviews: [] });
  });

  it('日报详情只展示核心指标和自动赛后报告，不再展示旧的单场复盘长表', async () => {
    render(<ReviewsPage />);

    fireEvent.change(await screen.findByLabelText('日期索引'), { target: { value: '2026-08-09' } });

    expect(await screen.findByText('自动赛后报告')).toBeInTheDocument();
    expect(screen.getByText('量化复盘指标')).toBeInTheDocument();
    expect(screen.queryByText('旧日报摘要，不应再展示')).not.toBeInTheDocument();
    expect(screen.queryByText('赛后复盘解读')).not.toBeInTheDocument();
    expect(screen.queryByText('单场复盘')).not.toBeInTheDocument();
  });
});
