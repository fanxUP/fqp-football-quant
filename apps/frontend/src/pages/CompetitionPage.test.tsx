import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CompetitionPage from './CompetitionPage';

const apiMocks = vi.hoisted(() => ({
  results: vi.fn(),
  tickets: vi.fn(),
  decisions: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    betting: { results: apiMocks.results, tickets: apiMocks.tickets },
    competition: { decisions: apiMocks.decisions },
  },
}));

describe('CompetitionPage', () => {
  beforeEach(() => {
    apiMocks.results.mockResolvedValue({
      owners: {
        me: { ticketCount: 0, stake: 0, settledAmount: 0, profitLoss: 0, roi: 0, settled: 0, pending: 0, hitCount: 0 },
        agent: { ticketCount: 0, stake: 0, settledAmount: 0, profitLoss: 0, roi: 0, settled: 0, pending: 0, hitCount: 0 },
      },
      leader: 'draw', bySource: {}, trend: [], updatedAt: null,
    });
    apiMocks.tickets.mockResolvedValue({ tickets: [], total: 0 });
    apiMocks.decisions.mockResolvedValue({
      decisions: [{
        decisionDate: '2026-07-14', status: 'abstained', totalBudget: 500,
        totalStake: 0, unusedBudget: 500, reason: '数据完整度不足，今日不投注',
        updatedAt: '2026-07-14T16:00:00',
      }],
      total: 1,
    });
  });

  it('shows the Agent daily buy-or-abstain decision', async () => {
    render(<CompetitionPage />);

    expect(await screen.findByText('Agent 每日决策')).toBeInTheDocument();
    expect(screen.getByText('已放弃')).toBeInTheDocument();
    expect(screen.getByText('数据完整度不足，今日不投注')).toBeInTheDocument();
    expect(apiMocks.decisions).toHaveBeenCalledWith(14);
  });
});
