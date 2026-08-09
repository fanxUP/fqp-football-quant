import type { PlayTypeWinRate } from '../../core/types';
import { playTypeLabel } from '../../shared/constants';

export interface PlayTypeWinRateTrendSeries {
  id: string;
  name: string;
  data: Array<{ time: string; value: number }>;
}

function toPercent(value: number): number {
  return Math.round(value * 1000) / 10;
}

/** Converts daily play-type settlement data into Lightweight Charts series. */
export function buildPlayTypeWinRateSeries(
  points: PlayTypeWinRate[],
): PlayTypeWinRateTrendSeries[] {
  const grouped = new Map<string, PlayTypeWinRate[]>();

  for (const point of points) {
    if (!Number.isFinite(point.win_rate)) continue;
    const rows = grouped.get(point.play_type) ?? [];
    rows.push(point);
    grouped.set(point.play_type, rows);
  }

  return [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([playType, rows]) => ({
      id: playType,
      name: playTypeLabel(playType),
      data: [...rows]
        .sort((left, right) => left.settle_date.localeCompare(right.settle_date))
        .map((point) => ({ time: point.settle_date, value: toPercent(point.win_rate) })),
    }));
}
