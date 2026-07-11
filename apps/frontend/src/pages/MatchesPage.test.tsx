import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import MatchesPage from './MatchesPage';

const { active } = vi.hoisted(() => ({ active: vi.fn() }));

active.mockResolvedValue({
  total: 2,
  matches: [
    {
      match_id: 11, league_name: '中超', home_team_name: '上海海港', away_team_name: '北京国安',
      kickoff_time: '2026-07-12T19:35:00', match_status: 'scheduled', match_num_str: '周日001',
    },
    {
      match_id: 12, league_name: '中超', home_team_name: '成都蓉城', away_team_name: '山东泰山',
      kickoff_time: '2026-07-12T20:00:00', match_status: 'Selling', match_num_str: '周日002',
    },
  ],
});

vi.mock('../core/apiClient', () => ({ api: { matches: { active } } }));

describe('MatchesPage', () => {
  it('lists every unfinished official match without requiring that it is still sellable', async () => {
    render(<MatchesPage />);

    await waitFor(() => expect(active).toHaveBeenCalledWith({ limit: 500 }));
    expect(await screen.findByText('比赛中心')).toBeInTheDocument();
    expect(screen.getByText(/体彩官方未结束比赛/)).toBeInTheDocument();
    expect(screen.getByText('上海海港')).toBeInTheDocument();
    expect(screen.getByText('成都蓉城')).toBeInTheDocument();
  });
});
