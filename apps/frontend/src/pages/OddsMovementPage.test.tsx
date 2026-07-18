import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import OddsMovementPage from './OddsMovementPage';

const { oddsIndex, oddsMovements } = vi.hoisted(() => ({
  oddsIndex: vi.fn(),
  oddsMovements: vi.fn(),
}));

oddsIndex.mockResolvedValue({
  current: { count: 2 },
  history: [{ business_date: '2026-07-13', match_count: 3 }],
});
oddsMovements.mockResolvedValue({
  scope: 'current',
  business_date: null,
  play_type: 'spf',
  resolution: 'raw',
  total: 2,
  matches: [
    {
      id: 304, official_match_code: '周二201', business_date: '2026-07-14', league_name: '英超',
      home_team_name: '曼彻斯特城', away_team_name: '利雅得新月',
      kickoff_time: '2026-07-14T19:15:00+08:00', capture_status: { status: 'complete', capture_kind: 'opening', failure_reason: null },
      series: [{ snapshot_id: 1, snapshot_time: '2026-07-14T17:30:00+08:00', play_type: 'spf', option_code: 'h', option_name: '主胜', sp_value: 1.27, handicap: null, implied_probability: 0.78, prev_sp_value: null }],
      anomalies: [],
    },
    {
      id: 305, official_match_code: '周二202', business_date: '2026-07-14', league_name: '西甲',
      home_team_name: '巴塞罗那', away_team_name: '皇家马德里',
      kickoff_time: '2026-07-14T20:00:00+08:00', capture_status: null,
      series: [], anomalies: [],
    },
  ],
});

vi.mock('../core/apiClient', () => ({
  api: {
    official: { oddsIndex },
    dashboard: { oddsMovements },
  },
}));
vi.mock('../visualization', () => ({
  OddsSeriesChart: ({ title }: { title: string }) => <div>{title} 图表</div>,
}));

describe('OddsMovementPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    oddsIndex.mockResolvedValue({
      current: { count: 2 },
      history: [{ business_date: '2026-07-13', match_count: 3 }],
      sales_window: { is_open: true },
    });
    oddsMovements.mockResolvedValue({
      scope: 'current',
      business_date: null,
      play_type: 'spf',
      resolution: 'raw',
      total: 2,
      sales_window: { is_open: true },
      matches: [
        {
          id: 304, official_match_code: '周二201', business_date: '2026-07-14', league_name: '英超',
          home_team_name: '曼彻斯特城', away_team_name: '利雅得新月',
          kickoff_time: '2026-07-14T19:15:00+08:00', capture_status: { status: 'complete', capture_kind: 'opening', failure_reason: null },
          series: [{ snapshot_id: 1, snapshot_time: '2026-07-14T17:30:00+08:00', play_type: 'spf', option_code: 'h', option_name: '主胜', sp_value: 1.27, handicap: null, implied_probability: 0.78, prev_sp_value: null }],
          anomalies: [],
        },
        {
          id: 305, official_match_code: '周二202', business_date: '2026-07-14', league_name: '西甲',
          home_team_name: '巴塞罗那', away_team_name: '皇家马德里',
          kickoff_time: '2026-07-14T20:00:00+08:00', capture_status: null,
          series: [], anomalies: [],
        },
      ],
    });
  });

  it('休市时用官方恢复时间解释当前比赛为空', async () => {
    oddsIndex.mockResolvedValue({
      current: { count: 0 },
      history: [{ business_date: '2026-07-13', match_count: 3 }],
      sales_window: {
        is_open: false,
        message: '官方竞彩休市中，今日 11:00 恢复开售',
      },
    });
    oddsMovements.mockResolvedValue({
      scope: 'current', business_date: null, play_type: 'spf', resolution: 'raw', total: 0,
      matches: [],
      sales_window: {
        is_open: false,
        message: '官方竞彩休市中，今日 11:00 恢复开售',
      },
    });

    render(<OddsMovementPage />);

    expect(await screen.findByText('官方竞彩休市中，今日 11:00 恢复开售')).toBeInTheDocument();
    expect(screen.queryByText('赛程开盘后会自动出现在这里')).not.toBeInTheDocument();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('按当前与历史日期批量展示全部比赛', async () => {
    render(<OddsMovementPage />);

    await waitFor(() => expect(oddsIndex).toHaveBeenCalledOnce());
    await waitFor(() => expect(oddsMovements).toHaveBeenCalledWith({
      scope: 'current', business_date: undefined, play_type: 'spf', resolution: 'raw', limit: 200,
    }));
    expect(await screen.findByText(/周二201/)).toBeInTheDocument();
    expect(screen.getByText(/周二202/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /07-13/ }));

    await waitFor(() => expect(oddsMovements).toHaveBeenLastCalledWith({
      scope: 'history', business_date: '2026-07-13', play_type: 'spf', resolution: 'hour', limit: 200,
    }));
  });

  it('定时同步当前开盘比赛的新赔率', async () => {
    vi.useFakeTimers();
    render(<OddsMovementPage />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(oddsMovements).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(30_000); await Promise.resolve(); });
    expect(oddsMovements).toHaveBeenCalledTimes(2);
    expect(oddsIndex).toHaveBeenCalledTimes(2);
  });
});
