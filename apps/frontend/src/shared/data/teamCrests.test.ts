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

  it('uses verified cached EPL crests for Chinese, English and traditional aliases', () => {
    expect(findTeamCrest('阿森纳')).toMatchObject({ logoUrl: '/team-crests/titan007-19.png', source: 'titan007' });
    expect(findTeamCrestUrl('Arsenal')).toBe('/team-crests/titan007-19.png');
    expect(findTeamCrestUrl('阿仙奴')).toBe('/team-crests/titan007-19.png');
    expect(findTeamCrestUrl('托特纳姆热刺')).toBe('/team-crests/titan007-33.png');
    expect(findTeamCrestUrl('曼城')).toBe(findTeamCrestUrl('Manchester City'));
    expect(findTeamCrestUrl('曼联')).toBe('/team-crests/titan007-27.png');
  });

  it('preserves national-team identity and assigns each EPL alias to one crest', () => {
    expect(findTeamCrestUrl('中国')).toBe('/team-crests/500-426.png');
    const verified = TEAM_CREST_REGISTRY.filter((entry) => entry.source === 'titan007');
    expect(verified).toHaveLength(20);
    for (const entry of verified) {
      for (const name of entry.names) {
        expect(TEAM_CREST_REGISTRY.filter((candidate) => candidate.names.includes(name))).toHaveLength(1);
      }
    }
  });

  it('contains a non-circular crest asset for every current database team', () => {
    expect(TEAM_CREST_REGISTRY.length).toBeGreaterThanOrEqual(119);
    expect(TEAM_CREST_REGISTRY.every((entry) => entry.logoUrl.startsWith('/team-crests/'))).toBe(true);
    expect(TEAM_CREST_REGISTRY.every((entry) => /\.(jpg|png|webp)$/.test(entry.logoUrl))).toBe(true);
  });
});
