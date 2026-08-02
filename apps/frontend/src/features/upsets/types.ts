export interface UpsetSummary {
  settled_match_count: number;
  upset_count: number;
  upset_rate: number;
  severe_count: number;
  extreme_count: number;
  favourite_failed_count: number;
  model_warned_count: number;
  user_involved_count: number;
  agent_involved_count: number;
  level_counts: Record<string, number>;
  play_counts: Record<string, number>;
}

export interface UpsetListItem {
  id: number;
  business_date: string;
  official_match_code: string;
  league_name: string;
  home_team_name: string;
  away_team_name: string;
  full_score: string;
  primary_play_type: string;
  primary_upset_type: string;
  actual_outcome: string;
  market_favourite_outcome: string | null;
  market_favourite_probability: number | null;
  actual_outcome_probability: number;
  surprise_bits: number;
  upset_level: string | null;
  favourite_failed: boolean;
  model_warned: boolean | null;
  user_bet_involved: boolean;
  agent_bet_involved: boolean;
  review_status: string;
  kickoff_time?: string | null;
  data_completeness?: number | null;
  confidence?: number | null;
}

export interface UpsetMarketSignal {
  id: number;
  play_type: string;
  handicap?: number | null;
  actual_outcome: string;
  actual_outcome_probability: number;
  market_favourite_probability: number | null;
  opening_snapshot_time: string;
  closing_snapshot_time: string;
  opening_odds_json: Record<string, number>;
  closing_odds_json: Record<string, number>;
  upset_level: string | null;
}

export interface UpsetTicketImpact {
  ticket_id: number;
  ticket_no?: string | null;
  stake_amount?: number | null;
  prize_amount?: number | null;
  profit_loss?: number | null;
  roi?: number | null;
  settlement_status?: string;
}

export interface UpsetReview {
  summary?: string | null;
  facts_json: Array<{ text?: string } | string>;
  prematch_signals_json: Array<{ text?: string } | string>;
  in_match_turning_points_json: Array<{ text?: string } | string>;
  inferences_json: Array<{ text?: string } | string>;
  hypotheses_json: Array<{ text?: string } | string>;
  randomness_json: Array<{ text?: string } | string>;
  model_postmortem_json: Record<string, unknown>;
  data_completeness?: number | null;
  confidence?: number | null;
  validation_status: string;
}

export interface UpsetDetail {
  event: UpsetListItem & {
    full_home_goals: number;
    full_away_goals: number;
    half_home_goals?: number | null;
    half_away_goals?: number | null;
    rule_key?: string;
  };
  market_signals: UpsetMarketSignal[];
  evidence: Array<Record<string, unknown>>;
  review: UpsetReview | null;
  user_tickets: UpsetTicketImpact[];
  agent_tickets: UpsetTicketImpact[];
}

export interface UpsetFilters {
  start_date?: string;
  end_date?: string;
  league_name?: string;
  level?: string;
  play_type?: string;
  user_involved?: boolean;
  agent_involved?: boolean;
  review_status?: string;
}

export interface UpsetLeagueOption {
  league_name: string;
  upset_count: number;
}

export interface UpsetReport {
  id: number;
  report_type: 'daily' | 'weekly' | 'monthly';
  period_start: string;
  period_end: string;
  report_version: string;
  report_markdown: string;
  pdf_available: boolean;
  validation_status: string;
  generated_at: string;
}
