import type { MatchDetailLineup, MatchDetailLineupPlayer } from '../../core/types';
import { formatTimestamp } from '../../shared/utils';
export type PositionBand = 'GK' | 'DF' | 'MF' | 'FW';
export type SchematicNode = { player: MatchDetailLineupPlayer; band: PositionBand; position: [number, number, number] };
const bands: Record<string, PositionBand> = {
  GK: 'GK', GOALKEEPER: 'GK', 门将: 'GK', 守门员: 'GK',
  DF: 'DF', DEFENDER: 'DF', CB: 'DF', LB: 'DF', RB: 'DF', LWB: 'DF', RWB: 'DF', 后卫: 'DF',
  MF: 'MF', MIDFIELDER: 'MF', DM: 'MF', CDM: 'MF', CM: 'MF', AM: 'MF', CAM: 'MF', LM: 'MF', RM: 'MF', 中场: 'MF',
  FW: 'FW', FORWARD: 'FW', ST: 'FW', CF: 'FW', LW: 'FW', RW: 'FW', 前锋: 'FW',
};
function category(value: string | null): PositionBand | null { return value ? bands[value.trim().toUpperCase()] ?? null : null; }
function positive(value: unknown) { return Number.isSafeInteger(value) && Number(value) > 0; }
export function schematic(lineup: MatchDetailLineup | null, matchId: number, teamId: number | null): { nodes: SchematicNode[]; reason: string | null } {
  const empty = (reason: string) => ({ nodes: [], reason });
  if (!lineup) return empty('尚无阵容快照，二维名单仍可核验。');
  if (!positive(lineup.snapshot_id) || lineup.match_id !== matchId || !positive(teamId) || lineup.team_id !== teamId || !lineup.source?.trim() || !lineup.snapshot_time || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/i.test(lineup.snapshot_time) || formatTimestamp(lineup.snapshot_time) === '—') return empty('来源、时间或身份不完整，暂不生成阵型示意。');
  if (!['confirmed','predicted','historical'].includes(lineup.lineup_type ?? '')) return empty('名单类型未知，暂不生成阵型示意。');
  const starters = lineup.players.filter(p => p.is_starting);
  if (starters.length !== 11 || new Set(starters.map(p => p.player_id)).size !== 11 || starters.some(p => !positive(p.player_id) || p.is_substitute)) return empty('首发名单不足或身份冲突，暂不生成阵型示意。');
  const grouped: Record<PositionBand, MatchDetailLineupPlayer[]> = { GK: [], DF: [], MF: [], FW: [] };
  for (const player of starters) {
    const position = category(player.position?.trim() || null);
    const primary = category(player.primary_position?.trim() || null);
    // Snapshot position takes precedence. Unknown or contradictory values must not be guessed from a role.
    const band = player.position?.trim() ? position : primary;
    if (!band || (position && primary && position !== primary)) return empty('位置类别缺失或冲突，暂不生成阵型示意。');
    grouped[band].push(player);
  }
  if (grouped.GK.length !== 1 || !grouped.DF.length || !grouped.MF.length || !grouped.FW.length) return empty('位置分区证据不足，暂不生成阵型示意。');
  const depth: Record<PositionBand, number> = { GK: 45, DF: 22, MF: -5, FW: -32 };
  const nodes = (['GK','DF','MF','FW'] as const).flatMap(band => grouped[band].sort((a,b) => a.player_id - b.player_id).map((player, i, players) => ({
    player, band, position: [(i - (players.length - 1) / 2) * Math.min(14, 56 / Math.max(1, players.length - 1)), 1.3, depth[band]] as [number,number,number],
  })));
  return { nodes, reason: null };
}
