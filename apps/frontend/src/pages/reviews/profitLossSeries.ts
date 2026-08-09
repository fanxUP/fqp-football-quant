import type { DailyReview } from '../../core/types';

export interface ProfitLossTrendSeries {
  id: string;
  name: string;
  data: Array<{ time: string; value: number }>;
}

type ProfitLossPoint = Pick<DailyReview, 'review_date' | 'real_profit_loss'>;

/** Builds daily and cumulative real-ticket P&L series from settled daily reviews. */
export function buildProfitLossSeries(points: ProfitLossPoint[]): ProfitLossTrendSeries[] {
  if (points.length === 0) return [];

  const ordered = [...points].sort((left, right) => left.review_date.localeCompare(right.review_date));
  let cumulative = 0;

  return [
    {
      id: 'daily-profit-loss',
      name: '日盈亏',
      data: ordered.map((point) => ({ time: point.review_date, value: point.real_profit_loss })),
    },
    {
      id: 'cumulative-profit-loss',
      name: '累计盈亏',
      data: ordered.map((point) => {
        cumulative += point.real_profit_loss;
        return { time: point.review_date, value: cumulative };
      }),
    },
  ];
}
