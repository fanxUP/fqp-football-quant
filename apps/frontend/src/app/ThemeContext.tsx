import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from 'react';
import { loadTheme, saveTheme } from '../theme/storage';
import type { ThemeId } from '../theme/types';

interface ThemeContextValue {
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function applyTheme(theme: ThemeId): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  for (const attribute of ['density', 'motion', 'radius', 'card-style', 'sidebar-mode', 'financial-colors', 'background-effect', 'number-font', 'chart-style']) {
    root.removeAttribute(`data-${attribute}`);
  }
  saveTheme(theme);
}

/** Apply the stored palette before charts can read CSS during their first render. */
export function initializeTheme(): void {
  applyTheme(loadTheme());
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, updateTheme] = useState<ThemeId>(() => loadTheme());

  useLayoutEffect(() => applyTheme(theme), [theme]);

  const setTheme = useCallback((next: ThemeId) => {
    // Chart consumers read CSS tokens while rendering, so publish the palette first.
    applyTheme(next);
    updateTheme(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'polar-lab' ? 'redline-quant' : 'polar-lab');
  }, [setTheme, theme]);

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [setTheme, theme, toggleTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme must be used within ThemeProvider');
  return value;
}
