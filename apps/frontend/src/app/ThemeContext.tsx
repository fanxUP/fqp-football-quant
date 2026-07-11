import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

export type Theme = 'dark' | 'light' | 'matrix' | 'cyberpunk' | 'anime' | 'ink';

interface ThemeContextValue {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void; // quick toggle dark↔light
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'dark',
  setTheme: () => {},
  toggleTheme: () => {},
});

const STORAGE_KEY = 'fqp-theme';

const VALID_THEMES: Set<string> = new Set(['dark', 'light', 'matrix', 'cyberpunk', 'anime', 'ink']);

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && VALID_THEMES.has(stored)) return stored as Theme;
  } catch { /* ignore */ }
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, _setTheme] = useState<Theme>(getInitialTheme);

  const applyTheme = (t: Theme) => {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem(STORAGE_KEY, t); } catch { /* ignore */ }
  };

  useEffect(() => { applyTheme(theme); }, [theme]);

  // Listen for system preference changes when no explicit choice
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const handler = (e: MediaQueryListEvent) => {
      try {
        if (!localStorage.getItem(STORAGE_KEY)) {
          _setTheme(e.matches ? 'light' : 'dark');
        }
      } catch { /* ignore */ }
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const setTheme = (t: Theme) => _setTheme(t);

  // Quick toggle: cycles dark ↔ light, preserves other themes
  const toggleTheme = () => {
    _setTheme((t) => {
      if (t === 'dark') return 'light';
      if (t === 'light') return 'dark';
      // If on a custom theme, switch to dark
      return 'dark';
    });
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
