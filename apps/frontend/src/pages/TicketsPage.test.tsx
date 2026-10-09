import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TicketsPage from './TicketsPage';
import { calculateLedgerStats } from '../core/bettingTickets';

const apiMocks = vi.hoisted(() => ({
  tickets: vi.fn(),
  deleteTicket: vi.fn(),
  deleteSimulationTicket: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: { betting: apiMocks, simulator: { tickets: { delete: apiMocks.deleteSimulationTicket } } },
}));

const realTicket = {
  ticketUid: 'real:12', legacyId: 12, owner: 'me' as const, kind: 'real' as const,
  ticketNumber: '20260714001',
  source: 'manual' as const, status: 'pending', date: '2026-07-14', createdAt: '2026-07-14T10:00:00',
  title: '实票 #12', playType: 'mixed', passType: 'single', multiple: 1, betCount: 1,
  matchCount: 1, stake: 2, maxPrize: 4, settledAmount: null, profitLoss: null, roi: null,
  itemCount: 1, route: '/tickets/12', items: [],
};

const simulationTicket = {
  ...realTicket,
  ticketUid: 'simulator:7', ticketNumber: '20260714002', legacyId: 7,
  kind: 'simulation' as const, title: '模拟票 #7',
  route: '/simulator/history/7',
};

