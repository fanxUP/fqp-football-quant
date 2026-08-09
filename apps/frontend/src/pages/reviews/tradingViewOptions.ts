import { getChartColors } from '../../theme/chartTokens';

type ChartOption = Record<string, unknown>;

function asObject(value: unknown): ChartOption {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as ChartOption
    : {};
}

function decorateAxis(axis: unknown, position: 'bottom' | 'left' | 'right') {
  const colors = getChartColors();
  const decorate = (value: unknown, axisPosition = position) => {
    const input = asObject(value);
    const splitLine = axisPosition === 'right'
      ? { show: true, lineStyle: { color: colors.gridLine, type: 'dashed', opacity: 0.72 } }
      : { show: false };
    return {
      ...input,
      axisLine: { show: false, ...asObject(input.axisLine) },
      axisTick: { show: false, ...asObject(input.axisTick) },
      axisLabel: {
        color: colors.textMuted,
        fontSize: 11,
        fontFamily: 'var(--fqp-font-mono)',
        ...asObject(input.axisLabel),
      },
      splitLine: { ...splitLine, ...asObject(input.splitLine) },
      position: input.position ?? axisPosition,
    };
  };

  return Array.isArray(axis)
    ? axis.map((value, index) => decorate(value, index === 0 ? 'left' : 'right'))
    : decorate(axis);
}

/**
 * Applies a compact financial-chart treatment without changing report data or
 * the global chart style used by odds and model-performance pages.
 */
export function asTradingViewChart(option: ChartOption): ChartOption {
  const colors = getChartColors();
  const { tooltip, grid, xAxis, yAxis, ...content } = option;

  return {
    ...content,
    animation: false,
    textStyle: { color: colors.text, fontFamily: 'var(--fqp-font-mono)' },
    tooltip: {
      trigger: 'axis',
      backgroundColor: colors.tooltipBg,
      borderColor: colors.tooltipBorder,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: colors.text, fontSize: 12 },
      axisPointer: {
        type: 'cross',
        lineStyle: { color: colors.gridLine, type: 'solid' },
        crossStyle: { color: colors.gridLine },
      },
      ...asObject(tooltip),
    },
    grid: {
      left: 12,
      right: 12,
      top: 28,
      bottom: 32,
      containLabel: true,
      ...asObject(grid),
    },
    xAxis: decorateAxis(xAxis, 'bottom'),
    yAxis: decorateAxis(yAxis, 'right'),
  };
}
