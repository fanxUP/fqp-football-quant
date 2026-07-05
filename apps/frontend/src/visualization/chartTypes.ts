/** Unified data shapes for all visualization components. */

// ---- KPI ----
export interface KpiData {
  title: string;
  value: number | string;
  unit?: string;
  trend?: 'up' | 'down' | 'flat';
  trendValue?: number;
  status?: 'success' | 'danger' | 'warning' | 'neutral';
  icon?: string;
  loading?: boolean;
}

// ---- Risk ----
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export interface RiskBadgeData {
  level: RiskLevel;
  score?: number;
  showBar?: boolean;
  label?: string;
}

// ---- Series ----
export interface ChartSeries {
  name: string;
  data: number[];
  type?: 'line' | 'bar' | 'scatter';
  color?: string;
  yAxisIndex?: number;
  areaStyle?: boolean;
  smooth?: boolean;
}

// ---- Time-series point ----
export interface TimeSeriesPoint {
  time: string;       // ISO or display timestamp
  value: number;
  label?: string;
  anomaly?: boolean;
}

// ---- ROI ----
export interface RoiPoint {
  date: string;
  agentRoi: number | null;
  userRoi: number | null;
}

export interface RoiBarPoint {
  date: string;
  agentDailyRoi: number;
  userDailyRoi: number;
}

// ---- EV ----
export interface EvBarItem {
  label: string;
  ev: number;
  color?: string;
}

// ---- Radar ----
export interface RadarDimension {
  name: string;
  value: number;
  maxValue?: number;
}

// ---- Drawdown ----
export interface DrawdownPoint {
  date: string;
  drawdownPct: number;
}

// ---- Odds movement ----
export interface OddsPoint {
  time: string;
  spValue: number;
  impliedProb: number;
  anomaly?: boolean;
}

// ---- Heatmap ----
export interface HeatmapData {
  data: number[][];
  rowLabels: string[];
  colLabels: string[];
}

// ---- Chart wrapper props (shared with ChartCard) ----
export interface ChartWrapperProps {
  title: string;
  subtitle?: string;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
  error?: string | null;
  updatedAt?: string;
  children?: React.ReactNode;
}
