import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OddsMovementPoint } from '../core/types';
import OddsMovementPage from './OddsMovementPage';
import OddsSnapshotHeatmap from './odds/OddsSnapshotHeatmap';

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

  it('休市时显示已保存的赔率和源快照时间', async () => {
    const salesWindow = { is_open: false, message: '官方竞彩休市中，今日 11:00 恢复开售' };
    const match = oddsFixture(304, '英超', [oddsPoint(1, 11, 'h', '主胜', 2.1)]);
    oddsIndex.mockResolvedValue({ current: { count: 1 }, history: [], sales_window: salesWindow });
    oddsMovements.mockResolvedValue({ ...oddsResponse([match]), sales_window: salesWindow });

    render(<OddsMovementPage />);

    expect(await screen.findByText(/官方竞彩休市中.*已保存的赔率快照/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '当前 (1)' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: '赔率快照对照' })).toBeInTheDocument();
    expect(screen.getByText(/最新源快照：/)).toBeInTheDocument();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('通过日历选择历史日期，清空后返回当前赔率', async () => {
    render(<OddsMovementPage />);

    await waitFor(() => expect(oddsIndex).toHaveBeenCalledOnce());
    await waitFor(() => expect(oddsMovements).toHaveBeenCalledWith({
      scope: 'current', business_date: undefined, play_type: 'spf', resolution: 'raw', limit: 200,
    }));
    expect(await screen.findByRole('heading', { name: /周二201/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /周二202/ })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '赔率联赛' })).toBeInTheDocument();

    const dateInput = screen.getByLabelText('赔率历史日期');
    expect(dateInput).toHaveAttribute('type', 'date');
    expect(dateInput).toHaveAttribute('min', '2026-07-13');
    expect(dateInput).toHaveAttribute('max', '2026-07-13');
    expect(dateInput).toHaveValue('');
    fireEvent.change(dateInput, { target: { value: '2026-07-13' } });

    await waitFor(() => expect(oddsMovements).toHaveBeenLastCalledWith({
      scope: 'history', business_date: '2026-07-13', play_type: 'spf', resolution: 'hour', limit: 200,
    }));
    expect(screen.getByText('2026-07-13 · 3 场')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '当前 (2)' })).toHaveAttribute('aria-pressed', 'false');

    fireEvent.change(dateInput, { target: { value: '' } });
    await waitFor(() => expect(oddsMovements).toHaveBeenLastCalledWith({
      scope: 'current', business_date: undefined, play_type: 'spf', resolution: 'raw', limit: 200,
    }));
    expect(screen.getByRole('button', { name: '当前 (2)' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('没有历史日期时禁用日历，仍然展示当前赔率', async () => {
    oddsIndex.mockResolvedValue({ current: { count: 2 }, history: [] });
    render(<OddsMovementPage />);

    expect(await screen.findByLabelText('赔率历史日期')).toBeDisabled();
    expect(screen.getByText('暂无历史赔率记录')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: /周二201/ })).toBeInTheDocument();
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

function oddsFixture(id = 304, league = '英超', series: OddsMovementPoint[] = []) {
  return { id, official_match_code: `测试${id}`, business_date: '2026-07-13', league_name: league,
    home_team_name: `界面测试主队${id}`, away_team_name: '界面测试客队', kickoff_time: '2026-07-13T19:00:00+08:00',
    capture_status: null, series, anomalies: [] };
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
    await screen.findByRole('heading', { name: /测试304/ });
    oddsMovements.mockResolvedValue({ ...oddsResponse([]), play_type: 'bf' });
    fireEvent.click(screen.getByRole('tab', { name: '比分' }));
    expect(await screen.findByText('当前没有开盘比赛')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /测试304/ })).not.toBeInTheDocument();
  });

  it('旧日期晚返回不会覆盖当前查询', async () => {
    let resolveOld!: (value: unknown) => void;
    oddsMovements.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    render(<OddsMovementPage />);
    await screen.findByLabelText('赔率历史日期');
    oddsMovements.mockResolvedValue({ ...oddsResponse([oddsFixture(305)]), scope: 'history', business_date: '2026-07-13', resolution: 'hour' });
    fireEvent.change(screen.getByLabelText('赔率历史日期'), { target: { value: '2026-07-13' } });
    await screen.findByRole('heading', { name: /测试305/ });
    await waitFor(() => expect(oddsMovements).toHaveBeenCalledTimes(2));
    await act(async () => resolveOld(oddsResponse([oddsFixture(999)])));
    expect(screen.queryByRole('heading', { name: /测试999/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /测试305/ })).toBeInTheDocument();
  });

  it('同查询刷新失败保留最后成功结果并允许恢复', async () => {
    render(<OddsMovementPage />); await screen.findByRole('heading', { name: /测试304/ });
    oddsMovements.mockRejectedValueOnce(new Error('测试断线'));
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText(/测试断线/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /测试304/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    await waitFor(() => expect(screen.queryByText(/测试断线/)).not.toBeInTheDocument());
  });

  it('初次失败可以手动重试', async () => {
    oddsMovements.mockRejectedValueOnce(new Error('首次失败'));
    render(<OddsMovementPage />);
    expect(await screen.findByText(/首次失败/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByRole('heading', { name: /测试304/ })).toBeInTheDocument();
  });

  it('索引失败不挡住当前赔率', async () => {
    oddsIndex.mockRejectedValueOnce(new Error('索引失败'));
    render(<OddsMovementPage />);
    expect(await screen.findByRole('heading', { name: /测试304/ })).toBeInTheDocument();
    expect(screen.getByText(/索引失败/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新日期索引' })).toBeInTheDocument();
  });

  it('组合筛选与分页只展示十场比赛并重置页码', async () => {
    oddsMovements.mockResolvedValue(oddsResponse(Array.from({ length: 12 }, (_, i) => oddsFixture(400 + i, i % 2 ? '西甲' : '英超'))));
    render(<OddsMovementPage />); await screen.findByRole('heading', { name: /测试400/ });
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
    render(<OddsMovementPage />); await screen.findByRole('heading', { name: /测试304/ });
    oddsMovements.mockResolvedValue({ ...oddsResponse(), scope: 'history', business_date: '2026-07-13', resolution: 'hour' });
    fireEvent.change(screen.getByLabelText('赔率历史日期'), { target: { value: '2026-07-13' } });
    await waitFor(() => expect(oddsMovements).toHaveBeenCalledTimes(2));
    vi.useFakeTimers();
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(oddsMovements).toHaveBeenCalledTimes(2);
  });

  it('重复赛事响应拒绝覆盖，保留深链接', async () => {
    render(<OddsMovementPage />); await screen.findByRole('heading', { name: /测试304/ });
    expect(screen.getByRole('link', { name: '查看赛事详情' })).toHaveAttribute('href', '#/matches/304');
    oddsMovements.mockResolvedValue(oddsResponse([oddsFixture(), oddsFixture()]));
    fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText(/赔率数据格式不正确/)).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });
});

function oddsPoint(snapshot_id: number, hour: number, option_code: string, option_name: string, sp_value: number,
  play_type = 'spf', handicap: number | null = null): OddsMovementPoint {
  return {
    snapshot_id, snapshot_time: `2026-07-13T${hour}:00:00+08:00`,
    option_code, option_name, sp_value, play_type, handicap, implied_probability: null, prev_sp_value: null,
  };
}

describe('赔率快照热力图', () => {
  it('按快照时间展示初始赔率，末次格显示涨跌分档与单笔状态', async () => {
    const data = [
      oddsPoint(5, 15, 'h', '主胜', 4.6), oddsPoint(1, 11, 'h', '主胜', 4.2), oddsPoint(2, 11, 'h', '主胜', 4),
      oddsPoint(3, 11, 'd', '平局', 2), oddsPoint(6, 15, 'd', '平局', 1.9), oddsPoint(4, 11, 'a', '客胜', 2.5),
    ];
    oddsIndex.mockResolvedValue({ current: { count: 1 }, history: [] });
    oddsMovements.mockResolvedValue(oddsResponse([oddsFixture(304, '英超', data)]));
    render(<OddsMovementPage />);

    const table = within(await screen.findByRole('table', { name: '赔率快照对照' }));
    expect(table.getAllByRole('columnheader').map(header => header.textContent)).toEqual(['赔率来源', '主胜', '平局', '客胜']);
    const source = within(table.getByRole('row', { name: /中国体彩/ }));
    const home = within(source.getByRole('cell', { name: /初始赔率：4\.00.*最新赔率：4\.60/ }));
    expect(home.getByText('4.60').parentElement).toHaveAttribute('data-direction', 'up');
    expect(home.getByText('↑ 15.0%').parentElement).toHaveAttribute('data-strength', '3');
    const draw = within(source.getByRole('cell', { name: /初始赔率：2\.00.*最新赔率：1\.90/ }));
    expect(draw.getByText('↓ 5.0%').parentElement).toHaveAttribute('data-strength', '2');
    expect(draw.getByText('1.90').parentElement).toHaveAttribute('data-direction', 'down');
    expect(table.getByText('仅一笔').parentElement).toHaveAttribute('data-direction', 'flat');
    expect(screen.queryByText('历史走势 图表')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('查看历史走势'));
    expect(await screen.findByText('历史走势 图表')).toBeInTheDocument();
  });

  it('历史标明最终赔率，让球变盘时只比较最新盘口的首末快照', async () => {
    oddsIndex.mockResolvedValue({ current: { count: 0 }, history: [{ business_date: '2026-07-13', match_count: 1 }] });
    const data = [
      oddsPoint(3, 15, 'h', '让球胜', 2.52, 'rqspf', -1),
      oddsPoint(1, 11, 'h', '让球胜', 1.8, 'rqspf', -2),
      oddsPoint(2, 13, 'h', '让球胜', 2.4, 'rqspf', -1),
    ];
    oddsMovements.mockImplementation(async params => ({
      ...oddsResponse(params.play_type === 'rqspf' ? [oddsFixture(304, '英超', data)] : []),
      scope: params.scope, business_date: params.business_date ?? null, play_type: params.play_type, resolution: params.resolution,
    }));
    render(<OddsMovementPage />);
    fireEvent.change(await screen.findByLabelText('赔率历史日期'), { target: { value: '2026-07-13' } });
    fireEvent.click(screen.getByRole('tab', { name: '让球胜平负' }));

    const table = within(await screen.findByRole('table', { name: '赔率快照对照' }));
    expect(table.getByRole('columnheader', { name: '让球胜' })).toBeInTheDocument();
    expect(table.getByText('-1 球')).toBeInTheDocument();
    expect(table.getByRole('cell', { name: /初始赔率：2\.40.*最终赔率：2\.52/ })).toBeInTheDocument();
    expect(table.getByText('↑ 5.0%')).toBeInTheDocument();
    expect(table.queryByText('1.80')).not.toBeInTheDocument();
  });

  it('不同公司各占一行，按选项对齐，缺失列留空并独立计算涨跌', () => {
    render(<OddsSnapshotHeatmap playType="spf" historical={false} sources={[
      { id: 'official', label: '中国体彩', snapshots: [
        oddsPoint(1, 11, 'h', '主胜', 2), oddsPoint(2, 15, 'h', '主胜', 2.2),
        oddsPoint(3, 11, 'd', '平局', 3.25),
      ] },
      { id: 'demo', label: '示例公司', snapshots: [
        oddsPoint(3, 11, 'a', '客胜', 4),
        oddsPoint(1, 11, 'h', '主胜', 2.5), oddsPoint(2, 15, 'h', '主胜', 2),
      ] },
    ]} />);

    const table = within(screen.getByRole('table', { name: '赔率快照对照' }));
    expect(table.getAllByRole('columnheader').map(header => header.textContent)).toEqual(['赔率来源', '主胜', '平局', '客胜']);
    expect(table.getAllByRole('rowheader').map(header => header.textContent)).toEqual(['中国体彩', '示例公司']);
    const official = within(table.getByRole('row', { name: /中国体彩/ })).getAllByRole('cell');
    const demo = within(table.getByRole('row', { name: /示例公司/ })).getAllByRole('cell');
    expect(official[0]).toHaveTextContent('↑ 10.0%');
    expect(demo[0]).toHaveTextContent('↓ 20.0%');
    expect(official[2]).toHaveAccessibleName('暂无快照');
    expect(demo[1]).toHaveAccessibleName('暂无快照');
    expect(demo[2]).toHaveTextContent('4.00');
  });
});


describe('赔率响应边界', () => {
  beforeEach(() => { vi.clearAllMocks(); oddsIndex.mockResolvedValue({ current: { count: 1 }, history: [{ business_date: '2026-07-13', match_count: 1 }] }); oddsMovements.mockResolvedValue(oddsResponse()); });
  it('错历史日期拒绝展示', async () => {
    render(<OddsMovementPage />); await screen.findByRole('heading', { name: /测试304/ });
    oddsMovements.mockResolvedValue({ ...oddsResponse(), scope: 'history', business_date: '2026-07-12', resolution: 'hour' });
    fireEvent.change(screen.getByLabelText('赔率历史日期'), { target: { value: '2026-07-13' } });
    expect(await screen.findByText(/赔率响应与当前查询不一致/)).toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });
  it('数据缩减后页码收敛并更新空响应', async () => {
    oddsMovements.mockResolvedValue(oddsResponse(Array.from({ length: 11 }, (_, i) => oddsFixture(400 + i))));
    render(<OddsMovementPage />); await screen.findByRole('heading', { name: /测试400/ });
    fireEvent.click(screen.getByRole('button', { name: '下一页赔率' }));
    oddsMovements.mockResolvedValue(oddsResponse()); fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByRole('heading', { name: /测试304/ })).toBeInTheDocument();
    expect(screen.getByText(/第 1 \/ 1 页/)).toBeInTheDocument();
    oddsMovements.mockResolvedValue(oddsResponse([])); fireEvent.click(screen.getByRole('button', { name: '刷新赔率' }));
    expect(await screen.findByText('当前没有开盘比赛')).toBeInTheDocument(); expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });
});
