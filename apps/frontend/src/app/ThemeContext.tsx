import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { DEFAULT_APPEARANCE_SETTINGS } from '../theme/defaults';
import { loadAppearanceSettings, saveAppearanceSettings } from '../theme/storage';
import type { AppearanceSettings, ThemeId } from '../theme/types';

export type Theme = ThemeId;

interface ThemeContextValue {
  appearance: AppearanceSettings;
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
  updateAppearance: (patch: Partial<AppearanceSettings>) => void;
  previewAppearance: (settings: AppearanceSettings) => void;
  commitAppearance: () => void;
  cancelPreview: () => void;
  resetAppearance: () => void;
  toggleTheme: () => void;
  isPreviewing: boolean;
}

function applyAppearance(settings: AppearanceSettings): void {
  const root = document.documentElement;
  root.dataset.theme = settings.theme;
  root.dataset.density = settings.density;
  root.dataset.motion = settings.reduceMotion ? 'off' : settings.motion;
  root.dataset.radius = settings.radius;
  root.dataset.cardStyle = settings.cardStyle;
  root.dataset.sidebarMode = settings.sidebarMode;
  root.dataset.financialColors = settings.financialColorMode;
  root.dataset.backgroundEffect = settings.backgroundEffect ? 'on' : 'off';
  root.dataset.numberFont = settings.numberFont;
  root.dataset.chartStyle = settings.chartStyle;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<AppearanceSettings>(() => loadAppearanceSettings());
  const savedAppearance = useRef(appearance);
  const [isPreviewing, setIsPreviewing] = useState(false);

  useLayoutEffect(() => {
    applyAppearance(appearance);
  }, [appearance]);

  useLayoutEffect(() => {
    saveAppearanceSettings(savedAppearance.current);
  }, []);

  const commit = useCallback((next: AppearanceSettings) => {
    savedAppearance.current = next;
    setAppearance(next);
    setIsPreviewing(false);
    saveAppearanceSettings(next);
  }, []);

  const setTheme = useCallback((theme: ThemeId) => {
    commit({ ...savedAppearance.current, theme });
  }, [commit]);

  const updateAppearance = useCallback((patch: Partial<AppearanceSettings>) => {
    commit({ ...savedAppearance.current, ...patch });
  }, [commit]);

  const previewAppearance = useCallback((settings: AppearanceSettings) => {
    setAppearance(settings);
    setIsPreviewing(true);
  }, []);

  const commitAppearance = useCallback(() => commit(appearance), [appearance, commit]);

  const cancelPreview = useCallback(() => {
    setAppearance(savedAppearance.current);
    setIsPreviewing(false);
  }, []);

  const resetAppearance = useCallback(() => {
    commit({ ...DEFAULT_APPEARANCE_SETTINGS });
  }, [commit]);

  const toggleTheme = useCallback(() => {
    commit({
      ...savedAppearance.current,
      theme: savedAppearance.current.theme === 'polar-lab' ? 'redline-quant' : 'polar-lab',
    });
  }, [commit]);

  const value = useMemo<ThemeContextValue>(() => ({
    appearance,
    theme: appearance.theme,
    setTheme,
    updateAppearance,
    previewAppearance,
    commitAppearance,
    cancelPreview,
    resetAppearance,
    toggleTheme,
    isPreviewing,
  }), [appearance, cancelPreview, commitAppearance, isPreviewing, previewAppearance, resetAppearance, setTheme, toggleTheme, updateAppearance]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme must be used within ThemeProvider');
  return value;
}
