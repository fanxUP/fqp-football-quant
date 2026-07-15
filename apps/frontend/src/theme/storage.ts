import { DEFAULT_APPEARANCE_SETTINGS } from './defaults';
import type { AppearanceSettings, ThemeId } from './types';

export const APPEARANCE_STORAGE_KEY = 'fqp.appearance.settings';

const LEGACY_THEME_MAP: Record<string, ThemeId> = {
  dark: 'redline-quant',
  light: 'polar-lab',
  matrix: 'code-matrix',
  cyberpunk: 'neon-grid',
  anime: 'anime-striker',
  ink: 'graphite-minimal',
};

const allowed = {
  theme: new Set(['black-gold-terminal', 'crimson-arena', 'polar-lab', 'deep-navy', 'tactical-board', 'quantum-forecast', 'graphite-minimal', 'global-match-center', 'redline-quant', 'neon-grid', 'code-matrix', 'anime-striker']),
  density: new Set(['comfortable', 'standard', 'compact', 'terminal']),
  motion: new Set(['off', 'light', 'standard', 'immersive']),
  radius: new Set(['square', 'subtle', 'soft']),
  cardStyle: new Set(['flat', 'bordered', 'elevated', 'glass', 'glow']),
  sidebarMode: new Set(['expanded', 'compact', 'icons', 'auto']),
  financialColorMode: new Set(['cn-finance', 'global-finance', 'semantic', 'colorblind-safe']),
  numberFont: new Set(['default', 'mono', 'display']),
  chartStyle: new Set(['professional', 'minimal', 'glow']),
};

function parseJson(raw: string | null): Record<string, unknown> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function normalize(raw: Record<string, unknown>): AppearanceSettings {
  const result = { ...DEFAULT_APPEARANCE_SETTINGS };
  for (const key of Object.keys(allowed) as Array<keyof typeof allowed>) {
    const value = raw[key];
    if (typeof value === 'string' && allowed[key].has(value)) {
      (result as unknown as Record<string, unknown>)[key] = value;
    }
  }
  for (const key of ['backgroundEffect', 'reduceMotion'] as const) {
    if (typeof raw[key] === 'boolean') result[key] = raw[key];
  }
  return result;
}

export function loadAppearanceSettings(storage: Storage = localStorage): AppearanceSettings {
  const stored = parseJson(storage.getItem(APPEARANCE_STORAGE_KEY));
  if (Object.keys(stored).length > 0) return normalize(stored);

  const legacyTheme = storage.getItem('fqp-theme');
  const legacySettings = parseJson(storage.getItem('fqp-settings'));
  return normalize({
    theme: legacyTheme ? LEGACY_THEME_MAP[legacyTheme] : undefined,
    motion: legacySettings.animationsEnabled === false ? 'off' : undefined,
    reduceMotion: legacySettings.animationsEnabled === false ? true : undefined,
    sidebarMode: legacySettings.sidebarCollapsed === true ? 'compact' : undefined,
  });
}

export function saveAppearanceSettings(settings: AppearanceSettings, storage: Storage = localStorage): void {
  storage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(settings));
}
