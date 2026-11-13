import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MatchOverview from './MatchOverview';

const api = vi.hoisted(() => ({ matches: { active: vi.fn(), detail: vi.fn() }, official: { oddsSnapshots: vi.fn() } }));
vi.mock('../../core/apiClient', () => ({ api }));
const metadata = { offset: 0, limit: 5, scope: 'current', leagues: [], statuses: [], selected_in_scope: false, selected_in_filter: false, started_total: 0, as_of: '', current_since: '' };
const match = (id: number, time = '2026-10-25T19:00:00+08:00') => ({ match_id: id, match_num_str: `周日${String(id).padStart(3, '0')}`, league_name: '界面测试联赛', home_team_name: `主队${id}`, away_team_name: `客队${id}`, kickoff_time: time, match_status: 'scheduled' });

describe('MatchOverview', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-25T12:00:00+08:00')); api.matches.active.mockResolvedValue({ ...metadata, matches: [match(1)], total: 1 }); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it('shows at most five upcoming matches ordered by kickoff with analysis links', async () => {
    api.matches.active.mockResolvedValue({ ...metadata, matches: Array.from({ length: 5 }, (_, i) => match(7 - i, `2026-10-25T${17 + i}:00:00+08:00`)), total: 7 });
    render(<MatchOverview />); await screen.findByText('主队7');
    expect(screen.getAllByRole('link', { name: /查看分析 / })).toHaveLength(5);
    expect(screen.getAllByRole('link', { name: /查看分析 / })[0]).toHaveAttribute('href', '#/matches?match_id=7');
    expect(screen.queryByText('主队1')).not.toBeInTheDocument();
    expect(api.matches.detail).not.toHaveBeenCalled(); expect(api.official.oddsSnapshots).not.toHaveBeenCalled();
    expect(document.querySelector('canvas')).toBeNull(); expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });

  it('separates awaiting results and unknown kickoff times from upcoming matches', async () => {
    api.matches.active.mockResolvedValue({ ...metadata, matches: [{ ...match(1, '2026-10-24T19:00:00+08:00'), match_status: 'awaiting_result' }, match(2, 'invalid'), match(3)], total: 3, started_total: 1 });
    render(<MatchOverview />); await screen.findByText('主队3');
    expect(screen.getByText(/未确认结束 1 场/)).toBeInTheDocument();
    expect(screen.getByText(/开球时间未明确 1 场/)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /查看分析 / })).toHaveLength(1);
    expect(screen.getByText(/本次获取 3 场/)).toBeInTheDocument();
    expect(screen.getByText(/最多 5 场/)).toBeInTheDocument();
  });

  it('distinguishes failure and empty data, then retains successful data after refresh failure', async () => {
    api.matches.active.mockRejectedValueOnce(new Error('测试网络失败')); render(<MatchOverview />);
    expect(await screen.findByText(/测试网络失败/)).toBeInTheDocument();
    expect(screen.queryByText('暂无即将开球的比赛')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新' })); await screen.findByText('主队1');
    api.matches.active.mockRejectedValueOnce(new Error('刷新失败')); fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    expect(await screen.findByText(/刷新失败.*保留上次成功数据/)).toBeInTheDocument();
    expect(screen.getByText('主队1')).toBeInTheDocument();
  });

  it('rejects invalid counts and statuses through the same list validation as MatchesPage', async () => {
    api.matches.active.mockResolvedValue({ ...metadata, matches: [{ ...match(1), match_status: null }], total: 1 }); render(<MatchOverview />);
    expect(await screen.findByText(/赛事状态或编号格式异常/)).toBeInTheDocument();
    expect(screen.queryByText('主队1')).not.toBeInTheDocument();
  });

  it('shows an honest empty list and pauses polling while the document is hidden', async () => {
    vi.useFakeTimers(); api.matches.active.mockResolvedValue({ ...metadata, matches: [], total: 0 }); render(<MatchOverview />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText('暂无即将开球的比赛')).toBeInTheDocument();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await act(async () => { vi.advanceTimersByTime(60_000); }); expect(api.matches.active).toHaveBeenCalledTimes(1); vi.useRealTimers();
  });
});
