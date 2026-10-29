import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
  api: { events: { catalog, list }, leagues: {
    catalog: vi.fn().mockResolvedValue({ status: 'not_connected', competitions: [{ code: 'premier-league', name: '英超', country: '英格兰', seasons: [] }] }),
  } },
}));

describe('EventsPage', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '#/events');
    vi.clearAllMocks();
  });
  it('shows only Sporttery matches with official display codes', async () => {
    render(<EventsPage />);

    await waitFor(() => expect(catalog).toHaveBeenCalledWith({ source: 'official', league_name: undefined, limit: 50, offset: 0 }));

    expect(await screen.findByText(/仅展示有官方体彩编号的中国竞彩网比赛/)).toBeInTheDocument();
    expect(screen.getByText('体彩官方')).toBeInTheDocument();
    expect(screen.getByText('阿森纳')).toBeInTheDocument();
    expect(screen.queryByText('无体彩编号')).not.toBeInTheDocument();
  });

  it('opens the league area without fetching official matches or fictional standings', async () => {
    window.history.replaceState(null, '', '#/events?view=league');
    render(<EventsPage />);
    expect(await screen.findByText('联赛数据待接入')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '联赛资料' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('combobox', { name: '赛季' })).toBeDisabled();
    expect(catalog).not.toHaveBeenCalled();
    expect(list).not.toHaveBeenCalled();
    expect(screen.queryByText('阿森纳')).not.toBeInTheDocument();
    expect(screen.getByText('球员与阵容事实')).toBeInTheDocument();
  });

  it('switches views and restores the same-route league link on browser navigation', async () => {
    render(<EventsPage />);
    await screen.findByText('阿森纳');
    fireEvent.click(screen.getByRole('button', { name: '联赛资料' }));
    await screen.findByText('联赛数据待接入');
    expect(window.location.hash).toContain('view=league');
    fireEvent.click(screen.getByRole('button', { name: '赛程赛果' }));
    expect(window.location.hash).toContain('tab=fixtures');
    act(() => {
      window.history.replaceState(null, '', '#/events?view=league&tab=teams');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    expect(screen.getByRole('button', { name: '球队' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: '竞彩比赛' }));
    await screen.findByText('阿森纳');
    expect(screen.getByText('体彩官方')).toBeInTheDocument();
  });
});
