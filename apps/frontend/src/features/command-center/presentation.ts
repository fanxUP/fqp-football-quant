import type { MatchDetailPrediction, TodayMatch } from '../../core/types';
import type { OfficialOddsSnapshot } from '../../core/apiClient';

export function validateMatches(value: unknown): TodayMatch[] {
  if (!Array.isArray(value)) throw new Error('赛事列表格式异常');
  const ids = new Set<number>();
  for (const row of value) {
    if (!row || !Number.isSafeInteger(row.match_id) || row.match_id <= 0 || ids.has(row.match_id)
      || typeof row.home_team_name !== 'string' || typeof row.away_team_name !== 'string'
      || typeof row.league_name !== 'string' || typeof row.kickoff_time !== 'string') {
      throw new Error('赛事数据验证失败：ID 或球队信息异常');
    }
    ids.add(row.match_id);
  }
  return value;
}

export function percent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? `${(value * 100).toFixed(1)}%` : '—';
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—';
  // Official match and prediction TIMESTAMP values have Shanghai wall time.
  const normalized = value.replace(' ', 'T');
  const dated = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}+08:00`);
  return Number.isNaN(dated.valueOf()) ? '—' : dated.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function freshness(receivedAt: number | null, now = Date.now()): string {
  return receivedAt === null ? '未获取' : now - receivedAt > 90_000 ? '响应已过期' : '已获取';
}

export function predictionGroups(rows: MatchDetailPrediction[]) {
  const groups = new Map<string, { key: string; model: string; play: string; time: string; rows: MatchDetailPrediction[] }>();
  for (const row of rows) {
    const key = JSON.stringify([row.model_name, row.play_type, row.predict_time]);
    if (!groups.has(key)) groups.set(key, { key, model: row.model_name, play: row.play_type, time: row.predict_time, rows: [] });
    groups.get(key)!.rows.push(row);
  }
  return [...groups.values()].sort((a, b) => b.time.localeCompare(a.time));
}

export function latestOdds(rows: OfficialOddsSnapshot[], matchId: number): OfficialOddsSnapshot[] {
  if (rows.some(row => row.match_id !== matchId || !Number.isSafeInteger(row.id) || !row.snapshot_time)) {
    throw new Error('赔率赛事 ID 或快照不一致，已停止展示');
  }
  const relevant = rows.filter(row => ['spf', 'had'].includes(row.play_type.toLowerCase()));
  const latest = [...relevant].sort((a, b) => b.snapshot_time.localeCompare(a.snapshot_time) || b.id - a.id)[0];
  // Each option is its own database row/ID. Equal timestamps are a display
  // grouping only; they are not evidence of a shared collection run.
  if (!latest) return [];
  const options = new Map<string, OfficialOddsSnapshot>();
  for (const row of relevant.filter(row => row.snapshot_time === latest.snapshot_time && row.play_type === latest.play_type && row.handicap === latest.handicap)) {
    const previous = options.get(row.option_code);
    if (!previous || previous.id < row.id) options.set(row.option_code, row);
  }
  return [...options.values()];
}

export function sceneNodes(matches: TodayMatch[], selectedId: number | null) {
  const visible = matches.slice(0, 24);
  const selected = matches.find(row => row.match_id === selectedId);
  if (selected && !visible.some(row => row.match_id === selectedId)) visible[visible.length - 1] = selected;
  return visible.map((match, index) => ({ match, position: [((index % 4) - 1.5) * 13, 1.6, (Math.floor(index / 4) - 2.5) * 15] as [number, number, number] }));
}
