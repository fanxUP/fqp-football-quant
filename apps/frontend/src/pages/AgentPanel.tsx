import { useState } from 'react';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import StatusBadge from '../shared/components/StatusBadge';
import { api } from '../core/apiClient';
import type { AgentTask, JobRun, AuditLog, ReviewGate, StaleJob, StaleTask } from '../core/types';
import useManualEvidence from './useManualEvidence';
import useBackgroundRefresh from '../shared/hooks/useBackgroundRefresh';
import ReadEvidenceStatus from './ReadEvidenceStatus';
import './BusinessEvidence.css';
import { agentLabel, agentTypeLabel, permissionLevelLabel, reviewStatusLabel, riskLabel, statusLabel } from '../shared/constants';
import { formatTimestamp } from '../shared/utils';

type TabKey = 'tasks' | 'jobs' | 'stale' | 'staleTasks' | 'gates' | 'audit';

function useAgentRead<T>(fetcher: () => Promise<T>) {
  const resource = useManualEvidence(fetcher);
  useBackgroundRefresh(resource.refresh);
  return resource;
}

function checkedList<T>(rows: T[], label: string): T[] {
  if (!Array.isArray(rows)) throw new Error(`${label}响应格式不正确`);
  return rows;
}

function AgentTable<T extends { id: number }>({ resource, columns, label, emptyText }: {
  resource: ReturnType<typeof useAgentRead<T[]>>; columns: Column<T>[]; label: string; emptyText: string;
}) {
  return <>
    <ReadEvidenceStatus resource={resource} label={label} note="可见页面每 30 秒刷新" />
    {(resource.data !== null || resource.loading) && <Card style={{ padding: 0, overflow: 'hidden' }}>
      <DataTable columns={columns} rows={resource.data ?? []} loading={resource.loading && resource.data === null} emptyText={emptyText} rowKey={row => row.id} />
    </Card>}
  </>;
}

