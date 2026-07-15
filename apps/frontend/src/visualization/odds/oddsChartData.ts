import type { UTCTimestamp } from 'lightweight-charts';
import type { OddsMovementPoint } from '../../core/types';

export interface OddsLinePoint {
  time: UTCTimestamp;
  value: number;
}

export interface OddsLineSeriesData {
  id: string;
  name: string;
  data: OddsLinePoint[];
}

export interface OddsHeatmapData {
  times: string[];
  options: string[];
  cells: [number, number, number][];
  min: number;
  max: number;
}

export function isDenseOddsPlay(playType: string): boolean {
  return playType === 'bf' || playType === 'bqc';
}

export function buildOddsLineSeries(points: OddsMovementPoint[]): OddsLineSeriesData[] {
  const grouped = new Map<string, { name: string; values: Map<number, number> }>();

  points.forEach((point) => {
    const timestamp = Date.parse(point.snapshot_time);
    if (!Number.isFinite(timestamp) || !Number.isFinite(point.sp_value)) return;
    const option = grouped.get(point.option_code) || {
      name: point.option_name,
      values: new Map<number, number>(),
    };
    option.values.set(Math.floor(timestamp / 1000), point.sp_value);
    grouped.set(point.option_code, option);
  });

  return Array.from(grouped, ([id, option]) => ({
    id,
    name: option.name,
    data: Array.from(option.values, ([time, value]) => ({
      time: time as UTCTimestamp,
      value,
    })).sort((left, right) => Number(left.time) - Number(right.time)),
  }));
}

export function buildOddsHeatmap(points: OddsMovementPoint[]): OddsHeatmapData {
  const times = Array.from(new Set(points.map((point) => point.snapshot_time))).sort(
    (left, right) => Date.parse(left) - Date.parse(right),
  );
  const options = Array.from(new Set(points.map((point) => point.option_name)));
  const timeIndex = new Map(times.map((time, index) => [time, index]));
  const optionIndex = new Map(options.map((option, index) => [option, index]));
  const values = points.map((point) => point.sp_value).filter(Number.isFinite);
  const cells = points.flatMap<[number, number, number]>((point) => {
    const x = timeIndex.get(point.snapshot_time);
    const y = optionIndex.get(point.option_name);
    return x === undefined || y === undefined || !Number.isFinite(point.sp_value)
      ? []
      : [[x, y, point.sp_value]];
  });

  return {
    times,
    options,
    cells,
    min: values.length ? Math.min(...values) : 0,
    max: values.length ? Math.max(...values) : 0,
  };
}
