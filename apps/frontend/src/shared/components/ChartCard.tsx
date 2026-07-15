import { useEffect, useRef } from 'react';
import { BarChart, HeatmapChart, LineChart, PieChart, RadarChart, ScatterChart } from 'echarts/charts';
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  RadarComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { init, use, type ECharts } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useTheme } from '../../app/ThemeContext';
import { getChartColors } from '../../theme/chartTokens';
import ChartFrame from '../../visualization/core/ChartFrame';

use([
  BarChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  RadarComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

interface ChartCardProps {
  title: string;
  subtitle?: string;
  option: Record<string, unknown>;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
  error?: string | null;
  updatedAt?: string;
}

export default function ChartCard({
  title,
  subtitle,
  option,
  height = 300,
  loading = false,
  empty = false,
  emptyReason,
  error,
  updatedAt,
}: ChartCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ECharts | null>(null);
  const { theme } = useTheme();
  const canRender = !loading && !empty && !error;

  useEffect(() => {
    if (!canRender || !chartRef.current) return;

    const instance = init(chartRef.current, undefined, { renderer: 'canvas' });
    instanceRef.current = instance;
    const resize = () => instance.resize();
    const observer = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(resize);

    if (observer) observer.observe(chartRef.current);
    else window.addEventListener('resize', resize);

    return () => {
      observer?.disconnect();
      if (!observer) window.removeEventListener('resize', resize);
      instance.dispose();
      instanceRef.current = null;
    };
  }, [canRender]);

  useEffect(() => {
    const instance = instanceRef.current;
    if (!instance || !canRender) return;

    const textColor = getChartColors().text;
    instance.setOption({
      backgroundColor: 'transparent',
      textStyle: { color: textColor, fontSize: 14 },
      legend: { textStyle: { color: textColor, fontSize: 14 } },
      aria: { show: true, description: subtitle ? `${title}。${subtitle}` : title },
      ...option,
    }, {
      notMerge: false,
      lazyUpdate: true,
      replaceMerge: ['series'],
    });
  }, [canRender, option, subtitle, theme, title]);

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      updatedAt={updatedAt}
      loading={loading}
      empty={empty}
      emptyReason={emptyReason}
      error={error}
      height={height}
    >
      <div
        ref={chartRef}
        className="fqp-anim-chartReveal"
        role="img"
        aria-label={subtitle ? `${title}。${subtitle}` : title}
        style={{ width: '100%', height }}
      />
    </ChartFrame>
  );
}
