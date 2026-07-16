import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentPanel from './AgentPanel';

afterEach(() => vi.unstubAllGlobals());

function mockFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/agent-summary')) {
      return { json: async () => ({ summary: { active_agents: 11, open_tasks: 2, running_jobs: 1, failed_jobs_24h: 0, pending_review_gates: 1, stale_jobs: 0, stale_tasks: 1, scheduler_running: true } }) } as Response;
    }
    if (url.includes('/api/agents')) {
      return { json: async () => ({ agents: [{ id: 1, agent_name: 'data_agent', agent_type: 'data', description: '官方数据采集', permission_level: 'P3_controlled', is_active: true }], total: 1 }) } as Response;
    }
    if (url.includes('/api/agent-review-gates')) {
      return { json: async () => ({ gates: [{ id: 1, task_code: 'RISK-001', task_title: '推荐审核', reason: 'L4', reviewer: null, review_status: 'pending', created_at: '2026-07-10T10:00:00' }], total: 1 }) } as Response;
    }
    if (url.includes('/api/agent-scheduler-status')) {
      return { json: async () => ({ scheduler: { running: true, heartbeat_at: '2026-07-10T10:00:00', pid: 123, pid_alive: true } }) } as Response;
    }
    if (url.includes('/api/agent-stale-tasks')) {
      return { json: async () => ({ tasks: [{ id: 7, task_code: 'TEST-001', task_title: 'Test task', owner_agent: 'qa_agent', status: 'in_progress', started_at: '2026-07-02T10:00:00', updated_at: '2026-07-02T10:05:00', stale_minutes: 20160.5 }], total: 1 }) } as Response;
    }
    return { json: async () => ({ tasks: [], jobs: [], logs: [], total: 0 }) } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('AgentPanel', () => {
  it('renders the operations summary and review gate tab', async () => {
    mockFetch();
    render(<AgentPanel />);
    await waitFor(() => expect(screen.getByText('活跃 Agent')).toBeInTheDocument());
    expect(screen.getByText('在线')).toBeInTheDocument();
    expect(screen.getByText(/心跳 2026-07-10 10:00:00/)).toBeInTheDocument();
    expect(screen.getByText('Agent 列表')).toBeInTheDocument();
    expect(screen.getByText('data_agent')).toBeInTheDocument();
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
    expect(screen.getByText('qa_agent')).toBeInTheDocument();
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
