import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
  sp_value: 2.08,
  fair_odds: 1.64,
  ev: 0.12,
  edge: 0.13,
  market_edge: 0.13,
  break_even_probability: 0.4808,
  breakeven_edge: 0.1292,
  confidence: 0.72,
  odds_snapshot_time: '2026-07-08T09:00:00',
  data_completeness: 92,
  validation_status: 'valid',
  model_independent: true,
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
    tickets.mockResolvedValue({ tickets: [], total: 0 });
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
    expect(formatRecommendationOptionDisplay({ option_name: '让胜(+1)', sp_value: 1.15 }, 'win')).toBe('主胜(+1)@1.15/胜利');
    expect(formatRecommendationOptionDisplay({ option_name: '让负(+1)', sp_value: 4.32 }, 'lose')).toBe('主负(+1)@4.32/失败');
    expect(formatRecommendationOptionDisplay({ option_name: '让平(+1)', sp_value: 3.9 }, null)).toBe('平(+1)@3.9');
    expect(formatRecommendationOptionDisplay({ play_type: 'bf', option_code: 'other_h', option_name: 'other_h', sp_value: 18 }, null)).toBe('胜其他@18');
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
      expect(screen.getByLabelText('上海海港 VS 山东泰山')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText('上海海港 VS 山东泰山'));

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
      expect(screen.getByLabelText('上海海港 VS 山东泰山')).toBeInTheDocument();
    });

    const table = container.querySelector('table.recommendation-table');
    expect(table).not.toBeNull();
    expect(table?.querySelectorAll('colgroup col')).toHaveLength(13);
    expect(table?.querySelectorAll('thead th')).toHaveLength(13);
  });

  it('renders the match cell as home team above away team with logo slots', async () => {
    const { container } = render(<RecommendationsPage embedded />);

    await waitFor(() => {
      expect(screen.getByLabelText('上海海港 VS 山东泰山')).toBeInTheDocument();
    });

    const teamStack = container.querySelector('.recommendation-team-stack');
    expect(teamStack?.textContent).toBe('上海海港山东泰山');
    expect(teamStack?.querySelectorAll('[data-testid="team-logo"]')).toHaveLength(2);
  });
});


