export interface TeamCrestEntry {
  names: string[];
  logoUrl: string;
  source: 'official' | '500com';
}

import { GENERATED_TEAM_CREST_REGISTRY } from './teamCrests.generated';

const normalizeTeamName = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/[·.。-]/g, '');

/**
 * Team crest registry.
 *
 * Every entry resolves to a locally bundled, original provider crest. Do not
 * add generated initials, simplified SVGs, or unofficial fan artwork here.
 */
export const TEAM_CREST_REGISTRY: TeamCrestEntry[] = GENERATED_TEAM_CREST_REGISTRY;

export function findTeamCrest(...names: Array<string | null | undefined>): TeamCrestEntry | null {
  const keys = names
    .filter((name): name is string => !!name)
    .map(normalizeTeamName)
    .filter(Boolean);

  if (!keys.length) return null;

  return TEAM_CREST_REGISTRY.find((entry) =>
    entry.names.some((name) => keys.includes(normalizeTeamName(name))),
  ) ?? null;
}

export function findTeamCrestUrl(...names: Array<string | null | undefined>): string | null {
  return findTeamCrest(...names)?.logoUrl ?? null;
}
