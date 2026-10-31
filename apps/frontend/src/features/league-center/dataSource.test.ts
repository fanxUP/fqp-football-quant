import { afterEach, describe, expect, it, vi } from 'vitest';
import { sharedLeagueSource } from './dataSource';

describe('shared PostgreSQL league adapter', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('reads only existing same-origin APIs, with filters and the selected revision', async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ competitionSeasonId: 42, evidence: { batchId: '17' }, total: 0, rows: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    await sharedLeagueSource.catalog();
    await sharedLeagueSource.season(42);
    await sharedLeagueSource.fixtures({ competitionSeasonId: 42, roundId: 'r9', status: 'upcoming', teamId: 3, limit: 20, offset: 40, batchId: '17' });
    const urls = fetch.mock.calls.map(call => String(call[0]));
    expect(urls[0]).toBe('/api/league-data/catalog');
    expect(urls[1]).toBe('/api/league-data/seasons/42');
    const page = new URL(urls[2], 'http://localhost');
    expect(page.pathname).toBe('/api/league-data/seasons/42/fixtures');
    expect(Object.fromEntries(page.searchParams)).toEqual({ round_id: 'r9', status: 'upcoming', team_id: '3', limit: '20', offset: '40', batch_id: '17' });
    expect(fetch.mock.calls.every(call => call[1]?.method === undefined || call[1]?.method === 'GET')).toBe(true);
  });
  it('surfaces read errors without fictional data or external fallback', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '联赛读取失败' }), { status: 503 }));
    vi.stubGlobal('fetch', fetch);
    await expect(sharedLeagueSource.catalog()).rejects.toThrow('联赛读取失败');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('carries the verified read scope through every existing endpoint', async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    await sharedLeagueSource.catalog('verified');
    await sharedLeagueSource.season(80, 'verified');
    await sharedLeagueSource.fixtures({ dataset: 'verified', competitionSeasonId: 80, roundId: null, status: 'finished', teamId: null, limit: 20, offset: 20 });
    const urls = fetch.mock.calls.map(call => new URL(String(call[0]), 'http://localhost'));
    expect(urls.every(url => url.searchParams.get('dataset') === 'verified')).toBe(true);
    expect(urls[2].searchParams.has('batch_id')).toBe(false);
  });

});
