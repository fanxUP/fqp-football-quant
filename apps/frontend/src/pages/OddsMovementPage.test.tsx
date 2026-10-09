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
    oddsMovements.mockImplementation(async (params) => ({
      scope: params.scope,
      business_date: params.business_date ?? null,
      play_type: params.play_type,
      resolution: params.resolution,
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
    }));
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
    expect(screen.getByRole('combobox', { name: '赔率联赛' })).toBeInTheDocument();

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

function oddsFixture(id = 304, league = '英超') {
  return { id, official_match_code: `测试${id}`, business_date: '2026-07-13', league_name: league,
    home_team_name: `界面测试主队${id}`, away_team_name: '界面测试客队', kickoff_time: '2026-07-13T19:00:00+08:00',
    capture_status: null, series: [], anomalies: [] };
}
function oddsResponse(matches = [oddsFixture()]) {
  return { scope: 'current', business_date: null, play_type: 'spf', resolution: 'raw', total: matches.length, matches };
}

describe('赔率查询隔离与筛选', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    oddsIndex.mockResolvedValue({ current: { count: 1 }, history: [{ business_date: '2026-07-13', match_count: 1 }] });
    oddsMovements.mockResolvedValue(oddsResponse());
  });
  afterEach(() => vi.useRealTimers());

  it('玩法空响应清除上一组曲线', async () => {
    render(<OddsMovementPage />);
    await screen.findByText(/测试304.*图表/);
    oddsMovements.mockResolvedValue({ ...oddsResponse([]), play_type: 'bf' });
    fireEvent.click(screen.getByRole('tab', { name: '比分' }));
    expect(await screen.findByText('当前没有开盘比赛')).toBeInTheDocument();
    expect(screen.queryByText(/测试304.*图表/)).not.toBeInTheDocument();
  });

  it('旧日期晚返回不会覆盖当前查询', async () => {
    let resolveOld!: (value: unknown) => void;
    oddsMovements.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    render(<OddsMovementPage />);
    await screen.findByRole('button', { name: /07-13/ });
    oddsMovements.mockResolvedValue({ ...oddsResponse([oddsFixture(305)]), scope: 'history', business_date: '2026-07-13', resolution: 'hour' });
    fireEvent.click(screen.getByRole('button', { name: /07-13/ }));
    await screen.findByText(/测试305.*图表/);
    await waitFor(() => expect(oddsMovements).toHaveBeenCalledTimes(2));
    await act(async () => resolveOld(oddsResponse([oddsFixture(999)])));
    expect(screen.queryByText(/测试999.*图表/)).not.toBeInTheDocument();
    expect(screen.getByText(/测试305.*图表/)).toBeInTheDocument();
  });

  it('同查询刷新失败保留最后成功结果并允许恢复', async () => {
    render(<OddsMovementPage />); await screen.findByText(/测试304.*图表/);
    oddsMovements.mockRejectedValueOnce(new Error('测试断线'));
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText(/测试断线/)).toBeInTheDocument();
    expect(screen.getByText(/测试304.*图表/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    await waitFor(() => expect(screen.queryByText(/测试断线/)).not.toBeInTheDocument());
  });

  it('初次失败可以手动重试', async () => {
    oddsMovements.mockRejectedValueOnce(new Error('首次失败'));
    render(<OddsMovementPage />);
    expect(await screen.findByText(/首次失败/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText(/测试304.*图表/)).toBeInTheDocument();
  });

  it('索引失败不挡住当前赔率', async () => {
    oddsIndex.mockRejectedValueOnce(new Error('索引失败'));
    render(<OddsMovementPage />);
    expect(await screen.findByText(/测试304.*图表/)).toBeInTheDocument();
    expect(screen.getByText(/索引失败/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新日期索引' })).toBeInTheDocument();
  });

  it('组合筛选与分页只挂载十场图表并重置页码', async () => {
    oddsMovements.mockResolvedValue(oddsResponse(Array.from({ length: 12 }, (_, i) => oddsFixture(400 + i, i % 2 ? '西甲' : '英超'))));
    render(<OddsMovementPage />); await screen.findByText(/测试400.*图表/);
    expect(screen.getAllByRole('article')).toHaveLength(10);
    fireEvent.click(screen.getByRole('button', { name: '下一页赔率' }));
    expect(screen.getAllByRole('article')).toHaveLength(2);
    fireEvent.change(screen.getByRole('combobox', { name: '赔率联赛' }), { target: { value: '英超' } });
    expect(screen.getAllByRole('article')).toHaveLength(6);
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索赔率赛事' }), { target: { value: '404' } });
    expect(screen.getAllByRole('article')).toHaveLength(1);
    fireEvent.change(screen.getByRole('combobox', { name: '采集状态' }), { target: { value: 'complete' } });
    expect(screen.getByText('筛选无结果')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '清空赔率筛选' }));
    expect(screen.getAllByRole('article')).toHaveLength(10);
  });

  it('错玩法响应拒绝展示', async () => {
    oddsMovements.mockResolvedValue({ ...oddsResponse(), play_type: 'bf' });
    render(<OddsMovementPage />);
    expect(await screen.findByText(/赔率响应与当前查询不一致/)).toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });

  it('历史模式不自动刷新', async () => {
    render(<OddsMovementPage />); await screen.findByText(/测试304.*图表/);
    oddsMovements.mockResolvedValue({ ...oddsResponse(), scope: 'history', business_date: '2026-07-13', resolution: 'hour' });
    fireEvent.click(screen.getByRole('button', { name: /07-13/ }));
    await waitFor(() => expect(oddsMovements).toHaveBeenCalledTimes(2));
    vi.useFakeTimers();
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(oddsMovements).toHaveBeenCalledTimes(2);
  });

  it('重复赛事响应拒绝覆盖，保留深链接', async () => {
    render(<OddsMovementPage />); await screen.findByText(/测试304.*图表/);
    expect(screen.getByRole('link', { name: '查看赛事详情' })).toHaveAttribute('href', '#/matches/304');
    oddsMovements.mockResolvedValue(oddsResponse([oddsFixture(), oddsFixture()]));
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText(/赔率数据格式不正确/)).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });
});


describe('赔率响应边界', () => {
  beforeEach(() => { vi.clearAllMocks(); oddsIndex.mockResolvedValue({ current: { count: 1 }, history: [{ business_date: '2026-07-13', match_count: 1 }] }); oddsMovements.mockResolvedValue(oddsResponse()); });
  it('错历史日期拒绝展示', async () => {
    render(<OddsMovementPage />); await screen.findByText(/测试304.*图表/);
    oddsMovements.mockResolvedValue({ ...oddsResponse(), scope: 'history', business_date: '2026-07-12', resolution: 'hour' });
    fireEvent.click(screen.getByRole('button', { name: /07-13/ }));
    expect(await screen.findByText(/赔率响应与当前查询不一致/)).toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });
  it('数据缩减后页码收敛并更新空响应', async () => {
    oddsMovements.mockResolvedValue(oddsResponse(Array.from({ length: 11 }, (_, i) => oddsFixture(400 + i))));
    render(<OddsMovementPage />); await screen.findByText(/测试400.*图表/);
    fireEvent.click(screen.getByRole('button', { name: '下一页赔率' }));
    oddsMovements.mockResolvedValue(oddsResponse()); fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText(/测试304.*图表/)).toBeInTheDocument();
    expect(screen.getByText(/第 1 \/ 1 页/)).toBeInTheDocument();
    oddsMovements.mockResolvedValue(oddsResponse([])); fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText('当前没有开盘比赛')).toBeInTheDocument(); expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });
});
