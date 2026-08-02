import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { useTheme } from '../app/ThemeContext';
import type { BettingResultTrendPoint } from '../core/types';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';

interface ProfitLossTrendChartProps {
  data: BettingResultTrendPoint[];
  updatedAt?: string;
}

function symmetricAmountLimit(data: BettingResultTrendPoint[]): number {
  const peak = Math.max(
    0,
    ...data.flatMap((point) => [
      Math.abs(point.meDailyProfitLoss),
      Math.abs(point.agentDailyProfitLoss),
      Math.abs(point.meCumulativeProfitLoss),
      Math.abs(point.agentCumulativeProfitLoss),
    ]),
  );
  if (peak === 0) return 10;
  const magnitude = 10 ** Math.floor(Math.log10(peak));
  const step = magnitude / 2;
  return Math.ceil((peak * 1.1) / step) * step;
}

export function buildProfitLossTrendOption(
  data: BettingResultTrendPoint[],
): Record<string, unknown> {
  const amountLimit = symmetricAmountLimit(data);
  const zeroLine = {
    silent: true,
    symbol: 'none',
    label: {
      show: true,
      formatter: '0 元',
      position: 'insideEndTop',
      color: CHART_COLORS.textMuted,
    },
    lineStyle: { color: CHART_COLORS.zeroRef, width: 1.5, type: 'solid' },
    data: [{ yAxis: 0 }],
  };

  return applyChartTheme({
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => `¥${Number(value).toFixed(2)}`,
    },
    legend: {
      type: 'scroll',
      top: 0,
      left: 0,
      right: 0,
      data: ['我的当日盈亏', '智能代理当日盈亏', '我的累计盈亏', '智能代理累计盈亏'],
    },
    grid: { left: 18, right: 24, top: 56, bottom: 24, containLabel: true },
    xAxis: {
      type: 'category',
      name: '时间',
      nameLocation: 'end',
      boundaryGap: true,
      data: data.map((point) => point.date),
      axisLabel: {
        formatter: (value: string) => value.slice(5),
        hideOverlap: true,
      },
    },
    yAxis: {
      type: 'value',
      name: '金额（元）',
      min: -amountLimit,
      max: amountLimit,
      axisLabel: { formatter: (value: number) => `¥${value.toFixed(0)}` },
      splitNumber: 6,
    },
    series: [
      {
        name: '我的当日盈亏',
        type: 'bar',
        data: data.map((point) => point.meDailyProfitLoss),
        barMaxWidth: 14,
        itemStyle: { color: CHART_COLORS.blue, opacity: 0.34 },
      },
      {
        name: '智能代理当日盈亏',
        type: 'bar',
        data: data.map((point) => point.agentDailyProfitLoss),
        barMaxWidth: 14,
        itemStyle: { color: CHART_COLORS.amber, opacity: 0.34 },
      },
      {
        name: '我的累计盈亏',
        type: 'line',
        data: data.map((point) => point.meCumulativeProfitLoss),
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { color: CHART_COLORS.blue, width: 2.5, type: 'solid' },
        itemStyle: { color: CHART_COLORS.blue },
        markLine: zeroLine,
      },
      {
        name: '智能代理累计盈亏',
        type: 'line',
        data: data.map((point) => point.agentCumulativeProfitLoss),
        symbol: 'emptyCircle',
        symbolSize: 6,
        lineStyle: { color: CHART_COLORS.amber, width: 2.5, type: 'solid' },
        itemStyle: { color: CHART_COLORS.amber },
      },
    ],
  } as EChartsOption) as Record<string, unknown>;
}

export default function ProfitLossTrendChart({
  data,
  updatedAt,
}: ProfitLossTrendChartProps) {
  const { theme } = useTheme();
  const option = useMemo(() => buildProfitLossTrendOption(data), [data, theme]);

  return (
    <ChartCard
      title="每日与累计盈亏趋势"
      subtitle="从首张含投注明细的彩票开始；柱表示当日盈亏，线表示累计盈亏，0 元为金额中线"
      option={option}
      height={340}
      empty={data.length === 0}
      emptyReason="暂无含投注明细的彩票"
      updatedAt={updatedAt}
    />
  );
}
