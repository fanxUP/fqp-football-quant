import { describe, expect, it } from 'vitest';
import { executionState, operationNodes, parseOverview, parseDetail, referenceRows } from './execution';
const job = { id: 9, job_code: 'prediction', job_name: '预测', owner_agent: 'model_agent', status: 'running', started_at: '2026-10-08T00:00:00Z', finished_at: null, duration_ms: null, retry_count: 0 };
const overview = { agents: [{ id: 1, agent_name: 'model_agent', agent_type: 'model', is_active: true }], jobs: [job], tasks: [], scheduler: { running: true, heartbeat_at: '2026-10-08T00:00:00Z' }, observed_at: '2026-10-08T00:00:00Z', limit: 100, task_limit: 50 };
describe('execution evidence', () => {
  it('rejects malformed lists and duplicate IDs', () => {
    expect(() => parseOverview({ ...overview, jobs: [job, job] })).toThrow();
    expect(() => parseOverview({ ...overview, tasks: null })).toThrow();
  });
  it('rejects wrong execution ID and preserves valid zero counts', () => {
    const detail = { ...job, input_refs: {}, output_refs: { result: { predictions: 0 } }, observed_at: overview.observed_at, has_error: false, upstream_run_ids: null, trace_gap: '未记录' };
    expect(() => parseDetail(detail, 10)).toThrow('执行 ID 不一致');
    expect(referenceRows(parseDetail(detail, 9).output_refs)).toContainEqual({ key: 'result.predictions', value: '0' });
  });
  it('does not present a reported running state as heartbeat-confirmed execution', () => {
    const now = Date.parse(overview.observed_at);
    expect(executionState(job, true, overview.scheduler, now)).toEqual({ label: '记录报告运行中', tone: 'running' });
    expect(executionState(job, false, overview.scheduler, now).label).toBe('观测过期 · 记录运行中');
    expect(executionState(job, true, { running: false, heartbeat_at: null }, now).label).toBe('心跳不可用 · 记录运行中');
  });
  it('rejects old scheduler heartbeat and future timestamps', () => {
    const now = Date.parse(overview.observed_at) + 120_000;
    expect(executionState(job, true, overview.scheduler, now).tone).toBe('unknown');
    expect(executionState(job, true, { ...overview.scheduler, heartbeat_at: '2030-01-01' }, now).tone).toBe('unknown');
  });
  it('does not invent completed states for pending/unknown records', () => {
    expect(executionState({ ...job, status: 'pending' }, true, overview.scheduler, 0).label).toBe('等待记录');
    expect(executionState({ ...job, status: 'weird' }, true, overview.scheduler, 0).label).toBe('未知状态');
  });
  it('maps only registry ownership, with no dependency inference by timestamps', () => {
    const parsed = parseOverview(overview); const graph = operationNodes(parsed, 9);
    expect(graph.nodes.map(row => row.key)).toEqual(['agent:1', 'job:9']);
    expect(graph.edges).toEqual([{ source: 'agent:1', target: 'job:9', kind: 'owner' }]);
    expect(operationNodes({ ...parsed, agents: [] }, 9).edges).toEqual([]);
  });
  it('caps scene executions to 24 while including a selected older record', () => {
    const parsed = parseOverview({ ...overview, jobs: Array.from({ length: 40 }, (_, i) => ({ ...job, id: i + 1 })) });
    const graph = operationNodes(parsed, 40);
    expect(graph.nodes.filter(row => row.kind === 'job')).toHaveLength(24);
    expect(graph.nodes.some(row => row.key === 'job:40')).toBe(true);
  });
  it('does not infer ownership when identifiers were normalized to unknown', () => {
    const value = parseOverview({ ...overview, agents: [{ ...overview.agents[0], agent_name: 'unknown' }], jobs: [{ ...job, owner_agent: 'unknown' }] });
    expect(operationNodes(value, 9).edges).toEqual([]);
  });

});
