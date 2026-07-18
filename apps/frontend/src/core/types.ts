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
  official_match_code: string | null;
  kickoff_time: string | null;
  match_num_str: string | null;
}

// ---- Matches & Events ----

export interface TodayMatch {
  match_id: number;
  league_name: string;
  home_team_name: string;
  away_team_name: string;
  kickoff_time: string;
  match_status: string;
  match_num_str: string;
  completeness: number | null;
  odds_count: number;
}

export interface EventSummary {
  league_name: string;
  match_count: number;
  first_match: string;
  last_match: string;
}

export interface EventMatch {
  match_id: number;
  home_team_name: string;
  away_team_name: string;
  kickoff_time: string;
  match_status: string;
  match_num_str: string;
  league_name?: string;
  ft_home_goals?: number | null;
  ft_away_goals?: number | null;
}

export interface EventCatalogMatch {
  source: 'official';
  source_row_id: number;
  source_match_code: string;
  competition_season_id: number | null;
  home_team_id: number | null;
  away_team_id: number | null;
  league_name: string;
  home_team_name: string;
  away_team_name: string;
  kickoff_time: string;
  match_status: string;
  ft_home_goals: number | null;
  ft_away_goals: number | null;
}

// ---- Official collection history ----

export interface OfficialCollectionStatus {
  id: number;
  business_date: string;
  crawl_type: string;
  source_name: string;
  status: 'ok' | 'partial' | 'blocked' | 'error' | string;
  source_url: string | null;
  source_artifact_path: string | null;
  source_artifact_hash: string | null;
  records_found: number;
  records_inserted: number;
  records_updated: number;
  error_message: string | null;
  updated_at: string;
}

export interface OfficialOddsHistoryMatch {
  id: number;
  official_match_code: string;
  league_name: string;
  home_team_name: string;
  away_team_name: string;
  kickoff_time: string;
  play_types: string[];
}

export interface OfficialOddsIndex {
  current: { count: number };
  history: { business_date: string; match_count: number }[];
}

export interface OddsMovementPoint {
  snapshot_id: number;
  snapshot_time: string;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: number;
  handicap: number | null;
  implied_probability: number | null;
  prev_sp_value: number | null;
}

export interface OddsCaptureStatus {
  status: 'running' | 'complete' | 'partial' | 'not_offered' | 'failed';
  capture_kind: 'opening' | 'periodic' | 'retry' | 'final';
  failure_reason: string | null;
}

export interface OddsMovementMatch {
  id: number;
  official_match_code: string;
  business_date: string;
  league_name: string;
  home_team_name: string;
  away_team_name: string;
  kickoff_time: string;
  capture_status: OddsCaptureStatus | null;
  series: OddsMovementPoint[];
  anomalies: DashboardOddsAnomaly[];
}

export interface OddsMovementsResponse {
  scope: 'current' | 'history';
  business_date: string | null;
  play_type: string;
  resolution: 'raw' | 'hour';
  matches: OddsMovementMatch[];
  total: number;
}

// ---- Match Detail (Events Center drawer) ----

export interface MatchDetailTeam {
  id: number | null;
  name_cn: string;
  name_en: string | null;
  short_name: string | null;
  country: string | null;
  logo_url: string;
}

export interface MatchDetailScores {
  ht_home: number | null;
  ht_away: number | null;
  ft_home: number | null;
  ft_away: number | null;
  spf_result: string | null;
  result_status: string | null;
}

export interface MatchDetailPrediction {
  model_name: string;
  play_type: string;
  option_code: string;
  model_probability: number | null;
  market_probability: number | null;
  fair_odds: number | null;
  ev: number | null;
  confidence: number | null;
  predict_time: string;
}

export interface MatchDetailLineupPlayer {
  player_id: number;
  is_starting: boolean;
  is_substitute: boolean;
  position: string | null;
  tactical_role: string | null;
  name_cn: string | null;
  name_en: string | null;
  primary_position: string | null;
}

export interface MatchDetailLineup {
  formation: string | null;
  strength_score: number | null;
  starting_11_value: number | null;
  key_player_count: number | null;
  lineup_type: string | null;
  players: MatchDetailLineupPlayer[];
}

