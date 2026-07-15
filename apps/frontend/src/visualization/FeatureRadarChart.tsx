/** Multi-dimensional radar chart for match features / risk assessment. */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import type { RadarDimension } from './chartTypes';
import { useTheme } from '../app/ThemeContext';

interface FeatureRadarChartProps {
  data: RadarDimension[];
  title?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
  name?: string;
}

export default function FeatureRadarChart({
  data,
  title = '特征雷达',
  height = 300,
  loading,
  empty,
  emptyReason,
  name = '当前比赛',
}: FeatureRadarChartProps) {
  const { theme } = useTheme();
  const option = useMemo(() => {
    if (!data.length) return null;
    const maxVal = Math.max(...data.map((d) => d.maxValue ?? 1), 1);

    return applyChartTheme({
      tooltip: {
        trigger: 'item',
      },
      radar: {
        indicator: data.map((d) => ({ name: d.name, max: d.maxValue ?? maxVal })),
        radius: '65%',
        shape: 'polygon',
        splitNumber: 4,
        axisName: {
          color: CHART_COLORS.textMuted,
          fontSize: 11,
        },
        splitArea: {
          areaStyle: {
            color: ['transparent', CHART_COLORS.areaDown],
          },
        },
        axisLine: {
          lineStyle: { color: CHART_COLORS.gridLine },
        },
        splitLine: {
          lineStyle: { color: CHART_COLORS.gridLine },
        },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: data.map((d) => d.value),
              name,
              areaStyle: { color: CHART_COLORS.areaDown },
              lineStyle: { color: CHART_COLORS.primary, width: 2 },
              itemStyle: { color: CHART_COLORS.primary },
            },
          ],
        },
      ],
    } as EChartsOption);
  }, [data, name, theme]);

  return (
    <ChartCard
      title={title}
      option={option || {}}
      height={height}
      loading={loading}
      empty={empty || !data.length}
      emptyReason={emptyReason || '暂无特征数据'}
    />
  );
}
