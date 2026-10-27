import { DEFAULT_THEME } from './themeRegistry';
import type { ThemeId } from './types';

export const THEME_STORAGE_KEY = 'fqp-theme';
const OLD_APPEARANCE_KEY = 'fqp.appearance.settings';

function normalizeTheme(value: unknown): ThemeId {
  return value === 'polar-lab' || value === 'light' ? 'polar-lab' : DEFAULT_THEME;
}

export function loadTheme(storage?: Storage): ThemeId {
  try {
    const target = storage ?? localStorage;
    const oldAppearance = target.getItem(OLD_APPEARANCE_KEY);
    if (oldAppearance) {
      try {
        const parsed: unknown = JSON.parse(oldAppearance);
        if (parsed && typeof parsed === 'object' && 'theme' in parsed) {
          return normalizeTheme(parsed.theme);
        }
      } catch {
        // A corrupt old record must not hide the valid shortcut preference.
      }
    }
    return normalizeTheme(target.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}

export function saveTheme(theme: ThemeId, storage?: Storage): void {
  try {
    const target = storage ?? localStorage;
    target.setItem(THEME_STORAGE_KEY, normalizeTheme(theme));
    target.removeItem(OLD_APPEARANCE_KEY);
  } catch {
    // Private browsing/storage restrictions must not prevent switching themes.
  }
}
