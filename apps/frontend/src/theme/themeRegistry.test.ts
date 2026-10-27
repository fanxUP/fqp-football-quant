import { describe, expect, it } from 'vitest';
import { AVAILABLE_THEME_IDS, THEME_REGISTRY } from './themeRegistry';

describe('theme registry', () => {
  it('exposes only black-red and polar', () => {
    expect(AVAILABLE_THEME_IDS).toEqual(['redline-quant', 'polar-lab']);
    expect(THEME_REGISTRY.map(({ id, name, mode }) => ({ id, name, mode }))).toEqual([
      { id: 'redline-quant', name: '黑红', mode: 'dark' },
      { id: 'polar-lab', name: '极地', mode: 'light' },
    ]);
  });
});
