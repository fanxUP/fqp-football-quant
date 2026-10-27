/** Shared UI read contract. Canonical IDs come from FQP, never provider IDs or array positions. */
export type StandingScope = 'all' | 'home' | 'away' | 'form';
export type FixtureFilter = 'all' | 'finished' | 'upcoming' | 'postponed';
export interface LeagueEvidence {
  sourceName: string | null;
  asOf: string | null; // timezone-qualified instant; not the browser fetch time
  batchId: string | null;
  completeness: 'complete' | 'partial' | 'unavailable';
  stale: boolean;
}
export interface LeagueCatalog {
  status: 'connected' | 'not_connected';
  competitions: {
    code: string;
    name: string;
    country: string;
    seasons: { id: number; label: string; isCurrent: boolean }[];
  }[];
}
export interface LeagueTeam {
  id: number;
  name: string;
  manager: string | null;
  stadium: string | null;
}
export interface LeagueStanding {
  team: LeagueTeam;
  rank: number | null;
  played: number | null;
  won: number | null;
  drawn: number | null;
  lost: number | null;
  goalsFor: number | null;
  goalsAgainst: number | null;
  goalDifference: number | null;
  points: number | null; // source value includes penalties; do not recalculate
  form: ('W' | 'D' | 'L')[] | null; // current league/season, oldest -> newest, at most 5
  note: string | null;
}
export interface LeagueSeasonData {
  competitionSeasonId: number;
  evidence: LeagueEvidence;
  coverage: { teams: number | null; expectedTeams: number | null; fixtures: number | null; expectedFixtures: number | null };
  overview: {
    played: number | null;
    goals: number | null;
    goalsPerMatch: number | null;
    homeWins: number | null;
    draws: number | null;
    awayWins: number | null;
  } | null;
  standings: Partial<Record<StandingScope, { evidence: LeagueEvidence; rows: LeagueStanding[] }>>;
  teams: LeagueTeam[];
  rounds: { id: string; label: string }[];
}
export interface LeagueFixture {
  id: string; // namespaced reference ID; never used as official match ID
  home: LeagueTeam;
  away: LeagueTeam;
  kickoff: string | null;
  roundId: string | null;
  status: 'scheduled' | 'live' | 'finished' | 'postponed' | 'cancelled' | 'unknown';
  homeGoals: number | null;
  awayGoals: number | null;
  officialMatch: { id: number; verification: 'verified' | 'pending' } | null;
}
export interface LeagueFixtureQuery {
  competitionSeasonId: number;
  roundId: string | null;
  status: FixtureFilter;
  teamId: number | null;
  limit: number;
  offset: number;
}
export interface LeagueFixturePage {
  competitionSeasonId: number;
  evidence: LeagueEvidence;
  total: number; // exact filtered count, not returned row count
  rows: LeagueFixture[];
}
/** Future implementation reads shared FQP APIs only; it must not collect data from the page. */
export interface LeagueDataSource {
  catalog: () => Promise<LeagueCatalog>;
  season: (competitionSeasonId: number) => Promise<LeagueSeasonData>;
  fixtures: (query: LeagueFixtureQuery) => Promise<LeagueFixturePage>;
}
