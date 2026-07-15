import type { BacktestResult, DashboardBacktestEquityItem } from '../../core/types';
import { modelNameLabel } from '../../shared/constants';
import { modelOrderIndex } from '../model/modelVisuals';

export interface BacktestTrendSeriesData {
  id: string;
  name: string;
  data: Array<{ time: string; value: number }>;
}

export interface BacktestWindowTrends {
  dateCount: number;
  roiSeries: BacktestTrendSeriesData[];
  drawdownSeries: BacktestTrendSeriesData[];
  drawdownRange: readonly [number, number];
}

export interface BacktestMetricRow {
  modelName: string;
  label: string;
  value: number;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function toSeries(
  grouped: Map<string, Map<string, number>>,
): BacktestTrendSeriesData[] {
  return [...grouped.entries()]
    .sort(([left], [right]) => modelOrderIndex(left) - modelOrderIndex(right) || left.localeCompare(right))
    .map(([modelName, points]) => ({
      id: modelName,
      name: modelNameLabel(modelName),
      data: [...points.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([time, value]) => ({ time, value })),
    }))
    .filter((series) => series.data.length > 0);
}

export function buildBacktestWindowTrends(
  rows: DashboardBacktestEquityItem[],
): BacktestWindowTrends {
  const roiByModel = new Map<string, Map<string, number>>();
  const drawdownByModel = new Map<string, Map<string, number>>();
  const dates = new Set<string>();

  for (const row of rows) {
    const date = row.test_end_date;
    if (!date) continue;
    dates.add(date);

    if (row.roi != null && Number.isFinite(row.roi)) {
      const points = roiByModel.get(row.model_name) ?? new Map<string, number>();
      points.set(date, round(row.roi * 100));
      roiByModel.set(row.model_name, points);
    }
    if (row.max_drawdown_pct != null && Number.isFinite(row.max_drawdown_pct)) {
      const points = drawdownByModel.get(row.model_name) ?? new Map<string, number>();
      points.set(date, -round(Math.abs(row.max_drawdown_pct)));
      drawdownByModel.set(row.model_name, points);
    }
  }

  const drawdownSeries = toSeries(drawdownByModel);
  const minDrawdown = Math.min(0, ...drawdownSeries.flatMap((series) => series.data.map((point) => point.value)));
  const paddedMinimum = minDrawdown === 0 ? -1 : Math.floor(minDrawdown * 1.08);

  return {
    dateCount: dates.size,
    roiSeries: toSeries(roiByModel),
    drawdownSeries,
    drawdownRange: [paddedMinimum, 0],
  };
}

export function buildBacktestMetricRows(
  results: BacktestResult[],
  metric: 'roi' | 'drawdown',
): BacktestMetricRow[] {
  return results
    .flatMap((result) => {
      const rawValue = metric === 'roi' ? result.roi : result.max_drawdown_pct;
      if (rawValue == null || !Number.isFinite(rawValue)) return [];
      return [{
        modelName: result.model_name,
        label: modelNameLabel(result.model_name),
        value: round(metric === 'roi' ? rawValue * 100 : Math.abs(rawValue)),
      }];
    })
    .sort((left, right) => (
      metric === 'roi'
        ? right.value - left.value
        : left.value - right.value
    ) || modelOrderIndex(left.modelName) - modelOrderIndex(right.modelName));
}
