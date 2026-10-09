import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReviewsPage from './ReviewsPage';

const apiMocks = vi.hoisted(() => ({
  daily: vi.fn(),
  playTypeWinRate: vi.fn(),
  weekly: vi.fn(),
  monthly: vi.fn(),
  settlements: vi.fn(),
  errors: vi.fn(),
  summary: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    reviews: apiMocks,
    settlements: { list: apiMocks.settlements },
    errorAnalysis: { list: apiMocks.errors, summary: apiMocks.summary },
  },
}));

vi.mock('../shared/components/DataTable', () => ({
  default: ({ rows, columns }: { rows: Array<{ id?: number }>; columns: Array<{ key: string; render?: (value: unknown, row: { id?: number }) => React.ReactNode }> }) => (
    <div>{rows.map(row => <div key={row.id}>{row.id}{columns.find(c => c.key === 'actions')?.render?.(undefined, row)}</div>)}</div>
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
    vi.resetAllMocks();
    apiMocks.daily.mockResolvedValue({ reviews: [{
      review_date: '2026-08-09', official_match_count: 1, analyzable_match_count: 1,
      simulation_ticket_count: 0, real_ticket_count: 0, real_profit_loss: 0,
      summary_text: '旧日报摘要，不应再展示', suggested_stake: 0, actual_stake: 0,
      budget_usage_rate: 0, max_single_ticket_loss: 0,
    }] });
    apiMocks.playTypeWinRate.mockResolvedValue({ data: [] });
    apiMocks.weekly.mockResolvedValue({ reviews: [] });
    apiMocks.monthly.mockResolvedValue({ reviews: [] });
    apiMocks.settlements.mockResolvedValue({ settlements: [], total: 0 });
    apiMocks.errors.mockResolvedValue({ errors: [], total: 0 });
    apiMocks.summary.mockResolvedValue({ errors: [] });
  });

  it('日报详情只展示核心指标和自动赛后报告，不再展示旧的单场复盘长表', async () => {
    render(<ReviewsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '查看 2026-08-09 日报' }));

    expect(await screen.findByText('自动赛后报告')).toBeInTheDocument();
    expect(screen.getByText('量化复盘指标')).toBeInTheDocument();
    expect(screen.queryByText('旧日报摘要，不应再展示')).not.toBeInTheDocument();
    expect(screen.queryByText('赛后复盘解读')).not.toBeInTheDocument();
    expect(screen.queryByText('单场复盘')).not.toBeInTheDocument();
  });

const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };
it('玩法统计失败不阻断日报详情', async () => {
  apiMocks.playTypeWinRate.mockRejectedValue(new Error('玩法故障'));
  render(<ReviewsPage />);
  fireEvent.click(await screen.findByRole('button', { name: '查看 2026-08-09 日报' }));
  expect(screen.getByText('自动赛后报告')).toBeInTheDocument();
  expect(screen.getByText(/玩法故障/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '刷新玩法统计' })).toBeInTheDocument();
});
it('日报失败可独立恢复，无需重载页面', async () => {
  apiMocks.daily.mockRejectedValueOnce(new Error('日报故障')).mockResolvedValue({ reviews: [] });
  render(<ReviewsPage />);
  await screen.findByText(/日报故障/);
  expect(screen.queryByText('暂无日报数据')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '刷新日报' }));
  await screen.findByText('暂无日报数据');
  expect(apiMocks.playTypeWinRate).toHaveBeenCalledTimes(1);
});
it('周报以原生按钮选择并携带归档日期', async () => {
  apiMocks.weekly.mockResolvedValue({ reviews: [{ id: 4, week_start: '2026-10-01', week_end: '2026-10-07', created_at: '2026-10-08' }] });
  render(<ReviewsPage />); fireEvent.click(screen.getByRole('button', { name: '周报' }));
  const button = await screen.findByRole('button', { name: '查看周报 2026-10-01' });
  fireEvent.click(button);
  expect(button).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByText('自动赛后报告')).toBeInTheDocument();
});
it('结算日期快速切换忽略旧金额', async () => {
  const old = deferred<{ settlements: Array<{ id: number; stake_amount: number; profit_loss: number }> ; total: number }>();
  apiMocks.settlements.mockImplementation(({ date }: { date: string }) => date === '2026-10-01' ? old.promise : Promise.resolve({ settlements: [], total: 0 }));
  render(<ReviewsPage />); fireEvent.click(screen.getByRole('button', { name: '结算记录' }));
  const input = screen.getByLabelText('结算日期');
  fireEvent.change(input, { target: { value: '2026-10-01' } });
  fireEvent.change(input, { target: { value: '2026-10-02' } });
  await waitFor(() => expect(apiMocks.settlements).toHaveBeenLastCalledWith({ date: '2026-10-02', limit: 100 }));
  await act(async () => { old.resolve({ settlements: [{ id: 11, stake_amount: 666, profit_loss: 22 }], total: 1 }); });
  expect(screen.queryByText('¥666.00')).not.toBeInTheDocument();
});
it('结算同日期刷新失败保留成功金额且提示口径', async () => {
  apiMocks.settlements.mockResolvedValueOnce({ settlements: [{ id: 11, ticket_id: 1, ticket_source: 'real', settle_time: '2026-10-09', stake_amount: 10, profit_loss: 0, prize_amount: 10, is_won: true }], total: 1 }).mockRejectedValue(new Error('结算故障'));
  render(<ReviewsPage />); fireEvent.click(screen.getByRole('button', { name: '结算记录' }));
  await screen.findByText('¥10.00');
  fireEvent.click(screen.getByRole('button', { name: '刷新结算记录' }));
  await screen.findByText(/结算故障/);
  expect(screen.getByText('¥10.00')).toBeInTheDocument();
  expect(screen.getByText(/当前返回.*最多 100.*非全日汇总/)).toBeInTheDocument();
});
it('错因摘要失败不阻断列表并独立重试', async () => {
  apiMocks.errors.mockResolvedValue({ errors: [{ id: 19, match_id: 4, error_type: 'market', root_cause: '测试原因' }], total: 1 });
  apiMocks.summary.mockRejectedValueOnce(new Error('摘要故障')).mockResolvedValue({ errors: [] });
  render(<ReviewsPage />); fireEvent.click(screen.getByRole('button', { name: '错因分析' }));
  await screen.findByText('19'); await screen.findByText(/摘要故障/);
  fireEvent.click(screen.getByRole('button', { name: '刷新错因摘要' }));
  await waitFor(() => expect(screen.queryByText(/摘要故障/)).not.toBeInTheDocument());
  expect(apiMocks.errors).toHaveBeenCalledTimes(1);
});
it('切换结算日期失败不显示上个日期金额', async () => {
  apiMocks.settlements.mockResolvedValueOnce({ settlements: [{ id: 12, ticket_id: 1, stake_amount: 777, prize_amount: 0, profit_loss: 1 }], total: 1 }).mockRejectedValue(new Error('新日期故障'));
  render(<ReviewsPage />); fireEvent.click(screen.getByRole('button', { name: '结算记录' }));
  await screen.findByText('¥777.00');
  fireEvent.change(screen.getByLabelText('结算日期'), { target: { value: '2026-10-01' } });
  await screen.findByText(/新日期故障/);
  expect(screen.queryByText('¥777.00')).not.toBeInTheDocument();
});

