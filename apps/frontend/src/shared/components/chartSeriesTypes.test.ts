import { describe, expect, it } from 'vitest';
import { chartSeriesTypes } from './chartSeriesTypes';

describe('chartSeriesTypes', () => {
  it('returns only the chart modules used by the current option', () => {
    expect(chartSeriesTypes({
      series: [
        { type: 'line', data: [1, 2] },
        { type: 'bar', data: [2, 3] },
        { type: 'line', data: [3, 4] },
      ],
    })).toEqual(['bar', 'line']);
  });

  it('falls back to line for options without an explicit series type', () => {
    expect(chartSeriesTypes({ series: [{ data: [1, 2] }] })).toEqual(['line']);
  });

  it('ignores unsupported series types instead of loading every chart module', () => {
    expect(chartSeriesTypes({ series: [{ type: 'custom', data: [] }] })).toEqual([]);
  });
});
