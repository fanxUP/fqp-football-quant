import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EventsPage from './EventsPage';

const { catalog, list } = vi.hoisted(() => ({ catalog: vi.fn(), list: vi.fn() }));

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
      source: 'supplemental', source_row_id: 202, source_match_code: 'third-party-202',
      competition_season_id: 9, home_team_id: null, away_team_id: null,
      league_name: '英超', home_team_name: '布伦特福德', away_team_name: '富勒姆',
      kickoff_time: '2026-08-16T21:00:00', match_status: 'scheduled',
      ft_home_goals: null, ft_away_goals: null,
    },
  ],
});
list.mockResolvedValue({
  total: 1,
  events: [{ league_name: '英超', match_count: 1, first_match: '2026-08-15T19:30:00', last_match: '2026-08-15T19:30:00' }],
});

vi.mock('../core/apiClient', () => ({
  api: { events: { catalog, list } },
}));

describe('EventsPage', () => {
  it('shows official and clearly labelled supplemental season entries', async () => {
    render(<EventsPage />);

    await waitFor(() => expect(catalog).toHaveBeenCalledWith({ source: 'all', league_name: undefined, limit: 50, offset: 0 }));

    expect(await screen.findByText(/赛季档案包含体彩官方与赛程补充/)).toBeInTheDocument();
    expect(screen.getByText('体彩官方')).toBeInTheDocument();
    expect(screen.getByText('阿森纳')).toBeInTheDocument();
    expect(screen.getByText('赛程补充')).toBeInTheDocument();
    expect(screen.getByText('无官方编号')).toBeInTheDocument();
    expect(screen.getByText('布伦特福德')).toBeInTheDocument();
  });
});
