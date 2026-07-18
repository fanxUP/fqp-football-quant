import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TicketsPage from './TicketsPage';

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
  beforeEach(() => {
    apiMocks.tickets.mockReset().mockResolvedValue({ tickets: [realTicket, simulationTicket], total: 2 });
    apiMocks.deleteTicket.mockReset().mockResolvedValue({ status: 'ok' });
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
    apiMocks.tickets.mockResolvedValueOnce({
      tickets: [
        { ...realTicket, ticketUid: 'real:13', ticketNumber: '20260714003', legacyId: 13, title: '赢票', status: 'settled', isWon: true },
        { ...realTicket, ticketUid: 'real:14', ticketNumber: '20260714004', legacyId: 14, title: '输票', status: 'settled', isWon: false },
      ],
      total: 2,
    });

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
});
