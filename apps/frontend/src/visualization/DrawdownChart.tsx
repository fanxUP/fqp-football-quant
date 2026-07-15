/** Drawdown area chart — shows peak-to-trough decline over time. */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import type { DrawdownPoint } from './chartTypes';
import { useTheme } from '../app/ThemeContext';

interface DrawdownChartProps {
  data: DrawdownPoint[];
  title?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
}

export default function DrawdownChart({
  data,
  title = '最大回撤',
  height = 260,
  loading,
  empty,
  emptyReason,
}: DrawdownChartProps) {
  const { theme } = useTheme();
  const option = useMemo(() => {
    if (!data.length) return null;
    const dates = data.map((d) => d.date);
    const values = data.map((d) => d.drawdownPct);

    return applyChartTheme({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number) => `${(v * 100).toFixed(2)}%`,
      },
      grid: { left: '3%', right: '6%', bottom: '10%', top: '8%', containLabel: true },
      xAxis: { type: 'category', data: dates },
      yAxis: {
        type: 'value',
        name: '回撤',
        min: (ext: { min: number }) => Math.min(ext.min * 1.15, 0),
        max: 0,
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series: [
        {
          type: 'line',
          data: values,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: CHART_COLORS.primary, width: 1.5 },
          itemStyle: { color: CHART_COLORS.primary },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: CHART_COLORS.areaDown },
                { offset: 1, color: 'transparent' },
              ],
            },
          },
          markLine: {
            silent: true,
            data: [{ type: 'min', label: { formatter: '最大回撤: {c}%' } }],
            lineStyle: { color: CHART_COLORS.primary, type: 'dashed' },
          },
        },
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
      emptyReason={emptyReason || '暂无回撤数据'}
    />
  );
}
