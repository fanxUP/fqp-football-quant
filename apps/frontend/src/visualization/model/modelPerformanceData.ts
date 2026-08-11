import type { ModelPerformancePoint } from '../../core/types';
import { modelNameLabel } from '../../shared/constants';
import { modelOrderIndex } from './modelVisuals';

export interface ModelPerformanceSeriesData {
  id: string;
  name: string;
  data: Array<{ time: string; value: number }>;
  latestSampleSize: number;
  dateCount: number;
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
    .sort(([left], [right]) => modelOrderIndex(left) - modelOrderIndex(right) || left.localeCompare(right))
    .map(([modelName, modelPoints]) => ({
      id: modelName,
      name: modelNameLabel(modelName),
      data: modelPoints.map((point) => ({ time: point.date, value: percent(point.hit_rate) })),
      latestSampleSize: modelPoints[modelPoints.length - 1]?.sample_size ?? 0,
      dateCount: new Set(modelPoints.map((point) => point.date)).size,
    }));
}
