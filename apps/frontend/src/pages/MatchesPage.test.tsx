import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MatchesPage from './MatchesPage';

const { active } = vi.hoisted(() => ({ active: vi.fn() }));
vi.mock('../core/apiClient', () => ({ api: { matches: { active } } }));
vi.mock('../features/command-center/MatchEvidence', () => ({ default: ({ match }: { match: { match_id: number } }) => <aside aria-label="所选赛事分析">所选赛事 #{match.match_id}</aside> }));
vi.mock('../features/command-center/SceneViewport', () => ({ default: ({ children }: { children: (active: boolean, fail: () => void) => React.ReactNode }) => <div>{children(true, () => {})}</div> }));
vi.mock('../features/command-center/PitchScene', () => ({ default: () => <div>数字球场已加载</div> }));
const matches = [
  { match_id: 11, league_name: '中超', home_team_name: '上海海港', away_team_name: '北京国安', kickoff_time: '2026-11-13T19:35:00', match_status: 'scheduled', result_status: 'missing', status_note: '开球时间已过，实际状态待核实', match_num_str: '周五001' },
  { match_id: 12, league_name: '中超', home_team_name: '成都蓉城', away_team_name: '山东泰山', kickoff_time: '2026-11-13T20:00:00', match_status: 'Selling', match_num_str: '周五002' },
  { match_id: 13, league_name: '英超', home_team_name: '测试主队', away_team_name: '测试客队', kickoff_time: '2026-11-14T20:00:00', match_status: 'unknown_test_status', match_num_str: '周六001' },
];
const page = (overrides = {}) => ({ matches, total: 3, limit: 50, offset: 0, scope: 'current', leagues: ['中超', '英超'], statuses: ['scheduled', 'Selling', 'unknown_test_status'], selected_in_scope: false, selected_in_filter: false, started_total: 1, as_of: '2026-11-13T12:00:00', current_since: '2026-11-11T12:00:00', ...overrides });
async function loaded() { await screen.findByText('上海海港'); }

describe('server-paged match center', () => {
  beforeEach(() => { window.history.replaceState(null, '', '#/matches'); active.mockReset(); active.mockResolvedValue(page()); });
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

  it('shows recorded status and missing-result evidence without claiming a live match is awaiting results', async () => {
    render(<MatchesPage />); await loaded();
    expect(active).toHaveBeenCalledWith(expect.objectContaining({ limit: 50, offset: 0, scope: 'current' }));
    expect(screen.getByText('开球时间已过，实际状态待核实')).toBeInTheDocument();
    expect(screen.queryByText('等待赛果')).not.toBeInTheDocument();
    expect(screen.getByText(/近48小时/)).toBeInTheDocument();
  });
  it('respects server order instead of sorting the response a second time', async () => {
    active.mockResolvedValue(page({ matches: [matches[2], matches[0], matches[1]] }));
    render(<MatchesPage />); await loaded();
    expect(screen.getAllByRole('button', { name: /查看分析 / })[0]).toHaveAccessibleName(/周六001/);
    fireEvent.change(screen.getByLabelText('开球排序'), { target: { value: 'desc' } });
    await waitFor(() => expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'desc' })));
  });
  it('searches and filters the complete backend scope, including a result outside the old 500-row cap', async () => {
    render(<MatchesPage />); await loaded();
    active.mockResolvedValue(page({ total: 1, matches: [{ ...matches[2], match_id: 601, home_team_name: '范围外搜索结果' }] }));
    fireEvent.change(screen.getByLabelText('搜索赛事'), { target: { value: '范围外' } });
    await screen.findByText('范围外搜索结果');
    expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ q: '范围外', offset: 0 }));
    fireEvent.change(screen.getByLabelText('联赛'), { target: { value: '英超' } });
    await waitFor(() => expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ league: '英超', q: '范围外' })));
    fireEvent.change(screen.getByLabelText('赛事状态'), { target: { value: 'scheduled' } });
    await waitFor(() => expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'scheduled' })));
  });
  it('requests the next page and displays the true total', async () => {
    active.mockResolvedValueOnce(page({ total: 601 }));
    render(<MatchesPage />); await loaded();
    expect(screen.getByText('第 1 / 13 页')).toBeInTheDocument();
    expect(screen.getByText(/本页 3 场 · 筛选总数 601 场/)).toBeInTheDocument();
    active.mockResolvedValue(page({ offset: 50, total: 601, matches: [matches[2]] }));
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await screen.findByText('第 2 / 13 页');
    expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 }));
    expect(screen.queryByText('上海海港')).not.toBeInTheDocument();
  });
  it('queries historical archives by Sporttery business day and persists it in the link', async () => {
    render(<MatchesPage />); await loaded();
    active.mockResolvedValue(page({ scope: 'history' }));
    fireEvent.change(screen.getByLabelText('赛事范围'), { target: { value: 'history' } });
    fireEvent.change(screen.getByLabelText('体彩业务日'), { target: { value: '2026-10-31' } });
    await waitFor(() => expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ scope: 'history', date_from: '2026-10-31', date_to: '2026-10-31', offset: 0 })));
    expect(window.location.hash).toContain('date=2026-10-31');
    expect(await screen.findByText('赛果待补')).toBeInTheDocument();
  });
  it('locates a linked ID on a server-selected page', async () => {
    window.history.replaceState(null, '', '#/matches?match_id=601');
    active.mockResolvedValue(page({ total: 601, offset: 600, matches: [{ ...matches[2], match_id: 601 }], selected_in_scope: true, selected_in_filter: true }));
    render(<MatchesPage />);
    await screen.findByText('第 13 / 13 页');
    expect(await screen.findByLabelText('所选赛事分析')).toHaveTextContent('#601');
    expect(active).toHaveBeenCalledWith(expect.objectContaining({ selected_id: 601 }));
  });
  it('does not substitute a different match for an unavailable linked ID', async () => {
    window.history.replaceState(null, '', '#/matches?match_id=999'); render(<MatchesPage />); await loaded();
    expect(screen.getByText(/当前查询范围内未找到比赛 #999/)).toBeInTheDocument();
    expect(screen.queryByLabelText('所选赛事分析')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看指定比赛详情' })).toHaveAttribute('href', '#/matches/999');
  });
  it('distinguishes a linked ID hidden by filters from one outside the scope', async () => {
    window.history.replaceState(null, '', '#/matches?match_id=12&league=英超');
    active.mockResolvedValue(page({ matches: [matches[2]], total: 1, selected_in_scope: true }));
    render(<MatchesPage />); await screen.findByText(/指定比赛被当前筛选隐藏/);
    active.mockResolvedValue(page({ selected_in_scope: true, selected_in_filter: true }));
    fireEvent.click(screen.getByRole('button', { name: '清除筛选查看该比赛' }));
    await waitFor(() => expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12'));
  });
  it('retains the same-query evidence after a failed refresh', async () => {
    render(<MatchesPage />); await loaded(); active.mockRejectedValueOnce(new Error('网络不可用'));
    fireEvent.click(screen.getByRole('button', { name: '刷新赛事' }));
    expect(await screen.findByText(/网络不可用.*保留上次成功数据/)).toBeInTheDocument();
    expect(screen.getByText('上海海港')).toBeInTheDocument();
  });
  it('clears old-scope rows if a new scope cannot load', async () => {
    render(<MatchesPage />); await loaded(); active.mockRejectedValue(new Error('历史加载失败'));
    fireEvent.change(screen.getByLabelText('赛事范围'), { target: { value: 'history' } });
    await screen.findByText(/历史加载失败/);
    expect(screen.queryByText('上海海港')).not.toBeInTheDocument();
  });
  it('reports empty and failed reads separately and supports retry', async () => {
    active.mockRejectedValueOnce(new Error('首次失败')); render(<MatchesPage />);
    await screen.findByText(/首次失败/); expect(screen.queryByText('暂无当前比赛')).not.toBeInTheDocument();
    active.mockResolvedValue(page({ matches: [], total: 0 }));
    fireEvent.click(screen.getByRole('button', { name: '刷新赛事' })); await screen.findByText('暂无当前比赛');
  });
  it('polls only one list and opens 3D without an extra read', async () => {
    render(<MatchesPage />); await loaded();
    fireEvent.click(screen.getByRole('button', { name: '打开 3D 选赛' })); await screen.findByText('数字球场已加载');
    expect(active).toHaveBeenCalledTimes(1);
  });
  it('preserves a warning while clamping a page using the server response', async () => {
    window.history.replaceState(null, '', '#/matches?page=999&sort=unsafe'); render(<MatchesPage />); await loaded();
    // The server normalizes offset; wait for the normalized URL's read rather
    // than holding an element from the preceding response during its reload.
    await waitFor(() => expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 })));
    await waitFor(() => {
      expect(screen.getByText('第 1 / 1 页')).toBeInTheDocument();
      expect(screen.getByText(/链接参数无效/)).toBeInTheDocument();
    });
  });
  it('restores scope and selected ID from a same-route history change', async () => {
    render(<MatchesPage />); await loaded();
    act(() => { window.history.replaceState(null, '', '#/matches?scope=history&date=2026-10-31&match_id=13'); window.dispatchEvent(new HashChangeEvent('hashchange')); });
    await waitFor(() => expect(active).toHaveBeenLastCalledWith(expect.objectContaining({ scope: 'history', selected_id: 13, date_from: '2026-10-31' })));
  });
});
