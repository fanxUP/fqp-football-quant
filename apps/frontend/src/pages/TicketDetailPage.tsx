import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { RealTicket, RealTicketItem } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import ErrorState from '../shared/components/ErrorState';
import EmptyState from '../shared/components/EmptyState';
import StatusBadge from '../shared/components/StatusBadge';
import DataTable, { type Column } from '../shared/components/DataTable';
import Modal from '../shared/components/Modal';
import { toast } from '../shared/components/Toast';
import { playTypeLabel, passTypeLabel, sourceTypeLabel, statusLabel } from '../shared/constants';

interface TicketDetailPageProps {
  ticketId: number;
}

export default function TicketDetailPage({ ticketId }: TicketDetailPageProps) {
  const [ticket, setTicket] = useState<RealTicket | null>(null);
  const [items, setItems] = useState<RealTicketItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const fetch = () => {
    setLoading(true);
    setError(null);
    api.realTickets
      .get(ticketId)
      .then((res) => {
        if (res.ticket) {
          setTicket(res.ticket);
          setItems(res.items || []);
        } else {
          setError('票单不存在');
        }
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => { fetch(); }, [ticketId]);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      const res = await api.realTickets.delete(ticketId);
      if (res.status === 'ok') {
        toast.success('实票已删除');
        navigate('/tickets');
      } else {
        toast.error('删除失败');
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '删除失败');
    } finally {
      setDeleting(false);
      setShowDelete(false);
    }
  };

  if (loading) return <LoadingSpinner text="加载实票详情..." size="lg" />;
  if (error) return <ErrorState message={error} onRetry={fetch} />;
  if (!ticket) return <EmptyState icon="🔍" title="票单不存在" />;

  const settleBadge = (s: string): 'ok' | 'warning' | 'error' | 'info' | 'disabled' => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      pending: 'warning',
      settled: 'ok',
    };
    return map[s] || 'info';
  };

  const itemColumns: Column<RealTicketItem>[] = [
    {
      key: 'match_id',
      title: '比赛编号',
      width: '90px',
      render: (v) => (v ? <span className="fqp-mono">#{String(v)}</span> : <span style={{ color: 'var(--fqp-text-muted)' }}>—</span>),
    },
    { key: 'play_type', title: '玩法', width: '80px', render: (v) => playTypeLabel(String(v)) },
    {
      key: 'option_code',
      title: '选项',
      width: '60px',
      render: (v) => <span className="fqp-mono">{String(v)}</span>,
    },
    { key: 'option_name', title: '选项名' },
    {
      key: 'sp_value',
      title: '赔率',
      render: (v) => <span className="fqp-mono">{Number(v).toFixed(2)}</span>,
    },
    {
      key: 'is_matched_to_model',
      title: '匹配模型',
      render: (v) => (
        <StatusBadge status={v ? 'ok' : 'disabled'} label={v ? '已匹配' : '未匹配'} />
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title={`实票 #${ticketId}`}
        actions={
          <div style={{ display: 'flex', gap: '8px' }}>
            <button className="fqp-btn fqp-btn-danger" onClick={() => setShowDelete(true)}>
              删除
            </button>
          </div>
        }
      />

      <div className="fqp-grid-2" style={{ marginBottom: '20px' }}>
        <Card entranceDelay={0}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <div className="fqp-label">过关方式</div>
              <div>{passTypeLabel(ticket.pass_type)}</div>
            </div>
            <div>
              <div className="fqp-label">倍数</div>
              <div className="fqp-mono">×{ticket.multiple}</div>
            </div>
            <div>
              <div className="fqp-label">来源</div>
              <div>{sourceTypeLabel(ticket.source_type)}</div>
            </div>
            <div>
              <div className="fqp-label">确认状态</div>
              <StatusBadge status={settleBadge(ticket.confirm_status)} label={statusLabel(ticket.confirm_status)} />
            </div>
            <div>
              <div className="fqp-label">结算状态</div>
              <StatusBadge status={settleBadge(ticket.settlement_status)} label={statusLabel(ticket.settlement_status)} />
            </div>
          </div>
        </Card>

        <Card entranceDelay={100}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <div className="fqp-label">投注金额</div>
              <div style={{ fontSize: '24px', fontWeight: 800 }}>¥{ticket.total_amount.toFixed(2)}</div>
            </div>
            <div>
              <div className="fqp-label">理论最高奖金</div>
              <div style={{ fontSize: '18px', color: 'var(--fqp-success)' }}>
                {ticket.theoretical_max_prize !== null
                  ? `¥${ticket.theoretical_max_prize.toFixed(2)}`
                  : '—'}
              </div>
            </div>
            <div>
              <div className="fqp-label">绑定推荐</div>
              <div>
                {ticket.linked_simulation_id
                  ? `#${ticket.linked_simulation_id}`
                  : '未绑定'}
              </div>
            </div>
            <div>
              <div className="fqp-label">投注时间</div>
              <div>{ticket.purchase_time.replace('T', ' ').slice(0, 19)}</div>
            </div>
          </div>
        </Card>
      </div>

      {ticket.notes && (
        <Card title="备注" style={{ marginBottom: '20px' }} entranceDelay={200}>
          <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>{ticket.notes}</div>
        </Card>
      )}

      {/* Items */}
      <Card title={`投注项 (${items.length})`} style={{ overflow: 'hidden' }} entranceDelay={300}>
        <DataTable
          columns={itemColumns}
          rows={items}
          emptyText="该票单无投注项"
          rowKey={(r) => String(r.id)}
        />
      </Card>

      {/* Delete confirmation modal */}
      <Modal
        open={showDelete}
        onClose={() => setShowDelete(false)}
        title="确认删除"
        footer={
          <>
            <button className="fqp-btn" onClick={() => setShowDelete(false)}>
              取消
            </button>
            <button
              className="fqp-btn fqp-btn-danger"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? '删除中...' : '确认删除'}
            </button>
          </>
        }
      >
        <p style={{ color: 'var(--fqp-text-muted)' }}>
          确定要删除实票 #{ticketId} 吗？此操作不可恢复，所有关联的投注项也将被删除。
        </p>
      </Modal>
    </div>
  );
}
