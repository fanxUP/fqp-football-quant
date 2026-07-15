/** Odds movement line chart — SP values + implied probability on dual Y-axes. */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import type { OddsPoint } from './chartTypes';
import { useTheme } from '../app/ThemeContext';

interface OddsMovementChartProps {
  data: OddsPoint[];
  title?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
}

export default function OddsMovementChart({
  data,
  title = '赔率走势',
  height = 320,
  loading,
  empty,
  emptyReason,
}: OddsMovementChartProps) {
  const { theme } = useTheme();
  const option = useMemo(() => {
    if (!data.length) return null;
    const times = data.map((d) => d.time);
    const sps = data.map((d) => d.spValue);
    const probs = data.map((d) => d.impliedProb);
    const anomalyTimes: string[] = [];
    const anomalySps: number[] = [];
    data.forEach((d, i) => {
      if (d.anomaly) { anomalyTimes.push(d.time); anomalySps.push(d.spValue); }
    });

    const manyPoints = data.length > 50;

    return applyChartTheme({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: { data: ['SP', '隐含概率'], top: 0 },
      grid: { left: '3%', right: '7%', bottom: '10%', top: '18%', containLabel: true },
      xAxis: {
        type: 'category',
        data: times,
        axisLabel: {
          rotate: 45,
          fontSize: 10,
          // Only show every Nth label for large datasets
          interval: manyPoints ? Math.floor(data.length / 20) : 0,
        },
      },
      yAxis: [
        {
          type: 'value',
          name: 'SP',
          axisLabel: { formatter: (v: number) => v.toFixed(2) },
          splitLine: { lineStyle: { color: 'var(--fqp-border-subtle)' } },
        },
        {
          type: 'value',
          name: '概率',
          min: 0,
          max: 100,
          axisLabel: { formatter: (v: number) => `${v}%` },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'SP',
          type: 'line',
          data: sps,
          smooth: true,
          // Hide individual point symbols when there are too many points
          symbol: manyPoints ? 'none' : 'circle',
          symbolSize: 5,
          lineStyle: { color: CHART_COLORS.blue, width: 2 },
          itemStyle: { color: CHART_COLORS.blue },
          areaStyle: { color: CHART_COLORS.areaAgent },
        },
        {
          name: '隐含概率',
          type: 'line',
          yAxisIndex: 1,
          data: probs.map((p) => p * 100),
          smooth: true,
          symbol: 'none',
          lineStyle: { color: CHART_COLORS.amber, width: 1.5, type: 'dashed' },
          itemStyle: { color: CHART_COLORS.amber },
        },
        ...(anomalyTimes.length > 0
          ? [{
              name: '异常',
              type: 'scatter' as const,
              data: anomalyTimes.map((t, i) => [t, anomalySps[i]]),
              symbol: 'pin',
              symbolSize: 20,
              itemStyle: { color: CHART_COLORS.primary },
              label: {
                show: true,
                formatter: '⚠',
                fontSize: 14,
                position: 'top' as const,
              },
            }]
          : []),
      ],
    } as EChartsOption);
  }, [data, theme]);

  return (
    <ChartCard
      title={title}
      option={option || {}}
      height={height}
      loading={loading}
      empty={empty || !data.length}
      emptyReason={emptyReason || '暂无赔率快照数据'}
    />
  );
}
