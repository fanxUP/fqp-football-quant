import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import OddsMovementPage from './OddsMovementPage';

const { oddsHistoryMatches, oddsMovement } = vi.hoisted(() => ({
  oddsHistoryMatches: vi.fn(),
  oddsMovement: vi.fn(),
}));

oddsHistoryMatches.mockResolvedValue({
  total: 1,
  matches: [{
    id: 304, official_match_code: '周一005', league_name: '英超',
    home_team_name: '曼彻斯特城', away_team_name: '利雅得新月',
    kickoff_time: '2025-07-01T03:00:00', play_types: ['spf'],
  }],
});
oddsMovement.mockResolvedValue({
  data: {
    series: [
      { option_code: 'h', option_name: '主胜', snapshot_time: '2025-06-28T09:48:36', sp_value: 1.27, implied_probability: 0.78, handicap: null },
      { option_code: 'h', option_name: '主胜', snapshot_time: '2025-06-30T10:19:40', sp_value: 1.18, implied_probability: 0.85, handicap: null },
    ],
    anomalies: [],
  },
});

vi.mock('../core/apiClient', () => ({
  api: {
    official: { oddsHistoryMatches },
    dashboard: { oddsMovement },
  },
}));
vi.mock('../visualization', () => ({
  OddsMovementChart: () => <div>走势图已渲染</div>,
  applyChartTheme: <T,>(option: T) => option,
  CHART_COLORS: { blue: '#00f', amber: '#fa0', areaAgent: 'transparent' },
}));
vi.mock('../shared/components/ChartCard', () => ({ default: () => <div>隐含概率图</div> }));

describe('OddsMovementPage', () => {
  it('loads persisted official history and searches historical matches', async () => {
    render(<OddsMovementPage />);

    await waitFor(() => expect(oddsHistoryMatches).toHaveBeenCalledWith({ limit: 200, search: undefined }));
    await waitFor(() => expect(oddsMovement).toHaveBeenCalledWith({ match_id: 304, play_type: 'spf' }));
    expect(await screen.findByText('走势图已渲染')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /周一005.*曼彻斯特城/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('搜索历史赔率比赛'), { target: { value: '曼彻斯特城' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索' }));

    await waitFor(() => expect(oddsHistoryMatches).toHaveBeenLastCalledWith({ limit: 200, search: '曼彻斯特城' }));
  });
});
