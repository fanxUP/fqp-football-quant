import { beforeEach, describe, expect, it, vi } from 'vitest';
import { compareKickoff, kickoffValue, loadActiveMatches } from './activeMatches';

const active = vi.hoisted(() => vi.fn());
vi.mock('../../core/apiClient', () => ({ api: { matches: { active } } }));
const match = { match_id: 1, home_team_name: '主队', away_team_name: '客队', league_name: '联赛', match_status: 'scheduled', match_num_str: '', kickoff_time: '2026-10-25T20:00:00', completeness: null, odds_count: 0 };

describe('shared active match reads', () => {
  beforeEach(() => { active.mockReset(); });
  it('uses one bounded read and accepts genuine zero and unknown statuses', async () => {
    active.mockResolvedValueOnce({ matches: [], total: 0 }); expect(await loadActiveMatches()).toEqual({ matches: [], total: 0 });
    active.mockResolvedValueOnce({ matches: [{ ...match, match_status: 'new_status' }], total: 1 });
    expect((await loadActiveMatches()).matches[0].match_status).toBe('new_status'); expect(active).toHaveBeenCalledWith({ limit: 500 });
  });
  it.each([-1, 0, 0.5, NaN, Infinity, '1'])('rejects an inconsistent or malformed count: %s', async total => {
    active.mockResolvedValue({ matches: [match], total }); await expect(loadActiveMatches()).rejects.toThrow('赛事数量格式异常');
  });
  it('rejects more than the requested limit', async () => {
    active.mockResolvedValue({ matches: Array.from({ length: 501 }, (_, index) => ({ ...match, match_id: index + 1 })), total: 501 });
    await expect(loadActiveMatches()).rejects.toThrow('赛事数量格式异常');
  });
  it('normalizes Shanghai wall time and sorts unknown dates last in both directions', () => {
    expect(kickoffValue(match.kickoff_time)).toBe(Date.parse('2026-10-25T12:00:00Z'));
    const invalid = { ...match, kickoff_time: 'invalid' };
    expect(compareKickoff(invalid, match, 'desc')).toBeGreaterThan(0);
    expect(compareKickoff(invalid, match)).toBeGreaterThan(0);
  });
});
