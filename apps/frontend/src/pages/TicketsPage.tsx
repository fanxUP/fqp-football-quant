import { useEffect, useMemo, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { BettingTicket } from '../core/types';
import { ApiError } from '../core/types';
import {
  calculateLedgerStats,
  groupTicketsByDate,
  ticketKindLabel,
  ticketOutcome,
  ticketOutcomeLabel,
  ticketOutcomeWatermark,
  ticketOwnerLabel,
  ticketPrimaryMatchCode,
  ticketPrimaryMatchLabel,
  ticketSourceLabel,
} from '../core/bettingTickets';
import PageHeader from '../shared/components/PageHeader';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import EmptyState from '../shared/components/EmptyState';
import TeamName from '../shared/components/TeamName';
import { optionLabel, passTypeLabel, playTypeLabel, statusLabel } from '../shared/constants';

type DateFilter = 'all' | string;

function money(value: number | null | undefined): string {
  return `¥${Number(value || 0).toFixed(0)}`;
}

function signedMoney(value: number | null | undefined): string {
  const amount = Number(value || 0);
  const sign = amount > 0 ? '+' : amount < 0 ? '-' : '';
  return `${sign}¥${Math.abs(amount).toFixed(0)}`;
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
}

function TicketCard({ ticket }: { ticket: BettingTicket }) {
  const pl = ticket.profitLoss;
  const outcome = ticketOutcome(ticket);
  const plColor = pl === null || pl === undefined
    ? 'var(--fqp-text-muted)'
    : pl >= 0 ? 'var(--fqp-success)' : 'var(--fqp-danger, #ef4444)';

  return (
    <details className="lottery-ticket-card" data-outcome={outcome}>
      <summary className="lottery-ticket-summary">
        <span className="lottery-ticket-watermark" aria-hidden="true">
          {ticketOutcomeWatermark(ticket)}
        </span>
        <span className="lottery-ticket-top">
          <span>
            <span className="lottery-ticket-title">{playTypeLabel(ticket.playType)}</span>
          </span>
        </span>

        <span className="lottery-ticket-grid" aria-label="彩票金额摘要">
          <span>
            <span>票面金额</span>
            <strong>{money(ticket.stake)}</strong>
          </span>
          <span>
            <span>比赛编号</span>
            <strong>{ticketPrimaryMatchCode(ticket)}</strong>
          </span>
          <span>
            <span>注数 / 倍数</span>
            <strong>{ticket.betCount ?? '—'} 注 · {ticket.multiple} 倍</strong>
          </span>
        </span>

        <span className="lottery-ticket-foot">
          <span>{ticketPrimaryMatchLabel(ticket)}</span>
          <span className="lottery-expand-cue">
            <span className="lottery-expand-open">展开</span>
            <span className="lottery-expand-close">收起</span>
          </span>
        </span>
      </summary>

      <div className="lottery-ticket-details">
        <div className="lottery-detail-grid">
          <div>
            <span>彩票编号</span>
            <strong>{ticket.ticketUid}</strong>
          </div>
          <div>
            <span>购买日期</span>
            <strong>{ticket.date || '未归档'}</strong>
          </div>
          <div>
            <span>玩法</span>
            <strong>{playTypeLabel(ticket.playType)}</strong>
          </div>
          <div>
            <span>串关</span>
            <strong>{passTypeLabel(ticket.passType)}</strong>
          </div>
        </div>

        <div className="lottery-detail-grid">
          <div>
            <span>投注注数</span>
            <strong>{ticket.betCount ?? '—'}</strong>
          </div>
          <div>
            <span>理论最高</span>
            <strong>{ticket.maxPrize === null ? '—' : money(ticket.maxPrize)}</strong>
          </div>
          <div>
            <span>结算金额</span>
            <strong>{ticket.settledAmount === null ? '—' : money(ticket.settledAmount)}</strong>
          </div>
          <div>
            <span>盈亏 / ROI</span>
            <strong style={{ color: plColor }}>
              {pl === null || pl === undefined ? '—' : `${signedMoney(pl)} / ${pct(ticket.roi)}`}
            </strong>
          </div>
          <div>
            <span>比赛项数</span>
            <strong>{ticket.itemCount} 项</strong>
          </div>
          <div>
            <span>结算时间</span>
            <strong>{ticket.settledAt ? ticket.settledAt.slice(0, 16).replace('T', ' ') : '待比赛完成'}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>{statusLabel(ticket.status)}</strong>
          </div>
        </div>

        {(ticket.items?.length ?? 0) > 0 && (
          <div className="lottery-match-list" aria-label="投注比赛">
            {ticket.items?.map((item) => (
              <div key={`${item.matchId}-${item.playType}-${item.optionCode}`} className="lottery-match-row">
                <span>{item.matchCode}</span>
                <strong style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <TeamName name={item.homeTeam} size={18} /><span>vs</span><TeamName name={item.awayTeam} size={18} />
                </strong>
                <em>{playTypeLabel(item.playType)} · {optionLabel(item.playType, item.optionCode || item.optionName)}{item.spValue ? ` @ ${item.spValue}` : ''}{item.oddsSource === 'synthetic_model' ? ' · 模型估算' : ''}</em>
              </div>
            ))}
          </div>
        )}

        <div className="lottery-detail-note">
          {ticket.source === 'agent_recommendation' && (
            <span>Agent 推荐：{ticket.strategyPool || '默认策略'} · EV {Number(ticket.expectedValue || 0).toFixed(3)} · 分层 {ticket.riskLevel || '—'}</span>
          )}
          <span>{ticketKindLabel(ticket)} · {ticketSourceLabel(ticket)} · {ticketOutcomeLabel(ticket)}</span>
          {ticket.confirmStatus && <span>确认状态：{statusLabel(ticket.confirmStatus)}</span>}
          {ticket.linkedSimulationId && <span>关联投注票：#{ticket.linkedSimulationId}</span>}
          {!ticket.confirmStatus && ticket.source !== 'agent_recommendation' && <span>投注项已在本卡片归档。</span>}
        </div>

      </div>
    </details>
  );
}

function TicketColumn({ title, tickets }: { title: string; tickets: BettingTicket[] }) {
  const stats = calculateLedgerStats(tickets);
  const grouped = groupTicketsByDate(tickets);

  return (
    <section className="lottery-column" aria-label={title}>
      <div className="lottery-column-head">
        <div>
          <h3>{title}</h3>
          <p>{stats.total} 张 · 投入 {money(stats.stake)} · 已结算 {stats.settled}</p>
        </div>
        <div className="lottery-column-pnl">
          <span>盈亏</span>
          <strong style={{ color: stats.profitLoss >= 0 ? 'var(--fqp-success)' : 'var(--fqp-danger, #ef4444)' }}>
            {money(stats.profitLoss)}
          </strong>
        </div>
      </div>

      {grouped.length === 0 ? (
        <EmptyState icon="票" title="暂无彩票" description="投注台确认后会自动进入这里" />
      ) : (
        <div className="lottery-date-list">
          {grouped.map(([date, items]) => (
            <div key={date} className="lottery-date-group">
              <div className="lottery-date-index">
                <span>{date}</span>
                <em>{items.length} 张</em>
              </div>
              <div className="lottery-ticket-stack">
                {items.map((ticket) => <TicketCard key={ticket.ticketUid} ticket={ticket} />)}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function TicketsPage() {
  const [tickets, setTickets] = useState<BettingTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dateFilter, setDateFilter] = useState<DateFilter>('all');
  const [statusFilter, setStatusFilter] = useState('');

  const fetchTickets = () => {
    setLoading(true);
    setError(null);
    api.betting.tickets({ limit: 200 })
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

  const dateOptions = useMemo(
    () => Array.from(new Set(tickets.map((ticket) => ticket.date))).sort((a, b) => b.localeCompare(a)),
    [tickets],
  );

  const filtered = tickets.filter((ticket) => {
    const dateOk = dateFilter === 'all' || ticket.date === dateFilter;
    const statusOk = !statusFilter || ticketOutcome(ticket) === statusFilter;
    return dateOk && statusOk;
  });

  const myTickets = filtered.filter((ticket) => ticket.owner === 'me');
  const agentTickets = filtered.filter((ticket) => ticket.owner === 'agent');
  const stats = calculateLedgerStats(filtered);

  if (loading) return <LoadingSpinner text="加载彩票台账..." size="lg" />;

  return (
    <div>
      <PageHeader
        title="彩票"
        subtitle="按日期归档我的彩票和 Agent 的彩票，统一展示票面、结算、盈亏和 ROI"
        lastUpdated={new Date().toLocaleString('zh-CN', { hour12: false })}
        actions={
          <button className="fqp-btn fqp-btn-primary" onClick={() => navigate('/betting?tab=bet-slip')}>
            去投注台
          </button>
        }
      />

      <div className="lottery-toolbar">
        <div className="lottery-toolbar-stats">
          <span>{stats.total} 张彩票</span>
          <strong>{money(stats.stake)}</strong>
          <em>{stats.settled} 已结算 / {stats.pending} 待结算</em>
        </div>
        <div className="lottery-filters">
          <select className="fqp-select" value={dateFilter} onChange={(e) => setDateFilter(e.target.value)}>
            <option value="all">全部日期</option>
            {dateOptions.map((date) => <option key={date} value={date}>{date}</option>)}
          </select>
          <select className="fqp-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">全部状态</option>
            <option value="won">赢</option>
            <option value="lost">输</option>
            <option value="pending">待结算</option>
          </select>
        </div>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={fetchTickets} />
      ) : (
        <div className="lottery-ledger">
          <TicketColumn title={ticketOwnerLabel('me')} tickets={myTickets} />
          <TicketColumn title={ticketOwnerLabel('agent')} tickets={agentTickets} />
        </div>
      )}
    </div>
  );
}
