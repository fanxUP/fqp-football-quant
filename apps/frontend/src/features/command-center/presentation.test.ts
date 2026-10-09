import { describe, expect, it } from 'vitest';
import { validateMatches, latestOdds, predictionGroups, percent, sceneNodes, freshness } from './presentation';
import type { MatchDetailPrediction, TodayMatch } from '../../core/types';
import type { OfficialOddsSnapshot } from '../../core/apiClient';
const match = (id: number): TodayMatch => ({ match_id: id, home_team_name: '主队', away_team_name: '客队', league_name: '联赛', kickoff_time: '2026-10-08T20:00:00', match_status: 'scheduled', match_num_str: `周四00${id}`, completeness: null, odds_count: 0 });
describe('command center evidence presentation', () => {
  it('rejects duplicate and malformed IDs', () => {
    expect(() => validateMatches([match(1), match(1)])).toThrow();
    expect(() => validateMatches([{ ...match(1), match_id: -1 }])).toThrow();
    expect(validateMatches([match(1)])[0].match_id).toBe(1);
  });
  it('keeps zero distinct from missing probabilities', () => {
    expect(percent(0)).toBe('0.0%'); expect(percent(null)).toBe('—'); expect(percent(2)).toBe('—');
  });
  it('never mixes predictions across models, plays or snapshots', () => {
    const base = { model_name: 'A', play_type: 'spf', predict_time: '2026-10-08T12:00:00', option_code: 'h', model_probability: 0.5 } as MatchDetailPrediction;
    const groups = predictionGroups([base, { ...base, model_name: 'B' }, { ...base, play_type: 'jqs' }, { ...base, predict_time: '2026-10-08T13:00:00' }]);
    expect(groups).toHaveLength(4); expect(groups[0].time).toBe('2026-10-08T13:00:00');
  });
  it('uses one actual odds snapshot and validates match IDs', () => {
    const base = { match_id: 1, id: 20, snapshot_time: '2026-10-08T12:00:00', option_code: 'h', play_type: 'spf', sp_value: 2 } as OfficialOddsSnapshot;
    expect(latestOdds([base, { ...base, id: 21, snapshot_time: '2026-10-08T13:00:00', option_code: 'd' }], 1)).toHaveLength(1);
    expect(latestOdds([base, { ...base, id: 21, option_code: 'd' }], 1)).toHaveLength(2);
    expect(() => latestOdds([{ ...base, match_id: 2 }], 1)).toThrow();
  });
  it('shows stale cached responses without inventing a snapshot time', () => {
    expect(freshness(null, 1000)).toBe('未获取'); expect(freshness(100, 200)).toBe('已获取'); expect(freshness(100, 100000)).toBe('响应已过期');
  });
  it('caps nodes but preserves the selected real ID', () => {
    const nodes = sceneNodes(Array.from({ length: 80 }, (_, i) => match(i + 1)), 80);
    expect(nodes.length).toBeLessThanOrEqual(24); expect(nodes.some(n => n.match.match_id === 80)).toBe(true);
    expect(new Set(nodes.map(n => n.match.match_id)).size).toBe(nodes.length);
  });
});
