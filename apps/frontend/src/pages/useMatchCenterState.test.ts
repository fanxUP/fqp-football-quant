import { describe, expect, it } from 'vitest';
import { matchCenterHash, readMatchCenterState } from './useMatchCenterState';

describe('match center URL state', () => {
  it('round-trips Chinese filters, reserved characters and explicit selection', () => {
    const state = { query: '北京 & 上海?#', league: '中超', status: 'awaiting_result', sort: 'desc' as const, page: 2, selectedId: 51, warning: null };
    expect(readMatchCenterState(matchCenterHash(state))).toEqual(state);
  });

  it.each(['0', '-1', '1.5', '1e3', 'Infinity', '9007199254740992', '', '12&match_id=13'])('rejects invalid or ambiguous IDs: %s', value => {
    const state = readMatchCenterState(`#/matches?match_id=${value}`);
    expect(state.selectedId).toBeNull(); expect(state.warning).toContain('链接参数无效');
  });

  it.each([
    ['q', 'query', '主队', '客队', ''],
    ['league', 'league', '中超', '英超', ''],
    ['status', 'status', 'scheduled', 'awaiting_result', ''],
    ['sort', 'sort', 'desc', 'asc', 'asc'],
    ['page', 'page', '2', '3', 1],
  ] as const)('defaults only the ambiguous %s field and preserves a valid selected match', (parameter, field, first, second, fallback) => {
    const params = new URLSearchParams([['match_id', '51'], [parameter, first], [parameter, second]]);
    const state = readMatchCenterState(`#/matches?${params}`);
    expect(state[field]).toBe(fallback);
    expect(state.selectedId).toBe(51);
    expect(state.warning).toContain('链接参数无效');
  });

  it('keeps unknown values as filters without introducing external return URLs', () => {
    const state = readMatchCenterState('#/matches?league=unknown&return=https://example.invalid');
    expect(state.league).toBe('unknown'); expect(matchCenterHash(state)).toBe('#/matches?league=unknown');
  });
});
