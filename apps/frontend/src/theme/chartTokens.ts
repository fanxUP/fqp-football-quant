export interface ChartColors {
  primary: string;
  blue: string;
  amber: string;
  green: string;
  purple: string;
  cyan: string;
  text: string;
  textMuted: string;
  gridLine: string;
  zeroRef: string;
  areaAgent: string;
  areaUser: string;
  areaDown: string;
  tooltipBg: string;
  tooltipBorder: string;
  neutral: string;
}

const FALLBACKS: ChartColors = {
  primary: '#FF2A3D',
  blue: '#3B82F6',
  amber: '#F5A524',
  green: '#22C55E',
  purple: '#8B5CF6',
  cyan: '#06B6D4',
  text: '#F5F5F7',
  textMuted: '#A1A1AA',
  gridLine: 'rgba(255,255,255,0.1)',
  zeroRef: 'rgba(255,255,255,0.15)',
  areaAgent: 'rgba(59,130,246,0.12)',
  areaUser: 'rgba(245,165,36,0.12)',
  areaDown: 'rgba(255,42,61,0.08)',
  tooltipBg: 'rgba(15,15,25,0.94)',
  tooltipBorder: 'rgba(255,255,255,0.12)',
  neutral: '#27272A',
};

function token(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function getChartColors(): ChartColors {
  return {
    primary: token('--fqp-chart-1', FALLBACKS.primary),
    blue: token('--fqp-chart-2', FALLBACKS.blue),
    amber: token('--fqp-chart-3', FALLBACKS.amber),
    green: token('--fqp-chart-4', FALLBACKS.green),
    purple: token('--fqp-chart-5', FALLBACKS.purple),
    cyan: token('--fqp-chart-6', FALLBACKS.cyan),
    text: token('--fqp-chart-text', FALLBACKS.text),
    textMuted: token('--fqp-chart-text-muted', FALLBACKS.textMuted),
    gridLine: token('--fqp-chart-grid', FALLBACKS.gridLine),
    zeroRef: token('--fqp-chart-grid', FALLBACKS.zeroRef),
    areaAgent: token('--fqp-chart-area-1', FALLBACKS.areaAgent),
    areaUser: token('--fqp-chart-area-2', FALLBACKS.areaUser),
    areaDown: token('--fqp-chart-area-danger', FALLBACKS.areaDown),
    tooltipBg: token('--fqp-chart-tooltip', FALLBACKS.tooltipBg),
    tooltipBorder: token('--fqp-chart-tooltip-border', FALLBACKS.tooltipBorder),
    neutral: token('--fqp-chart-neutral', FALLBACKS.neutral),
  };
}
