import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { AgentDailyDecision, BettingResultBucket, BettingResults, BettingTicket } from '../core/types';
import { ApiError } from '../core/types';
import AgentDecisionTimeline from '../features/competition/AgentDecisionTimeline';
import EmptyState from '../shared/components/EmptyState';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import PageHeader from '../shared/components/PageHeader';
import ProfitLossTrendChart from '../visualization/ProfitLossTrendChart';

const RESULTS_REFRESH_INTERVAL_MS = 30_000;

function money(value: number): string {
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function signedMoney(value: number): string {
  return `${value >= 0 ? '+' : '-'}${money(Math.abs(value))}`;
}

function percent(value: number): string {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
}

function pnlColor(value: number): string {
  if (value > 0) return 'var(--fqp-success, #16a34a)';
  if (value < 0) return 'var(--fqp-danger, #dc2626)';
  return 'var(--fqp-text)';
}

function sourceLabel(sourceKey: string): string {
  const [owner, kind, source] = sourceKey.split(':');
  const ownerLabel = owner === 'agent' ? 'Agent' : '我的';
  const kindLabel = kind === 'real' ? '彩票' : '投注票';
  const sourceMap: Record<string, string> = {
    manual: '手动',
    ocr: 'OCR',
    agent_recommendation: '推荐',
  };
  return `${ownerLabel}${kindLabel} · ${sourceMap[source] || source}`;
}

function ticketLabel(ticket: BettingTicket): string {
  const ticketType = ticket.owner === 'agent'
    ? 'Agent票'
    : ticket.kind === 'real' ? '实票' : '投注票';
  return `${ticketType} · ${ticket.ticketNumber}`;
}

function ownerCards(results: BettingResults) {
  const me = results.owners.me;
  const agent = results.owners.agent;
  const diff = me.profitLoss - agent.profitLoss;
  return [
    { label: '我的盈亏', value: signedMoney(me.profitLoss), detail: `投入 ${money(me.stake)} · 回收 ${money(me.settledAmount)}`, color: pnlColor(me.profitLoss) },
    { label: 'Agent 盈亏', value: signedMoney(agent.profitLoss), detail: `投入 ${money(agent.stake)} · 回收 ${money(agent.settledAmount)}`, color: pnlColor(agent.profitLoss) },
    { label: '当前领先', value: results.leader === 'me' ? '我' : results.leader === 'agent' ? 'Agent' : '持平', detail: `差额 ${money(Math.abs(diff))}`, color: results.leader === 'draw' ? 'var(--fqp-text)' : 'var(--fqp-text)' },
    { label: '结算进度', value: `${me.settled + agent.settled}/${me.ticketCount + agent.ticketCount}`, detail: `待结算 ${me.pending + agent.pending} 张 · 命中 ${me.hitCount + agent.hitCount} 张`, color: 'var(--fqp-text)' },
  ];
}

function ResultBucketTable({ rows }: { rows: Array<[string, BettingResultBucket]> }) {
  if (rows.length === 0) {
    return <EmptyState icon="彩票" title="暂无彩票汇总" description="投注或结算后会自动生成彩票统计" />;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="fqp-table" style={{ width: '100%', fontSize: '13px' }}>
        <thead>
          <tr>
            <th>来源</th>
            <th style={{ textAlign: 'right' }}>票数</th>
            <th style={{ textAlign: 'right' }}>投入</th>
            <th style={{ textAlign: 'right' }}>回收</th>
            <th style={{ textAlign: 'right' }}>盈亏</th>
            <th style={{ textAlign: 'right' }}>ROI</th>
            <th style={{ textAlign: 'right' }}>结算</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, bucket]) => (
            <tr key={key}>
              <td style={{ fontWeight: 600 }}>{sourceLabel(key)}</td>
              <td className="fqp-mono" style={{ textAlign: 'right' }}>{bucket.ticketCount}</td>
              <td className="fqp-mono" style={{ textAlign: 'right' }}>{money(bucket.stake)}</td>
              <td className="fqp-mono" style={{ textAlign: 'right' }}>{money(bucket.settledAmount)}</td>
              <td className="fqp-mono" style={{ textAlign: 'right', color: pnlColor(bucket.profitLoss) }}>
                {signedMoney(bucket.profitLoss)}
              </td>
              <td className="fqp-mono" style={{ textAlign: 'right', color: pnlColor(bucket.roi) }}>{percent(bucket.roi)}</td>
              <td className="fqp-mono" style={{ textAlign: 'right' }}>{bucket.settled}/{bucket.ticketCount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TicketRow({ ticket }: { ticket: BettingTicket }) {
  return (
    <tr>
      <td className="fqp-mono" style={{ fontWeight: 600 }}>{ticketLabel(ticket)}</td>
      <td>{ticket.owner === 'agent' ? 'Agent' : '我的'}</td>
      <td>{ticket.kind === 'real' ? '彩票' : '投注票'}</td>
      <td className="fqp-mono">{ticket.date}</td>
      <td className="fqp-mono" style={{ textAlign: 'right' }}>{money(ticket.stake)}</td>
      <td className="fqp-mono" style={{ textAlign: 'right' }}>
        {ticket.settledAmount === null ? '-' : money(ticket.settledAmount)}
      </td>
      <td className="fqp-mono" style={{ textAlign: 'right', color: pnlColor(ticket.profitLoss || 0) }}>
        {ticket.profitLoss === null ? '-' : signedMoney(ticket.profitLoss)}
      </td>
      <td>{ticket.status === 'settled' ? '已结算' : '待结算'}</td>
    </tr>
  );
}

export default function CompetitionPage() {
  const [results, setResults] = useState<BettingResults | null>(null);
  const [tickets, setTickets] = useState<BettingTicket[]>([]);
  const [decisions, setDecisions] = useState<AgentDailyDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchResults = useCallback((showLoading = true) => {
    if (showLoading) {
      setLoading(true);
      setError(null);
    }
    Promise.all([
      api.betting.results({ limit: 300 }),
      api.betting.tickets({ limit: 80 }),
      api.competition.decisions(14),
    ])
      .then(([resultRes, ticketRes, decisionRes]) => {
        setResults(resultRes);
        setTickets(ticketRes.tickets || []);
        setDecisions(decisionRes.decisions || []);
        setError(null);
      })
      .catch((e) => {
        if (showLoading) {
          setError(e instanceof ApiError ? e.message : '比赛结果加载失败');
        }
      })
      .finally(() => {
        if (showLoading) setLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchResults();
    const timer = window.setInterval(() => fetchResults(false), RESULTS_REFRESH_INTERVAL_MS);
    const refreshOnFocus = () => fetchResults(false);
    window.addEventListener('focus', refreshOnFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', refreshOnFocus);
    };
  }, [fetchResults]);

  if (loading) return <LoadingSpinner text="加载比赛结果..." size="lg" />;

  if (error) {
    return (
      <div>
        <PageHeader title="比赛结果" />
        <ErrorState message={error} onRetry={() => fetchResults()} />
      </div>
    );
  }

  if (!results) {
    return <EmptyState icon="结果" title="暂无比赛结果" />;
  }

  const cards = ownerCards(results);
  const sourceRows = Object.entries(results.bySource).sort((a, b) => b[1].stake - a[1].stake);
  const recentTickets = tickets.slice(0, 12);

  return (
    <div>
      <PageHeader
        title="比赛结果"
        subtitle="汇总投注台、我的彩票、Agent 彩票与推荐票的结算盈亏"
        actions={(
          <button className="fqp-btn fqp-btn-secondary" onClick={() => navigate('/betting?tab=tickets')}>
            查看彩票
          </button>
        )}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 16 }}>
        {cards.map((card) => (
          <div key={card.label} className="fqp-card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, color: 'var(--fqp-text-muted)', marginBottom: 8 }}>{card.label}</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: card.color }}>{card.value}</div>
            <div style={{ fontSize: 12, color: 'var(--fqp-text-muted)', marginTop: 6 }}>{card.detail}</div>
          </div>
        ))}
      </div>

      <div style={{ marginBottom: 16 }}>
        <ProfitLossTrendChart
          data={results.trend}
          updatedAt={results.updatedAt ? results.updatedAt.replace('T', ' ').slice(0, 16) : undefined}
        />
      </div>

      <div className="fqp-card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>Agent 每日决策</div>
        <div style={{ fontSize: 12, color: 'var(--fqp-text-muted)', marginBottom: 12 }}>
          只记录系统内虚拟购买；放弃投注也会保留门槛原因
        </div>
        <AgentDecisionTimeline decisions={decisions} />
      </div>

      <div className="fqp-card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ fontWeight: 700, marginBottom: 12 }}>彩票汇总</div>
        <ResultBucketTable rows={sourceRows} />
      </div>

      <div className="fqp-card" style={{ padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontWeight: 700 }}>彩票投注列表</div>
          <button className="fqp-btn" onClick={() => navigate('/betting?tab=bet-slip')}>打开投注台</button>
        </div>
        {recentTickets.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="fqp-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr>
                  <th>票据</th>
                  <th>归属</th>
                  <th>类型</th>
                  <th>日期</th>
                  <th style={{ textAlign: 'right' }}>投入</th>
                  <th style={{ textAlign: 'right' }}>回收</th>
                  <th style={{ textAlign: 'right' }}>盈亏</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {recentTickets.map((ticket) => <TicketRow key={ticket.ticketUid} ticket={ticket} />)}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon="彩票" title="暂无彩票" description="在投注台提交或导入 OCR 彩票后会出现在这里" />
        )}
      </div>
    </div>
  );
}
