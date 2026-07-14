/** Multi-option official odds chart for one match and one play type. */

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { OddsMovementPoint } from '../core/types';
import ChartCard from '../shared/components/ChartCard';
import { applyChartTheme } from './chartTheme';

interface OddsSeriesChartProps {
  data: OddsMovementPoint[];
  title: string;
  subtitle: string;
  emptyReason?: string;
}

export default function OddsSeriesChart({
  data,
  title,
  subtitle,
  emptyReason,
}: OddsSeriesChartProps) {
  const option = useMemo(() => {
    const times = Array.from(new Set(data.map((point) => point.snapshot_time))).sort();
    const options = new Map<string, { name: string; points: Map<string, number> }>();
    data.forEach((point) => {
      const optionData = options.get(point.option_code) || {
        name: point.option_name,
        points: new Map<string, number>(),
      };
      optionData.points.set(point.snapshot_time, point.sp_value);
      options.set(point.option_code, optionData);
    });
    const optionList = Array.from(options.values());
    const selected = Object.fromEntries(
      optionList.map((item, index) => [item.name, optionList.length <= 10 || index < 8]),
    );

    return applyChartTheme({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', top: 0, selected },
      grid: { left: '3%', right: '4%', bottom: '12%', top: '20%', containLabel: true },
      xAxis: {
        type: 'category',
        data: times,
        axisLabel: {
          rotate: 35,
          formatter: (value: string) => value.slice(5, 16).replace('T', ' '),
        },
      },
      yAxis: {
        type: 'value',
        name: 'SP',
        scale: true,
        axisLabel: { formatter: (value: number) => value.toFixed(2) },
      },
      series: optionList.map((item) => ({
        name: item.name,
        type: 'line',
        data: times.map((time) => item.points.get(time) ?? null),
        connectNulls: true,
        showSymbol: times.length <= 12,
        symbolSize: 5,
        smooth: false,
        lineStyle: { width: 2 },
      })),
    } as EChartsOption);
  }, [data]);

  return (
    <ChartCard
      title={title}
      subtitle={subtitle}
      option={option as Record<string, unknown>}
      empty={!data.length}
      emptyReason={emptyReason || '该玩法暂无官方赔率快照'}
      height={300}
    />
  );
}
