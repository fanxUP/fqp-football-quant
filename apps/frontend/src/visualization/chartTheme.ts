/** Red-black tech ECharts theme — shared defaults for all charts. */

import * as echarts from 'echarts';

// Palette from the FQP red-black tech design system
const PALETTE = ['#FF2A3D', '#3B82F6', '#F5A524', '#22C55E', '#8B5CF6', '#06B6D4'];

export const CHART_COLORS = {
  primary: '#FF2A3D',
  blue: '#3B82F6',
  amber: '#F5A524',
  green: '#22C55E',
  purple: '#8B5CF6',
  cyan: '#06B6D4',
  text: '#F5F5F7',
  textMuted: '#A1A1AA',
  gridLine: 'var(--fqp-hover-bg)',
  zeroRef: 'rgba(255,255,255,0.15)',
  areaAgent: 'rgba(59,130,246,0.12)',
  areaUser: 'rgba(245,165,36,0.12)',
  areaDown: 'rgba(255,42,61,0.08)',
  tooltipBg: 'rgba(15,15,25,0.94)',
  tooltipBorder: 'rgba(255,255,255,0.12)',
};

/** Apply FQP red-black theme defaults to any ECharts option. */
export function applyChartTheme(option: echarts.EChartsOption): echarts.EChartsOption {
  return {
    backgroundColor: 'transparent',
    color: PALETTE,
    textStyle: {
      color: CHART_COLORS.text,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Noto Sans SC', monospace",
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: CHART_COLORS.tooltipBg,
      borderColor: CHART_COLORS.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: CHART_COLORS.text, fontSize: 12 },
      axisPointer: {
        type: 'cross',
        crossStyle: { color: CHART_COLORS.gridLine },
        lineStyle: { color: CHART_COLORS.gridLine },
      },
    },
    legend: {
      textStyle: { color: CHART_COLORS.textMuted, fontSize: 12 },
      pageTextStyle: { color: CHART_COLORS.textMuted },
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
      axisLine: { lineStyle: { color: CHART_COLORS.gridLine } },
      axisLabel: { color: CHART_COLORS.textMuted, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: CHART_COLORS.textMuted, fontSize: 11 },
      splitLine: {
        lineStyle: {
          color: CHART_COLORS.gridLine,
          type: 'dashed',
        },
      },
    },
    ...option,
  };
}
