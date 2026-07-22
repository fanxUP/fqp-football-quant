export type ThemeId =
  | 'black-gold-terminal'
  | 'crimson-arena'
  | 'polar-lab'
  | 'deep-navy'
  | 'tactical-board'
  | 'quantum-forecast'
  | 'graphite-minimal'
  | 'global-match-center'
  | 'redline-quant'
  | 'neon-grid'
  | 'code-matrix'
  | 'anime-striker';

export type DensityMode = 'comfortable' | 'standard' | 'compact' | 'terminal';
export type MotionMode = 'off' | 'light' | 'standard' | 'immersive';
export type RadiusMode = 'square' | 'subtle' | 'soft';
export type CardStyle = 'flat' | 'bordered' | 'elevated' | 'glass' | 'glow';
export type SidebarMode = 'expanded' | 'compact' | 'icons' | 'auto';
export type FinancialColorMode = 'cn-finance' | 'global-finance' | 'semantic' | 'colorblind-safe';
export type NumberFont = 'default' | 'mono' | 'display';
export type ChartStyle = 'professional' | 'minimal' | 'glow';
export type ThemeCategory = 'professional' | 'football' | 'future' | 'personal';

export interface AppearanceSettings {
  theme: ThemeId;
  density: DensityMode;
  motion: MotionMode;
  radius: RadiusMode;
  cardStyle: CardStyle;
  sidebarMode: SidebarMode;
  financialColorMode: FinancialColorMode;
  backgroundEffect: boolean;
  reduceMotion: boolean;
  numberFont: NumberFont;
  chartStyle: ChartStyle;
}

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  description: string;
  category: ThemeCategory;
  mode: 'dark' | 'light';
  available: boolean;
  preview: {
    background: string;
    surface: string;
    primary: string;
    secondary: string;
  };
  defaults: Pick<AppearanceSettings, 'density' | 'motion' | 'radius' | 'cardStyle' | 'numberFont' | 'chartStyle'>;
}
