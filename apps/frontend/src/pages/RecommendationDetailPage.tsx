import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { SimulationTicket } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import ErrorState from '../shared/components/ErrorState';
import StatusBadge from '../shared/components/StatusBadge';
import EmptyState from '../shared/components/EmptyState';
import { passTypeLabel, riskLabel, statusLabel, strategyPoolLabel } from '../shared/constants';
import { formatTimestamp } from '../shared/utils';

interface RecommendationDetailPageProps {
  ticketId: number;
}

export default function RecommendationDetailPage({ ticketId }: RecommendationDetailPageProps) {
  const [ticket, setTicket] = useState<SimulationTicket | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    // Fetch all tickets and find ours (no single-ticket endpoint for simulation tickets)
    api
      .tickets({ limit: 200 })
      .then((res) => {
        if (cancelled) return;
        const found = res.tickets.find((t) => t.id === ticketId) || null;
        setTicket(found);
        setLoading(false);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : '加载失败');
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [ticketId]);

  if (loading) return <LoadingSpinner text="加载票单详情..." size="lg" />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!ticket) return <EmptyState icon="🔍" title="票单不存在" description={`票单 #${ticketId} 未找到或已被删除`} />;

  const statusColor = (s: string) => {
    const map: Record<string, 'ok' | 'warning' | 'error' | 'info' | 'disabled'> = {
      generated: 'info',
      activated: 'warning',
      settled: 'ok',
      invalidated: 'disabled',
    };
    return map[s] || 'info';
  };

  return (
    <div>
      <PageHeader title={`推荐票单 #${ticketId}`} />

      <div className="fqp-grid-2" style={{ marginBottom: '20px' }}>
        <Card entranceDelay={0}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <div className="fqp-label">策略池</div>
              <div>{strategyPoolLabel(ticket.strategy_pool)}</div>
            </div>
            <div>
              <div className="fqp-label">过关方式</div>
              <div>{passTypeLabel(ticket.pass_type)}</div>
            </div>
            <div>
              <div className="fqp-label">包含场次</div>
              <div className="fqp-mono">{ticket.item_count} 场</div>
            </div>
            <div>
              <div className="fqp-label">状态</div>
              <StatusBadge status={statusColor(ticket.status)} label={statusLabel(ticket.status)} />
            </div>
          </div>
        </Card>

        <Card entranceDelay={100}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <div className="fqp-label">建议金额</div>
              <div className="fqp-mono" style={{ fontSize: '24px', fontWeight: 800 }}>
                ¥{ticket.suggested_stake.toFixed(0)}
              </div>
            </div>
            <div>
              <div className="fqp-label">预估回报</div>
              <div className="fqp-mono" style={{ fontSize: '18px', color: 'var(--fqp-success)' }}>
                {ticket.estimated_return !== null ? `¥${ticket.estimated_return.toFixed(2)}` : '—'}
              </div>
            </div>
            <div>
              <div className="fqp-label">期望值 (EV)</div>
              <div
                className="fqp-mono"
                style={{
                  fontSize: '18px',
                  color: (ticket.expected_value ?? 0) > 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)',
                }}
              >
                {ticket.expected_value !== null
                  ? `${ticket.expected_value >= 0 ? '+' : ''}${ticket.expected_value.toFixed(4)}`
                  : '—'}
              </div>
            </div>
            <div>
              <div className="fqp-label">风险等级</div>
              <StatusBadge
                status={ticket.risk_level === 'high' ? 'error' : ticket.risk_level === 'medium' ? 'warning' : 'ok'}
                label={riskLabel(ticket.risk_level)}
              />
            </div>
          </div>
        </Card>
      </div>

      <Card entranceDelay={200}>
        <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
          <div className="fqp-label">创建时间</div>
          <div>{formatTimestamp(ticket.created_at)}</div>
          <div style={{ marginTop: '16px', padding: '12px', background: 'var(--fqp-panel)', borderRadius: 'var(--fqp-radius-sm)' }}>
            ⚠️ 明细项（各场次的具体选项与赔率）需要后端提供 <code>/api/tickets/{'{id}'}/items</code> 端点。
            当前后端仅有列表端点。待补充该端点后即可显示完整明细。
          </div>
        </div>
      </Card>
    </div>
  );
}
