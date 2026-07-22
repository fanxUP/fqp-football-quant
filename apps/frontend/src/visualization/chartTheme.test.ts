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

  it('forces every chart line style to solid', () => {
    const values = new Float32Array([1, 2]);
    const option = applyChartTheme({
      series: [
        {
          type: 'line',
          lineStyle: { type: 'dashed' },
          markLine: { lineStyle: { type: 'dotted' } },
        },
        { type: 'line', data: values },
      ],
    }) as Record<string, any>;

    expect(option.yAxis.splitLine.lineStyle.type).toBe('solid');
    expect(option.series[0].lineStyle.type).toBe('solid');
    expect(option.series[0].markLine.lineStyle.type).toBe('solid');
    expect(option.series[1].data).toBe(values);
  });
});
