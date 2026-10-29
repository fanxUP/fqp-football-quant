import { api } from '../../core/apiClient';
import type { LeagueDataSource } from './types';

/** Same-origin shared PostgreSQL reads through the ordinary session-auth API client. */
export const sharedLeagueSource: LeagueDataSource = {
  catalog: () => api.leagues.catalog(),
  season: id => api.leagues.season(id),
  fixtures: query => api.leagues.fixtures(query),
};

/** Explicit disconnected source for isolated empty-state tests.
 * The catalogue is product scope, not evidence of season/team/data coverage.
 * No demo facts, external requests, fake season IDs or fallback to official-only matches.
 */
export const disconnectedLeagueSource: LeagueDataSource = {
  async catalog() {
    return { status: 'not_connected', competitions: [
      { code: 'premier-league', name: '英超', country: '英格兰', seasons: [] },
    ] };
  },
  async season() { throw new Error('联赛数据尚未接入'); },
  async fixtures() { throw new Error('联赛赛程尚未接入'); },
};
