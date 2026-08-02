import type { OddsMovementPoint } from '../../core/types';

export interface ScoreOddsOption {
  code: string;
  name: string;
  currentSp: number;
  previousSp: number | null;
  delta: number | null;
  homeGoals?: number;
  awayGoals?: number;
}

export interface ScoreOddsView {
  exactScores: ScoreOddsOption[];
  otherScores: ScoreOddsOption[];
  featuredScores: ScoreOddsOption[];
}

function toScoreOption(code: string, name: string, points: OddsMovementPoint[]): ScoreOddsOption | null {
  const ordered = points
    .filter((point) => Number.isFinite(point.sp_value) && Number.isFinite(Date.parse(point.snapshot_time)))
    .sort((left, right) => Date.parse(left.snapshot_time) - Date.parse(right.snapshot_time));
  const latest = ordered[ordered.length - 1];
  if (!latest) return null;
  const previous = ordered.length > 1 ? ordered[ordered.length - 2]?.sp_value ?? null : null;
  const score = /^(\d):(\d)$/.exec(code);

  return {
    code,
    name,
    currentSp: latest.sp_value,
    previousSp: previous,
    delta: previous === null ? null : Number((latest.sp_value - previous).toFixed(2)),
    ...(score ? { homeGoals: Number(score[1]), awayGoals: Number(score[2]) } : {}),
  };
}

export function buildScoreOddsView(points: OddsMovementPoint[]): ScoreOddsView {
  const grouped = new Map<string, OddsMovementPoint[]>();
  points.forEach((point) => {
    const existing = grouped.get(point.option_code) || [];
    existing.push(point);
    grouped.set(point.option_code, existing);
  });

  const options = Array.from(grouped, ([code, snapshots]) => (
    toScoreOption(code, snapshots[0]?.option_name || code, snapshots)
  )).filter((item): item is ScoreOddsOption => item !== null);
  const exactScores = options
    .filter((item) => item.homeGoals !== undefined && item.awayGoals !== undefined)
    .sort((left, right) => (left.homeGoals! - right.homeGoals!) || (left.awayGoals! - right.awayGoals!));
  const otherScores = options.filter((item) => item.homeGoals === undefined);

  return {
    exactScores,
    otherScores,
    featuredScores: [...exactScores].sort((left, right) => left.currentSp - right.currentSp).slice(0, 6),
  };
}
