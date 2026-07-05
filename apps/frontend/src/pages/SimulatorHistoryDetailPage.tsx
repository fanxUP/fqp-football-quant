import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { SimulatorTicketDetail } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import { PLAY_TYPE_LABELS, PASS_TYPE_LABELS } from '../shared/constants';
import { formatTimestamp } from '../shared/utils';

interface Props {
  ticketId: number;
}

export default function SimulatorHistoryDetailPage({ ticketId }: Props) {
  const [ticket, setTicket] = useState<SimulatorTicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTicket = useCallback(() => {
    setLoading(true);
    setError(null);
    api.simulator.tickets
      .get(ticketId)
      .then((res) => {
        setTicket(res.ticket);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, [ticketId]);

  useEffect(() => { fetchTicket(); }, [fetchTicket]);

  if (loading) return <LoadingSpinner text="加载票单详情..." size="lg" />;
  if (error) return <ErrorState message={error} onRetry={fetchTicket} />;
  if (!ticket) return <ErrorState message="票单不存在" />;

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

  const itemColumns: Column<NonNullable<SimulatorTicketDetail['items']>[number]>[] = [
    {
      key: 'match_id',
      title: '场次',
      width: '60px',
      render: (v) => <span className="fqp-mono">#{String(v)}</span>,
    },
    {
      key: 'home_team_name',
      title: '主队',
      width: '100px',
      render: (v) => <span style={{ fontSize: '12px' }}>{String(v)}</span>,
    },
    {
      key: 'away_team_name',
      title: '客队',
      width: '100px',
      render: (v) => <span style={{ fontSize: '12px' }}>{String(v)}</span>,
    },
    {
      key: 'play_type',
      title: '玩法',
      width: '80px',
      render: (v) => <span style={{ fontSize: '12px' }}>{PLAY_TYPE_LABELS[String(v)] || String(v)}</span>,
    },
    {
      key: 'option_name',
      title: '选项',
      width: '80px',
      render: (v, row) => (
        <span style={{ fontSize: '12px', fontWeight: 600 }}>
          {String(v)}
          {row.handicap != null ? ` (${row.handicap > 0 ? '+' : ''}${row.handicap})` : ''}
        </span>
      ),
    },
    {
      key: 'sp_value',
      title: '赔率',
      width: '60px',
      render: (v) => <span className="fqp-mono" style={{ color: 'var(--fqp-accent)' }}>{Number(v).toFixed(2)}</span>,
    },
    {
      key: 'is_dan',
      title: '胆',
      width: '40px',
      render: (v) => v ? '⭐' : '---',
    },
  ];

  return (
    <div>
      <PageHeader
        title={`票单 #${ticket.id}`}
        actions={
          <button className="fqp-btn fqp-btn-primary" onClick={() => navigate('/simulator/history')}>
            ← 返回历史
          </button>
        }
      />

      {/* Ticket summary cards — staggered entrance */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: '12px',
        marginBottom: '16px',
      }}>
        <Card entranceDelay={0}>
          <div style={{ textAlign: 'center' }}>
            <div className="fqp-stat-label">玩法</div>
            <div className="fqp-stat-value" style={{ fontSize: '18px' }}>
              {PLAY_TYPE_LABELS[ticket.play_type] || ticket.play_type}
            </div>
          </div>
        </Card>
        <Card entranceDelay={60}>
          <div style={{ textAlign: 'center' }}>
            <div className="fqp-stat-label">过关方式</div>
            <div className="fqp-stat-value" style={{ fontSize: '18px' }}>
              {PASS_TYPE_LABELS[ticket.pass_type] || ticket.pass_type}
            </div>
          </div>
        </Card>
        <Card entranceDelay={120}>
          <div style={{ textAlign: 'center' }}>
            <div className="fqp-stat-label">投注金额</div>
            <div className="fqp-stat-value" style={{ fontSize: '18px', color: 'var(--fqp-accent)' }}>
              ¥{ticket.total_cost.toFixed(2)}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
              {ticket.bet_count}注 × 2元 × {ticket.multiple}倍
            </div>
          </div>
        </Card>
        <Card entranceDelay={180}>
          <div style={{ textAlign: 'center' }}>
            <div className="fqp-stat-label">最高奖金</div>
            <div className="fqp-stat-value" style={{ fontSize: '18px', color: 'var(--fqp-success)' }}>
              ¥{ticket.max_prize.toFixed(2)}
            </div>
          </div>
        </Card>
        <Card entranceDelay={240}>
          <div style={{ textAlign: 'center' }}>
            <div className="fqp-stat-label">状态</div>
            <StatusBadge status={statusBadge(ticket.status)} label={statusLabel(ticket.status)} />
          </div>
        </Card>
        <Card entranceDelay={300}>
          <div style={{ textAlign: 'center' }}>
            <div className="fqp-stat-label">投注时间</div>
            <div style={{ fontSize: '13px' }}>{formatTimestamp(ticket.created_at)}</div>
          </div>
        </Card>
      </div>

      {/* Notes */}
      {ticket.notes && (
        <Card title="备注" style={{ marginBottom: '16px' }}>
          <p style={{ fontSize: '14px', margin: 0 }}>{ticket.notes}</p>
        </Card>
      )}

      {/* Items */}
      <Card title="投注项" style={{ marginBottom: '16px' }}>
        <DataTable
          columns={itemColumns}
          rows={ticket.items || []}
          rowKey={(r) => String(r.id)}
          emptyText="无投注项"
        />
      </Card>

      {/* Settlement */}
      {ticket.settlement && (
        <Card title="结算信息">
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
            gap: '12px',
          }}>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">中奖</div>
              <div style={{ fontSize: '18px', fontWeight: 600, color: ticket.settlement.is_won ? 'var(--fqp-success)' : 'var(--fqp-danger)' }}>
                {ticket.settlement.is_won ? '✅ 中奖' : '❌ 未中'}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">奖金</div>
              <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--fqp-accent)' }}>
                ¥{ticket.settlement.prize_amount.toFixed(2)}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">税金</div>
              <div style={{ fontSize: '18px', fontWeight: 600 }}>
                ¥{ticket.settlement.tax_amount.toFixed(2)}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">税后奖金</div>
              <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--fqp-success)' }}>
                ¥{ticket.settlement.net_prize.toFixed(2)}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">盈亏</div>
              <div style={{
                fontSize: '18px',
                fontWeight: 600,
                color: ticket.settlement.profit_loss >= 0 ? 'var(--fqp-success)' : 'var(--fqp-danger)',
              }}>
                {ticket.settlement.profit_loss >= 0 ? '+' : ''}¥{ticket.settlement.profit_loss.toFixed(2)}
              </div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">结算时间</div>
              <div style={{ fontSize: '13px' }}>{formatTimestamp(ticket.settlement.settle_time)}</div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
