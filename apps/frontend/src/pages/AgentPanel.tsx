import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import StatusBadge from '../shared/components/StatusBadge';
import ErrorState from '../shared/components/ErrorState';
import { statusLabel, riskLabel, actionLabel } from '../shared/constants';

type TabKey = 'tasks' | 'jobs' | 'audit';

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

export default function AgentPanel() {
  const [activeTab, setActiveTab] = useState<TabKey>('tasks');

  return (
    <div>
      <PageHeader title="Codex Agent" />
      <div className="fqp-tabs">
        {([
          ['tasks', 'Agent 任务'],
          ['jobs', '任务执行'],
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
        {activeTab === 'audit' && <AuditTab />}
      </div>
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
    { key: 'owner_agent', title: '负责Agent' },
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
      render: (v) => v ? String(v).replace('T', ' ').slice(0, 19) : '—',
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
          emptyText="暂无 Agent 任务记录"
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

  useEffect(() => { fetchJobs(); }, []);

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
    { key: 'owner_agent', title: '负责Agent' },
    {
      key: 'status',
      title: '状态',
      render: (v) => <StatusBadge status={statusBadge(String(v))} label={statusLabel(String(v))} />,
    },
    {
      key: 'started_at',
      title: '开始时间',
      render: (v) => v ? String(v).replace('T', ' ').slice(0, 19) : '—',
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
    { key: 'agent_name', title: 'Agent' },
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
      render: (v) => v ? String(v).replace('T', ' ').slice(0, 19) : '—',
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
