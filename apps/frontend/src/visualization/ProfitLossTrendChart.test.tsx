import { describe, expect, it } from 'vitest';
import type { BettingResultTrendPoint } from '../core/types';
import { buildProfitLossTrendOption } from './ProfitLossTrendChart';

const points: BettingResultTrendPoint[] = [
  {
    date: '2026-07-04',
    meDailyStake: 10,
    meDailyProfitLoss: -10,
    agentDailyStake: 0,
    agentDailyProfitLoss: 0,
    meCumulativeProfitLoss: -10,
    agentCumulativeProfitLoss: 0,
    meCumulativeRoi: -1,
    agentCumulativeRoi: 0,
  },
  {
    date: '2026-07-05',
    meDailyStake: 0,
    meDailyProfitLoss: 0,
    agentDailyStake: 10,
    agentDailyProfitLoss: 25,
    meCumulativeProfitLoss: -10,
    agentCumulativeProfitLoss: 25,
    meCumulativeRoi: -1,
    agentCumulativeRoi: 2.5,
  },
];

describe('ProfitLossTrendChart', () => {
  it('uses calendar dates and symmetric amount bounds around zero', () => {
    const option = buildProfitLossTrendOption(points);
    const xAxis = option.xAxis as { data: string[] };
    const yAxis = option.yAxis as { min: number; max: number };

    expect(xAxis.data).toEqual(['2026-07-04', '2026-07-05']);
    expect(yAxis.min).toBe(-30);
    expect(yAxis.max).toBe(30);
  });

  it('plots both daily amounts and cumulative amount lines', () => {
    const option = buildProfitLossTrendOption(points);
    const series = option.series as Array<{ name: string; type: string; data: number[] }>;

    expect(series.map((item) => item.name)).toEqual([
      '我的当日盈亏',
      'Agent 当日盈亏',
      '我的累计盈亏',
      'Agent 累计盈亏',
    ]);
    expect(series[0].data).toEqual([-10, 0]);
    expect(series[1].data).toEqual([0, 25]);
    expect(series[2].data).toEqual([-10, -10]);
    expect(series[3].data).toEqual([0, 25]);
  });

  it('uses solid lines for both cumulative series and the zero reference', () => {
    const option = buildProfitLossTrendOption(points);
    const series = option.series as Array<{
      type: string;
      lineStyle?: { type?: string };
      markLine?: { lineStyle?: { type?: string } };
    }>;
    const cumulativeSeries = series.filter((item) => item.type === 'line');

    expect(cumulativeSeries.map((item) => item.lineStyle?.type)).toEqual(['solid', 'solid']);
    expect(cumulativeSeries[0].markLine?.lineStyle?.type).toBe('solid');
  });
});
