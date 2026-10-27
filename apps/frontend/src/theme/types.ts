export type ThemeId = 'redline-quant' | 'polar-lab';

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  description: string;
  mode: 'dark' | 'light';
}
