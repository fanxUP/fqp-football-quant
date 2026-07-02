import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { SimulationTicket } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';

export default function RecommendationsPage() {
  const [tickets, setTickets] = useState<SimulationTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .tickets({ limit: 100 })
      .then((res) => {
        if (!cancelled) {
          setTickets(res.tickets);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : '加载失败');
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, []);

  const filtered = statusFilter
    ? tickets.filter((t) => t.status === statusFilter)
    : tickets;

  const riskBadge = (level: string) => {
    const map: Record<string, 'ok' | 'warning' | 'error'> = {
      low: 'ok',
      medium: 'warning',
      high: 'error',
    };
    return <StatusBadge status={map[level] || 'info'} label={level.toUpperCase()} />;
  };

  const statusBadge = (s: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      generated: 'info',
      activated: 'warning',
      settled: 'ok',
      invalidated: 'disabled',
    };
    return map[s] || 'disabled';
  };

  const columns: Column<SimulationTicket>[] = [
    {
      key: 'id',
      title: '票单ID',
      width: '80px',
      render: (v) => <span className="fqp-mono">#{String(v)}</span>,
    },
    { key: 'strategy_pool', title: '策略池' },
    { key: 'pass_type', title: '过关方式' },
    {
      key: 'suggested_stake',
      title: '建议金额',
      render: (v) => <span className="fqp-mono">¥{Number(v).toFixed(0)}</span>,
    },
    {
      key: 'estimated_return',
      title: '预估回报',
      render: (v) => {
        const val = v as number | null;
        return val !== null ? <span className="fqp-mono">¥{val.toFixed(0)}</span> : '—';
      },
    },
    {
      key: 'expected_value',
      title: 'EV',
      render: (v) => {
        const val = v as number | null;
        if (val === null) return '—';
        const color = val > 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)';
        return <span style={{ color }}>{val >= 0 ? '+' : ''}{val.toFixed(4)}</span>;
      },
    },
    {
      key: 'risk_level',
      title: '风险',
      render: (v) => riskBadge(String(v)),
    },
    {
      key: 'status',
      title: '状态',
      render: (v) => <StatusBadge status={statusBadge(String(v))} label={String(v)} />,
    },
    {
      key: 'created_at',
      title: '创建时间',
      render: (v) => String(v).replace('T', ' ').slice(0, 19),
    },
    {
      key: 'item_count',
      title: '场次',
      width: '60px',
      render: (v) => <span className="fqp-mono">{String(v)}</span>,
    },
  ];

  if (error) {
    return (
      <div>
        <PageHeader title="推荐票单" />
        <ErrorState message={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="推荐票单"
        lastUpdated={new Date().toLocaleString('zh-CN', { hour12: false })}
      />
      <FilterBar>
        <select
          className="fqp-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ minWidth: '160px' }}
        >
          <option value="">全部状态</option>
          <option value="generated">待激活</option>
          <option value="activated">已激活</option>
          <option value="settled">已结算</option>
          <option value="invalidated">已失效</option>
        </select>
      </FilterBar>
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        <DataTable
          columns={columns}
          rows={filtered}
          loading={loading}
          emptyText="暂无推荐票单，系统将在每日 16:00 从模型预测中生成推荐候选"
          onRowClick={(row) => navigate(`/recommendations/${row.id}`)}
          rowKey={(r) => String(r.id)}
        />
      </Card>
    </div>
  );
}
