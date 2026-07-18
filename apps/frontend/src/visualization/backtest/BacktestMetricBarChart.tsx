import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { useTheme } from '../../app/ThemeContext';
import ChartCard from '../../shared/components/ChartCard';
import { applyChartTheme, CHART_COLORS } from '../chartTheme';
import type { BacktestMetricRow } from './backtestChartData';

interface BacktestMetricBarChartProps {
  rows: BacktestMetricRow[];
  metric: 'roi' | 'drawdown';
  title: string;
  loading?: boolean;
  height?: number;
}

const COMPACT_MODEL_LABELS: Record<string, string> = {
  dixon_coles: '迪克森-科尔斯',
  maher_poisson: '马赫泊松',
};

export default function BacktestMetricBarChart({
  rows,
  metric,
  title,
  loading = false,
  height = 260,
}: BacktestMetricBarChartProps) {
  const { theme } = useTheme();
  const option = useMemo(() => applyChartTheme({
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => `${value >= 0 && metric === 'roi' ? '+' : ''}${value.toFixed(2)}%`,
    },
    grid: {
      left: '4%', right: '4%', top: '5%', bottom: '4%',
      outerBoundsMode: 'same',
      outerBoundsContain: 'axisLabel',
    },
    xAxis: {
      type: 'value',
      min: metric === 'drawdown' ? 0 : undefined,
      splitNumber: 3,
      axisLabel: { formatter: (value: number) => `${value}%`, hideOverlap: true },
      splitLine: { lineStyle: { color: CHART_COLORS.gridLine, type: 'solid' } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((row) => COMPACT_MODEL_LABELS[row.modelName] ?? row.label),
      axisLabel: { width: 108, overflow: 'truncate' },
    },
    series: [{
      name: metric === 'roi' ? 'ROI' : '最大回撤',
      type: 'bar',
      data: rows.map((row) => row.value),
      barMaxWidth: 24,
      itemStyle: {
        color: metric === 'roi'
          ? (params: { value: number }) => params.value >= 0 ? CHART_COLORS.blue : CHART_COLORS.amber
          : CHART_COLORS.amber,
        borderRadius: [0, 3, 3, 0],
      },
      label: {
        show: true,
        position: 'insideRight',
        color: CHART_COLORS.tooltipBg,
        formatter: (params: { value: number }) => (
          `${params.value >= 0 && metric === 'roi' ? '+' : ''}${Number(params.value).toFixed(1)}%`
        ),
      },
    }],
  } as EChartsOption), [metric, rows, theme]);

  return (
    <ChartCard
      title={title}
      subtitle={metric === 'roi' ? '聚合结果 · 越高越好 · 单位 %' : '聚合结果 · 越低越好 · 单位 %'}
      option={option as Record<string, unknown>}
      height={height}
      loading={loading}
      empty={!loading && rows.length === 0}
      emptyReason="暂无可比较的聚合结果"
    />
  );
}
