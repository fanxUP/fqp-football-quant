import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentPanel from './AgentPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

function mockFetch(override?: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const response = override?.(url, init);
    if (response) return response;
    if (url.includes('/api/agent-summary')) {
      return jsonResponse({ summary: { active_agents: 11, open_tasks: 2, running_jobs: 1, failed_jobs_24h: 0, pending_review_gates: 1, stale_jobs: 0, stale_tasks: 1, scheduler_running: true } });
    }
    if (url.includes('/api/agents')) {
      return jsonResponse({ agents: [{ id: 1, agent_name: 'data_agent', agent_type: 'data', description: '官方数据采集', permission_level: 'P3_controlled', is_active: true }], total: 1 });
    }
    if (url.includes('/api/agent-review-gates')) {
      return jsonResponse({ gates: [{ id: 1, task_code: 'RISK-001', task_title: '推荐审核', reason: 'L4', reviewer: null, review_status: 'pending', created_at: '2026-07-10T10:00:00' }], total: 1 });
    }
    if (url.includes('/api/agent-scheduler-status')) {
      return jsonResponse({ scheduler: { running: true, heartbeat_at: '2026-07-10T10:00:00+08:00', pid: 123, pid_alive: true } });
    }
    if (url.includes('/api/agent-stale-tasks')) {
      return jsonResponse({ tasks: [{ id: 7, task_code: 'TEST-001', task_title: 'Test task', owner_agent: 'qa_agent', status: 'in_progress', started_at: '2026-07-02T10:00:00', updated_at: '2026-07-02T10:05:00', stale_minutes: 20160.5 }], total: 1 });
    }
    return jsonResponse({ tasks: [], jobs: [], logs: [], total: 0 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('AgentPanel', () => {
  it('renders the operations summary and review gate tab', async () => {
    mockFetch();
    render(<AgentPanel />);
    await waitFor(() => expect(screen.getByText('活跃智能代理')).toBeInTheDocument());
    expect(screen.getByText('在线')).toBeInTheDocument();
    expect(screen.getByText(/心跳 2026-07-10 10:00:00/)).toBeInTheDocument();
    expect(screen.getByText('智能代理列表')).toBeInTheDocument();
    expect(screen.getByText('数据代理')).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes('1 个超时任务'))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '审核闸门' }));
    expect(await screen.findByText('RISK-001')).toBeInTheDocument();
    expect(screen.getByText('L4')).toBeInTheDocument();
  });

  it('shows stale agent tasks in a dedicated diagnostics tab', async () => {
    mockFetch();
    render(<AgentPanel />);
    fireEvent.click(await screen.findByRole('button', { name: '超时任务' }));
    expect(await screen.findByText('TEST-001')).toBeInTheDocument();
    expect(screen.getByText('Test task')).toBeInTheDocument();
    expect(screen.getByText('质量验证代理')).toBeInTheDocument();
  });

  it('requires a reviewer before sending an approval request', async () => {
    const fetchMock = mockFetch();
    render(<AgentPanel />);
    fireEvent.click(await screen.findByRole('button', { name: '审核闸门' }));
    const approve = await screen.findByRole('button', { name: '批准' });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText('审核人'), { target: { value: 'human' } });
    expect(approve).not.toBeDisabled();
    fireEvent.click(approve);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/agent-review-gates/1/resolve', expect.objectContaining({ method: 'POST' })));
  });
});

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
}

const summaryFixture = { active_agents: 11, open_tasks: 2, running_jobs: 1, failed_jobs_24h: 0, pending_review_gates: 1, stale_jobs: 0, stale_tasks: 1, scheduler_running: true };

