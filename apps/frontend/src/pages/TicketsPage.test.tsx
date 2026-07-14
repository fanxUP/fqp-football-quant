import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TicketsPage from './TicketsPage';

const apiMocks = vi.hoisted(() => ({
  tickets: vi.fn(),
  deleteTicket: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: { betting: apiMocks },
}));

const realTicket = {
  ticketUid: 'real:12', legacyId: 12, owner: 'me' as const, kind: 'real' as const,
  source: 'manual' as const, status: 'pending', date: '2026-07-14', createdAt: '2026-07-14T10:00:00',
  title: '实票 #12', playType: 'spf', passType: 'single', multiple: 1, betCount: 1,
  matchCount: 1, stake: 2, maxPrize: 4, settledAmount: null, profitLoss: null, roi: null,
  itemCount: 1, route: '/tickets/12', items: [],
};

const simulationTicket = {
  ...realTicket,
  ticketUid: 'simulator:7', legacyId: 7, kind: 'simulation' as const, title: '模拟票 #7',
  route: '/simulator/history/7',
};

describe('TicketsPage', () => {
  beforeEach(() => {
    apiMocks.tickets.mockReset().mockResolvedValue({ tickets: [realTicket, simulationTicket], total: 2 });
    apiMocks.deleteTicket.mockReset().mockResolvedValue({ status: 'ok' });
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('confirms then removes a real ticket without exposing deletion for simulation tickets', async () => {
    render(<TicketsPage />);

    const deleteButton = await screen.findByRole('button', { name: '删除彩票 实票 #12' });
    expect(screen.queryByRole('button', { name: '删除彩票 模拟票 #7' })).not.toBeInTheDocument();

    fireEvent.click(deleteButton);

    expect(window.confirm).toHaveBeenCalledWith('删除后无法恢复，确认删除这张彩票吗？');
    await waitFor(() => expect(apiMocks.deleteTicket).toHaveBeenCalledWith(12));
    await waitFor(() => expect(screen.queryByText('real:12')).not.toBeInTheDocument());
    expect(screen.getByText('simulator:7')).toBeInTheDocument();
  });
});
