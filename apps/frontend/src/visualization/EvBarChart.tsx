/** Expected Value (EV) horizontal bar chart. */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import type { EvBarItem } from './chartTypes';

interface EvBarChartProps {
  data: EvBarItem[];
  title?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
}

export default function EvBarChart({
  data,
  title = 'EV 价值排行',
  height = 280,
  loading,
  empty,
  emptyReason,
}: EvBarChartProps) {
  const option = useMemo(() => {
    if (!data.length) return null;
    // Sort descending by EV
    const sorted = [...data].sort((a, b) => b.ev - a.ev);
    const labels = sorted.map((d) => d.label);
    const values = sorted.map((d) => d.ev);

    return applyChartTheme({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => v.toFixed(4),
      },
      grid: { left: '20%', right: '6%', bottom: '6%', top: '8%', containLabel: true },
      xAxis: {
        type: 'value',
        name: 'EV',
        axisLabel: { formatter: (v: number) => v.toFixed(2) },
        splitLine: { lineStyle: { color: 'var(--fqp-border-subtle)' } },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisLabel: { fontSize: 11 },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v) => ({
            value: v,
            itemStyle: {
              color: v >= 0 ? CHART_COLORS.green : CHART_COLORS.primary,
              borderRadius: [0, 4, 4, 0],
            },
          })),
          barWidth: '55%',
          markLine: {
            silent: true,
            data: [{ xAxis: 0 }],
            lineStyle: { color: CHART_COLORS.zeroRef, type: 'dashed' },
            label: { show: false },
          },
        },
      ],
    } as EChartsOption);
  }, [data]);

  return (
    <ChartCard
      title={title}
      option={option || {}}
      height={height}
      loading={loading}
      empty={empty || !data.length}
      emptyReason={emptyReason || '暂无 EV 数据'}
    />
  );
}
