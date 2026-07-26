import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { useTheme } from '../../app/ThemeContext';
import type { OddsMovementPoint } from '../../core/types';
import ChartCard from '../../shared/components/ChartCard';
import { getChartColors } from '../../theme/chartTokens';
import { applyChartTheme } from '../chartTheme';
import { buildOddsHeatmap } from './oddsChartData';

interface OddsHeatmapCardProps {
  data: OddsMovementPoint[];
  playType: string;
  title: string;
  subtitle: string;
  emptyReason?: string;
  anomalyCount?: number;
}

function formatAxisTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(date);
}

export default function OddsHeatmapCard({
  data,
  title,
  subtitle,
  emptyReason,
  anomalyCount = 0,
}: OddsHeatmapCardProps) {
  const { theme } = useTheme();
  const heatmap = useMemo(() => buildOddsHeatmap(data), [data]);
  const height = Math.max(380, Math.min(720, heatmap.options.length * 18 + 150));
  const option = useMemo(() => {
    const colors = getChartColors();
    const showZoom = heatmap.times.length > 12;

    return applyChartTheme({
      tooltip: {
        trigger: 'item',
        formatter: (raw: unknown) => {
          const params = raw as { value?: [number, number, number] };
          const [x = 0, y = 0, value = 0] = params.value || [];
          return `${heatmap.options[y] || '-'}<br/>${formatAxisTime(heatmap.times[x] || '')}<br/>SP ${value.toFixed(2)}`;
        },
      },
      grid: { left: 76, right: 28, top: 12, bottom: showZoom ? 94 : 68, containLabel: true },
      xAxis: {
        type: 'category',
        data: heatmap.times,
        name: '采集时间',
        axisLabel: {
          hideOverlap: true,
          formatter: (value: string) => formatAxisTime(value),
        },
      },
      yAxis: {
        type: 'category',
        data: heatmap.options,
        name: '投注选项',
        axisLabel: { interval: 0, width: 66, overflow: 'truncate' },
      },
      visualMap: {
        min: heatmap.min,
        max: heatmap.max || heatmap.min + 1,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 4,
        precision: 2,
        text: ['高 SP', '低 SP'],
        inRange: { color: [colors.neutral, colors.blue, colors.cyan, colors.amber] },
      },
      dataZoom: showZoom ? [
        { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
        { type: 'slider', xAxisIndex: 0, height: 16, bottom: 36, showDetail: false },
      ] : [],
      series: [{
        name: 'SP',
        type: 'heatmap',
        data: heatmap.cells,
        progressive: 1200,
        itemStyle: { borderColor: colors.gridLine, borderWidth: 1 },
        emphasis: { itemStyle: { borderColor: colors.text, borderWidth: 1 } },
      }],
    } as EChartsOption) as Record<string, unknown>;
  }, [heatmap, theme]);

  const context = anomalyCount ? `${subtitle} · 检出 ${anomalyCount} 次异常波动` : subtitle;

  return (
    <ChartCard
      title={title}
      subtitle={`${context} · 颜色表示 SP 高低，鼠标悬停查看精确值`}
      option={option}
      empty={!heatmap.cells.length}
      emptyReason={emptyReason || '该玩法暂无官方赔率快照'}
      height={height}
    />
  );
}
