/** Red-black tech ECharts theme — shared defaults for all charts. */

import type { EChartsCoreOption } from 'echarts/core';
import { getChartColors, type ChartColors } from '../theme/chartTokens';

export const CHART_COLORS = Object.defineProperties(
  {},
  Object.fromEntries(
    (Object.keys(getChartColors()) as (keyof ChartColors)[]).map((key) => [
      key,
      { enumerable: true, get: () => getChartColors()[key] },
    ]),
  ),
) as ChartColors;

/** Apply FQP red-black theme defaults to any ECharts option. */
export function applyChartTheme(option: EChartsCoreOption): EChartsCoreOption {
  const colors = getChartColors();
  const palette = [colors.primary, colors.blue, colors.amber, colors.green, colors.purple, colors.cyan];
  return {
    backgroundColor: 'transparent',
    color: palette,
    textStyle: {
      color: colors.text,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Noto Sans SC', monospace",
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: colors.tooltipBg,
      borderColor: colors.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: colors.text, fontSize: 12 },
      axisPointer: {
        type: 'cross',
        crossStyle: { color: colors.gridLine },
        lineStyle: { color: colors.gridLine },
      },
    },
    legend: {
      textStyle: { color: colors.textMuted, fontSize: 12 },
      pageTextStyle: { color: colors.textMuted },
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '8%',
      top: '12%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      axisLine: { lineStyle: { color: colors.gridLine } },
      axisLabel: { color: colors.textMuted, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: colors.textMuted, fontSize: 11 },
      splitLine: {
        lineStyle: {
          color: colors.gridLine,
          type: 'dashed',
        },
      },
    },
    ...option,
  };
}
