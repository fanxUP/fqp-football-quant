import { getChartColors } from '../../theme/chartTokens';
import type { LightweightLineSeries } from '../timeseries/LightweightLineChart';

export const MODEL_ORDER = ['elo_rating', 'market_baseline', 'dixon_coles', 'maher_poisson'];

const MODEL_PATTERNS: Record<string, LightweightLineSeries['pattern']> = {
  elo_rating: 'solid',
  market_baseline: 'dashed',
  dixon_coles: 'dotted',
  maher_poisson: 'solid',
};

export function modelOrderIndex(modelName: string): number {
  const index = MODEL_ORDER.indexOf(modelName);
  return index === -1 ? MODEL_ORDER.length : index;
}

export function getModelLineVisual(
  modelName: string,
): Pick<LightweightLineSeries, 'color' | 'pattern'> {
  const colors = getChartColors();
  const modelColors: Record<string, string> = {
    elo_rating: colors.blue,
    market_baseline: colors.amber,
    dixon_coles: colors.green,
    maher_poisson: colors.primary,
  };

  return {
    color: modelColors[modelName] ?? colors.purple,
    pattern: MODEL_PATTERNS[modelName] ?? 'dashed',
  };
}
