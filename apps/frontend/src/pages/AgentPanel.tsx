import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import StatusBadge from '../shared/components/StatusBadge';
import ErrorState from '../shared/components/ErrorState';
import { actionLabel, agentLabel, agentTypeLabel, permissionLevelLabel, reviewStatusLabel, riskLabel, statusLabel } from '../shared/constants';
import { formatTimestamp } from '../shared/utils';

type TabKey = 'tasks' | 'jobs' | 'stale' | 'staleTasks' | 'gates' | 'audit';

// ---- Types for agent data ----
interface AgentTask {
  id: number;
  task_code: string;
  task_title: string;
  task_type: string;
  owner_agent: string;
  priority: string;
  risk_level: string;
  status: string;
  human_review_required: boolean;
  created_at: string | null;
}

interface JobRun {
  id: number;
  job_code: string;
  job_name: string;
  owner_agent: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
}

interface AuditLog {
  id: number;
  task_id: number | null;
  agent_name: string;
  action_type: string;
  result_status: string;
  result_summary: string;
  created_at: string | null;
}

interface ReviewGate {
  id: number;
  task_code: string;
  task_title: string;
  gate_type: string;
  reason: string;
  reviewer: string | null;
  review_status: string;
  review_comment: string | null;
  created_at: string | null;
}

interface AgentSummary {
  active_agents: number;
  open_tasks: number;
  running_jobs: number;
  stale_jobs: number;
  stale_tasks: number;
  failed_jobs_24h: number;
  pending_review_gates: number;
  scheduler_running: boolean;
}

interface AgentDefinition {
  id: number;
  agent_name: string;
  agent_type: string;
  description: string;
  permission_level: string;
  is_active: boolean;
}

interface SchedulerStatus {
  running: boolean;
  heartbeat_at: string | null;
  pid: number | null;
  pid_alive: boolean;
}

interface StaleJob {
  id: number;
  job_code: string;
  job_name: string;
  owner_agent: string;
  started_at: string;
  running_minutes: number;
}

interface StaleTask {
  id: number;
  task_code: string;
  task_title: string;
  owner_agent: string;
  status: string;
  started_at: string | null;
  updated_at: string | null;
  stale_minutes: number;
}

