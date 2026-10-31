import { describe, expect, it } from 'vitest';
import { eventCenterHash, readEventCenterState } from './state';

describe('league URL state', () => {
  it('roundtrips the verified dataset and namespaced canonical competition', () => {
    const state = readEventCenterState('#/events?view=league&dataset=verified&competition=sporttery:c4169e38cdfd&competition_season_id=42&tab=fixtures');
    expect(state).toMatchObject({ dataset: 'verified', competition: 'sporttery:c4169e38cdfd', warning: null });
    expect(readEventCenterState(eventCenterHash(state))).toEqual(state);
  });
  it('keeps an unselected verified catalog independent of the old default competition', () => {
    expect(readEventCenterState('#/events?view=league&dataset=verified')).toMatchObject({ dataset: 'verified', competition: '', seasonId: null, tab: 'fixtures' });
  });
  it('warns on unknown datasets and duplicate dataset fields', () => {
    expect(readEventCenterState('#/events?view=league&dataset=other').warning).not.toBeNull();
    expect(readEventCenterState('#/events?view=league&dataset=verified&dataset=reference').warning).not.toBeNull();
  });
  it('keeps the existing official entry as default', () => {
    expect(readEventCenterState('#/events').view).toBe('official');
  });
  it('restores a canonical season and team without inferring a calendar year', () => {
    const state = readEventCenterState('#/events?view=league&competition=premier-league&competition_season_id=42&tab=teams&team_id=8&page=3');
    expect(state).toMatchObject({ view: 'league', seasonId: 42, teamId: 8, page: 3, tab: 'teams', warning: null });
    expect(readEventCenterState(eventCenterHash(state))).toEqual(state);
  });
  it.each([
    'competition_season_id=0', 'competition_season_id=-1', 'competition_season_id=2.5',
    'competition_season_id=9007199254740992', 'competition_season_id=1&competition_season_id=2',
    'team_id=NaN', 'page=0', 'tab=simulation', 'scope=xpts', 'status=bad',
    'competition=../../matches', 'tab=teams&tab=fixtures', 'view=league&view=official',
  ])('warns on invalid or ambiguous parameters: %s', query => {
    expect(readEventCenterState(`#/events?view=league&${query}`).warning).not.toBeNull();
  });
  it('preserves valid fields when a single parameter is invalid', () => {
    expect(readEventCenterState('#/events?view=league&competition_season_id=42&tab=fixtures&page=bad'))
      .toMatchObject({ seasonId: 42, tab: 'fixtures', page: 1 });
  });
});