describe('TicketsPage', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    let currentTickets = [realTicket, simulationTicket];
    apiMocks.tickets.mockReset().mockImplementation(() => Promise.resolve({
      tickets: currentTickets, total: currentTickets.length,
      summary: calculateLedgerStats(currentTickets),
      byOwner: { me: calculateLedgerStats(currentTickets) }, nextCursor: null,
    }));
    apiMocks.deleteTicket.mockReset().mockImplementation(async (id: number) => {
      currentTickets = currentTickets.filter((ticket) => ticket.legacyId !== id);
      return { status: 'ok' };
    });
    apiMocks.deleteSimulationTicket.mockReset().mockResolvedValue({ status: 'ok', refunded: 2 });
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('confirms then removes a real ticket and exposes deletion for pending simulation tickets', async () => {
    render(<TicketsPage />);

    const deleteButton = await screen.findByRole('button', { name: '删除彩票 实票 #12' });
    expect(screen.getAllByText('混合过关').length).toBeGreaterThan(0);
    expect(screen.getAllByText('单关').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/20260714001/)).toHaveLength(2);
    expect(screen.queryByText('real:12')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '删除彩票 模拟票 #7' })).toBeInTheDocument();

    fireEvent.click(deleteButton);

    expect(window.confirm).toHaveBeenCalledWith('删除后无法恢复，确认删除这张彩票吗？');
    await waitFor(() => expect(apiMocks.deleteTicket).toHaveBeenCalledWith(12));
    await waitFor(() => expect(screen.queryByText(/20260714001/)).not.toBeInTheDocument());
    expect(screen.getAllByText(/20260714002/)).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: '删除彩票 模拟票 #7' }));

    expect(window.confirm).toHaveBeenLastCalledWith('删除后将退回该票金额，确认删除这张彩票吗？');
    await waitFor(() => expect(apiMocks.deleteSimulationTicket).toHaveBeenCalledWith(7));
  });

  it('赢票使用红色、输票使用绿色，且卡片和大水印共用状态色', () => {
    const outcomeTickets = [
        { ...realTicket, ticketUid: 'real:13', ticketNumber: '20260714003', legacyId: 13, title: '赢票', status: 'settled', isWon: true },
        { ...realTicket, ticketUid: 'real:14', ticketNumber: '20260714004', legacyId: 14, title: '输票', status: 'settled', isWon: false },
      ];
    apiMocks.tickets.mockResolvedValueOnce({ tickets: outcomeTickets, total: 2,
      summary: calculateLedgerStats(outcomeTickets), byOwner: { me: calculateLedgerStats(outcomeTickets) }, nextCursor: null });

    const { container } = render(<TicketsPage />);
    return waitFor(() => {
      const wonCard = container.querySelector<HTMLElement>(".lottery-ticket-card[data-outcome='won']");
      const lostCard = container.querySelector<HTMLElement>(".lottery-ticket-card[data-outcome='lost']");

      expect(wonCard?.style.getPropertyValue('--lottery-outcome-color')).toBe('var(--fqp-danger, #ef4444)');
      expect(lostCard?.style.getPropertyValue('--lottery-outcome-color')).toBe('var(--fqp-success, #16a34a)');
      expect(wonCard?.querySelector('.lottery-ticket-watermark')).toHaveTextContent('赢');
      expect(lostCard?.querySelector('.lottery-ticket-watermark')).toHaveTextContent('输');
    });
  });

  it('页面保持打开时自动同步新增和结算的彩票', async () => {
    vi.useFakeTimers();

    render(<TicketsPage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(apiMocks.tickets).toHaveBeenCalledTimes(1);
    expect(apiMocks.tickets).toHaveBeenNthCalledWith(1, { date: undefined, status: undefined, limit: 100 });

    await act(async () => {
      vi.advanceTimersByTime(30_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(apiMocks.tickets).toHaveBeenCalledTimes(2);
    expect(apiMocks.tickets).toHaveBeenNthCalledWith(2, { date: undefined, status: undefined, limit: 100 });
  });
  it('显示完整统计并按游标加载更多，重复彩票只显示一次', async () => {
    const summary = { total: 301, stake: 602, settled: 0, pending: 301 };
    apiMocks.tickets.mockResolvedValueOnce({ tickets: [realTicket], total: 301,
      summary, byOwner: { me: summary }, nextCursor: 'page-two' });
    apiMocks.tickets.mockResolvedValueOnce({ tickets: [realTicket, simulationTicket], total: 301,
      summary, byOwner: { me: summary }, nextCursor: null });
    render(<TicketsPage />);
    expect(await screen.findByText('301 张彩票')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));
    await screen.findByRole('button', { name: '删除彩票 模拟票 #7' });
    expect(apiMocks.tickets).toHaveBeenLastCalledWith({ date: undefined, status: undefined, limit: 100, cursor: 'page-two' });
    expect(screen.getAllByRole('button', { name: '删除彩票 实票 #12' })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: '加载更多' })).not.toBeInTheDocument();
  });

  it('切换状态将筛选传给后端并清除旧分页游标', async () => {
    render(<TicketsPage />);
    fireEvent.change(await screen.findByRole('combobox', { name: '彩票状态' }), { target: { value: 'won' } });
    await waitFor(() => expect(apiMocks.tickets).toHaveBeenLastCalledWith({ date: undefined, status: 'won', limit: 100 }));
  });

  it('历史彩票在后续页面时不会误报为没有彩票', async () => {
    const ownerSummary = { total: 1, stake: 2, settled: 0, pending: 1 };
    apiMocks.tickets.mockResolvedValueOnce({ tickets: [{ ...realTicket, owner: 'agent' }], total: 2,
      summary: { total: 2, stake: 4, settled: 0, pending: 2 },
      byOwner: { me: ownerSummary, agent: ownerSummary }, nextCursor: 'older' });
    render(<TicketsPage />);
    expect(await screen.findByText('本页暂无彩票')).toBeInTheDocument();
    expect(screen.getByText('符合筛选的彩票还在后续页面，请加载更多或按日期筛选。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '加载更多' })).toBeInTheDocument();
  });

});

describe('TicketsPage query evidence', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal('confirm', vi.fn(() => true)); });
  const response = () => ({ tickets: [realTicket], total: 1, summary: calculateLedgerStats([realTicket]), byOwner: { me: calculateLedgerStats([realTicket]) }, nextCursor: 'older' });
  it('新筛选失败不显示旧票或旧游标且不误报暂无彩票', async () => {
    apiMocks.tickets.mockResolvedValueOnce(response()).mockRejectedValue(new Error('筛选故障'));
    render(<TicketsPage />); await screen.findByRole('button', { name: '删除彩票 实票 #12' });
    fireEvent.change(screen.getByRole('combobox', { name: '彩票状态' }), { target: { value: 'won' } });
    await screen.findByText(/筛选故障/);
    expect(screen.queryByRole('button', { name: '删除彩票 实票 #12' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '加载更多' })).not.toBeInTheDocument();
    expect(screen.queryByText('暂无彩票')).not.toBeInTheDocument();
  });
  it('同筛选手动刷新失败保留成功票和游标', async () => {
    apiMocks.tickets.mockResolvedValueOnce(response()).mockRejectedValueOnce(new Error('刷新故障')).mockResolvedValue({ ...response(), tickets: [], total: 0, summary: calculateLedgerStats([]), byOwner: {}, nextCursor: null });
    render(<TicketsPage />); await screen.findByRole('button', { name: '删除彩票 实票 #12' });
    fireEvent.click(screen.getByRole('button', { name: '刷新彩票' }));
    await screen.findByText(/刷新故障/);
    expect(screen.getByRole('button', { name: '删除彩票 实票 #12' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新彩票' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: '删除彩票 实票 #12' })).not.toBeInTheDocument());
  });
  it('换日期后的迟到旧票不会混入新日期', async () => {
    let resolve!: (value: ReturnType<typeof response>) => void;
    apiMocks.tickets.mockImplementation(({ date }: { date?: string }) => !date ? new Promise(r => { resolve = r; }) : Promise.resolve({ ...response(), tickets: [], total: 0, summary: calculateLedgerStats([]), byOwner: {}, nextCursor: null }));
    render(<TicketsPage />);
    fireEvent.change(screen.getByLabelText('购买日期'), { target: { value: '2026-10-01' } });
    await waitFor(() => expect(apiMocks.tickets).toHaveBeenLastCalledWith({ date: '2026-10-01', status: undefined, limit: 100 }));
    await act(async () => { resolve(response()); });
    expect(screen.queryByRole('button', { name: '删除彩票 实票 #12' })).not.toBeInTheDocument();
  });
  it('坏分页统计被拒绝并保留旧票', async () => {
    apiMocks.tickets.mockResolvedValueOnce(response()).mockResolvedValueOnce({ ...response(), summary: { ...response().summary, stake: NaN } });
    render(<TicketsPage />); await screen.findByRole('button', { name: '删除彩票 实票 #12' });
    fireEvent.click(screen.getByRole('button', { name: '刷新彩票' }));
    await screen.findByText(/彩票分页或统计格式不正确/);
    expect(screen.getByRole('button', { name: '删除彩票 实票 #12' })).toBeInTheDocument();
  });
  it('分页游标没有前进时保留成功页并提示刷新', async () => {
    apiMocks.tickets.mockResolvedValue(response());
    render(<TicketsPage />); await screen.findByRole('button', { name: '删除彩票 实票 #12' });
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));
    await screen.findByText(/分页游标未前进/);
    expect(screen.getAllByRole('button', { name: '删除彩票 实票 #12' })).toHaveLength(1);
  });

  it('非法彩票盈亏金额被拒绝，不显示NaN', async () => {
    apiMocks.tickets.mockResolvedValue({ ...response(), tickets: [{ ...realTicket, profitLoss: NaN }] });
    render(<TicketsPage />);
    await screen.findByText(/彩票分页或统计格式不正确/);
    expect(screen.queryByRole('button', { name: '删除彩票 实票 #12' })).not.toBeInTheDocument();
    expect(screen.queryByText(/¥NaN/)).not.toBeInTheDocument();
  });

});
