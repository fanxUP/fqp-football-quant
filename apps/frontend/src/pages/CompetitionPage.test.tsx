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

  it('shows a purchased Agent competition ticket with its daily decision', async () => {
    apiMocks.results.mockResolvedValue({
      owners: {
        me: { ticketCount: 0, stake: 0, settledAmount: 0, profitLoss: 0, roi: 0, settled: 0, pending: 0, hitCount: 0 },
        agent: { ticketCount: 1, stake: 2, settledAmount: 0, profitLoss: 0, roi: 0, settled: 0, pending: 1, hitCount: 0 },
      },
      leader: 'draw',
      bySource: {
        'agent:simulation:agent_recommendation': {
          ticketCount: 1, stake: 2, settledAmount: 0, profitLoss: 0,
          roi: 0, settled: 0, pending: 1, hitCount: 0,
        },
      },
      trend: [], updatedAt: '2026-07-14T16:00:00',
    });
    apiMocks.tickets.mockResolvedValue({
      tickets: [{
        ticketUid: 'agent:52', legacyId: 52, owner: 'agent', kind: 'simulation',
        source: 'agent_recommendation', status: 'pending', date: '2026-07-14',
        createdAt: '2026-07-14T16:00:00', title: 'Agent 票 #52', playType: 'hhgg',
        passType: '2x1', multiple: 1, betCount: 1, matchCount: 2, stake: 2,
        maxPrize: null, settledAmount: null, profitLoss: null, roi: null, itemCount: 2,
        route: '/competition', expectedValue: 1.0005,
        strategyPool: 'agent_competition_observation', riskLevel: 'high', items: [],
      }],
      total: 1,
    });
    apiMocks.decisions.mockResolvedValue({
      decisions: [{
        decisionDate: '2026-07-14', status: 'purchased', totalBudget: 500,
        totalStake: 2, unusedBudget: 498,
        reason: '已用 2 元生成 1 张高风险虚拟观察票',
        updatedAt: '2026-07-14T16:00:00',
      }],
      total: 1,
    });

    render(<CompetitionPage />);

    expect(await screen.findByText('Agent 票 #52')).toBeInTheDocument();
    expect(screen.getByText('已购买')).toBeInTheDocument();
    expect(screen.getByText('已用 2 元生成 1 张高风险虚拟观察票')).toBeInTheDocument();
    expect(screen.getByText('¥498.00')).toBeInTheDocument();
  });
});
