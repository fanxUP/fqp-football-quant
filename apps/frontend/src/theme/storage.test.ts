import { beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_APPEARANCE_SETTINGS } from './defaults';
import { APPEARANCE_STORAGE_KEY, loadAppearanceSettings, saveAppearanceSettings } from './storage';

describe('appearance storage', () => {
  beforeEach(() => localStorage.clear());

  it('migrates the existing theme and local settings keys', () => {
    localStorage.setItem('fqp-theme', 'matrix');
    localStorage.setItem('fqp-settings', JSON.stringify({ animationsEnabled: false, sidebarCollapsed: true }));

    expect(loadAppearanceSettings()).toMatchObject({
      theme: 'code-matrix',
      motion: 'off',
      reduceMotion: true,
      sidebarMode: 'compact',
    });
  });

  it('ignores unknown values while preserving valid fields', () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({
      theme: 'unknown-theme',
      density: 'terminal',
      motion: 'hyperdrive',
      backgroundEffect: false,
    }));

    expect(loadAppearanceSettings()).toEqual({
      ...DEFAULT_APPEARANCE_SETTINGS,
      density: 'terminal',
      backgroundEffect: false,
    });
  });

  it('saves the complete normalized settings object', () => {
    const settings = { ...DEFAULT_APPEARANCE_SETTINGS, theme: 'deep-navy' as const };

    saveAppearanceSettings(settings);

    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? '{}')).toEqual(settings);
  });
});
