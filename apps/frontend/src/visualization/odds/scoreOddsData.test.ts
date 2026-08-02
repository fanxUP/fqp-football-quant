import { describe, expect, it } from 'vitest';
import type { OddsMovementPoint } from '../../core/types';
import { buildScoreOddsView } from './scoreOddsData';

const points: OddsMovementPoint[] = [
  { snapshot_id: 1, snapshot_time: '2026-08-01T10:00:00+08:00', play_type: 'bf', option_code: '0:0', option_name: '0:0', sp_value: 7.2, handicap: null, implied_probability: null, prev_sp_value: null },
  { snapshot_id: 2, snapshot_time: '2026-08-01T11:00:00+08:00', play_type: 'bf', option_code: '0:0', option_name: '0:0', sp_value: 6.8, handicap: null, implied_probability: null, prev_sp_value: 7.2 },
  { snapshot_id: 3, snapshot_time: '2026-08-01T11:00:00+08:00', play_type: 'bf', option_code: '1:0', option_name: '1:0', sp_value: 5.6, handicap: null, implied_probability: null, prev_sp_value: null },
  { snapshot_id: 4, snapshot_time: '2026-08-01T11:00:00+08:00', play_type: 'bf', option_code: 'other_h', option_name: '胜其他', sp_value: 18, handicap: null, implied_probability: null, prev_sp_value: null },
];

describe('buildScoreOddsView', () => {
  it('按主客进球归档比分，并保留最后一次赔率与变化', () => {
    const view = buildScoreOddsView(points);

    expect(view.exactScores).toContainEqual(expect.objectContaining({
      code: '0:0', homeGoals: 0, awayGoals: 0, currentSp: 6.8, previousSp: 7.2, delta: -0.4,
    }));
    expect(view.exactScores).toContainEqual(expect.objectContaining({
      code: '1:0', homeGoals: 1, awayGoals: 0, currentSp: 5.6,
    }));
    expect(view.otherScores).toEqual([expect.objectContaining({ code: 'other_h', currentSp: 18 })]);
  });

  it('默认以当前 SP 最低的六个比分作为热门比分', () => {
    const view = buildScoreOddsView(points);

    expect(view.featuredScores.map((item) => item.code)).toEqual(['1:0', '0:0']);
  });
});