it('合法空日报响应移除旧详情，错误刷新保留归档', async () => {
  render(<ReviewsPage />);
  fireEvent.click(await screen.findByRole('button', { name: '查看 2026-08-09 日报' }));
  apiMocks.daily.mockRejectedValueOnce(new Error('归档故障')).mockResolvedValueOnce({ reviews: [] });
  fireEvent.click(screen.getByRole('button', { name: '刷新日报' }));
  await screen.findByText(/归档故障/);
  expect(screen.getByText('自动赛后报告')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '刷新日报' }));
  await screen.findByText('暂无日报数据');
  expect(screen.queryByText('自动赛后报告')).not.toBeInTheDocument();
});
it('结算NaN响应保留旧金额而不是呈现错误数字', async () => {
  apiMocks.settlements.mockResolvedValueOnce({ settlements: [{ id: 11, ticket_id: 1, stake_amount: 12, prize_amount: 0, profit_loss: 0 }], total: 1 }).mockResolvedValueOnce({ settlements: [{ id: 11, stake_amount: NaN, prize_amount: 0, profit_loss: 0 }], total: 1 });
  render(<ReviewsPage />); fireEvent.click(screen.getByRole('button', { name: '结算记录' }));
  await screen.findByText('¥12.00');
  fireEvent.click(screen.getByRole('button', { name: '刷新结算记录' }));
  await screen.findByText(/结算金额格式不正确/);
  expect(screen.getByText('¥12.00')).toBeInTheDocument();
  expect(screen.queryByText(/¥NaN/)).not.toBeInTheDocument();
});
it('月报通过原生按钮打开且刷新失败不丢失归档', async () => {
  apiMocks.monthly.mockResolvedValueOnce({ reviews: [{ id: 5, review_month: '2026-09', created_at: '2026-10-01' }] }).mockRejectedValue(new Error('月报故障'));
  render(<ReviewsPage />); fireEvent.click(screen.getByRole('button', { name: '月报' }));
  fireEvent.click(await screen.findByRole('button', { name: '查看月报 2026-09' }));
  fireEvent.click(screen.getByRole('button', { name: '刷新月报' }));
  await screen.findByText(/月报故障/);
  expect(screen.getByText('自动赛后报告')).toBeInTheDocument();
});

it('非法玩法统计独立报错，日报仍可查看', async () => {
  apiMocks.playTypeWinRate.mockResolvedValue({ data: [{ play_type: 'spf', settle_date: '2026-10-08', total: 1, wins: 2, win_rate: 2 }] });
  render(<ReviewsPage />);
  await screen.findByText(/玩法统计格式不正确/);
  expect(await screen.findByRole('button', { name: '查看 2026-08-09 日报' })).toBeInTheDocument();
});

});
