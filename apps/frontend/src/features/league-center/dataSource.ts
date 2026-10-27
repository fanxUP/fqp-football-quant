import type { LeagueDataSource } from './types';

/** Deliberately disconnected until the shared-data adapter is implemented.
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