export interface MatchDetailFeatureSnapshot {
  completeness_score: number | null;
  uncertainty_score: number | null;
  home_rest_days: number | null;
  away_rest_days: number | null;
  rest_days_diff: number | null;
  home_lineup_strength: number | null;
  away_lineup_strength: number | null;
  lineup_strength_diff: number | null;
  home_absence_impact: number | null;
  away_absence_impact: number | null;
  absence_impact_diff: number | null;
  home_motivation: number | null;
  away_motivation: number | null;
  motivation_diff: number | null;
  temperature: number | null;
  precipitation: number | null;
  wind_speed: number | null;
  weather_impact: number | null;
  travel_distance_km: number | null;
  travel_fatigue: number | null;
  stadium_id: number | null;
}

export interface MatchDetailH2HMatch {
  date: string;
  home: string;
  away: string;
  home_goals: number | null;
  away_goals: number | null;
  league: string;
}

export interface MatchDetailH2H {
  total_matches: number;
  home_wins: number;
  draws: number;
  away_wins: number;
  recent_matches: MatchDetailH2HMatch[];
}

export interface MatchDetailFormEntry {
  date: string;
  opponent: string;
  is_home: boolean;
  goals_for: number | null;
  goals_against: number | null;
  status: string | null;
  league: string;
}

export interface MatchDetailStandingEntry {
  rank: number;
  team_name: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_diff: number;
  points: number;
  round: number;
}

export interface MatchDetailInjury {
  team_id: number;
  status: string;
  injury_type: string | null;
  body_part: string | null;
  expected_return: string | null;
  impact_score: number | null;
  player_name_cn: string | null;
  player_name_en: string | null;
  position: string | null;
}

export interface MatchDetail {
  match: {
    id: number;
    league_name: string;
    home_team_name: string;
    away_team_name: string;
    kickoff_time: string;
    match_status: string;
    sale_status: string;
  };
  scores: MatchDetailScores | null;
  teams: {
    home: MatchDetailTeam;
    away: MatchDetailTeam;
  };
  predictions: {
    models: MatchDetailPrediction[];
    best_ev_model: string | null;
    best_ev_option: string | null;
  } | null;
  lineups: {
    home: MatchDetailLineup | null;
    away: MatchDetailLineup | null;
  };
  feature_snapshot: MatchDetailFeatureSnapshot | null;
  h2h: MatchDetailH2H;
  form: {
    home: MatchDetailFormEntry[];
    away: MatchDetailFormEntry[];
  };
  standings: MatchDetailStandingEntry[];
  injuries: MatchDetailInjury[];
}

// ---- Stage 4: Model Predictions ----

export interface Prediction {
  id: number;
  match_id: number;
  predict_time: string;
  model_name: string;
  play_type: string;
  option_code: string;
  raw_model_probability: number | null;
  model_probability: number | null;
  feature_adjusted: boolean;
  market_probability: number | null;
  fair_odds: number | null;
  ev: number | null;
  confidence: number | null;
  home_team: string;
  away_team: string;
}

// ---- Stage 4: Recommendation tickets ----

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

