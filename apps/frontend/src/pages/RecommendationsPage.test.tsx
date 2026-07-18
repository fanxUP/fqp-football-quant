import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RecommendationsPage, {
  buildRecommendationInsightSummary,
  formatRecommendationOptionDisplay,
} from './RecommendationsPage';
import type { LiveRecommendation, SimulationTicket } from '../core/types';

const { tickets, liveRecommendations } = vi.hoisted(() => ({
  tickets: vi.fn(async () => ({ tickets: [] as SimulationTicket[], total: 0 })),
  liveRecommendations: vi.fn(),
}));

const recommendation: LiveRecommendation = {
  prediction_id: 10,
  match_id: 901,
  play_type: 'spf',
  play_type_name: '胜平负',
  option_code: '3',
  option_name: '主胜',
  model_probability: 0.61,
  market_probability: 0.48,
  fair_odds: 1.64,
  ev: 0.12,
  edge: 0.13,
  confidence: 0.72,
  predict_time: '2026-07-08T09:00:00',
  model_name: 'xgb-main',
  home_team: '上海海港',
  away_team: '山东泰山',
  league: '中超',
  kickoff_time: '2026-07-08T19:35:00',
  match_status: 'Scheduled',
  match_num_str: '3001',
  ht_home_goals: null,
  ht_away_goals: null,
  ft_home_goals: null,
  ft_away_goals: null,
  et_home_goals: null,
  et_away_goals: null,
  pk_home_goals: null,
  pk_away_goals: null,
  spf_result: null,
  rqspf_result: null,
  total_goals_result: null,
  score_result: null,
  half_full_result: null,
};

vi.mock('../core/apiClient', () => ({
  api: {
    tickets,
    liveRecommendations,
  },
}));

vi.mock('../shared/components/ChartCard', () => ({
  default: ({ title }: { title: string }) => <div>{title}</div>,
}));

vi.mock('../shared/components/TeamLogo', () => ({
  default: ({ nameCn }: { nameCn?: string | null }) => (
    <span data-testid="team-logo" aria-label={`${nameCn}队徽`} />
  ),
}));

describe('RecommendationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    liveRecommendations.mockResolvedValue({
      status: 'ok',
      recommendations: [recommendation],
      total: 1,
      sales_window: { is_open: true },
    });
  });

  it('休市时显示官方提示且不回退为模型基线推荐', async () => {
    liveRecommendations.mockResolvedValue({
      status: 'resting',
      recommendations: [],
      total: 0,
      sales_window: {
        is_open: false,
        message: '官方竞彩休市中，今日 11:00 恢复开售',
      },
    });

    render(<RecommendationsPage embedded />);

    expect(await screen.findByText('官方竞彩休市中，今日 11:00 恢复开售')).toBeInTheDocument();
    expect(liveRecommendations).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/模型基线分析/)).not.toBeInTheDocument();
  });

  it('formats recommendation option rows with odds and settlement result', () => {
    expect(formatRecommendationOptionDisplay({ option_name: '让胜(+1)', fair_odds: 1.15 }, 'win')).toBe('主胜(+1)@1.15/胜利');
    expect(formatRecommendationOptionDisplay({ option_name: '让负(+1)', fair_odds: 4.32 }, 'lose')).toBe('主负(+1)@4.32/失败');
    expect(formatRecommendationOptionDisplay({ option_name: '让平(+1)', fair_odds: 3.9 }, null)).toBe('平(+1)@3.9');
  });

  it('summarizes strong and conflicting match signals from live recommendations', () => {
    const awayRecommendation: LiveRecommendation = {
      ...recommendation,
      prediction_id: 11,
      option_code: '0',
      option_name: '客胜',
      model_probability: 0.58,
      market_probability: 0.39,
      ev: 0.18,
      edge: 0.19,
      confidence: 0.74,
    };
    const weakerRecommendation: LiveRecommendation = {
      ...recommendation,
      prediction_id: 12,
      match_id: 902,
      home_team: '北京国安',
      away_team: '成都蓉城',
      ev: 0.03,
      edge: 0.04,
      confidence: 0.42,
    };

    const summary = buildRecommendationInsightSummary([
      recommendation,
      awayRecommendation,
      weakerRecommendation,
    ]);

    expect(summary.strongSignals[0]).toMatchObject({
      matchId: 901,
      bestOptionName: '主负',
      directionCount: 2,
    });
    expect(summary.conflictSignals).toHaveLength(1);
    expect(summary.conflictSignals[0]).toMatchObject({
      matchId: 901,
      homeTeam: '上海海港',
      awayTeam: '山东泰山',
    });
  });

  it('passes the grouped match recommendation when a live row is selected', async () => {
    const onMatchSelect = vi.fn();

    render(<RecommendationsPage embedded onMatchSelect={onMatchSelect} />);

    await waitFor(() => {
      expect(screen.getByLabelText('上海海港 对阵 山东泰山')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText('上海海港 对阵 山东泰山'));

    expect(onMatchSelect).toHaveBeenCalledWith(expect.objectContaining({
      matchId: 901,
      homeTeam: '上海海港',
      awayTeam: '山东泰山',
      playTypeName: '胜平负',
      options: [recommendation],
    }));
  });

  it('locks the live recommendation table to the same column model as its header', async () => {
    const { container } = render(<RecommendationsPage embedded />);

    await waitFor(() => {
      expect(screen.getByLabelText('上海海港 对阵 山东泰山')).toBeInTheDocument();
    });

    const table = container.querySelector('table.recommendation-table');
    expect(table).not.toBeNull();
    expect(table?.querySelectorAll('colgroup col')).toHaveLength(13);
    expect(table?.querySelectorAll('thead th')).toHaveLength(13);
  });

  it('renders the match cell as home team above away team with logo slots', async () => {
    const { container } = render(<RecommendationsPage embedded />);

    await waitFor(() => {
      expect(screen.getByLabelText('上海海港 对阵 山东泰山')).toBeInTheDocument();
    });

    const teamStack = container.querySelector('.recommendation-team-stack');
    expect(teamStack?.textContent).toBe('上海海港山东泰山');
    expect(teamStack?.querySelectorAll('[data-testid="team-logo"]')).toHaveLength(2);
  });
});
