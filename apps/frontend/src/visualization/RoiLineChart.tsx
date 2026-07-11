/** Cumulative ROI dual-line chart (Agent vs User). */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from './chartTheme';
import type { RoiPoint } from './chartTypes';

interface RoiLineChartProps {
  data: RoiPoint[];
  title?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
  agentLabel?: string;
  userLabel?: string;
}

export default function RoiLineChart({
  data,
  title = '累计 ROI',
  height = 300,
  loading,
  empty,
  emptyReason,
  agentLabel = 'Agent 资金池',
  userLabel = '我的票池',
}: RoiLineChartProps) {
  const option = useMemo(() => {
    if (!data.length) return null;
    const dates = data.map((d) => d.date);
    const agent = data.map((d) => d.agentRoi);
    const user = data.map((d) => d.userRoi);

    return applyChartTheme({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: number) => `${(v * 100).toFixed(2)}%`,
      },
      legend: { data: [agentLabel, userLabel] },
      grid: { left: '3%', right: '6%', bottom: '10%', top: '14%', containLabel: true },
      xAxis: { type: 'category', data: dates },
      yAxis: {
        type: 'value',
        name: 'ROI',
        axisLabel: {
          formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
        },
      },
      series: [
        {
          name: agentLabel,
          type: 'line',
          data: agent,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: CHART_COLORS.blue, width: 2 },
          itemStyle: { color: CHART_COLORS.blue },
          areaStyle: { color: CHART_COLORS.areaAgent },
        },
        {
          name: userLabel,
          type: 'line',
          data: user,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: CHART_COLORS.amber, width: 2 },
          itemStyle: { color: CHART_COLORS.amber },
          areaStyle: { color: CHART_COLORS.areaUser },
        },
      ],
    } as EChartsOption);
  }, [data, agentLabel, userLabel]);

  return (
    <ChartCard
      title={title}
      option={option || {}}
      height={height}
      loading={loading}
      empty={empty || !data.length}
      emptyReason={emptyReason || '暂无 ROI 数据'}
    />
  );
}