export interface TicketOcrResult {
  success: boolean;
  ticket_no?: string;
  pass_type?: string;
  multiple?: number;
  total_amount?: number;
  items: {
    match_code?: string;
    home_team?: string;
    away_team?: string;
    play_type?: string;
    option_code?: string;
    option_name?: string;
    sp_value?: number;
    handicap?: string;
  }[];
  raw_text?: string;
  ocr_engine?: string;
  confidence?: number;
  warnings?: string[];
  filename?: string;
  size_bytes?: number;
  ticket_image_url?: string;
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

export interface PlayTypeWinRate {
  settle_date: string;
  play_type: string;
  total: number;
  wins: number;
  win_rate: number;
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

// ---- Phase 10: Pool Lottery ----

export interface PoolMatchInfo {
  index: number;
  match_id: number | null;
  home_team: string;
  away_team: string;
  league: string;
  match_date: string;
  prob_home: number;
  prob_draw: number;
  prob_away: number;
  max_prob_option: string;
  max_prob: number;
  cold_gate_index: number;
  uncertainty: number;
  data_quality: number;
  classification: 'dan' | 'tuo' | 'defense' | 'normal';
  entropy: number;
}

export interface PoolAnalysis {
  period_id: string;
  matches: PoolMatchInfo[];
  classification: {
    dan: string[];
    tuo: string[];
    defense: string[];
  };
  full_combinations: {
    count: number;
    total_cost: number;
    combinations: {
      selections: string[];
      estimated_hit_prob: number;
      cold_gate_coverage: number;
    }[];
  };
  rx9: {
    selected_matches: string[];
    combinations_count: number;
    total_cost: number;
  };
  monte_carlo: {
    hit14_prob: number;
    hit13_prob: number;
    rx9_prob: number;
    simulations: number;
  };
  warnings: string[];
  generated_at: string;
}

// ---- Batch 5: Analysis ----

export interface EvalModelSummary {
  model_name: string;
  n: number;
  avg_brier: number;
  avg_logloss: number;
  avg_rps: number;
  avg_clv: number | null;
  sample_status: 'monitoring' | 'preliminary' | 'qualified';
  is_publishable: boolean;
}

export interface EvaluationSummary {
  status: string;
  models: EvalModelSummary[];
  overall: {
    total_evaluated: number;
    overall_brier: number;
    overall_logloss: number;
    publication_min_samples: number;
    publishable_models: number;
  };
}

export interface ModelPerformancePoint {
  date: string;
  play_type: string;
  model_name: string;
  hit_rate: number;
  sample_size: number;
}

export interface ModelPerformanceSample {
  play_type: string;
  model_name: string;
  total_samples: number;
  settled_dates: number;
  first_date: string;
  last_date: string;
}

export interface ModelPerformanceHistory {
  status: string;
  metric: 'rolling_hit_rate';
  window: number;
  days: number;
  points: ModelPerformancePoint[];
  samples: ModelPerformanceSample[];
}

export interface CalibrationBin {
  bin_center: number;
  pred_mean: number;
  actual_freq: number;
  count: number;
}

export interface CalibrationData {
  status: string;
  model_name: string;
  bins: CalibrationBin[];
  ece: number;
  mce: number;
  n_predictions: number;
}

export interface FeatureRanking {
  feature: string;
  label: string;
  importance: number;
  std?: number;
}

export interface FeatureImportanceData {
  status: string;
  method: string;
  rankings: FeatureRanking[];
  model_accuracy: number;
  n_features: number;
}

export interface FeatureModelInfo {
  status: string;
  n_samples?: number;
  n_features?: number;
  train_accuracy?: number;
  class_distribution?: Record<string, number>;
}

export interface ModelCompareItem {
  name: string;
  n_predictions: number;
  brier: number;
  log_loss: number;
  rps: number;
  clv: number | null;
  flb_score: number | null;
  hit_rate?: number;
  roi?: number;
  sharpe?: number;
  max_drawdown_pct?: number;
  profit_factor?: number;
  total_profit?: number;
}

export interface RadarDimension {
  key: string;
  label: string;
  invert?: boolean;
}

export interface ModelCompareData {
  status: string;
  models: ModelCompareItem[];
  total_models: number;
  radar_dimensions: RadarDimension[];
}

export interface ShapEntry {
  feature: string;
  label: string;
  shap_value: number;
  shap_abs: number;
  feature_value: number;
}

export interface ShapExplanation {
  status: string;
  match_id: number;
  home_team: string;
  away_team: string;
  predicted_probs: {
    home: number;
    draw: number;
    away: number;
  };
  base_values: number[];
  shap_values: ShapEntry[];
  n_features_used: number;
}

export interface ConditionSegment {
  league_name?: string;
  odds_range?: string;
  confidence_range?: string;
  model_name: string;
  n: number;
  avg_brier: number;
  avg_logloss?: number;
}

export interface ConditionPerformanceData {
  status: string;
  dimension: string;
  segments: ConditionSegment[];
}

export interface LiveRecommendation {
  prediction_id: number;
  match_id: number;
  play_type: string;
  play_type_name: string;
  option_code: string;
  option_name: string;
  model_probability: number;
  market_probability: number;
  fair_odds: number;
  ev: number;
  edge: number;
  confidence: number;
  predict_time: string;
  model_name: string;
  home_team: string;
  away_team: string;
  league: string;
  kickoff_time: string | null;
  match_status: string;
  match_num_str: string | null;
  ht_home_goals: number | null;
  ht_away_goals: number | null;
  ft_home_goals: number | null;
  ft_away_goals: number | null;
  et_home_goals: number | null;
  et_away_goals: number | null;
  pk_home_goals: number | null;
  pk_away_goals: number | null;
  spf_result: string | null;
  rqspf_result: string | null;
  total_goals_result: string | null;
  score_result: string | null;
  half_full_result: string | null;
}

export interface ModelPlayTypeRecommendation {
  rank: number;
  model_name: string;
  play_type: string;
  total: number;
  wins: number;
  hit_rate: number;
}

// ---- Settings (localStorage) ----

// ---- Betting terminal ----

export interface SimulatorOddsOption {
  option_code: string;
  option_name: string;
  sp_value: number;
}

export interface SimulatorOddsGroup {
  handicap?: number | null;
  is_single_allowed?: boolean;
  is_pass_allowed?: boolean;
  options: SimulatorOddsOption[];
}

export interface SimulatorMatchOdds {
  spf: SimulatorOddsGroup;
  rqspf: SimulatorOddsGroup;
  zjq: SimulatorOddsGroup;
  bf: SimulatorOddsGroup;
  bqc: SimulatorOddsGroup;
}

export interface SimulatorMatch {
  match_id: number;
  business_date: string;
  league_name: string;
  home_team_name: string;
  away_team_name: string;
  kickoff_time: string;
  match_status: string;
  match_num_str?: string;
  odds: SimulatorMatchOdds;
}

export interface BetSlipItem {
  match_id: number;
  home_team: string;
  away_team: string;
  league_name: string;
  kickoff_time: string;
  play_type: string;
  play_type_label: string;
  option_code: string;
  option_name: string;
  sp_value: number;
  handicap?: number | null;
  is_single_allowed?: boolean;
  is_pass_allowed?: boolean;
  is_dan: boolean;
  basis?: {
    source: 'manual' | 'ocr' | 'recommendation';
    modelProbability?: number;
    marketProbability?: number;
    edge?: number;
    ev?: number;
    confidence?: number;
    sentimentWeight?: number;
    summary?: string;
  };
}

export interface BetComboDetail {
  items: { match_id: number; option_code: string; sp_value: number }[];
  combo_sp: number;
  max_prize: number;
}

/** Subset of BetSlipItem sent to the betting calculation and ticket endpoints. */
export interface CalculateItem {
  match_id: number;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: number;
  handicap?: number | null;
  is_dan: boolean;
  is_single_allowed?: boolean;
  is_pass_allowed?: boolean;
}

export interface CalculationResult {
  pass_type: string;
  multiple: number;
  bet_count: number;
  total_cost: number;
  max_prize: number;
  match_count: number;
  selection_count?: number;
  combinations: BetComboDetail[];
  available_pass_types: string[];
}

export interface SimulatorTicket {
  id: number;
  play_type: string;
  pass_type: string;
  multiple: number;
  total_cost: number;
  bet_count: number;
  max_prize: number;
  match_count: number;
  status: string;
  notes: string;
  created_at: string;
  updated_at: string;
  item_count: number;
}

export interface SimulatorTicketItem {
  id: number;
  match_id: number;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: number;
  handicap?: number | null;
  is_dan: boolean;
  home_team_name: string;
  away_team_name: string;
  league_name: string;
  kickoff_time: string;
}

export interface SimulatorTicketDetail extends SimulatorTicket {
  items: SimulatorTicketItem[];
  settlement?: Settlement;
}

export type BettingOddsOption = SimulatorOddsOption;
export type BettingMatch = SimulatorMatch;
export type BettingTicketHistory = SimulatorTicket;
export type BettingTicketHistoryDetail = SimulatorTicketDetail;

export interface BankrollSummary {
  account_id: number;
  initial_balance: number;
  current_balance: number;
  total_staked: number;
  total_won: number;
  profit_loss: number;
  roi: number;
}

export interface BankrollTransaction {
  id: number;
  transaction_type: string;
  amount: number;
  balance_after: number;
  transaction_time: string;
  remark: string;
}

// ---- Unified betting center ----

export type BettingTicketOwner = 'me' | 'agent';
export type BettingTicketKind = 'simulation' | 'real';
export type BettingTicketSource = 'manual' | 'ocr' | 'agent_recommendation';

export interface BettingTicketItemSummary {
  matchId: number | null;
  matchCode: string;
  homeTeam: string;
  awayTeam: string;
  playType: string;
  optionCode: string;
  optionName: string;
  spValue: number | null;
  oddsSource?: 'official' | 'synthetic_model' | string;
}

export interface BettingTicket {
  ticketUid: string;
  ticketNumber: string;
  legacyId: number;
  owner: BettingTicketOwner;
  kind: BettingTicketKind;
  source: BettingTicketSource;
  status: string;
  date: string;
  createdAt: string | null;
  title: string;
  playType: string;
  passType: string;
  multiple: number;
  betCount: number | null;
  matchCount: number;
  stake: number;
  maxPrize: number | null;
  settledAmount: number | null;
  profitLoss: number | null;
  roi: number | null;
  settledAt?: string | null;
  isWon?: boolean;
  itemCount: number;
  route: string;
  confirmStatus?: string;
  linkedSimulationId?: number | null;
  expectedValue?: number;
  strategyPool?: string;
  riskLevel?: string;
  items?: BettingTicketItemSummary[];
}

export interface BettingTicketSummary {
  total: number;
  stake: number;
  settled: number;
  pending: number;
  profitLoss?: number;
}

export interface BettingResultBucket {
  ticketCount: number;
  stake: number;
  settledAmount: number;
  profitLoss: number;
  roi: number;
  settled: number;
  pending: number;
  hitCount: number;
}

export interface BettingResultTrendPoint {
  date: string;
  meDailyStake: number;
  meDailyProfitLoss: number;
  agentDailyStake: number;
  agentDailyProfitLoss: number;
  meCumulativeProfitLoss: number;
  agentCumulativeProfitLoss: number;
  meCumulativeRoi: number;
  agentCumulativeRoi: number;
}

export interface BettingResults {
  owners: {
    me: BettingResultBucket;
    agent: BettingResultBucket;
  };
  leader: 'me' | 'agent' | 'draw';
  bySource: Record<string, BettingResultBucket>;
  trend: BettingResultTrendPoint[];
  updatedAt: string | null;
}

// ---- Competition (Agent vs User) ----

export interface CompetitionSnapshot {
  id: number;
  round_id: number;
  snapshot_date: string;
  agent_daily_stake: number;
  agent_daily_prize: number;
  agent_daily_profit_loss: number;
  agent_daily_roi: number;
  agent_cumulative_stake: number;
  agent_cumulative_prize: number;
  agent_cumulative_roi: number;
  agent_budget_usage_rate: number;
  agent_ticket_count: number;
  user_daily_stake: number;
  user_daily_prize: number;
  user_daily_profit_loss: number;
  user_daily_roi: number;
  user_cumulative_stake: number;
  user_cumulative_prize: number;
  user_cumulative_roi: number;
  user_ticket_count: number;
  created_at: string;
}

export interface CompetitionRound {
  id: number;
  round_label: string;
  round_start: string;
  round_end: string;
  agent_total_stake: number;
  agent_total_prize: number;
  agent_profit_loss: number;
  agent_roi: number;
  user_total_stake: number;
  user_total_prize: number;
  user_profit_loss: number;
  user_roi: number;
  winner: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  snapshots?: CompetitionSnapshot[];
  trend?: CompetitionTrendPoint[];
  days_remaining?: number;
  total_days?: number;
}

export interface CompetitionTrendPoint {
  snapshot_date: string;
  agent_cumulative_roi: number;
  user_cumulative_roi: number;
  agent_cumulative_stake: number;
  agent_cumulative_prize: number;
  user_cumulative_stake: number;
  user_cumulative_prize: number;
}

export interface CompetitionSummary {
  total_rounds: number;
  completed_rounds: number;
  agent_wins: number;
  user_wins: number;
  draws: number;
  active_rounds: number;
  current_round: {
    id: number | null;
    round_label: string | null;
    status: string | null;
  };
}

export interface CompetitionTicketItem {
  item_id: number;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: number;
  model_probability: number;
  home_team: string;
  away_team: string;
  league: string;
  kickoff_time: string | null;
  match_code: string;
}

export interface CompetitionTicket {
  id: number;
  stake: number;
  ev: number;
  strategy_pool: string;
  risk_level: string;
  status: string;
  created_at: string;
  pass_type: string;
  ticket_type: string;
  items: CompetitionTicketItem[];
}

export interface AgentDailyDecision {
  decisionDate: string;
  status: 'purchased' | 'abstained' | 'failed';
  totalBudget: number;
  totalStake: number;
  unusedBudget: number;
  reason: string;
  updatedAt: string | null;
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

// ---- Dashboard (data visualization) ----

export interface DashboardTodayKpi {
  key: string;
  label: string;
  value: number;
  prefix?: string;
}

export interface DashboardTodayResponse {
  chart_type: string;
  title: string;
  empty: boolean;
  kpis: DashboardTodayKpi[];
  meta: { updated_at: string; source: string };
  extras: {
    current_round_label: string | null;
    current_round_id: number | null;
    business_date: string;
  };
}

export interface DashboardRoiDailyItem {
  snapshot_date: string;
  round_label: string;
  round_id: number;
  agent_daily_stake: number;
  agent_daily_prize: number;
  agent_daily_profit_loss: number;
  agent_daily_roi: number | null;
  agent_cumulative_roi: number;
  agent_ticket_count: number;
  user_daily_stake: number;
  user_daily_prize: number;
  user_daily_profit_loss: number;
  user_daily_roi: number | null;
  user_cumulative_roi: number;
  user_ticket_count: number;
  daily_winner: string;
}

export interface DashboardRoiPeriodItem {
  round_id: number;
  round_label: string;
  round_start: string;
  round_end: string;
  status: string;
  agent_total_stake: number;
  agent_total_prize: number;
  agent_profit_loss: number;
  agent_roi: number | null;
  user_total_stake: number;
  user_total_prize: number;
  user_profit_loss: number;
  user_roi: number | null;
  winner: string | null;
}

export interface DashboardRecommendationItem {
  prediction_id: number;
  business_date: string;
  match_id: number;
  official_match_code: string;
  league_name: string;
  home_team_name: string;
  away_team_name: string;
  kickoff_time: string;
  play_type: string;
  option_code: string;
  option_name: string;
  market_probability: number;
  model_probability: number;
  probability_edge: number | null;
  ev: number | null;
  fair_odds: number | null;
  confidence_score: number | null;
  risk_score: number | null;
  model_name: string;
  model_version: string;
}

export interface DashboardOddsPoint {
  snapshot_id: number;
  match_id: number;
  official_match_code: string;
  home_team_name: string;
  away_team_name: string;
  league_name: string;
  snapshot_time: string;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: number;
  handicap: number | null;
  implied_probability: number | null;
  minutes_before_stop: number | null;
  is_open: boolean;
  prev_sp_value: number | null;
}

export interface DashboardOddsAnomaly {
  time: string;
  option_name: string;
  sp_value: number;
  prev_sp_value: number;
  ratio: number;
  type: 'jump' | 'drop';
}

export interface DashboardModelPerfItem {
  model_version_id: number;
  model_name: string;
  version: string;
  model_type: string;
  sample_count: number;
  good_calibration_count: number;
  avg_brier_score: number | null;
  avg_log_loss: number | null;
  avg_ev: number | null;
  n_bets: number | null;
  n_wins: number | null;
  hit_rate: number | null;
  roi: number | null;
  total_profit: number | null;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  profit_factor: number | null;
}

export interface DashboardBacktestEquityItem {
  run_id: number;
  run_name: string;
  run_status: string;
  window_index: number;
  test_start_date: string;
  test_end_date: string;
  window_bets: number;
  model_name: string;
  n_bets: number;
  n_wins: number;
  hit_rate: number | null;
  roi: number | null;
  total_profit: number | null;
  max_drawdown: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  profit_factor: number | null;
}

export interface DashboardTicketReviewItem {
  settle_date: string;
  ticket_source: string;
  ticket_count: number;
  won_count: number;
  total_stake: number;
  total_prize: number;
  total_profit_loss: number;
  roi: number | null;
}

export interface DashboardPanelConfig {
  id: string;
  name: string;
  route: string;
  order: number;
}

export interface DashboardResponse<T> {
  code: number;
  data: {
    chart_type: string;
    title: string;
    empty: boolean;
    series?: T[];
    kpis?: DashboardTodayKpi[];
    anomalies?: DashboardOddsAnomaly[];
    panels?: DashboardPanelConfig[];
    meta: { updated_at: string; source: string };
    extras?: Record<string, unknown>;
  };
}
