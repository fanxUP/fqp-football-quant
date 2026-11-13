import { beforeEach, describe, expect, it, vi } from 'vitest';
import { kickoffValue, loadActiveMatches } from './activeMatches';

const active = vi.hoisted(() => vi.fn());
vi.mock('../../core/apiClient', () => ({ api: { matches: { active } } }));
const metadata = { offset: 0, limit: 500, scope: 'current', leagues: [], statuses: [], selected_in_scope: false, selected_in_filter: false, started_total: 0, as_of: '', current_since: '' };
const match = { match_id: 1, home_team_name: '主队', away_team_name: '客队', league_name: '联赛', match_status: 'scheduled', match_num_str: '', kickoff_time: '2026-10-25T20:00:00', completeness: null, odds_count: 0 };

describe('shared active match reads', () => {
  beforeEach(() => { active.mockReset(); });
  it('uses one bounded read and accepts genuine zero and unknown statuses', async () => {
    active.mockResolvedValueOnce({ ...metadata, matches: [], total: 0 }); expect(await loadActiveMatches()).toEqual({ ...metadata, matches: [], total: 0 });
    active.mockResolvedValueOnce({ ...metadata, matches: [{ ...match, match_status: 'new_status' }], total: 1 });
    expect((await loadActiveMatches()).matches[0].match_status).toBe('new_status'); expect(active).toHaveBeenCalledWith({ limit: 500 });
  });
  it.each([-1, 0, 0.5, NaN, Infinity, '1'])('rejects an inconsistent or malformed count: %s', async total => {
    active.mockResolvedValue({ ...metadata, matches: [match], total }); await expect(loadActiveMatches()).rejects.toThrow('赛事数量格式异常');
  });
  it('rejects more than the requested limit', async () => {
    active.mockResolvedValue({ ...metadata, matches: Array.from({ length: 501 }, (_, index) => ({ ...match, match_id: index + 1 })), total: 501 });
    await expect(loadActiveMatches()).rejects.toThrow('赛事数量格式异常');
  });
  it('normalizes Shanghai wall time without inventing unknown dates', () => {
    expect(kickoffValue(match.kickoff_time)).toBe(Date.parse('2026-10-25T12:00:00Z'));
    expect(Number.isNaN(kickoffValue('invalid'))).toBe(true);
  });
});
