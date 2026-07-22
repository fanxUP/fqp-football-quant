import { render, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./app/layout/Layout', () => ({
  default: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));

vi.mock('./pages/DashboardPage', () => ({ default: () => <div>Dashboard</div> }));
vi.mock('./pages/MatchesPage', () => ({ default: () => <div>Matches</div> }));
vi.mock('./pages/MatchDetailPage', () => ({ default: () => <div>Match Detail</div> }));
vi.mock('./pages/RecommendationDetailPage', () => ({ default: () => <div>Recommendation Detail</div> }));
vi.mock('./pages/BettingCenterPage', () => ({
  default: ({ initialTab = 'bet-slip' }: { initialTab?: string }) => (
    <div data-testid="betting-center">{initialTab}</div>
  ),
}));
vi.mock('./pages/ModelsPage', () => ({ default: () => <div>Models</div> }));
vi.mock('./pages/DataHealthPage', () => ({ default: () => <div>Data Health</div> }));
vi.mock('./pages/EventsPage', () => ({ default: () => <div>Events</div> }));
vi.mock('./pages/ModulesPage', () => ({ default: () => <div>Modules</div> }));
vi.mock('./pages/SettingsPage', () => ({ default: () => <div>Settings</div> }));
vi.mock('./pages/AgentPanel', () => ({ default: () => <div>Agent</div> }));
vi.mock('./pages/BacktestPage', () => ({ default: () => <div>Backtest</div> }));
vi.mock('./pages/PoolPage', () => ({ default: () => <div>Pool</div> }));
vi.mock('./pages/AnalysisPage', () => ({ default: () => <div>Analysis</div> }));
vi.mock('./pages/OddsMovementPage', () => ({ default: () => <div>Odds</div> }));

describe('App legacy route redirects', () => {
  beforeEach(() => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));
    window.location.hash = '#/';
    localStorage.clear();
  });

  it.each([
    ['#/simulator', '#/betting?tab=bet-slip'],
    ['#/simulator/history/12', '#/betting?tab=tickets'],
    ['#/simulator/history', '#/betting?tab=tickets'],
    ['#/simulator/bankroll', '#/betting?tab=competition'],
    ['#/tickets/new', '#/betting?tab=bet-slip'],
    ['#/tickets/42', '#/betting?tab=tickets'],
    ['#/competition/history', '#/betting?tab=competition'],
    ['#/recommendations', '#/analysis?section=pre_match'],
    ['#/reviews', '#/analysis?section=reviews'],
  ])('redirects legacy route %s to its unified workspace', async (from, to) => {
    window.location.hash = from;

    render(<App />);

    await waitFor(() => {
      expect(window.location.hash).toBe(to);
    });
  });
});