describe('预测独立资源与证据分组', () => {
  beforeEach(() => {
    vi.clearAllMocks(); tickets.mockResolvedValue({ tickets: [], total: 0 });
    liveRecommendations.mockResolvedValue({ status: 'ok', recommendations: [recommendation], total: 1, sales_window: { is_open: true } });
  });
  afterEach(() => vi.useRealTimers());

  it('票单失败仍展示预测', async () => {
    tickets.mockRejectedValueOnce(new Error('票单故障'));
    render(<RecommendationsPage embedded />);
    expect(await screen.findByLabelText('上海海港 VS 山东泰山')).toBeInTheDocument();
    expect(screen.getByText(/票单故障/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新票单' })).toBeInTheDocument();
  });

  it('推荐失败有独立重试且没有伪装空数据', async () => {
    liveRecommendations.mockRejectedValueOnce(new Error('预测故障'));
    render(<RecommendationsPage embedded />);
    expect(await screen.findByText(/预测故障/)).toBeInTheDocument();
    expect(screen.queryByText('暂无模型推荐')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新预测' }));
    expect(await screen.findByLabelText('上海海港 VS 山东泰山')).toBeInTheDocument();
  });

  it('搜索联赛筛选和清空保持现有选择联动', async () => {
    const onMatchSelect = vi.fn();
    render(<RecommendationsPage embedded onMatchSelect={onMatchSelect} />);
    await screen.findByLabelText('上海海港 VS 山东泰山');
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索预测赛事' }), { target: { value: '不存在' } });
    expect(screen.getByText('预测筛选无结果')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '清空预测筛选' }));
    fireEvent.change(screen.getByRole('combobox', { name: '预测联赛' }), { target: { value: '中超' } });
    fireEvent.click(screen.getByLabelText('上海海港 VS 山东泰山'));
    expect(onMatchSelect).toHaveBeenCalledWith(expect.objectContaining({ matchId: 901 }));
  });

  it('不同模型或时间不能合并成同组', async () => {
    liveRecommendations.mockResolvedValue({ status: 'ok', total: 4, recommendations: [recommendation,
      { ...recommendation, prediction_id: 11, model_name: '模型B' },
      { ...recommendation, prediction_id: 12, predict_time: '2026-07-08T10:00:00' },
      { ...recommendation, prediction_id: 13, odds_snapshot_time: '2026-07-08T10:00:00' }], sales_window: { is_open: true } });
    const { container } = render(<RecommendationsPage embedded />);
    await waitFor(() => expect(container.querySelectorAll('table.recommendation-table tbody tr')).toHaveLength(4));
  });

  it('推荐分页每页25组，筛选后回第一页', async () => {
    liveRecommendations.mockResolvedValue({ status: 'ok', total: 26,
      recommendations: Array.from({ length: 26 }, (_, i) => ({ ...recommendation, prediction_id: 20 + i, match_id: 1000 + i, home_team: `界面测试主队${i}` })), sales_window: { is_open: true } });
    const { container } = render(<RecommendationsPage embedded />);
    await waitFor(() => expect(container.querySelectorAll('table.recommendation-table tbody tr')).toHaveLength(25));
    fireEvent.click(screen.getByRole('button', { name: '下一页预测' }));
    expect(container.querySelectorAll('table.recommendation-table tbody tr')).toHaveLength(1);
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索预测赛事' }), { target: { value: '主队0' } });
    expect(screen.getByText(/第 1 \/ 1 页/)).toBeInTheDocument();
  });

  it('刷新失败保留预测并提示', async () => {
    render(<RecommendationsPage embedded />); await screen.findByLabelText('上海海港 VS 山东泰山');
    liveRecommendations.mockRejectedValueOnce(new Error('刷新断线'));
    fireEvent.click(screen.getByRole('button', { name: '刷新预测' }));
    expect(await screen.findByText(/刷新断线/)).toBeInTheDocument();
    expect(screen.getByLabelText('上海海港 VS 山东泰山')).toBeInTheDocument();
  });

  it('休市空响应保留旧推荐时明确标识', async () => {
    render(<RecommendationsPage embedded />); await screen.findByLabelText('上海海港 VS 山东泰山');
    liveRecommendations.mockResolvedValue({ status: 'resting', recommendations: [], total: 0, sales_window: { is_open: false, message: '休市测试' } });
    fireEvent.click(screen.getByRole('button', { name: '刷新预测' }));
    expect(await screen.findByText(/休市保留上次推荐/)).toBeInTheDocument();
    expect(screen.getByLabelText('上海海港 VS 山东泰山')).toBeInTheDocument();
  });

  it('正EV为空时保留原基线回退查询并说明', async () => {
    liveRecommendations.mockResolvedValueOnce({ status: 'ok', recommendations: [], total: 0, sales_window: { is_open: true } });
    render(<RecommendationsPage embedded />);
    expect(await screen.findByText(/当前无正 EV 投注推荐/)).toBeInTheDocument();
    expect(liveRecommendations).toHaveBeenLastCalledWith({ limit: 500, min_ev: -1, min_confidence: 0 });
  });

  it('每30秒刷新预测和票单', async () => {
    vi.useFakeTimers(); render(<RecommendationsPage embedded />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(30_000); await Promise.resolve(); });
    expect(liveRecommendations).toHaveBeenCalledTimes(2); expect(tickets).toHaveBeenCalledTimes(2);
  });
});


describe('预测数值与边界', () => {
  beforeEach(() => { vi.clearAllMocks(); tickets.mockResolvedValue({ tickets: [], total: 0 }); });
  it('零概率和负EV准确显示', async () => {
    liveRecommendations.mockResolvedValue({ status: 'ok', recommendations: [{ ...recommendation, model_probability: 0, ev: -0.12 }], total: 1 });
    render(<RecommendationsPage embedded />);
    expect(await screen.findByText('0.0%')).toBeInTheDocument(); expect(screen.getByText('-0.120')).toBeInTheDocument();
    expect(screen.queryByText('+-0.120')).not.toBeInTheDocument();
  });
  it('非法概率拒绝而非NaN显示', async () => {
    liveRecommendations.mockResolvedValue({ status: 'ok', recommendations: [{ ...recommendation, model_probability: NaN }], total: 1 });
    render(<RecommendationsPage embedded />);
    expect(await screen.findByText(/预测数据格式不正确/)).toBeInTheDocument(); expect(screen.queryByText('NaN%')).not.toBeInTheDocument();
  });
  it('分组选择只返回该模型证据并支持键盘', async () => {
    const onMatchSelect = vi.fn();
    liveRecommendations.mockResolvedValue({ status: 'ok', recommendations: [recommendation, { ...recommendation, prediction_id: 11, model_name: '模型B' }], total: 2 });
    render(<RecommendationsPage embedded onMatchSelect={onMatchSelect} />);
    const labels = await screen.findAllByLabelText('上海海港 VS 山东泰山');
    fireEvent.keyDown(labels[1].closest('tr')!, { key: 'Enter' });
    expect(onMatchSelect).toHaveBeenCalledWith(expect.objectContaining({ options: [expect.objectContaining({ model_name: '模型B' })] }));
    fireEvent.click(screen.getByLabelText('强信号队列').querySelector('button')!);
    expect(onMatchSelect).toHaveBeenLastCalledWith(expect.objectContaining({ options: [recommendation] }));
  });
});
