import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EventsPage from './EventsPage';

const { catalog } = vi.hoisted(() => ({ catalog: vi.fn() }));

catalog.mockResolvedValue({
  source: 'all',
  total: 3,
  matches: [
    {
      source: 'official', source_row_id: 101, source_match_code: '周五001',
      competition_season_id: 7, home_team_id: 1, away_team_id: 2,
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
    {
      source: 'supplemental', source_row_id: 103, source_match_code: '500-103',
      competition_season_id: 8, home_team_id: 5, away_team_id: 6,
      league_name: '西甲', home_team_name: '皇家马德里', away_team_name: '巴塞罗那',
      kickoff_time: '2026-08-17T20:00:00', match_status: 'Scheduled',
      ft_home_goals: null, ft_away_goals: null,
    },
  ],
});

vi.mock('../core/apiClient', () => ({
  api: { events: { catalog } },
}));

describe('EventsPage', () => {
  it('shows the complete current-season catalog instead of only sellable official matches', async () => {
    render(<EventsPage />);

    await waitFor(() => expect(catalog).toHaveBeenCalledWith({ source: 'all', limit: 5000 }));

    expect(await screen.findByText(/2 个联赛 · 3 场比赛 · 完整赛季档案/)).toBeInTheDocument();
    expect(screen.getByText('体彩官方')).toBeInTheDocument();
    expect(screen.getAllByText('补充赛程')).toHaveLength(2);
    expect(screen.getByText('阿森纳')).toBeInTheDocument();
    expect(screen.getByText('利物浦')).toBeInTheDocument();
  });
});
