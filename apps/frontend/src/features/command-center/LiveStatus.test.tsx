import { StrictMode } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveStatusProvider, useLiveStatus, pipelineSummary } from './LiveStatus';
const api = vi.hoisted(() => ({ health: vi.fn(), ops: { pipeline: vi.fn() }, dashboard: { today: vi.fn() } }));
vi.mock('../../core/apiClient', () => ({ api }));
function ReadStatus() { const { today } = useLiveStatus(); return <><div>{today.data?.businessDate || '未知业务日'}</div><div>{today.data?.kpis[0]?.value ?? '缺失'}</div><div>{today.error}</div></>; }
const summary = { code: 0, data: { kpis: [{ key: 'count', value: 0 }], extras: { business_date: '2026-10-08' }, meta: { source: 'view', updated_at: '2026-10-08T23:00:00+08:00' } } };
describe('shared live evidence', () => {
  beforeEach(() => { vi.clearAllMocks(); api.health.mockResolvedValue({ status: 'ok' }); api.ops.pipeline.mockResolvedValue({ sources: [], jobs: [] }); api.dashboard.today.mockResolvedValue(summary); });
  afterEach(() => { vi.useRealTimers(); });
  it('loads once in StrictMode and gives consumers the same response', async () => {
    render(<StrictMode><LiveStatusProvider><ReadStatus /><ReadStatus /></LiveStatusProvider></StrictMode>);
    await waitFor(() => expect(screen.getAllByText('2026-10-08')).toHaveLength(2));
    expect(api.dashboard.today).toHaveBeenCalledTimes(1); expect(api.health).toHaveBeenCalledTimes(1);
  });
  it('retains valid zero after a refresh failure', async () => {
    vi.useFakeTimers(); render(<LiveStatusProvider><ReadStatus /></LiveStatusProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    api.dashboard.today.mockRejectedValue(new Error('刷新失败'));
    await act(async () => { vi.advanceTimersByTime(30_000); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText('0')).toBeInTheDocument(); expect(screen.getByText('刷新失败')).toBeInTheDocument();
  });
  it('rejects empty dashboard responses without displaying fabricated zeros', async () => {
    api.dashboard.today.mockResolvedValue({ code: 0, data: { empty: true } }); render(<LiveStatusProvider><ReadStatus /></LiveStatusProvider>);
    await screen.findByText('总览数据缺失或格式异常'); expect(screen.getByText('缺失')).toBeInTheDocument();
  });
  it('counts actual reported statuses without treating unobserved jobs as completed', () => {
    expect(pipelineSummary({ jobs: [{ status: 'running' }, { status: 'pending' }, { status: 'stale' }], sources: [{ status: 'degraded' }] })).toEqual({ running: 1, alerts: 2 });
  });
});
