import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EventsPage from './EventsPage';

const { catalog, list } = vi.hoisted(() => ({ catalog: vi.fn(), list: vi.fn() }));

catalog.mockResolvedValue({
  source: 'official',
  total: 1,
  matches: [
    {
      source: 'official', source_row_id: 101, source_match_code: '周五001',
      competition_season_id: null, home_team_id: null, away_team_id: null,
      league_name: '英超', home_team_name: '阿森纳', away_team_name: '切尔西',
      kickoff_time: '2026-08-15T19:30:00', match_status: 'Selling',
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
  it('shows only Sporttery-official historical entries', async () => {
    render(<EventsPage />);

    await waitFor(() => expect(catalog).toHaveBeenCalledWith({ source: 'official', limit: 50, offset: 0 }));

    expect(await screen.findByText(/1 个联赛 · 1 场比赛 · 体彩官方已收录/)).toBeInTheDocument();
    expect(screen.getByText('体彩官方')).toBeInTheDocument();
    expect(screen.getByText('阿森纳')).toBeInTheDocument();
    expect(screen.queryByText('赛程补充')).not.toBeInTheDocument();
  });
});
