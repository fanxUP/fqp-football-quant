import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { RealTicket } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import DisclaimerBanner, { PAGE_DEFAULTS } from '../shared/components/DisclaimerBanner';

export default function TicketsPage() {
  const [tickets, setTickets] = useState<RealTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');

  const fetchTickets = () => {
    setLoading(true);
    setError(null);
    api
      .realTickets
      .list({ limit: 100 })
      .then((res) => {
        setTickets(res.tickets);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => { fetchTickets(); }, []);

  const filtered = statusFilter
    ? tickets.filter((t) => t.settlement_status === statusFilter || t.confirm_status === statusFilter)
    : tickets;

  const settleBadge = (s: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      pending: 'warning',
      settled: 'ok',
      confirmed: 'info',
    };
    return map[s] || 'disabled';
  };

  const columns: Column<RealTicket>[] = [
    {
      key: 'id',
      title: '票单ID',
      width: '80px',
      render: (v) => <span className="fqp-mono">#{String(v)}</span>,
    },
    {
      key: 'pass_type',
      title: '过关方式',
      width: '80px',
    },
    {
      key: 'total_amount',
      title: '投注金额',
      render: (v) => <span className="fqp-mono">¥{Number(v).toFixed(0)}</span>,
    },
    {
      key: 'theoretical_max_prize',
      title: '最高奖金',
      render: (v) => {
        const val = v as number | null;
        return val !== null ? <span className="fqp-mono">¥{val.toFixed(0)}</span> : '—';
      },
    },
    {
      key: 'confirm_status',
      title: '确认状态',
      render: (v) => <StatusBadge status={settleBadge(String(v))} label={String(v)} />,
    },
    {
      key: 'settlement_status',
      title: '结算状态',
      render: (v) => <StatusBadge status={settleBadge(String(v))} label={String(v)} />,
    },
    {
      key: 'linked_simulation_id',
      title: '绑定推荐',
      render: (v) => (v ? <span className="fqp-mono">#{String(v)}</span> : <span style={{ color: 'var(--fqp-text-muted)' }}>未绑定</span>),
    },
    {
      key: 'purchase_time',
      title: '投注时间',
      render: (v) => String(v).replace('T', ' ').slice(0, 19),
    },
  ];

  return (
    <div>
      <PageHeader
        title="实票管理"
        lastUpdated={new Date().toLocaleString('zh-CN', { hour12: false })}
        actions={
          <button className="fqp-btn fqp-btn-primary" onClick={() => navigate('/tickets/new')}>
            + 录入实票
          </button>
        }
      />
      <DisclaimerBanner text={PAGE_DEFAULTS.tickets} type="page" />
      <FilterBar>
        <select
          className="fqp-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ minWidth: '160px' }}
        >
          <option value="">全部状态</option>
          <option value="pending">待结算</option>
          <option value="settled">已结算</option>
          <option value="confirmed">已确认</option>
        </select>
      </FilterBar>

      {error ? (
        <ErrorState message={error} onRetry={fetchTickets} />
      ) : (
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <DataTable
            columns={columns}
            rows={filtered}
            loading={loading}
            emptyText="尚未录入任何实票，点击「+ 录入实票」开始记录线下投注"
            onRowClick={(row) => navigate(`/tickets/${row.id}`)}
            rowKey={(r) => String(r.id)}
          />
        </Card>
      )}

      {/* FAB — quick add */}
      <button className="fqp-fab" onClick={() => navigate('/tickets/new')} title="录入实票">
        +
      </button>
    </div>
  );
}
