export type ChartSeriesType = 'bar' | 'heatmap' | 'line' | 'pie' | 'radar' | 'scatter';

const SUPPORTED_TYPES = new Set<ChartSeriesType>([
  'bar',
  'heatmap',
  'line',
  'pie',
  'radar',
  'scatter',
]);

export function chartSeriesTypes(option: Record<string, unknown>): ChartSeriesType[] {
  const rawSeries = option.series;
  const series = Array.isArray(rawSeries) ? rawSeries : rawSeries ? [rawSeries] : [];
  const types = new Set<ChartSeriesType>();

  for (const item of series) {
    if (!item || typeof item !== 'object') continue;
    const rawType = (item as { type?: unknown }).type;
    if (rawType == null) {
      types.add('line');
    } else if (typeof rawType === 'string' && SUPPORTED_TYPES.has(rawType as ChartSeriesType)) {
      types.add(rawType as ChartSeriesType);
    }
  }

  return [...types].sort();
}
