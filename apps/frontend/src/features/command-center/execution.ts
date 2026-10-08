export interface Execution {
  id: number; job_code: string; job_name: string; owner_agent: string; status: string;
  started_at: string | null; finished_at: string | null; duration_ms: number | null; retry_count: number;
}
export interface RegistryAgent { id: number; agent_name: string; agent_type: string; is_active: boolean }
export interface HumanTask { id: number; task_code: string; task_title: string; owner_agent: string; status: string; started_at: string | null; finished_at: string | null; updated_at: string | null; human_review_required: boolean }
export interface Scheduler { running: boolean; heartbeat_at: string | null }
export interface ExecutionOverview { agents: RegistryAgent[]; jobs: Execution[]; tasks: HumanTask[]; scheduler: Scheduler; observed_at: string; limit: number; task_limit: number }
export type ReferenceValue = number | string | boolean | number[] | string[] | References;
export interface References { [key: string]: ReferenceValue }
export interface ExecutionDetail extends Execution { input_refs: References; output_refs: References; has_error: boolean; error_summary: string | null; observed_at: string; trace_gap: string; upstream_run_ids: null }
export type Tone = 'running' | 'success' | 'failed' | 'unknown';
function object(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === 'object' && !Array.isArray(value); }
const validId = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const text = (value: unknown) => typeof value === 'string' && value.length > 0 && value.length <= 200;
const time = (value: unknown) => value === null || (typeof value === 'string' && Number.isFinite(Date.parse(value)));
function list(value: unknown, validate: (row: Record<string, unknown>) => boolean) {
  if (!Array.isArray(value) || value.length > 200 || value.some(row => !object(row) || !validId(row.id) || !validate(row)) || new Set(value.map(row => row.id)).size !== value.length) throw new Error('执行概览格式异常');
}
const validJob = (row: Record<string, unknown>) => ['job_code', 'job_name', 'owner_agent', 'status'].every(key => text(row[key])) && time(row.started_at) && time(row.finished_at) && (row.duration_ms === null || (typeof row.duration_ms === 'number' && Number.isFinite(row.duration_ms) && row.duration_ms >= 0)) && Number.isSafeInteger(row.retry_count) && Number(row.retry_count) >= 0;
export function parseOverview(value: unknown): ExecutionOverview {
  if (!object(value) || !object(value.scheduler) || typeof value.scheduler.running !== 'boolean' || !time(value.scheduler.heartbeat_at) || !text(value.observed_at) || !time(value.observed_at) || !validId(value.limit) || Number(value.limit) > 200 || value.task_limit !== 50) throw new Error('执行概览格式异常');
  list(value.agents, row => text(row.agent_name) && text(row.agent_type) && typeof row.is_active === 'boolean');
  list(value.jobs, validJob);
  list(value.tasks, row => ['task_code', 'task_title', 'owner_agent', 'status'].every(key => text(row[key])) && time(row.started_at) && time(row.finished_at) && time(row.updated_at) && typeof row.human_review_required === 'boolean');
  return value as unknown as ExecutionOverview;
}
export function parseDetail(value: unknown, id: number): ExecutionDetail {
  if (!object(value) || value.id !== id) throw new Error('执行 ID 不一致');
  if (!validJob(value) || !object(value.input_refs) || !object(value.output_refs) || typeof value.has_error !== 'boolean' || !text(value.observed_at) || !time(value.observed_at) || !text(value.trace_gap)) throw new Error('执行详情格式异常');
  return value as unknown as ExecutionDetail;
}
export function executionState(job: Pick<Execution, 'status'>, fresh: boolean, scheduler: Scheduler, now: number): { label: string; tone: Tone } {
  if (['running', 'in_progress'].includes(job.status)) {
    if (!fresh) return { label: '观测过期 · 记录运行中', tone: 'unknown' };
    const heartbeat = scheduler.heartbeat_at ? Date.parse(scheduler.heartbeat_at) : NaN;
    if (!scheduler.running || !Number.isFinite(heartbeat) || now - heartbeat > 90_000 || heartbeat - now > 5_000) return { label: '心跳不可用 · 记录运行中', tone: 'unknown' };
    return { label: '记录报告运行中', tone: 'running' };
  }
  if (['ok', 'success', 'completed', 'closed', 'merged'].includes(job.status)) return { label: '记录已完成', tone: 'success' };
  if (['error', 'failed', 'rejected'].includes(job.status)) return { label: '记录失败', tone: 'failed' };
  const labels: Record<string, string> = { pending: '等待记录', queued: '排队中', created: '已创建', assigned: '已分配', waiting_review: '等待审核', blocked: '受阻', approved: '已批准', passed_tests: '已通过测试', cancelled: '已取消', skipped: '已跳过', waiting: '等待中', no_data: '无数据', partial: '部分完成' };
  return { label: labels[job.status] ?? '未知状态', tone: 'unknown' };
}
export function observationFresh(receivedAt: number | null, observedAt: string | undefined, error: string | null, now: number) {
  const time = observedAt ? Date.parse(observedAt) : NaN;
  return !error && receivedAt !== null && now - receivedAt <= 65_000 && Number.isFinite(time) && now - time <= 65_000 && time - now <= 5_000;
}
export function referenceRows(refs: References, prefix = ''): { key: string; value: string }[] {
  return Object.entries(refs).flatMap(([key, value]) => {
    const name = prefix ? `${prefix}.${key}` : key;
    return object(value) ? referenceRows(value as References, name) : [{ key: name, value: Array.isArray(value) ? value.join(', ') : String(value) }];
  });
}
export interface OperationNode { key: string; kind: 'agent' | 'job'; label: string; position: [number, number, number]; job?: Execution }
export function operationNodes(value: ExecutionOverview, selectedId: number | null) {
  const nodes: OperationNode[] = value.agents.slice(0, 24).map((agent, i) => ({ key: `agent:${agent.id}`, kind: 'agent', label: agent.agent_name, position: [-25, 1, -44 + i * 88 / Math.max(1, Math.min(value.agents.length, 24) - 1)] }));
  const jobs = value.jobs.slice(0, 24);
  const selected = value.jobs.find(row => row.id === selectedId);
  if (selected && !jobs.some(row => row.id === selected.id)) jobs[jobs.length - 1] = selected;
  nodes.push(...jobs.map((job, i): OperationNode => ({ key: `job:${job.id}`, kind: 'job', label: job.job_name, job, position: [10 + i % 3 * 12, 1, -44 + Math.floor(i / 3) * 12] })));
  const edges = jobs.flatMap(job => {
    const agent = value.agents.slice(0, 24).find(row => job.owner_agent !== 'unknown' && row.agent_name === job.owner_agent);
    return agent ? [{ source: `agent:${agent.id}`, target: `job:${job.id}`, kind: 'owner' as const }] : [];
  });
  return { nodes, edges };
}