export default function AgentPanel() {
  const [activeTab, setActiveTab] = useState<TabKey>('tasks');
  const overview = useAgentRead(async () => {
    // Wait for all readers to settle before releasing the refresh guard.
    const responses = await Promise.allSettled([
      api.agentOperations.summary(), api.agentOperations.scheduler(), api.agentOperations.list(),
    ] as const);
    const [summaryResponse, schedulerResponse, agentsResponse] = responses;
    for (const response of responses) if (response.status === 'rejected') throw response.reason;
    if (summaryResponse.status !== 'fulfilled' || schedulerResponse.status !== 'fulfilled' || agentsResponse.status !== 'fulfilled') throw new Error('代理概览读取失败');
    const summary = summaryResponse.value.summary;
    if (!summary || !schedulerResponse.value.scheduler ||
        [summary.active_agents, summary.open_tasks, summary.running_jobs, summary.stale_jobs, summary.stale_tasks,
          summary.failed_jobs_24h, summary.pending_review_gates].some(value => !Number.isSafeInteger(value) || value < 0) ||
        typeof summary.scheduler_running !== 'boolean') throw new Error('代理概览响应格式不正确');
    return { summary: summaryResponse.value.summary, scheduler: schedulerResponse.value.scheduler, agents: checkedList(agentsResponse.value.agents, '代理列表') };
  });
  const summary = overview.data?.summary;
  const scheduler = overview.data?.scheduler;
  const agents = overview.data?.agents ?? [];

  return (
    <div className="be-page">
      <PageHeader title="智能代理中心" />
      <ReadEvidenceStatus resource={overview} label="刷新代理概览" note="可见页面每 30 秒刷新" />
      {(overview.data !== null || overview.loading) && <Card style={{ padding: 0, overflow: 'hidden', marginBottom: 20 }}>
        <div style={{ padding: '16px 20px 8px' }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>智能代理列表</h2>
          <div className="fqp-stat-sub">已注册 {agents.length} 个本地智能代理</div>
        </div>
        <DataTable
          columns={[
            { key: 'agent_name', title: '智能代理', render: (value) => agentLabel(String(value)) },
            { key: 'agent_type', title: '类型', render: (value) => agentTypeLabel(String(value)) },
            { key: 'description', title: '职责' },
            { key: 'permission_level', title: '权限', render: (value) => permissionLevelLabel(String(value)) },
            { key: 'is_active', title: '状态', render: (value) => <StatusBadge status={value ? 'ok' : 'disabled'} label={value ? '启用' : '停用'} /> },
          ]}
          rows={agents}
          loading={overview.loading && overview.data === null}
          emptyText="暂无已注册智能代理"
          rowKey={(row) => row.id}
        />
      </Card>}
      {summary && (
        <div className="fqp-grid-4" style={{ marginBottom: 20 }}>
          <Card className="fqp-stat-card"><div className="fqp-stat-label">活跃智能代理</div><div className="fqp-stat-value">{summary.active_agents}</div></Card>
          <Card className="fqp-stat-card"><div className="fqp-stat-label">未完成任务</div><div className="fqp-stat-value">{summary.open_tasks}</div></Card>
          <Card className="fqp-stat-card"><div className="fqp-stat-label">运行中任务</div><div className="fqp-stat-value">{summary.running_jobs}</div></Card>
          <Card className="fqp-stat-card"><div className="fqp-stat-label">疑似卡住</div><div className="fqp-stat-value" style={{ color: summary.stale_jobs + summary.stale_tasks ? 'var(--fqp-warning)' : undefined }}>{summary.stale_jobs + summary.stale_tasks}</div><div className="fqp-stat-sub">{summary.stale_tasks} 个超时任务 · {summary.stale_jobs} 个超时调度任务</div></Card>
          <Card className="fqp-stat-card"><div className="fqp-stat-label">待审核闸门</div><div className="fqp-stat-value" style={{ color: summary.pending_review_gates ? 'var(--fqp-warning)' : undefined }}>{summary.pending_review_gates}</div></Card>
          <Card className="fqp-stat-card"><div className="fqp-stat-label">24 小时失败任务</div><div className="fqp-stat-value" style={{ color: summary.failed_jobs_24h ? 'var(--fqp-red-neon)' : undefined }}>{summary.failed_jobs_24h}</div></Card>
          <Card className="fqp-stat-card"><div className="fqp-stat-label">调度器</div><div className="fqp-stat-value" style={{ color: summary.scheduler_running ? 'var(--fqp-green-neon)' : 'var(--fqp-red-neon)', fontSize: 24 }}>{summary.scheduler_running ? '在线' : '离线'}</div><div className="fqp-stat-sub">{scheduler?.heartbeat_at ? `心跳 ${formatTimestamp(scheduler.heartbeat_at)}` : '请启动本机调度器'}</div></Card>
        </div>
      )}
      <div className="fqp-tabs">
        {([
          ['tasks', '智能代理任务'],
          ['jobs', '任务执行'],
          ['stale', '超时调度任务'],
          ['staleTasks', '超时任务'],
          ['gates', '审核闸门'],
          ['audit', '审计日志'],
        ] as [TabKey, string][]).map(([key, label]) => (
          <button
            key={key}
            className={`fqp-tab${activeTab === key ? ' active' : ''}`}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div key={activeTab} className="fqp-anim-fadeIn">
        {activeTab === 'tasks' && <TasksTab />}
        {activeTab === 'jobs' && <JobsTab />}
        {activeTab === 'stale' && <StaleJobsTab />}
        {activeTab === 'staleTasks' && <StaleTasksTab />}
        {activeTab === 'gates' && <GatesTab />}
        {activeTab === 'audit' && <AuditTab />}
      </div>
    </div>
  );
}

function StaleTasksTab() {
  const resource = useAgentRead(async () => checkedList((await api.agentOperations.staleTasks()).tasks, '刷新超时任务'));
  const columns: Column<StaleTask>[] = [
    { key: 'task_code', title: '任务编号' },
    { key: 'task_title', title: '任务标题' },
    { key: 'owner_agent', title: '负责代理', render: (v) => agentLabel(String(v)) },
    { key: 'status', title: '状态', render: (v) => <StatusBadge status="warning" label={statusLabel(String(v))} /> },
    { key: 'stale_minutes', title: '未更新时长', render: (v) => `${Number(v).toFixed(1)} 分钟` },
    { key: 'updated_at', title: '最后更新', render: (v) => formatTimestamp(v) },
  ];
  return <AgentTable resource={resource} columns={columns} label="刷新超时任务" emptyText="暂无超时智能代理任务" />;
}

function StaleJobsTab() {
  const resource = useAgentRead(async () => checkedList((await api.agentOperations.staleJobs()).jobs, '刷新超时调度任务'));
  const columns: Column<StaleJob>[] = [
    { key: 'job_code', title: '调度任务编码' },
    { key: 'job_name', title: '任务名称' },
    { key: 'owner_agent', title: '负责代理', render: (v) => agentLabel(String(v)) },
    { key: 'running_minutes', title: '运行时长', render: (v) => `${Number(v).toFixed(1)} 分钟` },
    { key: 'started_at', title: '开始时间', render: (v) => formatTimestamp(v) },
  ];
  return <AgentTable resource={resource} columns={columns} label="刷新超时调度任务" emptyText="暂无超时调度任务" />;
}

function GatesTab() {
  const resource = useAgentRead(async () => checkedList((await api.agentOperations.gates()).gates, '刷新审核闸门'));
  const columns: Column<ReviewGate>[] = [
    { key: 'task_code', title: '任务编号' },
    { key: 'task_title', title: '任务标题' },
    { key: 'reason', title: '审核原因' },
    { key: 'reviewer', title: '审核人', render: (v) => typeof v === 'string' && v ? v : '待审核' },
    { key: 'review_status', title: '状态', render: (v) => <StatusBadge status={v === 'approved' ? 'ok' : v === 'rejected' ? 'error' : 'warning'} label={reviewStatusLabel(String(v))} /> },
    { key: 'id', title: '操作', render: (_v, row) => row.review_status === 'pending' ? <GateActions gateId={row.id} onResolved={resource.refresh} /> : '—' },
    { key: 'created_at', title: '创建时间', render: (v) => formatTimestamp(v) },
  ];
  return <AgentTable resource={resource} columns={columns} label="刷新审核闸门" emptyText="暂无人工审核闸门" />;
}

function GateActions({ gateId, onResolved }: { gateId: number; onResolved: () => void | Promise<void> }) {
  const [reviewer, setReviewer] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resolve = async (status: 'approved' | 'rejected') => {
    if (!reviewer.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api.agentOperations.resolveGate(gateId, { reviewer: reviewer.trim(), status, comment });
      if (data.status !== 'ok') throw new Error(data.error || '审核未保存，请重试');
      await onResolved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '审核未保存，请重试');
    } finally { setBusy(false); }
  };
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', minWidth: 300 }} onClick={(e) => e.stopPropagation()}>
      {error && <span role="alert">{error}</span>}
      <input aria-label="审核人" className="fqp-input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="审核人" style={{ width: 80 }} />
      <input aria-label="审核评论" className="fqp-input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="评论" style={{ width: 100 }} />
      <button className="fqp-btn fqp-btn-primary" disabled={busy || !reviewer.trim()} onClick={() => resolve('approved')}>批准</button>
      <button className="fqp-btn" disabled={busy || !reviewer.trim()} onClick={() => resolve('rejected')}>拒绝</button>
    </div>
  );
}

// ---- Tasks Tab ----
function TasksTab() {
  const [statusFilter, setStatusFilter] = useState('');
  return <div>
      <div className="fqp-filter-bar">
        <select aria-label="任务状态" className="fqp-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ minWidth: '160px' }}>
          <option value="">全部状态</option>
          <option value="created">已创建</option>
          <option value="in_progress">执行中</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
        </select>
      </div>
    <TasksList key={statusFilter} statusFilter={statusFilter} />
  </div>;
}

function TasksList({ statusFilter }: { statusFilter: string }) {
  const resource = useAgentRead(async () => checkedList((await api.agentOperations.tasks(statusFilter)).tasks, '智能代理任务'));
  const statusBadge = (s: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      created: 'info',
      in_progress: 'warning',
      completed: 'ok',
      failed: 'error',
      cancelled: 'disabled',
    };
    return map[s] || 'info';
  };

  const columns: Column<AgentTask>[] = [
    { key: 'task_code', title: '任务编号' },
    { key: 'task_title', title: '标题' },
    { key: 'owner_agent', title: '负责代理', render: (v) => agentLabel(String(v)) },
    {
      key: 'risk_level',
      title: '风险',
      width: '60px',
      render: (v) => <StatusBadge status={v === 'L4' || v === 'L5' ? 'error' : v === 'L3' ? 'warning' : 'info'} label={riskLabel(String(v))} />,
    },
    {
      key: 'status',
      title: '状态',
      render: (v) => <StatusBadge status={statusBadge(String(v))} label={statusLabel(String(v))} />,
    },
    {
      key: 'human_review_required',
      title: '需人工审核',
      width: '100px',
      render: (v) => <StatusBadge status={v ? 'warning' : 'ok'} label={v ? '是' : '否'} />,
    },
    {
      key: 'created_at',
      title: '创建时间',
      render: (v) => formatTimestamp(v),
    },
  ];

  return <AgentTable resource={resource} columns={columns} label="刷新智能代理任务" emptyText="暂无智能代理任务记录" />;
}

// ---- Jobs Tab ----
function JobsTab() {
  const resource = useAgentRead(async () => checkedList((await api.agentOperations.jobs()).jobs, '刷新任务执行'));
  const statusBadge = (status: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const statuses = { running: 'warning', success: 'ok', failed: 'error', pending: 'info' } as const;
    return statuses[status as keyof typeof statuses] ?? 'disabled';
  };
  const columns: Column<JobRun>[] = [
    { key: 'job_code', title: '任务编码' },
    { key: 'job_name', title: '任务名称' },
    { key: 'owner_agent', title: '负责代理', render: (v) => agentLabel(String(v)) },
    {
      key: 'status',
      title: '状态',
      render: (v) => <StatusBadge status={statusBadge(String(v))} label={statusLabel(String(v))} />,
    },
    {
      key: 'started_at',
      title: '开始时间',
      render: (v) => formatTimestamp(v),
    },
    {
      key: 'duration_ms',
      title: '耗时',
      render: (v) => v !== null && v !== undefined ? `${(Number(v) / 1000).toFixed(1)}s` : '—',
    },
    {
      key: 'error_message',
      title: '错误',
      render: (v) => v ? <span style={{ color: 'var(--fqp-red-neon)', fontSize: '12px' }}>{String(v).slice(0, 80)}</span> : '—',
    },
  ];

  return <AgentTable resource={resource} columns={columns} label="刷新任务执行" emptyText="暂无任务执行记录，等待定时任务首次触发" />;
}

// ---- Audit Tab ----
function AuditTab() {
  const resource = useAgentRead(async () => checkedList((await api.agentOperations.audit()).logs, '刷新审计日志'));
  const columns: Column<AuditLog>[] = [
    {
      key: 'task_id',
      title: '关联任务',
      width: '80px',
      render: (v) => v ? <span className="fqp-mono">#{String(v)}</span> : '—',
    },
    { key: 'agent_name', title: '智能代理', render: (v) => agentLabel(String(v)) },
    { key: 'action_type', title: '动作类型' },
    {
      key: 'result_status',
      title: '结果',
      render: (v) => <StatusBadge status={v === 'completed' ? 'ok' : v === 'failed' ? 'error' : 'info'} label={statusLabel(String(v))} />,
    },
    {
      key: 'result_summary',
      title: '摘要',
      render: (v) => String(v || '').slice(0, 100),
    },
    {
      key: 'created_at',
      title: '时间',
      render: (v) => formatTimestamp(v),
    },
  ];

  return <AgentTable resource={resource} columns={columns} label="刷新审计日志" emptyText="暂无审计日志记录" />;
}
