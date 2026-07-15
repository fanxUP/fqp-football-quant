import { afterEach, describe, expect, it } from 'vitest';
import { applyChartTheme } from './chartTheme';

describe('applyChartTheme', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('style');
  });

  it('builds ECharts defaults from the current appearance tokens', () => {
    const root = document.documentElement;
    root.style.setProperty('--fqp-chart-1', '#2F6BFF');
    root.style.setProperty('--fqp-chart-2', '#0FA3B1');
    root.style.setProperty('--fqp-chart-text', '#172033');
    root.style.setProperty('--fqp-chart-text-muted', '#657089');
    root.style.setProperty('--fqp-chart-tooltip', '#FFFFFF');

    const option = applyChartTheme({ series: [] }) as Record<string, any>;

    expect(option.color.slice(0, 2)).toEqual(['#2F6BFF', '#0FA3B1']);
    expect(option.textStyle.color).toBe('#172033');
    expect(option.legend.textStyle.color).toBe('#657089');
    expect(option.tooltip.backgroundColor).toBe('#FFFFFF');
  });
});
