import { createContext, useContext, type ReactNode } from 'react';
import { api } from '../../core/apiClient';
import type { DashboardTodayKpi } from '../../core/types';
import useReadOnlyResource from './useReadOnlyResource';

export interface TodaySummary {
  kpis: DashboardTodayKpi[];
  businessDate: string;
  roundLabel: string | null;
  source: string;
  responseTime: string | null;
}
export interface PipelineSummary { running: number; alerts: number }
export function pipelineSummary(value: Record<string, unknown>): PipelineSummary {
  if (!Array.isArray(value.jobs) || !Array.isArray(value.sources)) throw new Error('任务状态数据格式异常');
  return {
    running: value.jobs.filter(row => row.status === 'running').length,
    alerts: [...value.jobs, ...value.sources].filter(row => ['failed', 'error', 'degraded', 'stale', 'unavailable'].includes(row.status)).length,
  };
}
async function fetchToday(): Promise<TodaySummary> {
  const value = await api.dashboard.today();
  const data = value.data;
  if (value.code !== undefined && value.code !== 0) throw new Error('总览接口返回异常');
  if (!data || data.empty || !Array.isArray(data.kpis) || data.kpis.some(row => !row.key || !Number.isFinite(row.value))) {
    throw new Error('总览数据缺失或格式异常');
  }
  return { kpis: data.kpis, businessDate: String(data.extras?.business_date ?? ''), roundLabel: typeof data.extras?.current_round_label === 'string' ? data.extras.current_round_label : null, source: data.meta?.source ?? '未提供', responseTime: data.meta?.updated_at ?? null };
}
function useLiveResources() {
  return {
    today: useReadOnlyResource(fetchToday),
    health: useReadOnlyResource(api.health),
    pipeline: useReadOnlyResource(async () => pipelineSummary(await api.ops.pipeline()), 60_000),
  };
}
type LiveResources = ReturnType<typeof useLiveResources>;
const Context = createContext<LiveResources | null>(null);
export function LiveStatusProvider({ children }: { children: ReactNode }) {
  const state = useLiveResources();
  return <Context.Provider value={state}>{children}</Context.Provider>;
}
export function useLiveStatus() {
  const value = useContext(Context);
  if (!value) throw new Error('LiveStatusProvider is required');
  return value;
}
