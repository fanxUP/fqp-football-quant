/** Typed fetch wrapper for all FQP backend APIs. */

import { ApiError } from './types';
import type { ModuleCategory, SidebarPanel } from '../panelRegistry';
import type {
  Team,
  FeatureSnapshot,
  Prediction,
  SimulationTicket,
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

export interface RuntimeModule {
  moduleCode: string;
  moduleName: string;
  category: ModuleCategory;
  required: boolean;
  safeDisable: boolean;
  status: 'active' | 'inactive' | 'coming_soon' | 'disabled';
  disabled: boolean;
  dependsOn: string[];
  panels: string[];
}

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

async function uploadRequest<T>(path: string, formData: FormData): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);

  try {
    const res = await fetch(path, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new ApiError(res.status, body || `HTTP ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error).name === 'AbortError') {
      throw new ApiError(0, 'OCR 处理超时，请稍后重试');
    }
    throw new ApiError(0, (e as Error).message || '上传失败');
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

  // Runtime registry
  ui: {
    modules: () =>
      request<{ modules: RuntimeModule[]; categories: ModuleCategory[]; total: number }>(
        '/api/v1/modules',
      ),
    panels: (params?: { disabledModules?: string[] }) => {
      const search = new URLSearchParams();
      for (const moduleCode of params?.disabledModules ?? []) {
        search.append('disabledModules', moduleCode);
      }
      const query = search.toString();
      return request<{ panels: SidebarPanel[]; total: number }>(
        `/api/v1/ui/panels${query ? `?${query}` : ''}`,
      );
    },
    setModuleStatus: (moduleCode: string, payload: { disabled: boolean }) =>
      request<{ module: RuntimeModule; disabledModules: string[] }>(
        `/api/v1/modules/${encodeURIComponent(moduleCode)}/status`,
        {
          method: 'PATCH',
          body: JSON.stringify(payload),
        },
      ),
  },

  // Teams
  teams: () => request<{ teams: Team[]; total: number }>('/api/teams'),

  // Matches
  matches: {
    today: () =>
      request<{ matches: import('./types').TodayMatch[]; total: number }>('/api/matches/today'),
    active: (params?: { limit?: number }) =>
      request<{ matches: import('./types').TodayMatch[]; total: number }>(
        `/api/matches/active${qs({ limit: params?.limit ?? 500 })}`,
      ),
    detail: (matchId: number) =>
      request<import('./types').MatchDetail>(`/api/matches/${matchId}/detail`),
  },

  // Events (tournament center)
  events: {
    catalog: (params?: { source?: 'official'; league_name?: string; start_date?: string; end_date?: string; limit?: number; offset?: number }) =>
      request<{ source: string; matches: import('./types').EventCatalogMatch[]; total: number }>(
        `/api/events/catalog${qs({ source: params?.source ?? 'official', league_name: params?.league_name, start_date: params?.start_date, end_date: params?.end_date, limit: params?.limit ?? 50, offset: params?.offset ?? 0 })}`,
      ),
    list: () =>
      request<{ events: import('./types').EventSummary[]; total: number }>('/api/events'),
    matches: (leagueName: string) =>
      request<{ league_name: string; matches: import('./types').EventMatch[]; total: number }>(
        `/api/events/${encodeURIComponent(leagueName)}`,
      ),
    allMatches: () =>
      request<{ matches: import('./types').EventMatch[]; total: number }>('/api/events/all/matches'),
  },

  // Official Sporttery source tracking. Third-party sources are not returned here.
  official: {
    oddsHistoryMatches: (params?: { search?: string; limit?: number }) =>
      request<{ matches: import('./types').OfficialOddsHistoryMatch[]; total: number }>(
        `/api/official/odds-history/matches${qs({ search: params?.search, limit: params?.limit ?? 200 })}`,
      ),
    collectionStatus: (params?: { business_date?: string; status?: string; limit?: number }) =>
      request<{ items: import('./types').OfficialCollectionStatus[]; total: number }>(
        `/api/official/collection-status${qs({
          business_date: params?.business_date,
          status: params?.status,
          limit: params?.limit ?? 100,
        })}`,
      ),
  },

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

  // Recommendation tickets
  tickets: (params?: { status?: string; limit?: number }) =>
    request<{ tickets: SimulationTicket[]; total: number }>(
      `/api/tickets${qs({ status: params?.status, limit: params?.limit ?? 50 })}`,
    ),

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
    pipeline: () => request<Record<string, unknown>>('/api/ops/pipeline'),
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

    performanceHistory: (params?: { window?: number; days?: number }) =>
      request<import('./types').ModelPerformanceHistory>(
        `/api/analysis/evaluation/history${qs({ window: params?.window, days: params?.days })}`,
      ),

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

  // Betting terminal
  bettingTerminal: {
    matches: (params?: { date?: string; league_name?: string; limit?: number }) =>
      request<{ matches: import('./types').BettingMatch[]; total: number }>(
        `/api/simulator/matches${qs({ date: params?.date, league_name: params?.league_name, limit: params?.limit ?? 50 })}`,
      ),

    calculate: (body: { items: import('./types').CalculateItem[]; pass_type: string; multiple: number }) =>
      request<import('./types').CalculationResult>('/api/simulator/calculate', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  },

  // Legacy endpoints kept for historical ticket detail and existing data screens.
  simulator: {
    matches: (params?: { date?: string; league_name?: string; limit?: number }) =>
      request<{ matches: import('./types').BettingMatch[]; total: number }>(
        `/api/simulator/matches${qs({ date: params?.date, league_name: params?.league_name, limit: params?.limit ?? 50 })}`,
      ),

    calculate: (body: { items: import('./types').CalculateItem[]; pass_type: string; multiple: number }) =>
      request<import('./types').CalculationResult>('/api/simulator/calculate', {
        method: 'POST',
        body: JSON.stringify(body),
      }),

    tickets: {
      list: (params?: { status?: string; limit?: number; offset?: number }) =>
        request<{ tickets: import('./types').SimulatorTicket[]; total: number }>(
          `/api/simulator/tickets${qs({ status: params?.status, limit: params?.limit ?? 20, offset: params?.offset ?? 0 })}`,
        ),

      get: (id: number) =>
        request<{ ticket: import('./types').SimulatorTicketDetail }>(`/api/simulator/tickets/${id}`),

      create: (body: { play_type: string; pass_type: string; multiple: number; items: import('./types').CalculateItem[]; notes?: string }) =>
        request<{ status: string; ticket: import('./types').SimulatorTicketDetail }>(
          '/api/simulator/tickets',
          { method: 'POST', body: JSON.stringify(body) },
        ),

      delete: (id: number) =>
        request<{ status: string; refunded?: number }>(`/api/simulator/tickets/${id}`, {
          method: 'DELETE',
        }),
    },

    bankroll: {
      summary: () =>
        request<import('./types').BankrollSummary>('/api/simulator/bankroll'),

      transactions: (limit?: number) =>
        request<{ transactions: import('./types').BankrollTransaction[]; total: number }>(
          `/api/simulator/bankroll/transactions${qs({ limit })}`,
        ),

      reset: () =>
        request<{ status: string; balance: number }>('/api/simulator/bankroll/reset', {
          method: 'POST',
          body: JSON.stringify({ confirm: true }),
        }),
    },
  },

  // Unified betting center
  betting: {
    tickets: (params?: { owner?: 'me' | 'agent'; date?: string; status?: string; limit?: number }) =>
      request<{
        tickets: import('./types').BettingTicket[];
        total: number;
        summary: import('./types').BettingTicketSummary;
      }>(
        `/api/v1/betting/tickets${qs({ owner: params?.owner, date: params?.date, status: params?.status, limit: params?.limit ?? 100 })}`,
      ),
    results: (params?: { limit?: number }) =>
      request<import('./types').BettingResults>(
        `/api/v1/betting/results${qs({ limit: params?.limit ?? 300 })}`,
      ),
    deleteTicket: (ticketId: number) =>
      request<{ status: 'ok' | 'error' }>(`/api/v1/real-tickets/${ticketId}`, {
        method: 'DELETE',
      }),
    createTicket: (body: {
      source: 'simulator' | 'real-user' | 'real-agent';
      play_type: string;
      pass_type: string;
      multiple: number;
      items: import('./types').CalculateItem[];
      notes?: string;
      ticket_no?: string;
      store_code?: string;
      ticket_image_url?: string;
      ocr_status?: string;
    }) =>
      request<{
        status: string;
        ticketUid: string;
        legacyId: number;
        owner: 'me' | 'agent';
        kind: 'real' | 'simulation';
        source: string;
        stake: number;
        maxPrize: number;
        betCount: number;
        route: string;
      }>('/api/v1/betting/tickets', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    ocrUpload: (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      return uploadRequest<import('./types').TicketOcrResult>('/api/tickets/ocr', formData);
    },
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

  // Competition (Agent vs User)
  competition: {
    currentRound: () =>
      request<import('./types').CompetitionRound>('/api/competition/rounds/current'),

    rounds: (params?: { limit?: number; status?: string }) =>
      request<{ rounds: import('./types').CompetitionRound[]; total: number }>(
        `/api/competition/rounds${qs({ limit: params?.limit, status: params?.status })}`,
      ),

    round: (id: number) =>
      request<import('./types').CompetitionRound>(`/api/competition/rounds/${id}`),

    trend: (roundId?: number) =>
      request<{ round_id: number; trend: import('./types').CompetitionTrendPoint[] }>(
        `/api/competition/trend${qs({ round_id: roundId })}`,
      ),

    summary: () =>
      request<import('./types').CompetitionSummary>('/api/competition/summary'),

    decisions: (limit = 14) =>
      request<{ decisions: import('./types').AgentDailyDecision[]; total: number }>(
        `/api/competition/decisions${qs({ limit })}`,
      ),

    currentTickets: () =>
      request<{
        round_id: number;
        round_label: string;
        tickets: import('./types').CompetitionTicket[];
        total: number;
        total_stake: number;
      }>('/api/competition/rounds/current/tickets'),
  },

  // Dashboard (data visualization)
  dashboard: {
    today: () =>
      request<import('./types').DashboardResponse<never>>('/api/dashboard/today'),

    roiDaily: (params?: { days?: number }) =>
      request<import('./types').DashboardResponse<import('./types').DashboardRoiDailyItem>>(
        `/api/dashboard/roi/daily${qs({ days: params?.days })}`,
      ),

    roiPeriod: (params?: { limit?: number }) =>
      request<import('./types').DashboardResponse<import('./types').DashboardRoiPeriodItem>>(
        `/api/dashboard/roi/period${qs({ limit: params?.limit })}`,
      ),

    recommendations: (params?: { match_id?: number; limit?: number; min_ev?: number }) =>
      request<import('./types').DashboardResponse<import('./types').DashboardRecommendationItem>>(
        `/api/dashboard/recommendations${qs({ match_id: params?.match_id, limit: params?.limit, min_ev: params?.min_ev })}`,
      ),

    oddsMovement: (params: { match_id: number; play_type?: string; option_code?: string }) =>
      request<import('./types').DashboardResponse<import('./types').DashboardOddsPoint>>(
        `/api/dashboard/odds/movement${qs({ match_id: params.match_id, play_type: params?.play_type, option_code: params?.option_code })}`,
      ),

    modelPerformance: (params?: { model_name?: string }) =>
      request<import('./types').DashboardResponse<import('./types').DashboardModelPerfItem>>(
        `/api/dashboard/model-performance${qs({ model_name: params?.model_name })}`,
      ),

    backtestEquity: (params: { run_id: number; model_name?: string }) =>
      request<import('./types').DashboardResponse<import('./types').DashboardBacktestEquityItem>>(
        `/api/dashboard/backtest/equity${qs({ run_id: params.run_id, model_name: params?.model_name })}`,
      ),

    ticketReview: (params?: { days?: number }) =>
      request<import('./types').DashboardResponse<import('./types').DashboardTicketReviewItem>>(
        `/api/dashboard/ticket-review${qs({ days: params?.days })}`,
      ),

    panels: () =>
      request<import('./types').DashboardResponse<import('./types').DashboardPanelConfig>>(
        '/api/dashboard/panels',
      ),
  },
};
