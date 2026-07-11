import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EventsPage from './EventsPage';

const { catalog } = vi.hoisted(() => ({ catalog: vi.fn() }));

catalog.mockResolvedValue({
  source: 'all',
  total: 2,
  matches: [
    {
      source: 'official', source_row_id: 101, source_match_code: '周五001',
      competition_season_id: null, home_team_id: null, away_team_id: null,
      league_name: '英超', home_team_name: '阿森纳', away_team_name: '切尔西',
      kickoff_time: '2026-08-15T19:30:00', match_status: 'Selling',
      ft_home_goals: null, ft_away_goals: null,
    },
    {
      source: 'supplemental', source_row_id: 102, source_match_code: '500-102',
      competition_season_id: 7, home_team_id: 3, away_team_id: 4,
      league_name: '英超', home_team_name: '利物浦', away_team_name: '曼城',
      kickoff_time: '2026-08-16T19:30:00', match_status: 'Scheduled',
      ft_home_goals: null, ft_away_goals: null,
    },
  ],
});

vi.mock('../core/apiClient', () => ({
  api: { events: { catalog } },
}));

describe('EventsPage', () => {
  it('shows complete season entries with non-official fixtures clearly labelled', async () => {
    render(<EventsPage />);

    await waitFor(() => expect(catalog).toHaveBeenCalledWith({ source: 'all', limit: 5000 }));

    expect(await screen.findByText(/1 个联赛 · 2 场比赛 · 完整赛季档案/)).toBeInTheDocument();
    expect(screen.getByText('体彩官方')).toBeInTheDocument();
    expect(screen.getByText('赛程补充')).toBeInTheDocument();
    expect(screen.getByText('无官方编号')).toBeInTheDocument();
    expect(screen.queryByText('500-102')).not.toBeInTheDocument();
    expect(screen.getByText('阿森纳')).toBeInTheDocument();
    expect(screen.getByText('利物浦')).toBeInTheDocument();
  });
});
