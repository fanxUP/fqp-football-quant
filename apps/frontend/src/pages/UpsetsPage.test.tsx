import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import UpsetsPage from './UpsetsPage';

const { summary, list, detail } = vi.hoisted(() => ({
  summary: vi.fn(),
  list: vi.fn(),
  detail: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: { upsets: { summary, list, detail } },
}));

describe('UpsetsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    summary.mockResolvedValue({
      settled_match_count: 100,
      upset_count: 24,
      upset_rate: 0.24,
      severe_count: 8,
      extreme_count: 2,
      favourite_failed_count: 10,
      model_warned_count: 3,
      user_involved_count: 4,
      agent_involved_count: 5,
      level_counts: { S: 2, A: 6, B: 9, C: 7 },
      play_counts: { spf: 12, rqspf: 12 },
    });
    list.mockResolvedValue({
      items: [{
        id: 7,
        business_date: '2026-07-20',
        official_match_code: '周一201',
        league_name: '测试联赛',
        home_team_name: '主队',
        away_team_name: '客队',
        full_score: '1:2',
        primary_play_type: 'spf',
        primary_upset_type: 'odds_and_favourite',
        actual_outcome: '0',
        market_favourite_outcome: '3',
        market_favourite_probability: 0.62,
        actual_outcome_probability: 0.18,
        surprise_bits: 2.47,
        upset_level: 'A',
        favourite_failed: true,
        model_warned: false,
        user_bet_involved: true,
        agent_bet_involved: false,
        review_status: 'waiting_data',
      }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    detail.mockResolvedValue({
      event: {
        id: 7,
        official_match_code: '周一201',
        league_name: '测试联赛',
        home_team_name: '主队',
        away_team_name: '客队',
        full_home_goals: 1,
        full_away_goals: 2,
        upset_level: 'A',
      },
      market_signals: [{
        id: 1,
        play_type: 'spf',
        actual_outcome: '0',
        actual_outcome_probability: 0.18,
        market_favourite_probability: 0.62,
        opening_snapshot_time: '2026-07-20T09:00:00',
        closing_snapshot_time: '2026-07-20T12:00:00',
        opening_odds_json: { '3': 1.45, '1': 4.2, '0': 6.5 },
        closing_odds_json: { '3': 1.5, '1': 4.0, '0': 6.0 },
        upset_level: 'A',
      }],
      evidence: [],
      review: null,
      user_tickets: [{ ticket_id: 12, stake_amount: 20, profit_loss: -20 }],
      agent_tickets: [],
    });
  });

  it('展示冷门统计、比赛卡片和数据等待状态', async () => {
    render(<UpsetsPage />);

    expect(await screen.findByText('冷门研究')).toBeInTheDocument();
    expect(screen.getByText('24')).toBeInTheDocument();
    expect(screen.getByText('24.0%')).toBeInTheDocument();
    expect(screen.getByText('主队 1:2 客队')).toBeInTheDocument();
    expect(screen.getByText('等待详细证据')).toBeInTheDocument();
    expect(screen.getByText('用户实票涉及')).toBeInTheDocument();
  });

  it('筛选条件会传给列表和统计接口', async () => {
    render(<UpsetsPage />);
    await screen.findByText('主队 1:2 客队');

    fireEvent.change(screen.getByLabelText('冷门等级'), { target: { value: 'A' } });
    fireEvent.change(screen.getByLabelText('玩法'), { target: { value: 'spf' } });

    await waitFor(() => expect(list).toHaveBeenLastCalledWith(expect.objectContaining({
      level: 'A',
      play_type: 'spf',
    })));
  });

  it('打开详情后展示完整赔率和彩票影响', async () => {
    render(<UpsetsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '查看复盘' }));

    await waitFor(() => expect(detail).toHaveBeenCalledWith(7));
    expect(await screen.findByText('市场与赛果')).toBeInTheDocument();
    expect(screen.getByText('实票 #12')).toBeInTheDocument();
    expect(screen.getByText('暂无充分证据，详细复盘等待数据补全。')).toBeInTheDocument();
  });
});
