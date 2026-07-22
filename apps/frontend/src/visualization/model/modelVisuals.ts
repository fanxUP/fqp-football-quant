import { getChartColors } from '../../theme/chartTokens';

export const MODEL_ORDER = ['elo_rating', 'market_baseline', 'dixon_coles', 'maher_poisson'];

export function modelOrderIndex(modelName: string): number {
  const index = MODEL_ORDER.indexOf(modelName);
  return index === -1 ? MODEL_ORDER.length : index;
}

export function getModelLineVisual(
  modelName: string,
): { color: string } {
  const colors = getChartColors();
  const modelColors: Record<string, string> = {
    elo_rating: colors.blue,
    market_baseline: colors.amber,
    dixon_coles: colors.green,
    maher_poisson: colors.primary,
  };

  return {
    color: modelColors[modelName] ?? colors.purple,
  };
}
