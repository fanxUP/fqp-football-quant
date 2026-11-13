import { api } from '../../core/apiClient';
import type { MatchCatalogQuery } from '../../core/types';
import { validateMatches } from './presentation';

export const ACTIVE_MATCH_LIMIT = 500;

export async function loadActiveMatches(params: MatchCatalogQuery = {}) {
  const limit = params.limit ?? ACTIVE_MATCH_LIMIT;
  const response = await api.matches.active({ ...params, limit });
  const matches = validateMatches(response.matches);
  if (matches.some(match => typeof match.match_status !== 'string' || (match.match_num_str != null && typeof match.match_num_str !== 'string'))) {
    throw new Error('赛事状态或编号格式异常');
  }
  if (matches.some(match => (match.result_status !== undefined && typeof match.result_status !== 'string')
    || (match.status_note != null && typeof match.status_note !== 'string'))) throw new Error('赛事证据格式异常');
  if (matches.length > limit || !Number.isSafeInteger(response.total) || response.total < matches.length
    || !Number.isSafeInteger(response.offset) || response.offset < 0
    || response.offset + matches.length > response.total
    || response.limit !== limit || !['current', 'history'].includes(response.scope)
    || !Number.isSafeInteger(response.started_total) || response.started_total < 0
    || typeof response.selected_in_scope !== 'boolean' || typeof response.selected_in_filter !== 'boolean'
    || !Array.isArray(response.leagues) || !response.leagues.every(value => typeof value === 'string')
    || !Array.isArray(response.statuses) || !response.statuses.every(value => typeof value === 'string')) {
    throw new Error('赛事数量格式异常');
  }
  return { ...response, matches };
}

export function kickoffValue(time: string) {
  const normalized = time.replace(' ', 'T');
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}+08:00`).valueOf();
}
