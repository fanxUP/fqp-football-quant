/** Daily ROI comparison bar chart (Agent vs User side-by-side). */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import type { RoiBarPoint } from './chartTypes';

interface RoiCompareBarChartProps {
  data: RoiBarPoint[];
  title?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
}

export default function RoiCompareBarChart({
  data,
  title = '每日 ROI 对比',
  height = 280,
  loading,
  empty,
  emptyReason,
}: RoiCompareBarChartProps) {
  const option = useMemo(() => {
    if (!data.length) return null;
    const dates = data.map((d) => d.date);
    const agent = data.map((d) => d.agentDailyRoi);
    const user = data.map((d) => d.userDailyRoi);

    return applyChartTheme({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v: number) => `${(v * 100).toFixed(2)}%`,
      },
      legend: { data: ['Agent 资金池', '我的票池'] },
      xAxis: { type: 'category', data: dates },
      yAxis: {
        type: 'value',
        name: '日 ROI',
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series: [
        {
          name: 'Agent 资金池',
          type: 'bar',
          data: agent,
          barWidth: '30%',
          barGap: '10%',
          itemStyle: {
            color: (p: { value: number }) =>
              p.value >= 0 ? CHART_COLORS.blue : CHART_COLORS.primary,
            borderRadius: [3, 3, 0, 0],
          },
        },
        {
          name: '我的票池',
          type: 'bar',
          data: user,
          barWidth: '30%',
          itemStyle: {
            color: (p: { value: number }) =>
              p.value >= 0 ? CHART_COLORS.amber : CHART_COLORS.primary,
            borderRadius: [3, 3, 0, 0],
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
      emptyReason={emptyReason || '暂无每日 ROI 数据'}
    />
  );
}
