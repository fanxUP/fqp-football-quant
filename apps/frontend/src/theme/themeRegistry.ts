import type { ThemeDefinition, ThemeId } from './types';

export const DEFAULT_THEME: ThemeId = 'redline-quant';
export const THEME_REGISTRY: ThemeDefinition[] = [
  { id: 'redline-quant', name: '黑红', description: '深色背景与红色重点，适合专注研究', mode: 'dark' },
  { id: 'polar-lab', name: '极地', description: '冷白背景与冰蓝重点，适合日间办公', mode: 'light' },
];
export const AVAILABLE_THEME_IDS: ThemeId[] = THEME_REGISTRY.map(({ id }) => id);
