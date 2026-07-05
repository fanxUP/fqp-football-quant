import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { SimulatorTicket } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import StatusBadge from '../shared/components/StatusBadge';
import Card from '../shared/components/Card';
import { PLAY_TYPE_LABELS, PASS_TYPE_LABELS } from '../shared/constants';
import { formatTimestamp } from '../shared/utils';

export default function SimulatorHistoryPage() {
  const [tickets, setTickets] = useState<SimulatorTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');

  const fetchTickets = useCallback(() => {
    setLoading(true);
    setError(null);
    api.simulator.tickets
      .list({ status: statusFilter || undefined, limit: 50 })
      .then((res) => {
        setTickets(res.tickets);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, [statusFilter]);

  useEffect(() => { fetchTickets(); }, [fetchTickets]);

  const statusBadge = (s: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      pending: 'warning',
      settled: 'ok',
      cancelled: 'disabled',
    };
    return map[s] || 'disabled';
  };

  const statusLabel = (s: string) => {
    const map: Record<string, string> = {
      pending: '待结算',
      settled: '已结算',
      cancelled: '已取消',
    };
    return map[s] || s;
  };

  const columns: Column<SimulatorTicket>[] = [
    {
      key: 'id',
      title: '票单ID',
      width: '70px',
      render: (v) => <span className="fqp-mono">#{String(v)}</span>,
    },
    {
      key: 'play_type',
      title: '玩法',
      width: '80px',
      render: (v) => <span style={{ fontSize: '12px' }}>{PLAY_TYPE_LABELS[String(v)] || String(v)}</span>,
    },
    {
      key: 'pass_type',
      title: '过关方式',
      width: '70px',
      render: (v) => <span style={{ fontSize: '12px' }}>{PASS_TYPE_LABELS[String(v)] || String(v)}</span>,
    },
    {
      key: 'match_count',
      title: '场次',
      width: '50px',
      render: (v) => <span className="fqp-mono">{String(v)}</span>,
    },
    {
      key: 'total_cost',
      title: '金额',
      width: '80px',
      render: (v) => (
        <span className="fqp-mono" style={{ fontWeight: 600 }}>
          ¥{Number(v).toFixed(2)}
        </span>
      ),
    },
    {
      key: 'status',
      title: '状态',
      width: '70px',
      render: (v) => <StatusBadge status={statusBadge(String(v))} label={statusLabel(String(v))} />,
    },
    {
      key: 'created_at',
      title: '投注时间',
      width: '140px',
      render: (v) => <span style={{ fontSize: '12px' }}>{formatTimestamp(v)}</span>,
    },
  ];

  return (
    <div>
      <PageHeader
        title="📋 模拟投注记录"
        actions={
          <button className="fqp-btn fqp-btn-primary" onClick={() => navigate('/simulator')}>
            ← 返回投注
          </button>
        }
      />

      <FilterBar>
        <select
          className="fqp-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ width: '150px' }}
        >
          <option value="">全部</option>
          <option value="pending">待结算</option>
          <option value="settled">已结算</option>
          <option value="cancelled">已取消</option>
        </select>
      </FilterBar>

      {error ? (
        <ErrorState message={error} onRetry={fetchTickets} />
      ) : (
        <Card title="投注记录">
          <DataTable
            columns={columns}
            rows={tickets}
            rowKey={(r) => String(r.id)}
            onRowClick={(ticket) => navigate(`/simulator/history/${ticket.id}`)}
            emptyText="暂无模拟投注记录，去投注页面开始吧！"
            loading={loading}
          />
        </Card>
      )}
    </div>
  );
}
