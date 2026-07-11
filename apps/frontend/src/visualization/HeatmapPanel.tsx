/** Heatmap panel — winner calendar / round-by-round comparison. */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import type { HeatmapData } from './chartTypes';

interface HeatmapPanelProps {
  data: HeatmapData;
  title?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
}

export default function HeatmapPanel({
  data,
  title = '每日胜者',
  height = 300,
  loading,
  empty,
  emptyReason,
}: HeatmapPanelProps) {
  const option = useMemo(() => {
    if (!data.data.length || !data.rowLabels.length) return null;

    const seriesData: { value: number[] }[] = [];
    data.data.forEach((row, ri) => {
      row.forEach((val, ci) => {
        // val: 0 = draw, 1 = agent win, 2 = user win
        seriesData.push({ value: [ci, ri, val] });
      });
    });

    return applyChartTheme({
      tooltip: {
        trigger: 'item',
        formatter: (p: { value: number[] }) => {
          const [col, row, val] = p.value;
          const labels = ['平局', 'AI 获胜', '用户获胜'];
          return `${data.rowLabels[row]} · ${data.colLabels[col]}: ${labels[val] || '未知'}`;
        },
      },
      grid: { left: '12%', right: '4%', bottom: '15%', top: '6%', containLabel: true },
      xAxis: {
        type: 'category',
        data: data.colLabels,
        splitArea: { show: true },
        axisLabel: { fontSize: 10 },
      },
      yAxis: {
        type: 'category',
        data: data.rowLabels,
        splitArea: { show: true },
        axisLabel: { fontSize: 10 },
      },
      visualMap: {
        min: 0,
        max: 2,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        inRange: {
          color: ['#27272A', CHART_COLORS.blue, CHART_COLORS.amber],
        },
        text: ['平局', 'AI 胜', '用户胜'],
        textStyle: { color: CHART_COLORS.textMuted },
        dimension: 2,
      },
      series: [
        {
          type: 'heatmap',
          data: seriesData.map((d) => d.value),
          label: {
            show: true,
            formatter: (p: { value: number[] }) => {
              const val = p.value[2];
              return val === 0 ? '—' : val === 1 ? '🤖' : '👤';
            },
            fontSize: 14,
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' },
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
      empty={empty || !data.data.length}
      emptyReason={emptyReason || '暂无历史对战数据'}
    />
  );
}
