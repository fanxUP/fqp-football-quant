import { useEffect, useState, useRef } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { CompetitionRound, CompetitionTicket, CompetitionTicketItem, CompetitionTrendPoint } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import EmptyState from '../shared/components/EmptyState';
import { RoiLineChart, DrawdownChart } from '../visualization';

function formatPct(v: number): string {
  const pct = v * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function formatMoney(v: number): string {
  return `¥${v.toFixed(2)}`;
}

function roiColor(v: number): string {
  if (v > 0) return 'var(--fqp-ok, #22c55e)';
  if (v < 0) return 'var(--fqp-error, #ef4444)';
  return 'var(--fqp-text-muted, #888)';
}

// ── Simple SVG ROI trend chart ──

function RoiTrendChart({ data }: { data: CompetitionTrendPoint[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Trigger line-draw animation after mount
    const t = setTimeout(() => setMounted(true), 200);
    return () => clearTimeout(t);
  }, []);

  if (!data || data.length < 1) {
    return <EmptyState icon="📉" title="暂无趋势数据" description="等待每日快照生成" />;
  }

  const W = 600;
  const H = 280;
  const PAD = { top: 20, right: 20, bottom: 40, left: 50 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  // Find min/max across both series
  let minVal = 0, maxVal = 0;
  data.forEach(d => {
    [d.agent_cumulative_roi, d.user_cumulative_roi].forEach(v => {
      if (v < minVal) minVal = v;
      if (v > maxVal) maxVal = v;
    });
  });
  // Add padding
  const range = maxVal - minVal || 0.1;
  minVal -= range * 0.1;
  maxVal += range * 0.1;

  const xScale = (i: number) => PAD.left + (i / Math.max(data.length - 1, 1)) * plotW;
  const yScale = (v: number) => PAD.top + plotH - ((v - minVal) / (maxVal - minVal)) * plotH;

  // Build polyline points for each series
  const agentPts = data.map((d, i) => `${xScale(i)},${yScale(d.agent_cumulative_roi)}`).join(' ');
  const userPts = data.map((d, i) => `${xScale(i)},${yScale(d.user_cumulative_roi)}`).join(' ');

  // Y-axis ticks
  const yTicks = 5;
  const yTickVals = Array.from({ length: yTicks }, (_, i) =>
    minVal + (i / (yTicks - 1)) * (maxVal - minVal)
  );

  // Total line length for stroke-dasharray animation
  const totalLen = 800;

  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', maxHeight: '300px' }}>
      {/* Grid lines */}
      {yTickVals.map((v, i) => (
        <g key={`grid-${i}`}>
          <line x1={PAD.left} y1={yScale(v)} x2={W - PAD.right} y2={yScale(v)}
            stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" />
          <text x={PAD.left - 6} y={yScale(v) + 4} textAnchor="end"
            fill="var(--fqp-text-muted)" fontSize="9">
            {formatPct(v)}
          </text>
        </g>
      ))}

      {/* Zero line */}
      {minVal < 0 && maxVal > 0 && (
        <line x1={PAD.left} y1={yScale(0)} x2={W - PAD.right} y2={yScale(0)}
          stroke="rgba(255,255,255,0.15)" strokeWidth="1" strokeDasharray="4,3" />
      )}

      {/* X-axis labels */}
      {data.map((d, i) => (
        <text key={`x-${i}`} x={xScale(i)} y={H - PAD.bottom + 18} textAnchor="middle"
          fill="var(--fqp-text-muted)" fontSize="9">
          {(d.snapshot_date || '').slice(5)}
        </text>
      ))}

      {/* Agent line — animated draw */}
      <polyline points={agentPts} fill="none" stroke="#3b82f6" strokeWidth="2"
        strokeLinejoin="round" strokeLinecap="round"
        strokeDasharray={totalLen}
        strokeDashoffset={mounted ? 0 : totalLen}
        style={{ transition: 'stroke-dashoffset 1.5s ease-in-out' }}
      />
      {data.map((d, i) => (
        <circle key={`a-${i}`} cx={xScale(i)} cy={yScale(d.agent_cumulative_roi)}
          r="3" fill="#3b82f6" />
      ))}

      {/* User line — animated draw */}
      <polyline points={userPts} fill="none" stroke="#f59e0b" strokeWidth="2"
        strokeLinejoin="round" strokeLinecap="round"
        strokeDasharray={totalLen}
        strokeDashoffset={mounted ? 0 : totalLen}
        style={{ transition: 'stroke-dashoffset 1.5s ease-in-out 0.3s' }}
      />
      {data.map((d, i) => (
        <circle key={`u-${i}`} cx={xScale(i)} cy={yScale(d.user_cumulative_roi)}
          r="3" fill="#f59e0b" />
      ))}
    </svg>
  );
}

// ── Main page ──

export default function CompetitionPage() {
  const [round, setRound] = useState<CompetitionRound | null>(null);
  const [tickets, setTickets] = useState<CompetitionTicket[]>([]);
  const [ticketTotal, setTicketTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chartView, setChartView] = useState<'svg' | 'echarts'>('svg');

  const fetchCurrent = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.competition.currentRound(),
      api.competition.currentTickets(),
    ])
      .then(([roundRes, ticketRes]) => {
        setRound(roundRes);
        setTickets(ticketRes.tickets || []);
        setTicketTotal(ticketRes.total_stake || 0);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => { fetchCurrent(); }, []);

  if (loading) return <LoadingSpinner text="加载竞赛数据..." size="lg" />;
  if (error) return (
    <div>
      <PageHeader title="对抗竞赛" />
      <ErrorState message={error} onRetry={fetchCurrent} />
    </div>
  );

  if (!round) return <EmptyState icon="⚔️" title="暂无竞赛数据" />;

  const trend = round.trend || [];
  const leader = round.agent_roi > round.user_roi ? 'agent'
    : round.user_roi > round.agent_roi ? 'user' : 'draw';

  return (
    <div>
      <PageHeader
        title="对抗竞赛"
        subtitle={`${round.round_label} · ${round.round_start} → ${round.round_end}`}
      />

      {/* Summary cards — staggered entrance */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
        {[
          { icon: '🤖', label: 'Agent 累计ROI', value: formatPct(round.agent_roi), color: roiColor(round.agent_roi), detail: `投入 ${formatMoney(round.agent_total_stake)} · 回报 ${formatMoney(round.agent_total_prize)}` },
          { icon: '🧑', label: '用户 累计ROI', value: formatPct(round.user_roi), color: roiColor(round.user_roi), detail: `投入 ${formatMoney(round.user_total_stake)} · 回报 ${formatMoney(round.user_total_prize)}` },
          { icon: '👑', label: '当前领先', value: leader === 'agent' ? '🤖 Agent' : leader === 'user' ? '🧑 用户' : '🤝 平局', color: 'var(--fqp-text)', detail: '' },
          { icon: '📅', label: '剩余天数', value: `${round.days_remaining ?? '—'} / ${round.total_days ?? '—'}`, color: 'var(--fqp-text)', detail: round.status === 'active' ? '进行中' : '已结束' },
        ].map((card, i) => (
          <div
            key={card.label}
            className="fqp-card"
            style={{
              textAlign: 'center',
              padding: '16px',
              animation: `fqpCardEnter 0.4s ease both`,
              animationDelay: `${i * 100}ms`,
            }}
          >
            <div style={{ fontSize: '12px', color: 'var(--fqp-text-muted)', marginBottom: '6px' }}>{card.icon} {card.label}</div>
            <div style={{ fontSize: '24px', fontWeight: 700, color: card.color }}>
              {card.value}
            </div>
            {card.detail && (
              <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', marginTop: '4px' }}>
                {card.detail}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ROI trend chart */}
      <div className="fqp-card" style={{ marginBottom: '20px', padding: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '12px' }}>
          <span style={{ fontWeight: 600, fontSize: '14px' }}>📈 ROI 趋势</span>
          <span style={{ fontSize: '11px', color: '#3b82f6' }}>● Agent</span>
          <span style={{ fontSize: '11px', color: '#f59e0b' }}>● 用户</span>
          <button
            className={`fqp-btn`}
            style={{ marginLeft: 'auto', padding: '2px 10px', fontSize: '11px' }}
            onClick={() => setChartView(chartView === 'svg' ? 'echarts' : 'svg')}
          >
            {chartView === 'svg' ? '切换到 ECharts' : '切换到 SVG'}
          </button>
        </div>
        {chartView === 'svg' ? (
          <RoiTrendChart data={trend} />
        ) : (
          <RoiLineChart
            data={trend.map((d) => ({
              date: d.snapshot_date.slice(5),
              agentRoi: d.agent_cumulative_roi,
              userRoi: d.user_cumulative_roi,
            }))}
            title=""
            height={280}
          />
        )}
      </div>

      {/* Daily breakdown table */}
      <div className="fqp-card" style={{ padding: '16px' }}>
        <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '12px' }}>📋 每日明细</div>
        {round.snapshots && round.snapshots.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="fqp-table" style={{ width: '100%', fontSize: '13px' }}>
              <thead>
                <tr>
                  <th>日期</th>
                  <th colSpan={3} style={{ textAlign: 'center', borderRight: '1px solid var(--fqp-border)' }}>🤖 Agent</th>
                  <th colSpan={3} style={{ textAlign: 'center' }}>🧑 用户</th>
                </tr>
                <tr>
                  <th></th>
                  <th>投入</th>
                  <th>回报</th>
                  <th style={{ borderRight: '1px solid var(--fqp-border)' }}>累计ROI</th>
                  <th>投入</th>
                  <th>回报</th>
                  <th>累计ROI</th>
                </tr>
              </thead>
              <tbody>
                {round.snapshots.map((s, i) => (
                  <tr key={s.id} className="fqp-anim-listItemEnter" style={{ animationDelay: `${i * 50}ms` }}>
                    <td style={{ fontWeight: 500 }}>{s.snapshot_date}</td>
                    <td className="fqp-mono">{formatMoney(s.agent_daily_stake)}</td>
                    <td className="fqp-mono">{formatMoney(s.agent_daily_prize)}</td>
                    <td className="fqp-mono" style={{ color: roiColor(s.agent_cumulative_roi), borderRight: '1px solid var(--fqp-border)' }}>
                      {formatPct(s.agent_cumulative_roi)}
                    </td>
                    <td className="fqp-mono">{formatMoney(s.user_daily_stake)}</td>
                    <td className="fqp-mono">{formatMoney(s.user_daily_prize)}</td>
                    <td className="fqp-mono" style={{ color: roiColor(s.user_cumulative_roi) }}>
                      {formatPct(s.user_cumulative_roi)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon="📋" title="暂无每日快照" description="快照每天23:50自动生成" />
        )}
      </div>

      {/* Agent ticket details */}
      <div className="fqp-card" style={{ marginTop: '20px', padding: '16px' }}>
        <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '12px' }}>
          🎫 Agent 今日投注 {tickets.length > 0 && <span style={{ fontWeight: 400, color: 'var(--fqp-text-muted)', fontSize: '12px' }}>· 共 {tickets.length} 张票 · 合计 {formatMoney(ticketTotal)}</span>}
        </div>
        {tickets.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="fqp-table" style={{ width: '100%', fontSize: '13px' }}>
              <thead>
                <tr>
                  <th>类型</th>
                  <th>赛事</th>
                  <th>开赛</th>
                  <th>选项</th>
                  <th>赔率</th>
                  <th>金额</th>
                  <th>池</th>
                  <th>EV</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => {
                  const isParlay = t.pass_type === '2x1' || t.pass_type === '3x1';
                  const combinedSp = t.items.reduce((prod, item) => prod * item.sp_value, 1);
                  return (
                    <tr key={t.id} style={isParlay ? { borderLeft: '3px solid var(--fqp-accent, #6366f1)' } : undefined}>
                      <td>
                        <span style={{
                          display: 'inline-block', padding: '1px 6px', borderRadius: '3px',
                          fontSize: '11px', fontWeight: 700,
                          background: isParlay ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.06)',
                          color: isParlay ? '#818cf8' : 'var(--fqp-text-muted)',
                        }}>
                          {t.pass_type === '2x1' ? '2串1' : t.pass_type === '3x1' ? '3串1' : '单关'}
                        </span>
                      </td>
                      <td style={{ maxWidth: '200px' }}>
                        {t.items.map((item: CompetitionTicketItem, i: number) => (
                          <div key={item.item_id} style={{
                            padding: i > 0 ? '3px 0 0 0' : '0',
                            borderTop: i > 0 ? '1px solid rgba(255,255,255,0.06)' : 'none',
                            marginTop: i > 0 ? '2px' : '0',
                          }}>
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                              {item.home_team} vs {item.away_team}
                            </span>
                            <span style={{ fontSize: '10px', color: 'var(--fqp-text-muted)' }}>{item.league}</span>
                          </div>
                        ))}
                      </td>
                      <td style={{ fontSize: '11px' }}>
                        {t.items.map((item: CompetitionTicketItem, i: number) => (
                          <div key={item.item_id} style={{ padding: i > 0 ? '3px 0 0 0' : '0' }}>
                            {item.kickoff_time ? item.kickoff_time.slice(5, 16).replace('T', ' ') : '—'}
                          </div>
                        ))}
                      </td>
                      <td>
                        {t.items.map((item: CompetitionTicketItem, i: number) => (
                          <div key={item.item_id} style={{ padding: i > 0 ? '2px 0 0 0' : '0' }}>
                            <span style={{
                              display: 'inline-block', padding: '1px 6px', borderRadius: '3px',
                              fontSize: '11px', fontWeight: 600,
                              background: item.option_code === '3' ? 'rgba(239,68,68,0.15)' :
                                          item.option_code === '1' ? 'rgba(245,158,11,0.15)' :
                                          'rgba(34,197,94,0.15)',
                              color: item.option_code === '3' ? '#ef4444' :
                                     item.option_code === '1' ? '#f59e0b' : '#22c55e',
                            }}>
                              {item.option_name}
                            </span>
                          </div>
                        ))}
                      </td>
                      <td className="fqp-mono" style={{ fontWeight: 600, color: 'var(--fqp-accent)' }}>
                        {isParlay ? (
                          <div>
                            <span style={{ fontSize: '13px' }}>{combinedSp.toFixed(2)}</span>
                            <div style={{ fontSize: '10px', color: 'var(--fqp-text-muted)' }}>
                              {t.items.map((item: CompetitionTicketItem) => item.sp_value.toFixed(2)).join(' × ')}
                            </div>
                          </div>
                        ) : (
                          t.items[0]?.sp_value.toFixed(2)
                        )}
                      </td>
                      <td className="fqp-mono" style={{ fontWeight: 600 }}>
                        {formatMoney(t.stake)}
                      </td>
                      <td style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                        {t.strategy_pool.replace('agent_', '')}
                      </td>
                      <td className="fqp-mono" style={{
                        color: t.ev > 0 ? 'var(--fqp-ok, #22c55e)' : 'var(--fqp-text-muted)',
                        fontSize: '12px',
                      }}>
                        {t.ev > 0 ? '+' : ''}{t.ev.toFixed(4)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon="🎫" title="暂无投注" description="Agent 每日 16:00 自动生成推荐" />
        )}
      </div>

      {/* History link */}
      <div style={{ marginTop: '16px', textAlign: 'center' }}>
        <button
          className="fqp-btn fqp-btn-ghost"
          onClick={() => navigate('/competition/history')}
        >
          📜 查看历史竞赛记录 →
        </button>
      </div>
    </div>
  );
}
