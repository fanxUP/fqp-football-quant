import { describe, expect, it } from 'vitest';
import { AVAILABLE_THEME_IDS, THEME_REGISTRY } from './themeRegistry';

describe('theme registry', () => {
  it('registers all twelve documented themes with unique identifiers', () => {
    expect(THEME_REGISTRY).toHaveLength(12);
    expect(new Set(THEME_REGISTRY.map((theme) => theme.id)).size).toBe(12);
  });

  it('marks all documented themes as available in the completed visual system', () => {
    expect(AVAILABLE_THEME_IDS).toEqual(THEME_REGISTRY.map((theme) => theme.id));
    expect(THEME_REGISTRY.every((theme) => theme.available)).toBe(true);
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
