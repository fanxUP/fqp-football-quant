import { afterEach, describe, expect, it } from 'vitest';
import { getChartColors } from './chartTokens';

describe('getChartColors', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('style');
  });

  it('reads the active theme chart tokens from the document root', () => {
    const root = document.documentElement;
    root.style.setProperty('--fqp-chart-1', '#C9A968');
    root.style.setProperty('--fqp-chart-text', '#F3F1EB');
    root.style.setProperty('--fqp-chart-grid', 'rgba(201, 169, 104, 0.2)');

    const colors = getChartColors();

    expect(colors.primary).toBe('#C9A968');
    expect(colors.text).toBe('#F3F1EB');
    expect(colors.gridLine).toBe('rgba(201, 169, 104, 0.2)');
  });

  it('returns safe defaults when a token is missing', () => {
    expect(getChartColors().primary).toBe('#FF2A3D');
  });
});
