import type { ModelPerformancePoint } from '../../core/types';
import { modelNameLabel } from '../../shared/constants';

const MODEL_ORDER = ['elo_rating', 'market_baseline', 'dixon_coles', 'maher_poisson'];

export interface ModelPerformanceSeriesData {
  id: string;
  name: string;
  data: Array<{ time: string; value: number }>;
  latestSampleSize: number;
  dateCount: number;
}

export interface ModelPerformanceOverviewItem {
  rank: number;
  modelName: string;
  label: string;
  latestHitRate: number;
  latestSampleSize: number;
  changePercentagePoints: number | null;
  dateCount: number;
  insufficientHistory: boolean;
}

function modelIndex(modelName: string): number {
  const index = MODEL_ORDER.indexOf(modelName);
  return index === -1 ? MODEL_ORDER.length : index;
}

function percent(value: number): number {
  return Math.round(value * 1000) / 10;
}

function validPoints(points: ModelPerformancePoint[], playType: string): ModelPerformancePoint[] {
  return points
    .filter((point) => point.play_type === playType && Number.isFinite(point.hit_rate))
    .sort((left, right) => left.date.localeCompare(right.date));
}

export function buildModelPerformanceSeries(
  points: ModelPerformancePoint[],
  playType: string,
): ModelPerformanceSeriesData[] {
  const grouped = new Map<string, ModelPerformancePoint[]>();

  for (const point of validPoints(points, playType)) {
    const modelPoints = grouped.get(point.model_name) ?? [];
    modelPoints.push(point);
    grouped.set(point.model_name, modelPoints);
  }

  return [...grouped.entries()]
    .sort(([left], [right]) => modelIndex(left) - modelIndex(right) || left.localeCompare(right))
    .map(([modelName, modelPoints]) => ({
      id: modelName,
      name: modelNameLabel(modelName),
      data: modelPoints.map((point) => ({ time: point.date, value: percent(point.hit_rate) })),
      latestSampleSize: modelPoints[modelPoints.length - 1]?.sample_size ?? 0,
      dateCount: new Set(modelPoints.map((point) => point.date)).size,
    }));
}

export function buildModelPerformanceOverview(
  points: ModelPerformancePoint[],
): ModelPerformanceOverviewItem[] {
  const series = buildModelPerformanceSeries(points, 'all');

  return series
    .map((item) => {
      const latest = item.data[item.data.length - 1]?.value ?? 0;
      const previous = item.data[item.data.length - 2]?.value;
      return {
        rank: 0,
        modelName: item.id,
        label: item.name,
        latestHitRate: latest,
        latestSampleSize: item.latestSampleSize,
        changePercentagePoints: previous == null ? null : Math.round((latest - previous) * 10) / 10,
        dateCount: item.dateCount,
        insufficientHistory: item.dateCount < 8,
      };
    })
    .sort((left, right) => right.latestHitRate - left.latestHitRate || right.latestSampleSize - left.latestSampleSize)
    .map((item, index) => ({ ...item, rank: index + 1 }));
}
