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
import { init, use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { chartSeriesTypes, type ChartSeriesType } from './chartSeriesTypes';

use([
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

const chartModuleLoaders: Record<ChartSeriesType, () => Promise<unknown>> = {
  bar: () => import('echarts/lib/chart/bar'),
  heatmap: () => import('echarts/lib/chart/heatmap'),
  line: () => import('echarts/lib/chart/line'),
  pie: () => import('echarts/lib/chart/pie'),
  radar: () => import('echarts/lib/chart/radar'),
  scatter: () => import('echarts/lib/chart/scatter'),
};

const loadedTypes = new Set<ChartSeriesType>();

export async function ensureChartRuntime(option: Record<string, unknown>) {
  const pendingTypes = chartSeriesTypes(option).filter((type) => !loadedTypes.has(type));
  await Promise.all(pendingTypes.map(async (type) => {
    await chartModuleLoaders[type]();
    loadedTypes.add(type);
  }));
  return { init };
}
