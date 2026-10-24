import { api } from '../../core/apiClient';
import type { TodayMatch } from '../../core/types';
import { validateMatches } from './presentation';

export const ACTIVE_MATCH_LIMIT = 500;

export async function loadActiveMatches() {
  const response = await api.matches.active({ limit: ACTIVE_MATCH_LIMIT });
  const matches = validateMatches(response.matches);
  if (matches.some(match => typeof match.match_status !== 'string' || (match.match_num_str != null && typeof match.match_num_str !== 'string'))) {
    throw new Error('赛事状态或编号格式异常');
  }
  if (matches.length > ACTIVE_MATCH_LIMIT || !Number.isSafeInteger(response.total) || response.total < matches.length) {
    throw new Error('赛事数量格式异常');
  }
  return { matches, total: response.total };
}

export function kickoffValue(time: string) {
  const normalized = time.replace(' ', 'T');
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}+08:00`).valueOf();
}

export function compareKickoff(a: TodayMatch, b: TodayMatch, sort = 'asc') {
  const left = kickoffValue(a.kickoff_time), right = kickoffValue(b.kickoff_time);
  if (!Number.isFinite(left) || !Number.isFinite(right)) {
    return Number.isFinite(left) ? -1 : Number.isFinite(right) ? 1 : a.match_id - b.match_id;
  }
  return (sort === 'desc' ? right - left : left - right) || a.match_id - b.match_id;
}
