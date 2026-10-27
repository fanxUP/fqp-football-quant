import { beforeEach, describe, expect, it, vi } from 'vitest';
import { loadTheme, saveTheme, THEME_STORAGE_KEY } from './storage';

const OLD_APPEARANCE_KEY = 'fqp.appearance.settings';

describe('two-theme storage', () => {
  beforeEach(() => localStorage.clear());

  it.each(['black-gold-terminal', 'deep-navy', 'matrix', 'cyberpunk', 'anime', 'ink'])('falls back from removed theme %s', (theme) => {
    localStorage.setItem(OLD_APPEARANCE_KEY, JSON.stringify({ theme, density: 'terminal', sidebarMode: 'icons' }));
    expect(loadTheme()).toBe('redline-quant');
  });

  it('preserves polar while discarding the old interface preferences', () => {
    localStorage.setItem(OLD_APPEARANCE_KEY, JSON.stringify({ theme: 'polar-lab', density: 'terminal', motion: 'immersive' }));
    const theme = loadTheme();
    expect(theme).toBe('polar-lab');
    saveTheme(theme);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('polar-lab');
    expect(localStorage.getItem(OLD_APPEARANCE_KEY)).toBeNull();
  });

  it.each([['dark', 'redline-quant'], ['light', 'polar-lab'], ['polar-lab', 'polar-lab']])('migrates legacy shortcut %s', (stored, expected) => {
    localStorage.setItem(THEME_STORAGE_KEY, stored);
    expect(loadTheme()).toBe(expected);
  });

  it('does not change business preferences during migration', () => {
    const business = JSON.stringify({ dailyBudget: 800, disabledModules: ['test'], riskMode: 'balanced' });
    localStorage.setItem('fqp-settings', business);
    saveTheme(loadTheme());
    expect(localStorage.getItem('fqp-settings')).toBe(business);
  });

  it('recovers from malformed old settings', () => {
    localStorage.setItem(OLD_APPEARANCE_KEY, '{invalid');
    localStorage.setItem(THEME_STORAGE_KEY, 'polar-lab');
    expect(loadTheme()).toBe('polar-lab');
  });

  it('works when browser storage is blocked', () => {
    const storage = { getItem: vi.fn(() => { throw new Error('blocked'); }), setItem: vi.fn(() => { throw new Error('blocked'); }), removeItem: vi.fn() } as unknown as Storage;
    expect(loadTheme(storage)).toBe('redline-quant');
    expect(() => saveTheme('polar-lab', storage)).not.toThrow();
  });
});
