import { StrictMode } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardPage from './DashboardPage';

const api = vi.hoisted(() => ({
  health: vi.fn().mockResolvedValue({ status: 'ok' }),
  teams: vi.fn().mockResolvedValue({ total: 0, teams: [] }),
  predictions: vi.fn().mockResolvedValue({ total: 0, predictions: [] }),
  tickets: vi.fn().mockResolvedValue({ total: 0, tickets: [] }),
  betting: { tickets: vi.fn().mockResolvedValue({ total: 0, tickets: [] }) },
  reviews: { daily: vi.fn().mockResolvedValue({ total: 0, reviews: [] }) },
  dashboard: {
    today: vi.fn().mockResolvedValue({ data: { kpis: [], extras: {} } }),
    roiDaily: vi.fn().mockResolvedValue({ data: { series: [] } }),
    modelPerformance: vi.fn().mockResolvedValue({ data: { series: [] } }),
  },
}));

vi.mock('../core/apiClient', () => ({ api }));
vi.mock('../shared/components/ChartCard', () => ({ default: () => <div /> }));
vi.mock('../visualization', () => ({
  RoiLineChart: () => <div />,
  EmptyChartState: () => <div />,
  AiPoolDashboard: () => <div />,
}));

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.dashboard.today.mockResolvedValue({
      data: {
        kpis: [
          { key: 'predicted_match_count', label: '已预测比赛', value: 15 },
          { key: 'ai_stake_today', label: 'AI 模拟投入', value: 120 },
          { key: 'ai_ticket_count', label: 'AI 票单数', value: 4 },
          { key: 'pending_settlement_count', label: '待开奖', value: 3 },
        ],
        extras: {},
      },
    });
    api.betting.tickets.mockResolvedValue({ total: 23, tickets: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('loads its initial dashboard data once in StrictMode', async () => {
    render(<StrictMode><DashboardPage /></StrictMode>);

    await waitFor(() => expect(api.dashboard.today).toHaveBeenCalledTimes(1));
    expect(api.health).toHaveBeenCalledTimes(1);
    expect(api.teams).toHaveBeenCalledTimes(1);
    expect(api.predictions).toHaveBeenCalledTimes(1);
  });

  it('使用真实 Agent 投入和待开奖数，并定时刷新驾驶舱', async () => {
    vi.useFakeTimers();

    render(<DashboardPage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      vi.advanceTimersByTime(700);
    });

    expect(screen.getByText('已使用 ¥120 / ¥500 （每日预算）')).toBeInTheDocument();
    expect(screen.getByText('张彩票已归档')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(30_000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.dashboard.today).toHaveBeenCalledTimes(2);
    expect(api.betting.tickets).toHaveBeenCalledTimes(2);
  });
});
