import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LeagueCenter from './LeagueCenter';
import { readEventCenterState, useEventCenterState } from './state';
import { disconnectedLeagueSource } from './dataSource';
import type { LeagueDataSource, LeagueSeasonData, LeagueFixturePage } from './types';

const evidence = { sourceName: '固定测试样本', asOf: '2026-10-27T00:00:00Z', batchId: 'test-batch-1', completeness: 'complete' as const, stale: false };
const home = { id: 1, name: '测试主队', manager: null, stadium: null };
const away = { id: 2, name: '测试客队', manager: '样本教练', stadium: null };
const season: LeagueSeasonData = {
  competitionSeasonId: 42, evidence,
  coverage: { teams: 2, expectedTeams: 2, fixtures: 1, expectedFixtures: null },
  overview: { played: 1, goals: 0, goalsPerMatch: 0, homeWins: 0, draws: 1, awayWins: 0 },
  standings: { all: { evidence, rows: [
    { team: home, rank: 1, played: 1, won: 0, drawn: 1, lost: 0, goalsFor: 0, goalsAgainst: 0, goalDifference: 0, points: -2, form: ['D'], note: '扣3分（样本）' },
    { team: away, rank: 2, played: 1, won: 0, drawn: 1, lost: 0, goalsFor: 0, goalsAgainst: 0, goalDifference: 0, points: 1, form: null, note: null },
  ] } },
  teams: [home, away], rounds: [{ id: 'r1', label: '第1轮' }],
};
const fixtures: LeagueFixturePage = {
  competitionSeasonId: 42, evidence, total: 2,
  rows: [
    { id: 'ref:11', home, away, kickoff: null, roundId: 'r1', status: 'postponed', homeGoals: null, awayGoals: null, officialMatch: null },
    { id: 'ref:12', home, away, kickoff: '2026-10-25T12:00:00Z', roundId: 'r1', status: 'finished', homeGoals: 0, awayGoals: 0, officialMatch: { id: 811, verification: 'verified' } },
  ],
};
function source(): LeagueDataSource {
  return {
    catalog: vi.fn().mockResolvedValue({ status: 'connected', competitions: [{ code: 'premier-league', name: '英超', country: '英格兰', seasons: [{ id: 42, label: '测试2026/27', isCurrent: true }, { id: 41, label: '测试2025/26', isCurrent: false }] }] }),
    season: vi.fn().mockResolvedValue(structuredClone(season)),
    fixtures: vi.fn().mockResolvedValue(structuredClone(fixtures)),
  };
}
function Harness({ dataSource }: { dataSource: LeagueDataSource }) {
  const [state, update] = useEventCenterState();
  return <LeagueCenter source={dataSource} state={state} onChange={update} />;
}
function SharedHarness() {
  const [state, update] = useEventCenterState();
  return <LeagueCenter state={state} onChange={update} />;
}
describe('LeagueCenter integration (isolated fixed samples only)', () => {
  beforeEach(() => window.history.replaceState(null, '', '#/events?view=league'));

  it('uses the shared backend by default and pins fixture reads to the season revision', async () => {
    const directory = await source().catalog();
    const actualSeason = { ...structuredClone(season), evidence: { ...evidence, batchId: '17' } };
    const actualPage = { ...structuredClone(fixtures), evidence: { ...evidence, batchId: '17' } };
    const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const path = String(input);
      const body = path.endsWith('/catalog') ? directory : path.includes('/fixtures?') ? actualPage : actualSeason;
      return new Response(JSON.stringify(body), { status: 200 });
    });
    const mounted = render(<SharedHarness />);
    try {
      await screen.findByRole('button', { name: '查看球队 测试主队' });
      fireEvent.click(screen.getByRole('button', { name: '赛程赛果' }));
      await screen.findByText('0 : 0');
      const urls = fetch.mock.calls.map(call => String(call[0]));
      expect(urls.every(url => url.startsWith('/api/league-data/'))).toBe(true);
      expect(urls.some(url => url.includes('/fixtures?') && new URL(url, 'http://localhost').searchParams.get('batch_id') === '17')).toBe(true);
    } finally {
      mounted.unmount();
      fetch.mockRestore();
    }
  });

  it('rejects fixture responses from a different published batch', async () => {
    const s = source();
    s.fixtures = vi.fn().mockResolvedValue({ ...structuredClone(fixtures), evidence: { ...evidence, batchId: 'another-batch' } });
    render(<Harness dataSource={s} />);
    await screen.findByRole('button', { name: '查看球队 测试主队' });
    fireEvent.click(screen.getByRole('button', { name: '赛程赛果' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('返回赛程与所选资料批次不一致');
    expect(screen.queryByText('0 : 0')).not.toBeInTheDocument();
  });

  it('has no network or business writes when real data is deferred', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    render(<Harness dataSource={disconnectedLeagueSource} />);
    expect(await screen.findByText('联赛数据待接入')).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByText('测试主队')).not.toBeInTheDocument();
    fetch.mockRestore();
  });
  it('shows real zeroes, negative penalty points, batch and coverage without deriving missing stats', async () => {
    const s = source(); render(<Harness dataSource={s} />);
    await screen.findByRole('button', { name: '查看球队 测试主队' });
    expect(screen.getByLabelText('总进球')).toHaveTextContent('0');
    expect(screen.getByLabelText('场均进球')).toHaveTextContent('0.00');
    expect(screen.getByText('-2')).toBeInTheDocument();
    expect(screen.getByText('扣3分（样本）')).toBeInTheDocument();
    expect(screen.getAllByText(/固定测试样本/).length).toBeGreaterThan(0);
    expect(screen.getByText(/赛程覆盖：1 \/ 未知/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '主场' }));
    expect(screen.getByText('主场榜暂无覆盖')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查看球队 测试主队' })).not.toBeInTheDocument();
  });
  it('uses paginated fixture reads and only links verified official IDs', async () => {
    const s = source(); render(<Harness dataSource={s} />);
    await screen.findByRole('button', { name: '查看球队 测试主队' });
    fireEvent.click(screen.getByRole('button', { name: '赛程赛果' }));
    expect(await screen.findByText('开球时间待定')).toBeInTheDocument();
    expect(screen.getByText('0 : 0')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看分析 ref:12' })).toHaveAttribute('href', '#/matches/811');
    expect(screen.queryByRole('link', { name: '查看分析 ref:11' })).not.toBeInTheDocument();
    expect(screen.getByText('未关联竞彩比赛')).toBeInTheDocument();
    expect(s.fixtures).toHaveBeenCalledWith({ competitionSeasonId: 42, batchId: 'test-batch-1', roundId: null, status: 'all', teamId: null, limit: 20, offset: 0 });
    fireEvent.change(screen.getByLabelText('赛程状态'), { target: { value: 'postponed' } });
    await waitFor(() => expect(s.fixtures).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'postponed', offset: 0 })));
    expect(window.location.hash).toContain('status=postponed');
  });
  it('opens the same-season team subview and scopes the fixture request', async () => {
    const s = source(); render(<Harness dataSource={s} />);
    await screen.findByRole('button', { name: '查看球队 测试主队' });
    fireEvent.click(screen.getByRole('button', { name: '查看球队 测试主队' }));
    expect(await screen.findByText('教练待接入')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '测试主队' })).toBeInTheDocument();
    await waitFor(() => expect(s.fixtures).toHaveBeenLastCalledWith(expect.objectContaining({ teamId: 1 })));
    expect(window.location.hash).toContain('team_id=1');
    fireEvent.click(screen.getByRole('button', { name: '返回球队列表' }));
    expect(screen.getByRole('button', { name: '查看球队 测试客队' })).toBeInTheDocument();
    expect(window.location.hash).not.toContain('team_id');
  });
  it('does not replace an unknown explicit season or team with a default', async () => {
    window.history.replaceState(null, '', '#/events?view=league&competition_season_id=999');
    const s = source(); render(<Harness dataSource={s} />);
    expect(await screen.findByText('链接中的赛季暂无覆盖')).toBeInTheDocument();
    expect(s.season).not.toHaveBeenCalled();
  });
  it('rejects an unknown team and does not fetch a different team schedule', async () => {
    window.history.replaceState(null, '', '#/events?view=league&tab=teams&team_id=999');
    const s = source(); render(<Harness dataSource={s} />);
    expect(await screen.findByText('该赛季未找到此球队')).toBeInTheDocument();
    expect(s.fixtures).not.toHaveBeenCalled();
  });
  it('shows directory failure as an error rather than claiming data is empty', async () => {
    const s = source(); vi.mocked(s.catalog).mockRejectedValueOnce(new Error('目录暂时不可用'));
    render(<Harness dataSource={s} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('目录暂时不可用');
    expect(screen.queryByText('联赛数据待接入')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新联赛目录' }));
    await screen.findByRole('button', { name: '查看球队 测试主队' });
  });
  it('isolates fixture failures from the standings and overview', async () => {
    window.history.replaceState(null, '', '#/events?view=league&tab=fixtures');
    const s = source(); vi.mocked(s.fixtures).mockRejectedValueOnce(new Error('赛程暂时不可用'));
    render(<Harness dataSource={s} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('赛程暂时不可用');
    expect(screen.getByLabelText('总进球')).toHaveTextContent('0');
    fireEvent.click(screen.getByRole('button', { name: '积分榜' }));
    expect(screen.getByRole('button', { name: '查看球队 测试主队' })).toBeInTheDocument();
  });
  it('requests a bounded next page and resets its offset on round filtering', async () => {
    window.history.replaceState(null, '', '#/events?view=league&tab=fixtures');
    const s = source(); vi.mocked(s.fixtures).mockResolvedValue({ ...fixtures, total: 21 });
    render(<Harness dataSource={s} />);
    await screen.findByText('开球时间待定');
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => expect(s.fixtures).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 20, offset: 20 })));
    fireEvent.change(screen.getByLabelText('轮次'), { target: { value: 'r1' } });
    await waitFor(() => expect(s.fixtures).toHaveBeenLastCalledWith(expect.objectContaining({ roundId: 'r1', offset: 0 })));
  });
  it('rejects a mismatched season response instead of displaying its facts', async () => {
    const s = source(); vi.mocked(s.season).mockResolvedValue({ ...season, competitionSeasonId: 99 });
    render(<Harness dataSource={s} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('返回资料与所选赛季不一致');
    expect(screen.queryByRole('button', { name: '查看球队 测试主队' })).not.toBeInTheDocument();
  });
  it('retains invalid-link warnings when the configured current season is resolved', async () => {
    window.history.replaceState(null, '', '#/events?view=league&page=bad');
    render(<Harness dataSource={source()} />);
    await screen.findByRole('button', { name: '查看球队 测试主队' });
    expect(screen.getByRole('alert')).toHaveTextContent('链接参数无效');
  });
  it('keeps same-season successful data on refresh failure and allows retry', async () => {
    const s = source(); render(<Harness dataSource={s} />);
    await screen.findByRole('button', { name: '查看球队 测试主队' });
    vi.mocked(s.season).mockRejectedValueOnce(new Error('隔离读取失败'));
    fireEvent.click(screen.getByRole('button', { name: '刷新联赛资料' }));
    expect(await screen.findByText(/隔离读取失败.*保留上次成功数据/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看球队 测试主队' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新联赛资料' }));
    await waitFor(() => expect(screen.queryByText(/隔离读取失败/)).not.toBeInTheDocument());
  });
  it('ignores a slow previous season and never mixes its standings into the new season', async () => {
    const s = source(); let resolveOld!: (data: LeagueSeasonData) => void;
    vi.mocked(s.season).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    render(<Harness dataSource={s} />);
    await waitFor(() => expect(s.season).toHaveBeenCalledWith(42));
    vi.mocked(s.season).mockResolvedValue({ ...structuredClone(season), competitionSeasonId: 41, standings: {}, teams: [], overview: null });
    fireEvent.change(screen.getByLabelText('赛季'), { target: { value: '41' } });
    expect(await screen.findByText('总榜暂无覆盖')).toBeInTheDocument();
    await act(async () => resolveOld(structuredClone(season)));
    expect(screen.queryByRole('button', { name: '查看球队 测试主队' })).not.toBeInTheDocument();
  });
  it('shows partial/stale evidence and refuses an incomplete standings batch', async () => {
    const s = source(); const partial = structuredClone(season);
    partial.evidence = { ...evidence, completeness: 'partial', stale: true };
    partial.standings.all!.evidence = partial.evidence;
    vi.mocked(s.season).mockResolvedValue(partial);
    render(<Harness dataSource={s} />);
    expect((await screen.findAllByText(/样本统计/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/已过期/).length).toBeGreaterThan(0);
    expect(screen.getByText('积分榜批次不完整')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查看球队 测试主队' })).not.toBeInTheDocument();
  });
  it('keeps fixture errors local and handles an out-of-range page without looping', async () => {
    const s = source(); window.history.replaceState(null, '', '#/events?view=league&tab=fixtures&page=99');
    vi.mocked(s.fixtures).mockResolvedValue({ ...fixtures, rows: [], total: 2 });
    render(<Harness dataSource={s} />);
    expect(await screen.findByText('该页超出当前赛程范围')).toBeInTheDocument();
    expect(s.fixtures).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '返回第一页' }));
    await waitFor(() => expect(s.fixtures).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText('总进球')).toHaveTextContent('0');
  });
  it('does not turn an unverified same-number reference into a single-match link', async () => {
    const s = source(); const pending = structuredClone(fixtures);
    pending.rows[0].officialMatch = { id: 11, verification: 'pending' };
    vi.mocked(s.fixtures).mockResolvedValue(pending);
    render(<LeagueCenter source={s} state={readEventCenterState('#/events?view=league&tab=fixtures')} onChange={vi.fn()} />);
    await screen.findByText('开球时间待定');
    const row = screen.getByText('开球时间待定').closest('li')!;
    expect(within(row).queryByRole('link')).not.toBeInTheDocument();
    expect(within(row).getByText('竞彩映射待核实')).toBeInTheDocument();
  });
  it('offers a distinct verified subset, clears old filters and exposes its planned dates', async () => {
    const s = source();
    const verifiedSeason = { ...structuredClone(season), dataset: 'verified' as const,
      evidence: { ...evidence, sourceName: '中国体育彩票', completeness: 'partial' as const, asOf: null, batchId: null },
      coverage: { teams: null, expectedTeams: null, fixtures: 1, expectedFixtures: null }, overview: null, standings: {}, teams: [], rounds: [],
      seasonIdentity: { label: '2024-2025', sourceSeasonId: '11817', plannedStartDate: '2024-08-16', plannedEndDate: '2025-05-26', timeZone: 'Asia/Shanghai' } };
    vi.mocked(s.catalog).mockImplementation(async dataset => dataset === 'verified' ? { dataset, status: 'connected', competitions: [{ code: 'sporttery:c4169e38cdfd', name: '英超', country: '英格兰', seasons: [{ id: 80, label: '2024-2025', isCurrent: false }] }] } : source().catalog());
    vi.mocked(s.season).mockImplementation(async (id, dataset) => dataset === 'verified' ? { ...verifiedSeason, competitionSeasonId: id } : structuredClone(season));
    vi.mocked(s.fixtures).mockImplementation(async query => ({ ...structuredClone(fixtures), competitionSeasonId: query.competitionSeasonId, dataset: query.dataset, evidence: query.dataset === 'verified' ? verifiedSeason.evidence : evidence }));
    render(<Harness dataSource={s} />);
    await screen.findByRole('button', { name: '查看球队 测试主队' });
    fireEvent.change(screen.getByLabelText('数据范围'), { target: { value: 'verified' } });
    expect(await screen.findByText(/计划赛季：2024-08-16 至 2025-05-26/)).toBeInTheDocument();
    await screen.findByText('0 : 0');
    expect(window.location.hash).toContain('dataset=verified');
    expect(window.location.hash).toContain('competition=sporttery%3Ac4169e38cdfd');
    expect(s.season).toHaveBeenLastCalledWith(80, 'verified');
    expect(s.fixtures).toHaveBeenLastCalledWith(expect.objectContaining({ dataset: 'verified', batchId: undefined, offset: 0, teamId: null, roundId: null }));
    expect(screen.getAllByText(/仅含已核实逐场赛季归属的竞彩比赛/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: '查看球队 测试主队' })).not.toBeInTheDocument();
  });
  it('rejects a reference-only season response in the verified dataset', async () => {
    window.history.replaceState(null, '', '#/events?view=league&dataset=verified&competition=premier-league&competition_season_id=42');
    const s = source();
    vi.mocked(s.catalog).mockResolvedValue({ ...await s.catalog(), dataset: 'verified' });
    render(<Harness dataSource={s} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('返回资料与所选数据范围不一致');
    expect(screen.queryByText('0 : 0')).not.toBeInTheDocument();
  });

  it('ignores a late reference season after switching to an empty verified catalog', async () => {
    const s = source(); let resolveOld!: (data: LeagueSeasonData) => void;
    vi.mocked(s.season).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    vi.mocked(s.catalog).mockImplementation(async dataset => dataset === 'verified' ? { dataset, status: 'not_connected', competitions: [] } : source().catalog());
    render(<Harness dataSource={s} />);
    await waitFor(() => expect(s.season).toHaveBeenCalledWith(42));
    fireEvent.change(screen.getByLabelText('数据范围'), { target: { value: 'verified' } });
    await waitFor(() => expect(screen.getByText('数据未接入')).toBeInTheDocument());
    await act(async () => resolveOld(structuredClone(season)));
    expect(screen.queryByRole('button', { name: '查看球队 测试主队' })).not.toBeInTheDocument();
    expect(s.fixtures).not.toHaveBeenCalled();
    expect(window.location.hash).not.toContain('competition_season_id');
  });
  it('rejects reference fixtures returned to a verified season', async () => {
    const s = source();
    window.history.replaceState(null, '', '#/events?view=league&dataset=verified&competition=premier-league&competition_season_id=42');
    vi.mocked(s.catalog).mockResolvedValue({ ...await s.catalog(), dataset: 'verified' });
    vi.mocked(s.season).mockResolvedValue({ ...structuredClone(season), dataset: 'verified', evidence: { ...evidence, batchId: null } });
    render(<Harness dataSource={s} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('返回赛程与所选数据范围不一致');
    expect(screen.queryByText('0 : 0')).not.toBeInTheDocument();
  });
  it('keeps an explicit unknown verified season without substituting another year', async () => {
    const s = source();
    window.history.replaceState(null, '', '#/events?view=league&dataset=verified&competition=premier-league&competition_season_id=999');
    vi.mocked(s.catalog).mockResolvedValue({ ...await s.catalog(), dataset: 'verified' });
    render(<Harness dataSource={s} />);
    expect(await screen.findByText('链接中的赛季暂无覆盖')).toBeInTheDocument();
    expect(s.season).not.toHaveBeenCalled();
    expect(window.location.hash).toContain('competition_season_id=999');
  });

});
