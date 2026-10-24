import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MatchesPage from './MatchesPage';

const { active } = vi.hoisted(() => ({ active: vi.fn() }));
vi.mock('../core/apiClient', () => ({ api: { matches: { active } } }));
vi.mock('../features/command-center/MatchEvidence', () => ({
  default: ({ match }: { match: { match_id: number } }) => <aside aria-label="所选赛事分析">所选赛事 #{match.match_id}</aside>,
}));
vi.mock('../features/command-center/SceneViewport', () => ({ default: ({ children }: { children: (active: boolean, fail: () => void) => React.ReactNode }) => <div>{children(true, () => {})}</div> }));
vi.mock('../features/command-center/PitchScene', () => ({ default: ({ onSelect }: { onSelect: (id: number) => void }) => <button onClick={() => onSelect(12)}>场景选择比赛12</button> }));
const matches = [
  { match_id: 11, league_name: '中超', home_team_name: '上海海港', away_team_name: '北京国安', kickoff_time: '2026-07-12T19:35:00', match_status: 'awaiting_result', match_num_str: '周日001' },
  { match_id: 12, league_name: '中超', home_team_name: '成都蓉城', away_team_name: '山东泰山', kickoff_time: '2026-07-12T20:00:00', match_status: 'Selling', match_num_str: '周日002' },
  { match_id: 13, league_name: '英超', home_team_name: '测试主队', away_team_name: '测试客队', kickoff_time: '2026-07-13T20:00:00', match_status: 'unknown_test_status', match_num_str: '周一001' },
];
async function loaded() { await screen.findByText('上海海港'); }

