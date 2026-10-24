import { useCallback, useEffect, useRef, useState } from 'react';

export interface MatchCenterState {
  query: string;
  league: string;
  status: string;
  sort: 'asc' | 'desc';
  page: number;
  selectedId: number | null;
  warning: string | null;
}

export function readMatchCenterState(hash = window.location.hash): MatchCenterState {
  const params = new URLSearchParams(hash.split('?')[1] ?? '');
  let invalid = false;
  function singleValue(field: string) {
    const values = params.getAll(field);
    if (values.length > 1) { invalid = true; return null; }
    return values[0] ?? null;
  }
  function positiveInteger(field: string, fallback: number | null) {
    const raw = singleValue(field);
    if (raw === null) return fallback;
    if (!/^[1-9]\d*$/.test(raw) || !Number.isSafeInteger(Number(raw))) {
      invalid = true; return fallback;
    }
    return Number(raw);
  }
  const selectedId = positiveInteger('match_id', null);
  const page = positiveInteger('page', 1)!;
  const sort = singleValue('sort') ?? 'asc';
  if (sort !== 'asc' && sort !== 'desc') invalid = true;
  return {
    query: singleValue('q') ?? '', league: singleValue('league') ?? '', status: singleValue('status') ?? '',
    sort: sort === 'desc' ? 'desc' : 'asc', page, selectedId,
    warning: invalid ? '链接参数无效，已使用安全默认值；请核对筛选和比赛编号。' : null,
  };
}

export function matchCenterHash(state: MatchCenterState) {
  const params = new URLSearchParams();
  if (state.query) params.set('q', state.query);
  if (state.league) params.set('league', state.league);
  if (state.status) params.set('status', state.status);
  if (state.sort !== 'asc') params.set('sort', state.sort);
  if (state.page !== 1) params.set('page', String(state.page));
  if (state.selectedId !== null) params.set('match_id', String(state.selectedId));
  const query = params.toString();
  return `#/matches${query ? `?${query}` : ''}`;
}

export default function useMatchCenterState() {
  const [state, setState] = useState(readMatchCenterState);
  const current = useRef(state);
  current.current = state;
  useEffect(() => {
    const restore = () => {
      if (window.location.hash.split('?')[0] !== '#/matches') return;
      const next = readMatchCenterState(); current.current = next; setState(next);
    };
    window.addEventListener('hashchange', restore);
    return () => window.removeEventListener('hashchange', restore);
  }, []);
  const update = useCallback((patch: Partial<MatchCenterState>) => {
    if (window.location.hash.split('?')[0] !== '#/matches') return;
    const next = { ...current.current, warning: null, ...patch };
    current.current = next;
    // Keep the current history entry ready for Back from match detail, without
    // adding an entry for every search keystroke or background page correction.
    window.history.replaceState(window.history.state, '', matchCenterHash(next));
    setState(next);
  }, []);
  return [state, update] as const;
}
