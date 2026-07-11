import { StrictMode } from 'react';
import { render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
  it('loads its initial dashboard data once in StrictMode', async () => {
    render(<StrictMode><DashboardPage /></StrictMode>);

    await waitFor(() => expect(api.dashboard.today).toHaveBeenCalledTimes(1));
    expect(api.health).toHaveBeenCalledTimes(1);
    expect(api.teams).toHaveBeenCalledTimes(1);
    expect(api.predictions).toHaveBeenCalledTimes(1);
  });
});