describe('MatchesPage', () => {
  beforeEach(() => { window.history.replaceState(null, '', '#/matches'); active.mockReset(); active.mockResolvedValue({ total: 3, matches }); });
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

  it('lists every unfinished official match including awaiting results', async () => {
    render(<MatchesPage />); await loaded();
    expect(active).toHaveBeenCalledWith({ limit: 500 });
    expect(screen.getByText(/体彩官方未结束比赛/)).toBeInTheDocument();
    expect(screen.getAllByText('等待赛果').length).toBeGreaterThan(0);
    expect(screen.getAllByText('VS')).toHaveLength(3);
    expect(screen.getAllByText('unknown_test_status').length).toBeGreaterThan(0);
  });
  it('定时同步未结束比赛的状态', async () => {
    vi.useFakeTimers(); render(<MatchesPage />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(active).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(30_000); await Promise.resolve(); });
    expect(active).toHaveBeenCalledTimes(2);
  });
  it('combines labelled search, league and status filters', async () => {
    render(<MatchesPage />); await loaded();
    fireEvent.change(screen.getByLabelText('搜索赛事'), { target: { value: '002' } });
    fireEvent.change(screen.getByLabelText('联赛'), { target: { value: '中超' } });
    fireEvent.change(screen.getByLabelText('赛事状态'), { target: { value: 'Selling' } });
    expect(screen.getByText('成都蓉城')).toBeInTheDocument();
    expect(screen.queryByText('上海海港')).not.toBeInTheDocument();
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12');
  });
  it('distinguishes no filter results and resets filters', async () => {
    render(<MatchesPage />); await loaded();
    fireEvent.change(screen.getByLabelText('搜索赛事'), { target: { value: '无此队' } });
    expect(screen.getByText('没有匹配的赛事')).toBeInTheDocument();
    expect(screen.queryByLabelText('所选赛事分析')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重置筛选' }));
    expect(screen.getByText('上海海港')).toBeInTheDocument();
  });
  it('keeps explicit selection and full detail link on the same ID', async () => {
    render(<MatchesPage />); await loaded();
    const button = screen.getByRole('button', { name: '查看分析 周日002 成都蓉城 VS 山东泰山' });
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12');
    expect(screen.getByRole('link', { name: '完整详情 周日002' })).toHaveAttribute('href', '#/matches/12');
  });
  it('paginates 50 records, selects on the current page, and resets page on filtering', async () => {
    active.mockResolvedValue({ total: 51, matches: Array.from({ length: 51 }, (_, index) => ({ ...matches[0], match_id: index + 1, match_num_str: `测试${index + 1}` })) });
    render(<MatchesPage />); await screen.findByRole('button', { name: /查看分析 测试1 / });
    expect(screen.getAllByRole('button', { name: /查看分析 / })).toHaveLength(50);
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    expect(screen.getAllByRole('button', { name: /查看分析 / })).toHaveLength(1);
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#51');
    fireEvent.change(screen.getByLabelText('搜索赛事'), { target: { value: '测试1' } });
    expect(screen.getByText('第 1 / 1 页')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled();
  });
  it('sorts by kickoff and changes current page selection accordingly', async () => {
    render(<MatchesPage />); await loaded();
    fireEvent.change(screen.getByLabelText('开球排序'), { target: { value: 'desc' } });
    expect(screen.getAllByRole('button', { name: /查看分析 / })[0]).toHaveAccessibleName(/周一001/);
  });
  it('preserves successful data and reports a failed refresh', async () => {
    render(<MatchesPage />); await loaded();
    active.mockRejectedValueOnce(new Error('网络不可用'));
    fireEvent.click(screen.getByRole('button', { name: '刷新赛事' }));
    expect(await screen.findByText(/网络不可用.*保留上次成功数据/)).toBeInTheDocument();
    expect(screen.getByText('上海海港')).toBeInTheDocument();
  });
  it('offers retry for initial error without pretending empty business data', async () => {
    active.mockRejectedValueOnce(new Error('首次失败'));
    render(<MatchesPage />);
    expect(await screen.findByText(/首次失败/)).toBeInTheDocument();
    expect(screen.queryByText('暂无未结束比赛')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新赛事' })); await loaded();
  });
  it('shows a genuine empty list with zero counts', async () => {
    active.mockResolvedValue({ total: 0, matches: [] }); render(<MatchesPage />);
    expect(await screen.findByText('暂无未结束比赛')).toBeInTheDocument();
    expect(screen.getByText(/已获取 0 场 · 接口总数 0 场/)).toBeInTheDocument();
  });
  it('states the 500-record fetch boundary separately from API total', async () => {
    active.mockResolvedValue({ total: 620, matches }); render(<MatchesPage />); await loaded();
    expect(screen.getByText(/已获取 3 场 · 接口总数 620 场/)).toBeInTheDocument();
    expect(screen.getByText(/每次最多获取 500 场/)).toBeInTheDocument();
  });
  it('rejects duplicate IDs without replacing the last good list', async () => {
    render(<MatchesPage />); await loaded();
    active.mockResolvedValueOnce({ total: 2, matches: [matches[0], matches[0]] });
    fireEvent.click(screen.getByRole('button', { name: '刷新赛事' }));
    expect(await screen.findByText(/赛事数据验证失败/)).toBeInTheDocument();
    expect(screen.getByText('成都蓉城')).toBeInTheDocument();
  });
  it('clamps pagination when refreshed data shrinks', async () => {
    active.mockResolvedValueOnce({ total: 51, matches: Array.from({ length: 51 }, (_, index) => ({ ...matches[0], match_id: index + 1, match_num_str: `测试${index + 1}` })) });
    render(<MatchesPage />); await screen.findByRole('button', { name: /查看分析 测试1 / });
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    fireEvent.click(screen.getByRole('button', { name: '刷新赛事' }));
    await waitFor(() => expect(screen.getByText('第 1 / 1 页')).toBeInTheDocument());
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#11');
  });
  it('rejects an invalid response count rather than claiming zero', async () => {
    active.mockResolvedValueOnce({ total: -1, matches }); render(<MatchesPage />);
    expect(await screen.findByText(/赛事数量格式异常/)).toBeInTheDocument();
    expect(screen.getByText(/赛事数量 —/)).toBeInTheDocument();
    expect(screen.queryByText('上海海港')).not.toBeInTheDocument();
  });
  it('places missing kickoff times last and displays an unknown date', async () => {
    active.mockResolvedValueOnce({ total: 2, matches: [{ ...matches[0], kickoff_time: 'invalid' }, matches[1]] });
    render(<MatchesPage />); await loaded();
    expect(screen.getAllByRole('button', { name: /查看分析 / })[0]).toHaveAccessibleName(/周日002/);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('locates a linked match beyond the first page', async () => {
    window.history.replaceState(null, '', '#/matches?match_id=51');
    active.mockResolvedValue({ total: 51, matches: Array.from({ length: 51 }, (_, index) => ({ ...matches[0], match_id: index + 1, match_num_str: `测试${index + 1}` })) });
    render(<MatchesPage />);
    expect(await screen.findByText('第 2 / 2 页')).toBeInTheDocument();
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#51');
  });

  it('does not substitute the first match when a linked ID is unavailable', async () => {
    window.history.replaceState(null, '', '#/matches?match_id=999'); render(<MatchesPage />); await loaded();
    expect(screen.getByText(/当前未结束列表中未找到比赛 #999/)).toBeInTheDocument();
    expect(screen.queryByLabelText('所选赛事分析')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看指定比赛详情' })).toHaveAttribute('href', '#/matches/999');
  });

  it('reveals a linked match hidden by filters only after the user clears them', async () => {
    window.history.replaceState(null, '', '#/matches?match_id=12&league=英超'); render(<MatchesPage />);
    expect(await screen.findByText(/指定比赛被当前筛选隐藏/)).toBeInTheDocument();
    expect(screen.queryByLabelText('所选赛事分析')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '清除筛选查看该比赛' }));
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12');
  });

  it('serializes filters and selection and restores them after remounting', async () => {
    const view = render(<MatchesPage />); await loaded();
    fireEvent.change(screen.getByLabelText('联赛'), { target: { value: '中超' } });
    fireEvent.change(screen.getByLabelText('开球排序'), { target: { value: 'desc' } });
    fireEvent.click(screen.getByRole('button', { name: /查看分析 周日002/ }));
    const params = new URLSearchParams(window.location.hash.split('?')[1]);
    expect(params.get('league')).toBe('中超'); expect(params.get('sort')).toBe('desc'); expect(params.get('match_id')).toBe('12');
    view.unmount(); render(<MatchesPage />); await screen.findByLabelText('所选赛事分析');
    expect(screen.getByLabelText('联赛')).toHaveValue('中超');
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12');
  });

  it('handles a same-route hash change and browser history restoration', async () => {
    render(<MatchesPage />); await loaded();
    act(() => { window.history.replaceState(null, '', '#/matches?match_id=13&sort=desc'); window.dispatchEvent(new HashChangeEvent('hashchange')); });
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#13');
    act(() => { window.history.replaceState(null, '', '#/matches?match_id=12'); window.dispatchEvent(new HashChangeEvent('hashchange')); });
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12');
  });

  it('reports invalid link parameters and uses safe defaults', async () => {
    window.history.replaceState(null, '', '#/matches?match_id=1e3&page=-2&sort=unsafe'); render(<MatchesPage />); await loaded();
    expect(screen.getByText(/链接参数无效/)).toBeInTheDocument();
    expect(screen.getByText('第 1 / 1 页')).toBeInTheDocument();
    expect(screen.getByLabelText('开球排序')).toHaveValue('asc');
  });

  it('retains an invalid-parameter warning while correcting an out-of-range page', async () => {
    window.history.replaceState(null, '', '#/matches?page=999&sort=unsafe'); render(<MatchesPage />); await loaded();
    expect(screen.getByText(/链接参数无效/)).toBeInTheDocument();
    expect(screen.getByText('第 1 / 1 页')).toBeInTheDocument();
  });

  it('opens 3D explicitly, shares selection and does not refetch the active list', async () => {
    render(<MatchesPage />); await loaded();
    expect(screen.queryByRole('button', { name: '场景选择比赛12' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开 3D 选赛' }));
    fireEvent.click(await screen.findByRole('button', { name: '场景选择比赛12' }));
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12');
    expect(active).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '关闭 3D 选赛' }));
    expect(screen.queryByRole('button', { name: '场景选择比赛12' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('所选赛事分析')).toHaveTextContent('#12');
  });

});
