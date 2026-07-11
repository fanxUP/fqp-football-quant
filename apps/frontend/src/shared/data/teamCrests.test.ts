import { describe, expect, it } from 'vitest';
import { findTeamCrest, findTeamCrestUrl, TEAM_CREST_REGISTRY } from './teamCrests';

describe('team crest registry', () => {
  it('resolves a locally bundled crest through a Chinese team name', () => {
    expect(findTeamCrestUrl('汉坎')).toBe('/team-crests/500-861.png');
  });

  it('returns crest provenance together with the local asset path', () => {
    expect(findTeamCrest('KFUM奥斯陆')).toEqual({
      names: expect.arrayContaining(['奥斯陆KFUM', 'KFUM奥斯陆']),
      logoUrl: '/team-crests/500-5263.png',
      source: '500com',
    });
  });

  it('contains a non-circular crest asset for every current database team', () => {
    expect(TEAM_CREST_REGISTRY).toHaveLength(119);
    expect(TEAM_CREST_REGISTRY.every((entry) => entry.logoUrl.startsWith('/team-crests/'))).toBe(true);
    expect(TEAM_CREST_REGISTRY.every((entry) => /\.(png|webp)$/.test(entry.logoUrl))).toBe(true);
  });
});