export default function AgentPanel() {
  const [activeTab, setActiveTab] = useState<TabKey>('tasks');
  const [summary, setSummary] = useState<AgentSummary | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);

  useEffect(() => {
    const refresh = () => {
      Promise.all([
        fetch('/api/agent-summary').then((r) => r.json()),
        fetch('/api/agent-scheduler-status').then((r) => r.json()),
        fetch('/api/agents').then((r) => r.json()),
      ])
        .then(([summaryResponse, schedulerResponse, agentsResponse]) => {
          setSummary(summaryResponse.summary ? { stale_tasks: 0, ...summaryResponse.summary } : null);
          setScheduler(schedulerResponse.scheduler || null);
          setAgents(agentsResponse.agents || []);
        })
        .catch(() => { setSummary(null); setScheduler(null); setAgents([]); });
    };
    refresh();
    const timer = window.setInterval(refresh, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div>
      <PageHeader title="智能代理中心" />
      <Card style={{ padding: 0, overflow: 'hidden', marginBottom: 20 }}>
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
          loading={!summary && agents.length === 0}
          emptyText="暂无已注册智能代理"
          rowKey={(row) => row.id}
        />
      </Card>
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
  const [tasks, setTasks] = useState<StaleTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchStaleTasks = () => {
    setLoading(true); setError(null);
    fetch('/api/agent-stale-tasks?threshold_minutes=60&limit=100')
      .then((r) => r.json())
      .then((d) => { setTasks(d.tasks || []); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  };
  useEffect(() => {
    fetchStaleTasks();
    const timer = window.setInterval(fetchStaleTasks, 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const columns: Column<StaleTask>[] = [
    { key: 'task_code', title: '任务编号' },
    { key: 'task_title', title: '任务标题' },
    { key: 'owner_agent', title: '负责代理', render: (v) => agentLabel(String(v)) },
    { key: 'status', title: '状态', render: (v) => <StatusBadge status="warning" label={statusLabel(String(v))} /> },
    { key: 'stale_minutes', title: '未更新时长', render: (v) => `${Number(v).toFixed(1)} 分钟` },
    { key: 'updated_at', title: '最后更新', render: (v) => formatTimestamp(v) },
  ];
  if (error) return <ErrorState message={error} onRetry={fetchStaleTasks} />;
  return <Card style={{ padding: 0, overflow: 'hidden' }}><DataTable columns={columns} rows={tasks} loading={loading} emptyText="暂无超时智能代理任务" rowKey={(r) => String(r.id)} /></Card>;
}

function StaleJobsTab() {
  const [jobs, setJobs] = useState<StaleJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchStaleJobs = () => {
    setLoading(true); setError(null);
    fetch('/api/agent-stale-jobs?threshold_minutes=30&limit=100')
      .then((r) => r.json())
      .then((d) => { setJobs(d.jobs || []); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  };
  useEffect(() => {
    fetchStaleJobs();
    const timer = window.setInterval(fetchStaleJobs, 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const columns: Column<StaleJob>[] = [
    { key: 'job_code', title: '调度任务编码' },
    { key: 'job_name', title: '任务名称' },
    { key: 'owner_agent', title: '负责代理', render: (v) => agentLabel(String(v)) },
    { key: 'running_minutes', title: '运行时长', render: (v) => `${Number(v).toFixed(1)} 分钟` },
    { key: 'started_at', title: '开始时间', render: (v) => formatTimestamp(v) },
  ];
  if (error) return <ErrorState message={error} onRetry={fetchStaleJobs} />;
  return <Card style={{ padding: 0, overflow: 'hidden' }}><DataTable columns={columns} rows={jobs} loading={loading} emptyText="暂无超时调度任务" rowKey={(r) => String(r.id)} /></Card>;
}

function GatesTab() {
  const [gates, setGates] = useState<ReviewGate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchGates = () => {
    setLoading(true); setError(null);
    fetch('/api/agent-review-gates?limit=100')
      .then((r) => r.json())
      .then((d) => { setGates(d.gates || []); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  };
  useEffect(() => {
    fetchGates();
    const timer = window.setInterval(fetchGates, 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const columns: Column<ReviewGate>[] = [
    { key: 'task_code', title: '任务编号' },
    { key: 'task_title', title: '任务标题' },
    { key: 'reason', title: '审核原因' },
    { key: 'reviewer', title: '审核人', render: (v) => typeof v === 'string' && v ? v : '待审核' },
    { key: 'review_status', title: '状态', render: (v) => <StatusBadge status={v === 'approved' ? 'ok' : v === 'rejected' ? 'error' : 'warning'} label={reviewStatusLabel(String(v))} /> },
    { key: 'id', title: '操作', render: (_v, row) => row.review_status === 'pending' ? <GateActions gateId={row.id} onResolved={fetchGates} /> : '—' },
    { key: 'created_at', title: '创建时间', render: (v) => formatTimestamp(v) },
  ];
  if (error) return <ErrorState message={error} onRetry={fetchGates} />;
  return <Card style={{ padding: 0, overflow: 'hidden' }}><DataTable columns={columns} rows={gates} loading={loading} emptyText="暂无人工审核闸门" rowKey={(r) => String(r.id)} /></Card>;
}

function GateActions({ gateId, onResolved }: { gateId: number; onResolved: () => void }) {
  const [reviewer, setReviewer] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const resolve = async (status: 'approved' | 'rejected') => {
    if (!reviewer.trim()) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/agent-review-gates/${gateId}/resolve`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer: reviewer.trim(), status, comment }),
      });
      const data = await response.json();
      if (data.status === 'ok') onResolved();
    } finally { setBusy(false); }
  };
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', minWidth: 300 }} onClick={(e) => e.stopPropagation()}>
      <input className="fqp-input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="审核人" style={{ width: 80 }} />
      <input className="fqp-input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="评论" style={{ width: 100 }} />
      <button className="fqp-btn fqp-btn-primary" disabled={busy || !reviewer.trim()} onClick={() => resolve('approved')}>批准</button>
      <button className="fqp-btn" disabled={busy || !reviewer.trim()} onClick={() => resolve('rejected')}>拒绝</button>
    </div>
  );
}

// ---- Tasks Tab ----
function TasksTab() {
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');

  const fetchTasks = () => {
    setLoading(true);
    setError(null);
    fetch(`/api/agent-tasks?limit=100${statusFilter ? `&status=${statusFilter}` : ''}`)
      .then((r) => r.json())
      .then((d) => { setTasks(d.tasks || []); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  };

  useEffect(() => { fetchTasks(); }, [statusFilter]);

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

  if (error) return <ErrorState message={error} onRetry={fetchTasks} />;

  return (
    <div>
      <div className="fqp-filter-bar">
        <select className="fqp-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ minWidth: '160px' }}>
          <option value="">全部状态</option>
          <option value="created">已创建</option>
          <option value="in_progress">执行中</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
        </select>
      </div>
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <DataTable
          columns={columns}
          rows={tasks}
          loading={loading}
          emptyText="暂无智能代理任务记录"
          rowKey={(r) => String(r.id)}
        />
      </Card>
    </div>
  );
}

// ---- Jobs Tab ----
function JobsTab() {
  const [jobs, setJobs] = useState<JobRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchJobs = () => {
    setLoading(true);
    setError(null);
    fetch('/api/ai-jobs?limit=100')
      .then((r) => r.json())
      .then((d) => { setJobs(d.jobs || []); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  };

  useEffect(() => {
    fetchJobs();
    const timer = window.setInterval(fetchJobs, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const statusBadge = (s: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      running: 'warning',
      success: 'ok',
      failed: 'error',
      pending: 'info',
    };
    return map[s] || 'disabled';
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

  if (error) return <ErrorState message={error} onRetry={fetchJobs} />;

  return (
    <Card style={{ padding: 0, overflow: 'hidden' }}>
      <DataTable
        columns={columns}
        rows={jobs}
        loading={loading}
        emptyText="暂无任务执行记录，等待定时任务首次触发"
        rowKey={(r) => String(r.id)}
      />
    </Card>
  );
}

// ---- Audit Tab ----
function AuditTab() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchLogs = () => {
    setLoading(true);
    setError(null);
    fetch('/api/agent-audit-logs?limit=100')
      .then((r) => r.json())
      .then((d) => { setLogs(d.logs || []); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  };

  useEffect(() => { fetchLogs(); }, []);

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

  if (error) return <ErrorState message={error} onRetry={fetchLogs} />;

  return (
    <Card style={{ padding: 0, overflow: 'hidden' }}>
      <DataTable
        columns={columns}
        rows={logs}
        loading={loading}
        emptyText="暂无审计日志记录"
        rowKey={(r) => String(r.id)}
      />
    </Card>
  );
}