describe('AgentPanel request lifecycle', () => {
  it.each([401, 500])('reports summary HTTP %s as failure instead of a successful empty state', async status => {
    mockFetch(url => url === '/api/agent-summary' ? jsonResponse({ detail: '代理读取失败' }, status) : undefined);
    render(<AgentPanel />);
    expect(await screen.findByRole('alert')).toHaveTextContent('代理读取失败');
    expect(screen.queryByText('暂无已注册智能代理')).not.toBeInTheDocument();
  });

  it('retains the last successful summary when a refresh fails, then supports retry', async () => {
    let failing = false;
    const fetchMock = mockFetch(url => failing && url === '/api/agent-summary' ? jsonResponse({ detail: '暂不可用' }, 500) : undefined);
    render(<AgentPanel />);
    await screen.findByText('活跃智能代理');
    failing = true;
    fireEvent.click(screen.getByRole('button', { name: '刷新代理概览' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('保留本查询上次成功数据');
    expect(screen.getByText('在线')).toBeInTheDocument();
    failing = false;
    fireEvent.click(screen.getByRole('button', { name: '刷新代理概览' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/agent-summary')).toHaveLength(3);
  });

  it('pauses hidden-page refresh and does not overlap initial, manual or focus reads', async () => {
    vi.useFakeTimers();
    let hidden = false;
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => hidden ? 'hidden' : 'visible');
    let resolve!: (response: Response) => void;
    const fetchMock = mockFetch(url => url === '/api/agent-summary' ? new Promise<Response>(r => { resolve = r; }) : undefined);
    await act(async () => { render(<AgentPanel />); });
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
      await vi.advanceTimersByTimeAsync(31_000);
      fireEvent.click(screen.getByRole('button', { name: '刷新代理概览' }));
    });
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/agent-summary')).toHaveLength(1);
    await act(async () => { resolve(jsonResponse({ summary: summaryFixture })); });
    hidden = true;
    const count = fetchMock.mock.calls.length;
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(90_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(count);
    hidden = false;
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/agent-summary')).toHaveLength(2);
    await act(async () => { resolve(jsonResponse({ summary: summaryFixture })); });
    cleanup();
    const finalCount = fetchMock.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); window.dispatchEvent(new Event('focus')); });
    expect(fetchMock).toHaveBeenCalledTimes(finalCount);
  });

  it('ignores a delayed response for a previous task status', async () => {
    let resolve!: (response: Response) => void;
    mockFetch(url => {
      if (url === '/api/agent-tasks?limit=100') return new Promise<Response>(r => { resolve = r; });
      if (url.includes('&status=completed')) return jsonResponse({ tasks: [{ id: 2, task_code: 'NEW-2', task_title: '新筛选任务', status: 'completed' }] });
    });
    render(<AgentPanel />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'completed' } });
    await screen.findByText('NEW-2');
    await act(async () => { resolve(jsonResponse({ tasks: [{ id: 1, task_code: 'OLD-1', task_title: '旧筛选任务' }] })); });
    expect(screen.queryByText('OLD-1')).not.toBeInTheDocument();
    expect(screen.getByText('NEW-2')).toBeInTheDocument();
  });

  it.each([
    ['任务执行', '/api/ai-jobs?limit=100', '暂无任务执行记录，等待定时任务首次触发'],
    ['超时调度任务', '/api/agent-stale-jobs?threshold_minutes=30&limit=100', '暂无超时调度任务'],
    ['超时任务', '/api/agent-stale-tasks?threshold_minutes=60&limit=100', '暂无超时智能代理任务'],
    ['审核闸门', '/api/agent-review-gates?limit=100', '暂无人工审核闸门'],
    ['审计日志', '/api/agent-audit-logs?limit=100', '暂无审计日志'],
  ])('reports errors from the %s tab', async (tab, endpoint, empty) => {
    mockFetch(url => url === endpoint ? jsonResponse({ detail: '标签读取失败' }, 500) : undefined);
    render(<AgentPanel />);
    fireEvent.click(screen.getByRole('button', { name: tab }));
    expect(await screen.findByRole('alert')).toHaveTextContent('标签读取失败');
    expect(screen.queryByText(empty)).not.toBeInTheDocument();
  });

  it('shows failed review writes and keeps the decision available for retry', async () => {
    let fail = true;
    mockFetch((url, init) => init?.method === 'POST' && url.includes('/resolve') ? jsonResponse(fail ? { status: 'error', error: '审核尚未保存' } : { status: 'ok' }) : undefined);
    render(<AgentPanel />);
    fireEvent.click(screen.getByRole('button', { name: '审核闸门' }));
    fireEvent.change(await screen.findByPlaceholderText('审核人'), { target: { value: 'human' } });
    fireEvent.click(screen.getByRole('button', { name: '批准' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('审核尚未保存');
    expect(screen.getByRole('button', { name: '批准' })).toBeEnabled();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: '批准' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('renders successful job rows and preserves them after a network error', async () => {
    let fail = false;
    mockFetch(url => {
      if (url === '/api/ai-jobs?limit=100') {
        if (fail) return Promise.reject(new Error('网络断开'));
        return jsonResponse({ jobs: [{ id: 9, job_code: 'JOB-9', job_name: '采集', status: 'success', duration_ms: 0 }] });
      }
    });
    render(<AgentPanel />);
    fireEvent.click(screen.getByRole('button', { name: '任务执行' }));
    await screen.findByText('JOB-9');
    expect(screen.getByText('0.0s')).toBeInTheDocument();
    fail = true;
    fireEvent.click(screen.getByRole('button', { name: '刷新任务执行' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('网络断开');
    expect(screen.getByText('JOB-9')).toBeInTheDocument();
  });

  it('rejects malformed successful list data rather than displaying an empty list', async () => {
    mockFetch(url => url === '/api/agent-tasks?limit=100' ? jsonResponse({ tasks: null }) : undefined);
    render(<AgentPanel />);
    expect(await screen.findByRole('alert')).toHaveTextContent('响应格式不正确');
    expect(screen.queryByText('暂无智能代理任务记录')).not.toBeInTheDocument();
  });
});
