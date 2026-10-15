/** Lightweight hash-based router — no external dependency. */

import { useState, useEffect, type ReactNode } from 'react';

export interface Route {
  path: string; // e.g. "/matches/:id"
  render: (params: Record<string, string>) => ReactNode;
}

export interface RouterState {
  currentPath: string;
  params: Record<string, string>;
  navigate: (path: string) => void;
}

let _routes: Route[] = [];
const _listeners: Array<(state: RouterState) => void> = [];

export function matchRoute(path: string, routes: Route[]): { route: Route; params: Record<string, string> } | null {
  const segments = path.split('/').filter(Boolean);

  for (const route of routes) {
    const routeSegs = route.path.split('/').filter(Boolean);
    if (routeSegs.length !== segments.length) continue;

    const params: Record<string, string> = {};
    let match = true;
    for (let i = 0; i < routeSegs.length; i++) {
      if (routeSegs[i].startsWith(':')) {
        params[routeSegs[i].slice(1)] = segments[i];
      } else if (routeSegs[i] !== segments[i]) {
        match = false;
        break;
      }
    }
    if (match) {
      return { route, params };
    }
  }

  return null;
}

function parseHash(): { currentPath: string; params: Record<string, string> } {
  const raw = window.location.hash.replace(/^#/, '') || '/';
  const [pathPart] = raw.split('?');
  const matched = matchRoute(pathPart, _routes);
  if (matched) {
    return { currentPath: matched.route.path, params: matched.params };
  }
  return { currentPath: pathPart, params: {} };
}

export function navigate(path: string) {
  window.location.hash = '#' + path;
}

function notify() {
  const state: RouterState = { ...parseHash(), navigate };
  _listeners.forEach((fn) => fn(state));
}

export function createRouter(routes: Route[]) {
  _routes = routes;
}

export function useRouter(): RouterState {
  const [state, setState] = useState<RouterState>(() => ({
    ...parseHash(),
    navigate,
  }));

  useEffect(() => {
    const handler = () => {
      setState({ ...parseHash(), navigate });
    };
    _listeners.push(handler);
    window.addEventListener('hashchange', notify);
    return () => {
      window.removeEventListener('hashchange', notify);
      const idx = _listeners.indexOf(handler);
      if (idx >= 0) _listeners.splice(idx, 1);
    };
  }, []);

  return state;
}
