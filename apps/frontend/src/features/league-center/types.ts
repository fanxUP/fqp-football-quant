/** Shared UI read contract. Canonical IDs come from FQP, never provider IDs or array positions. */
export type LeagueDataset = 'reference' | 'verified';
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
  dataset?: LeagueDataset;
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
  dataset?: LeagueDataset;
  seasonIdentity?: { label: string; sourceSeasonId: string; plannedStartDate: string; plannedEndDate: string; timeZone: string };
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
  home: Omit<LeagueTeam, 'id'> & { id: number | null };
  away: Omit<LeagueTeam, 'id'> & { id: number | null };
  kickoff: string | null;
  roundId: string | null;
  status: 'scheduled' | 'live' | 'finished' | 'postponed' | 'cancelled' | 'unknown';
  homeGoals: number | null;
  awayGoals: number | null;
  officialMatch: { id: number; verification: 'verified' | 'pending' } | null;
}
export interface LeagueFixtureQuery {
  dataset?: LeagueDataset;
  competitionSeasonId: number;
  batchId?: string; // freeze pagination to the selected season resource's revision
  roundId: string | null;
  status: FixtureFilter;
  teamId: number | null;
  limit: number;
  offset: number;
}
export interface LeagueFixturePage {
  dataset?: LeagueDataset;
  competitionSeasonId: number;
  evidence: LeagueEvidence;
  total: number; // exact filtered count, not returned row count
  rows: LeagueFixture[];
}
/** Future implementation reads shared FQP APIs only; it must not collect data from the page. */
export interface LeagueDataSource {
  catalog: (dataset?: LeagueDataset) => Promise<LeagueCatalog>;
  season: (competitionSeasonId: number, dataset?: LeagueDataset) => Promise<LeagueSeasonData>;
  fixtures: (query: LeagueFixtureQuery) => Promise<LeagueFixturePage>;
}
