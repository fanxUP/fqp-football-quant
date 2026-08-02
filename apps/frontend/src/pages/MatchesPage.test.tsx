import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MatchesPage from './MatchesPage';

const { active } = vi.hoisted(() => ({ active: vi.fn() }));

active.mockResolvedValue({
  total: 2,
  matches: [
    {
      match_id: 11, league_name: '中超', home_team_name: '上海海港', away_team_name: '北京国安',
      kickoff_time: '2026-07-12T19:35:00', match_status: 'awaiting_result', match_num_str: '周日001',
    },
    {
      match_id: 12, league_name: '中超', home_team_name: '成都蓉城', away_team_name: '山东泰山',
      kickoff_time: '2026-07-12T20:00:00', match_status: 'Selling', match_num_str: '周日002',
    },
  ],
});

vi.mock('../core/apiClient', () => ({ api: { matches: { active } } }));

describe('MatchesPage', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('lists every unfinished official match without requiring that it is still sellable', async () => {
    render(<MatchesPage />);

    await waitFor(() => expect(active).toHaveBeenCalledWith({ limit: 500 }));
    expect(await screen.findByText('比赛中心')).toBeInTheDocument();
    expect(screen.getByText(/体彩官方未结束比赛/)).toBeInTheDocument();
    expect(screen.getByText('上海海港')).toBeInTheDocument();
    expect(screen.getByText('成都蓉城')).toBeInTheDocument();
    expect(screen.getAllByText('VS')).toHaveLength(2);
    expect(screen.queryByText('对阵')).not.toBeInTheDocument();
    expect(screen.getByText('等待赛果')).toBeInTheDocument();
  });

  it('定时同步未结束比赛的状态', async () => {
    vi.useFakeTimers();
    render(<MatchesPage />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(active).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(30_000); await Promise.resolve(); });
    expect(active).toHaveBeenCalledTimes(2);
  });
});
