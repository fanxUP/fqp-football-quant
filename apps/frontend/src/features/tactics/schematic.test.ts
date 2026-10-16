import { expect, it } from 'vitest';
import type { MatchDetailLineup } from '../../core/types';
import { schematic } from './schematic';
export function lineup(): MatchDetailLineup {
  return { snapshot_id: 8, match_id: 101, team_id: 1, source: '界面测试来源', snapshot_time: '2026-10-10T12:00:00', collected_at: null, formation: '4-3-3', lineup_type: 'confirmed', strength_score: 0, starting_11_value: null, key_player_count: null,
    players: ['GK','CB','CB','LB','RB','CM','CM','DM','LW','RW','ST'].map((position, i) => ({ player_id: i + 30, name_cn: `测试球员${i}`, name_en: null, position, primary_position: null, tactical_role: null, is_starting: true, is_substitute: false })) };
}
it('uses actual IDs and category bands with bounded schematic coordinates', () => {
  const result = schematic(lineup(), 101, 1);
  expect(result.reason).toBeNull(); expect(result.nodes).toHaveLength(11);
  expect(result.nodes.map(n => n.player.player_id)).toEqual(lineup().players.map(p => p.player_id));
  expect(result.nodes.map(n => n.band)).toEqual(['GK','DF','DF','DF','DF','MF','MF','MF','FW','FW','FW']);
  expect(result.nodes.every(n => n.position.every(Number.isFinite) && Math.abs(n.position[0]) <= 28 && Math.abs(n.position[2]) <= 48)).toBe(true);
});
it('keeps layout stable after source order changes without deriving jersey numbers', () => {
  const data = lineup(); const first = schematic(data, 101, 1); data.players.reverse();
  expect(schematic(data, 101, 1)).toEqual(first); expect(first.nodes[0]).not.toHaveProperty('jersey');
});
it.each(['predicted', 'historical'])('supports explicitly labelled %s evidence without upgrading its type', type => {
  const data = lineup(); data.lineup_type = type;
  expect(schematic(data, 101, 1).nodes).toHaveLength(11); expect(data.lineup_type).toBe(type);
});
it.each(['source', 'snapshot_time', 'snapshot_id', 'match_id', 'team_id', 'lineup_type'])('refuses missing %s provenance', field => {
  const data = {...lineup(), [field]: undefined}; expect(schematic(data, 101, 1).nodes).toEqual([]); expect(schematic(data, 101, 1).reason).toBeTruthy();
});
it('rejects foreign identities, invalid times and unknown types', () => {
  for (const data of [{...lineup(), team_id:2}, {...lineup(), match_id:102}, {...lineup(), snapshot_time:'2026-99-99T12:00:00'}, {...lineup(),lineup_type:'other'}]) expect(schematic(data,101,1).nodes).toEqual([]);
});
it('refuses incomplete starters, duplicate identity or multiple goalkeepers', () => {
  const data = lineup(); data.players[10].is_starting = false; expect(schematic(data,101,1).nodes).toEqual([]);
  data.players[10].is_starting = true; data.players[10].player_id = 30; expect(schematic(data,101,1).nodes).toEqual([]);
  data.players[10].player_id = 40; data.players[10].position = 'GK'; expect(schematic(data,101,1).nodes).toEqual([]);
});
it('does not guess unknown positions, sides, roles or contradictory categories', () => {
  for (const position of [null, 'unknown', '7', 'WINGER']) { const data = lineup(); data.players[10].position = position; data.players[10].tactical_role = '射手'; expect(schematic(data,101,1).nodes).toEqual([]); }
  const data = lineup(); data.players[10].primary_position = 'DF'; expect(schematic(data,101,1).nodes).toEqual([]);
});
it('accepts primary category only if snapshot position is absent', () => {
  const data = lineup(); data.players[10].position = null; data.players[10].primary_position = 'FW'; expect(schematic(data,101,1).nodes).toHaveLength(11);
});
it('omits substitutes while keeping evidence untouched', () => {
  const data = lineup(); data.players.push({...data.players[10],player_id:999,is_starting:false,is_substitute:true});
  expect(schematic(data,101,1).nodes).toHaveLength(11); expect(data.players).toHaveLength(12);
});
it('uses category layout even when reported formation is missing or differs', () => {
  const data = lineup(); data.formation = null; expect(schematic(data,101,1).nodes).toHaveLength(11);
  data.formation = '3-5-2'; expect(schematic(data,101,1).nodes).toEqual(schematic(lineup(),101,1).nodes);
});
