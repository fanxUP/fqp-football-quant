/** Select the chart engine by odds density without loading both engines eagerly. */

import { lazy, Suspense } from 'react';
import type { OddsMovementPoint } from '../core/types';
import ChartFrame from './core/ChartFrame';
import { isDenseOddsPlay } from './odds/oddsChartData';

const OddsLineSeriesCard = lazy(() => import('./odds/OddsLineSeriesCard'));
const OddsHeatmapCard = lazy(() => import('./odds/OddsHeatmapCard'));
const ScoreOddsMatrixCard = lazy(() => import('./odds/ScoreOddsMatrixCard'));

interface OddsSeriesChartProps {
  data: OddsMovementPoint[];
  playType: string;
  title: string;
  subtitle: string;
  emptyReason?: string;
  anomalyCount?: number;
}

export default function OddsSeriesChart(props: OddsSeriesChartProps) {
  const Chart = props.playType === 'bf'
    ? ScoreOddsMatrixCard
    : isDenseOddsPlay(props.playType) ? OddsHeatmapCard : OddsLineSeriesCard;

  return (
    <Suspense
      fallback={(
        <ChartFrame title={props.title} subtitle={props.subtitle} loading>
          <div />
        </ChartFrame>
      )}
    >
      <Chart {...props} />
    </Suspense>
  );
}
