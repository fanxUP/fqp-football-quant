import { describe, expect, it } from 'vitest';
import { AVAILABLE_THEME_IDS, THEME_REGISTRY } from './themeRegistry';

describe('theme registry', () => {
  it('registers all twelve documented themes with unique identifiers', () => {
    expect(THEME_REGISTRY).toHaveLength(12);
    expect(new Set(THEME_REGISTRY.map((theme) => theme.id)).size).toBe(12);
  });

  it('marks the first delivery themes as available', () => {
    expect(AVAILABLE_THEME_IDS).toEqual([
      'redline-quant',
      'black-gold-terminal',
      'polar-lab',
      'deep-navy',
    ]);
  });

  it('provides preview colors and defaults for every theme', () => {
    for (const theme of THEME_REGISTRY) {
      expect(theme.preview.background).toMatch(/^#/);
      expect(theme.preview.primary).toMatch(/^#/);
      expect(theme.description.length).toBeGreaterThan(4);
      expect(theme.defaults.cardStyle).toBeTruthy();
    }
  });
});
