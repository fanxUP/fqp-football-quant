/** Typed fetch wrapper for all FQP backend APIs. */

import { ApiError } from './types';
import type {
  Team,
  FeatureSnapshot,
  Prediction,
  SimulationTicket,
  RealTicket,
  RealTicketItem,
  Settlement,
  SettlementSummary,
  DailyReview,
  WeeklyReview,
  MonthlyReview,
  ErrorAnalysis,
  ErrorSummary,
  PlayTypeWinRate,
  BacktestRun,
  BacktestWindow,
  BacktestResult,
} from './types';

// ---- Base request ----

const TIMEOUT_MS = 15_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...init?.headers,
      },
    });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new ApiError(res.status, body || `HTTP ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error).name === 'AbortError') {
      throw new ApiError(0, '请求超时，请检查后端服务是否正常运行');
    }
    throw new ApiError(0, (e as Error).message || '网络请求失败');
  } finally {
    clearTimeout(timer);
  }
}

function qs(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? '?' + parts.join('&') : '';
}

// ---- Typed endpoints ----

export const api = {
  // Health
  health: () => request<{ status: string; service?: string }>('/health'),

  // Teams
  teams: () => request<{ teams: Team[]; total: number }>('/api/teams'),

  // Feature snapshots
  features: (params?: { match_id?: number; limit?: number }) =>
    request<{ snapshots: FeatureSnapshot[]; total: number }>(
      `/api/features/snapshots${qs({ match_id: params?.match_id, limit: params?.limit ?? 50 })}`,
    ),

  // Predictions
  predictions: (params?: { match_id?: number; limit?: number }) =>
    request<{ predictions: Prediction[]; total: number }>(
      `/api/predictions${qs({ match_id: params?.match_id, limit: params?.limit ?? 50 })}`,
    ),

  // Live recommendations
  liveRecommendations: (params?: { limit?: number; min_ev?: number; min_confidence?: number }) =>
    request<{ status: string; recommendations: import('./types').LiveRecommendation[]; total: number }>(
      `/api/recommendations/live${qs({ limit: params?.limit, min_ev: params?.min_ev, min_confidence: params?.min_confidence })}`,
    ),

  // Simulation tickets
  tickets: (params?: { status?: string; limit?: number }) =>
    request<{ tickets: SimulationTicket[]; total: number }>(
      `/api/tickets${qs({ status: params?.status, limit: params?.limit ?? 50 })}`,
    ),

  // Real tickets
  realTickets: {
    list: (params?: { status?: string; limit?: number }) =>
      request<{ tickets: RealTicket[]; total: number }>(
        `/api/real-tickets${qs({ status: params?.status, limit: params?.limit ?? 50 })}`,
      ),

    get: (id: number) =>
      request<{ ticket: RealTicket; items: RealTicketItem[] }>(`/api/real-tickets/${id}`),

    create: (body: { ticket: Record<string, unknown>; items: Record<string, unknown>[] }) =>
      request<{ status: string; ticket_id: number; item_count: number }>('/api/real-tickets', {
        method: 'POST',
        body: JSON.stringify(body),
      }),

    update: (id: number, body: Record<string, unknown>) =>
      request<{ status: string }>(`/api/real-tickets/${id}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),

    delete: (id: number) =>
      request<{ status: string }>(`/api/real-tickets/${id}`, { method: 'DELETE' }),
  },

  // Settlements
  settlements: {
    list: (params?: { date?: string; source?: string; limit?: number }) =>
      request<{ settlements: Settlement[]; total: number }>(
        `/api/settlements${qs({ date: params?.date, source: params?.source, limit: params?.limit ?? 50 })}`,
      ),

    summary: (date: string) =>
      request<SettlementSummary>(`/api/settlements/summary?date=${encodeURIComponent(date)}`),
  },

  // Reviews
  reviews: {
    daily: (limit?: number) =>
      request<{ reviews: DailyReview[]; total: number }>(
        `/api/reviews/daily${qs({ limit })}`,
      ),

    dailyByDate: (date: string) =>
      request<DailyReview>(`/api/reviews/daily/${encodeURIComponent(date)}`),

    playTypeWinRate: (days?: number) =>
      request<{ status: string; data: PlayTypeWinRate[] }>(
        `/api/reviews/play-type-winrate${qs({ days })}`,
      ),

    weekly: (limit?: number) =>
      request<{ reviews: WeeklyReview[]; total: number }>(
        `/api/reviews/weekly${qs({ limit })}`,
      ),

    monthly: (limit?: number) =>
      request<{ reviews: MonthlyReview[]; total: number }>(
        `/api/reviews/monthly${qs({ limit })}`,
      ),
  },

  // Ops health (Stage 8)
  ops: {
    health: () => request<Record<string, unknown>>('/api/ops/health'),
    metrics: (days?: number) =>
      request<Record<string, unknown>>(`/api/ops/metrics${qs({ days })}`),
    evidenceChain: (days?: number) =>
      request<Record<string, unknown>>(`/api/ops/evidence-chain${qs({ days })}`),
    contamination: (days?: number) =>
      request<Record<string, unknown>>(`/api/ops/contamination-audit${qs({ days })}`),
    backups: (days?: number) =>
      request<Record<string, unknown>>(`/api/ops/backups${qs({ days })}`),
  },

  // Error analysis
  errorAnalysis: {
    list: (params?: { match_id?: number; error_type?: string; limit?: number }) =>
      request<{ errors: ErrorAnalysis[]; total: number }>(
        `/api/error-analysis${qs({ match_id: params?.match_id, error_type: params?.error_type, limit: params?.limit ?? 50 })}`,
      ),

    summary: (days?: number) =>
      request<ErrorSummary>(`/api/error-analysis/summary${qs({ days })}`),
  },

  // Backtest (Stage 11)
  backtests: {
    list: (params?: { limit?: number; offset?: number }) =>
      request<{ runs: BacktestRun[]; total: number }>(
        `/api/backtests${qs({ limit: params?.limit ?? 20, offset: params?.offset ?? 0 })}`,
      ),

    get: (id: number) =>
      request<{ run: BacktestRun; windows: BacktestWindow[]; results: BacktestResult[] }>(
        `/api/backtests/${id}`,
      ),

    equityCurve: (runId: number, modelName?: string) =>
      request<{ run_id: number; model_name: string | null; curves: Record<string, unknown> }>(
        `/api/backtests/${runId}/equity-curve${qs({ model_name: modelName })}`,
      ),

    create: (body: Record<string, unknown>) =>
      request<{ status: string; run_id?: number; total_bets?: number; aggregate?: Record<string, unknown> }>(
        '/api/backtests',
        { method: 'POST', body: JSON.stringify(body) },
      ),
  },

  // Analysis (Batch 5)
  analysis: {
    evaluationSummary: () =>
      request<import('./types').EvaluationSummary>('/api/analysis/evaluation/summary'),

    calibration: (params?: { model_name?: string; n_bins?: number }) =>
      request<import('./types').CalibrationData>(
        `/api/analysis/evaluation/calibration${qs({ model_name: params?.model_name, n_bins: params?.n_bins })}`,
      ),

    conditionPerformance: (dimension: 'league' | 'odds_range' | 'confidence' = 'league') =>
      request<import('./types').ConditionPerformanceData>(
        `/api/analysis/evaluation/by-condition${qs({ dimension })}`,
      ),

    modelCompare: () =>
      request<import('./types').ModelCompareData>('/api/analysis/models/compare'),

    featureImportance: (params?: { method?: 'permutation' | 'gain' | 'both'; top_n?: number }) =>
      request<import('./types').FeatureImportanceData>(
        `/api/analysis/features/importance${qs({ method: params?.method, top_n: params?.top_n })}`,
      ),

    featureModelInfo: () =>
      request<import('./types').FeatureModelInfo>('/api/analysis/features/model-info'),

    shapExplanation: (matchId: number, topN?: number) =>
      request<import('./types').ShapExplanation>(
        `/api/analysis/explain/${matchId}${qs({ top_n: topN })}`,
      ),

    recommendations: (params?: { min_samples?: number; top_n?: number }) =>
      request<{ status: string; recommendations: import('./types').ModelPlayTypeRecommendation[] }>(
        `/api/analysis/recommendations${qs({ min_samples: params?.min_samples, top_n: params?.top_n })}`,
      ),
  },

  // Pool lottery (Phase 10)
  pool: {
    analyze: (params?: { budget?: number; strategy?: string }) =>
      request<Record<string, unknown>>(
        `/api/pool/analyze${qs({ budget: params?.budget, strategy: params?.strategy })}`,
      ),

    sample: () =>
      request<Record<string, unknown>>('/api/pool/sample'),
  },
};
