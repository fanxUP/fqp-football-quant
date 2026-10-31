import { useCallback, useEffect, useRef, useState } from 'react';
import type { FixtureFilter, LeagueDataset, StandingScope } from './types';

export interface EventCenterState {
  view: 'official' | 'league';
  dataset: LeagueDataset;
  competition: string;
  seasonId: number | null;
  tab: 'standings' | 'fixtures' | 'teams';
  scope: StandingScope;
  status: FixtureFilter;
  roundId: string | null;
  teamId: number | null;
  page: number;
  warning: string | null;
}
export function readEventCenterState(hash = window.location.hash): EventCenterState {
  const params = new URLSearchParams(hash.split('?')[1] ?? '');
  let invalid = false;
  const single = (key: string) => {
    const values = params.getAll(key);
    if (values.length > 1) { invalid = true; return null; }
    return values[0] ?? null;
  };
  function choice<T extends string>(key: string, options: readonly T[], fallback: T): T {
    const raw = single(key);
    if (raw === null) return fallback;
    if (options.includes(raw as T)) return raw as T;
    invalid = true; return fallback;
  }
  const integer = (key: string, fallback: number | null) => {
    const raw = single(key);
    if (raw === null) return fallback;
    if (/^[1-9]\d*$/.test(raw) && Number.isSafeInteger(Number(raw))) return Number(raw);
    invalid = true; return fallback;
  };
  const token = (key: string, fallback: string | null) => {
    const raw = single(key);
    if (raw === null) return fallback;
    if ((key === 'competition' ? /^[a-zA-Z0-9][a-zA-Z0-9_:-]{0,63}$/ : /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/).test(raw)) return raw;
    invalid = true; return fallback;
  };
  const dataset = choice('dataset', ['reference', 'verified'], 'reference');
  const state: EventCenterState = {
    dataset,
    view: choice('view', ['official', 'league'], 'official'),
    competition: token('competition', dataset === 'verified' ? '' : 'premier-league')!,
    seasonId: integer('competition_season_id', null),
    tab: choice('tab', ['standings', 'fixtures', 'teams'], dataset === 'verified' ? 'fixtures' : 'standings'),
    scope: choice('scope', ['all', 'home', 'away', 'form'], 'all'),
    status: choice('status', ['all', 'finished', 'upcoming', 'postponed'], 'all'),
    roundId: token('round', null), teamId: integer('team_id', null), page: integer('page', 1)!, warning: null,
  };
  state.warning = invalid ? '链接参数无效，已使用安全默认值；请核对联赛、赛季和筛选条件。' : null;
  return state;
}
export function eventCenterHash(state: EventCenterState): string {
  const params = new URLSearchParams();
  if (state.view === 'league') {
    params.set('view', 'league');
    if (state.dataset === 'verified') params.set('dataset', state.dataset);
    if (state.competition && (state.dataset === 'verified' || state.competition !== 'premier-league')) params.set('competition', state.competition);
    if (state.seasonId !== null) params.set('competition_season_id', String(state.seasonId));
    if (state.tab !== (state.dataset === 'verified' ? 'fixtures' : 'standings')) params.set('tab', state.tab);
    if (state.scope !== 'all') params.set('scope', state.scope);
    if (state.status !== 'all') params.set('status', state.status);
    if (state.roundId !== null) params.set('round', state.roundId);
    if (state.teamId !== null) params.set('team_id', String(state.teamId));
    if (state.page !== 1) params.set('page', String(state.page));
  }
  const query = params.toString();
  return `#/events${query ? `?${query}` : ''}`;
}
export function useEventCenterState() {
  const [state, setState] = useState(readEventCenterState);
  const current = useRef(state); current.current = state;
  useEffect(() => {
    const restore = () => {
      if (window.location.hash.split('?')[0] !== '#/events') return;
      current.current = readEventCenterState(); setState(current.current);
    };
    window.addEventListener('hashchange', restore);
    return () => window.removeEventListener('hashchange', restore);
  }, []);
  const update = useCallback((patch: Partial<EventCenterState>, replace = false) => {
    if (window.location.hash.split('?')[0] !== '#/events') return;
    const next = { ...current.current, warning: null, ...patch };
    current.current = next;
    window.history[replace ? 'replaceState' : 'pushState'](window.history.state, '', eventCenterHash(next));
    setState(next);
  }, []);
  return [state, update] as const;
}
