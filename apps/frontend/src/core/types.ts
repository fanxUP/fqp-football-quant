/** Shared TypeScript types for FQP frontend. */

// ---- API error ----

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

// ---- Stage 3: Teams ----

export interface Team {
  id: number;
  team_code: string;
  team_name_cn: string;
  team_name_en: string;
  country: string;
  short_name: string;
  alias_count: number;
  profile_count: number;
}

// ---- Stage 3: Feature Snapshots ----

export interface FeatureSnapshot {
  id: number;
  match_id: number;
  snapshot_time: string;
  feature_version: string;
  home_team_id: number;
  away_team_id: number;
  data_completeness_score: number | null;
  uncertainty_score: number | null;
  home_rest_days: number;
  away_rest_days: number;
  rest_days_diff: number;
  home_team_name: string;
  away_team_name: string;
  league_name: string;
}

// ---- Stage 4: Model Predictions ----

export interface Prediction {
  id: number;
  match_id: number;
  predict_time: string;
  model_name: string;
  play_type: string;
  option_code: string;
  model_probability: number | null;
  market_probability: number | null;
  fair_odds: number | null;
  ev: number | null;
  confidence: number | null;
  home_team: string;
  away_team: string;
}

// ---- Stage 4: Simulation Tickets ----

export interface SimulationTicket {
  id: number;
  strategy_pool: string;
  pass_type: string;
  suggested_stake: number;
  estimated_return: number | null;
  expected_value: number | null;
  risk_level: string;
  status: string;
  created_at: string;
  item_count: number;
}

// ---- Stage 5: Real Tickets ----

export interface RealTicket {
  id: number;
  user_id: number;
  source_type: string;
  purchase_time: string;
  total_amount: number;
  pass_type: string;
  multiple: number;
  theoretical_max_prize: number | null;
  confirm_status: string;
  settlement_status: string;
  linked_simulation_id: number | null;
  ticket_image_url: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface RealTicketItem {
  id: number;
  real_ticket_id: number;
  match_id: number | null;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: number;
  amount: number | null;
  is_matched_to_model: boolean;
  model_deviation_note: string | null;
}

// ---- Stage 5: Settlements ----

export interface Settlement {
  id: number;
  ticket_source: string;
  ticket_id: number;
  settle_time: string;
  is_won: boolean;
  stake_amount: number;
  prize_amount: number;
  tax_amount: number;
  net_prize: number;
  profit_loss: number;
  roi: number;
  settlement_detail_json: unknown;
}

export interface SettlementSummary {
  date?: string;
  total_settled?: number;
  total_stake?: number;
  total_prize?: number;
  total_profit_loss?: number;
  avg_roi?: number;
  by_source?: Record<string, { count: number; stake: number; prize: number; pl: number }>;
  [key: string]: unknown;
}

// ---- Stage 5: Reviews ----

export interface DailyReview {
  id?: number;
  review_date: string;
  official_match_count: number;
  analyzable_match_count: number;
  recommended_match_count: number;
  simulation_ticket_count: number;
  real_ticket_count: number;
  suggested_stake: number;
  actual_stake: number;
  simulation_prize: number;
  real_prize: number;
  simulation_profit_loss: number;
  real_profit_loss: number;
  simulation_roi: number;
  real_roi: number;
  budget_usage_rate: number;
  max_single_ticket_loss: number;
  max_single_match_exposure: number;
  summary_text: string;
  next_day_adjustment: string;
  created_at?: string;
}

export interface WeeklyReview {
  id: number;
  week_start: string;
  week_end: string;
  summary_text: string;
  created_at: string;
  [key: string]: unknown;
}

export interface MonthlyReview {
  id: number;
  review_month: string;
  summary_text: string;
  created_at: string;
  [key: string]: unknown;
}

// ---- Stage 5: Error Analysis ----

export interface ErrorAnalysis {
  id: number;
  prediction_id: number;
  match_id: number;
  error_type: string;
  error_level: string;
  root_cause: string;
  model_probability: number;
  market_probability: number;
  actual_result: string;
  suggested_fix: string;
  created_at: string;
}

export interface ErrorSummary {
  errors?: { error_type: string; count: number; last_seen: string }[];
  total?: number;
  [key: string]: unknown;
}

// ---- Stage 11: Backtest ----

export interface BacktestRun {
  id: number;
  name: string;
  description: string | null;
  config: Record<string, unknown>;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface BacktestWindow {
  window_index: number;
  train_start_date: string | null;
  train_end_date: string | null;
  test_start_date: string;
  test_end_date: string;
  n_train_matches: number;
  n_test_matches: number;
  n_bets: number;
}

export interface BacktestResult {
  window_index: number | null;  // null = aggregate
  model_name: string;
  n_bets: number;
  n_wins: number;
  hit_rate: number | null;
  roi: number | null;
  total_profit: number;
  avg_odds: number | null;
  brier_score: number | null;
  log_loss: number | null;
  clv: number | null;
  max_drawdown: number;
  max_drawdown_pct: number;
  longest_losing_streak: number;
  sharpe_ratio: number | null;
  profit_factor: number | null;
  equity_curve: EquityPoint[] | null;
}

export interface EquityPoint {
  date: string;
  bankroll: number;
  drawdown_pct: number;
}

// ---- API response wrappers ----

export interface ListResponse<T> {
  [key: string]: T[] | number;
  total: number;
}

export interface StatusResponse {
  status: string;
  [key: string]: unknown;
}

// ---- Settings (localStorage) ----

export interface FqpSettings {
  dailyBudget: number;
  riskMode: 'conservative' | 'balanced' | 'aggressive';
  pinEnabled: boolean;
  pinCode: string;
  sidebarCollapsed: boolean;
  animationsEnabled: boolean;
  backupPath: string;
  disabledModules: string[];
}

export const DEFAULT_SETTINGS: FqpSettings = {
  dailyBudget: 500,
  riskMode: 'balanced',
  pinEnabled: false,
  pinCode: '',
  sidebarCollapsed: false,
  animationsEnabled: true,
  backupPath: '~/fqp-backups',
  disabledModules: [],
};
