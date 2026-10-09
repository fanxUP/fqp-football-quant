import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ExecutionCenter from './ExecutionCenter';
import CommandWorkspace from './CommandWorkspace';
const api = vi.hoisted(() => ({ executions: { overview: vi.fn(), detail: vi.fn() }, modelProviders: { bindings: vi.fn() } }));
vi.mock('../../core/apiClient', () => ({ api }));
vi.mock('./CommandCenter', () => ({ default: () => <div>赛事场景测试入口</div> }));
vi.mock('./SceneViewport', () => ({ default: () => <div>二维场景回退</div> }));
const job = { id: 9, job_code: 'prediction', job_name: '预测任务', owner_agent: 'model_agent', status: 'running', started_at: '2026-10-08T00:00:00Z', finished_at: null, duration_ms: null, retry_count: 0 };
const snapshot = () => ({ agents: [{ id: 1, agent_name: 'model_agent', agent_type: 'model', is_active: true }], jobs: [job, { ...job, id: 10, job_name: '采集任务', job_code: 'collection' }], tasks: [], scheduler: { running: false, heartbeat_at: null }, observed_at: new Date().toISOString(), limit: 100, task_limit: 50 });
const detail = (id: number) => ({ ...job, id, has_error: false, error_summary: null, input_refs: { dependencies: ['odds_snapshot'], model_version_id: 4 }, output_refs: { result: { predictions: 0 } }, observed_at: new Date().toISOString(), upstream_run_ids: null, trace_gap: '没有明确上游执行 ID' });
describe('Agent execution desk', () => {
  beforeEach(() => { vi.clearAllMocks(); api.modelProviders.bindings.mockResolvedValue({ bindings: [] }); api.executions.overview.mockImplementation(async () => snapshot()); api.executions.detail.mockImplementation(async id => detail(id)); });
  afterEach(() => { vi.useRealTimers(); });
  it('shows reported state, reference gaps and valid zero without pretending transfer', async () => {
    render(<ExecutionCenter />);
    await screen.findByText('result.predictions'); expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getAllByText('心跳不可用 · 记录运行中')).toHaveLength(2);
    expect(screen.getByText('没有明确上游执行 ID')).toBeInTheDocument();
    expect(screen.getByText(/没有产物消费证据，不播放传输动画/)).toBeInTheDocument();
  });
  it('prevents an old late detail response from overwriting a new selection', async () => {
    let resolveOld!: (value: unknown) => void;
    api.executions.detail.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    render(<ExecutionCenter />); await screen.findByRole('button', { name: /#10 采集任务/ });
    fireEvent.click(screen.getByRole('button', { name: /#10 采集任务/ }));
    await screen.findByText('result.predictions');
    await act(async () => resolveOld({ ...detail(9), output_refs: { old_only: 777 } }));
    expect(screen.queryByText('old_only')).not.toBeInTheDocument();
    expect(api.executions.detail).toHaveBeenLastCalledWith(10);
  });
  it('rejects a detail response for a different execution ID', async () => {
    api.executions.detail.mockResolvedValue(detail(200)); render(<ExecutionCenter />);
    await screen.findByText('执行 ID 不一致'); expect(screen.queryByText('result.predictions')).not.toBeInTheDocument();
  });
  it('freezes the historical list, avoids detail queries and supports stepping', async () => {
    render(<ExecutionCenter />); await screen.findByText('result.predictions');
    fireEvent.click(screen.getByRole('button', { name: '冻结为历史列表' }));
    expect(screen.getByRole('button', { name: '刷新概览' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '下一条' }));
    expect(screen.getByRole('heading', { name: '历史列表记录 #10' })).toBeInTheDocument();
    expect(api.executions.detail).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '返回实时观测' }));
    await waitFor(() => expect(api.executions.detail).toHaveBeenLastCalledWith(10));
  });
  it('retains previous successful records after a failed refresh', async () => {
    render(<ExecutionCenter />); await screen.findByText('result.predictions');
    api.executions.overview.mockRejectedValue(new Error('服务不可用'));
    fireEvent.click(screen.getByRole('button', { name: '刷新概览' }));
    await screen.findByText('服务不可用 · 保留上次成功数据，观测过期');
    expect(screen.getByRole('button', { name: /#9 预测任务/ })).toBeInTheDocument();
    expect(screen.getAllByText('观测过期 · 记录运行中')).toHaveLength(2);
  });
  it('shows an explicit empty state without inventing agents or jobs', async () => {
    api.executions.overview.mockResolvedValue({ ...snapshot(), agents: [], jobs: [] }); render(<ExecutionCenter />);
    await screen.findByText('没有注册 Agent'); expect(screen.getByText('没有符合条件的执行记录')).toBeInTheDocument();
    expect(api.executions.detail).not.toHaveBeenCalled();
  });
  it('pauses network polling while viewing the frozen historical list', async () => {
    vi.useFakeTimers(); render(<ExecutionCenter />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    fireEvent.click(screen.getByRole('button', { name: '冻结为历史列表' }));
    await act(async () => { vi.advanceTimersByTime(60_000); await Promise.resolve(); });
    expect(api.executions.overview).toHaveBeenCalledTimes(1);
    expect(api.executions.detail).toHaveBeenCalledTimes(1);
  });

  it('labels Pi bindings as configuration rather than current executions', async () => {
    api.modelProviders.bindings.mockResolvedValue({ bindings: [{ agentCode: 'test_llm', agentName: '界面测试分析角色', providerCode: 'test', providerName: '界面测试供应商', model: 'test-model', enabled: true, providerEnabled: true, updatedAt: null }] });
    render(<ExecutionCenter />); await screen.findByText('界面测试分析角色');
    expect(screen.getByText(/Pi 当前配置，不是某次执行的模型版本或运行状态/)).toBeInTheDocument();
    expect(screen.getByText('界面测试供应商 · test-model')).toBeInTheDocument();
  });

  it('unmounts the prior mode when switching the workspace', async () => {
    render(<CommandWorkspace />);
    expect(screen.getByText('赛事场景测试入口')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Agent 与管线' }));
    await screen.findByRole('heading', { name: 'Agent 状态网络' });
    expect(screen.queryByText('赛事场景测试入口')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '赛事指挥台' }));
    expect(screen.queryByRole('heading', { name: 'Agent 状态网络' })).not.toBeInTheDocument();
  });

});
