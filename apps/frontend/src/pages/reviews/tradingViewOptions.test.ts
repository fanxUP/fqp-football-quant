import { describe, expect, it } from 'vitest';
import { asTradingViewChart } from './tradingViewOptions';

describe('asTradingViewChart', () => {
  it('keeps report data while applying financial-chart axis and tooltip defaults', () => {
    const option = asTradingViewChart({
      xAxis: { type: 'category', data: ['07-01', '07-02'] },
      yAxis: { type: 'value', name: '盈亏' },
      series: [{ type: 'line', data: [12, -8] }],
    });

    expect(option.animation).toBe(false);
    expect(option.tooltip).toEqual(expect.objectContaining({ trigger: 'axis' }));
    expect(option.xAxis).toEqual(expect.objectContaining({ axisLine: expect.objectContaining({ show: false }) }));
    expect(option.yAxis).toEqual(expect.objectContaining({ position: 'right', name: '盈亏' }));
    expect(option.series).toEqual([{ type: 'line', data: [12, -8] }]);
  });
});
