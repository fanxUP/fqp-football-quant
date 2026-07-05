import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import type { SimulationTicket, LiveRecommendation } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import FilterBar from '../shared/components/FilterBar';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import StatusBadge from '../shared/components/StatusBadge';
import DisclaimerBanner, { PAGE_DEFAULTS } from '../shared/components/DisclaimerBanner';
import { statusLabel, riskLabel } from '../shared/constants';

export default function RecommendationsPage() {
  const [tickets, setTickets] = useState<SimulationTicket[]>([]);
  const [liveRecs, setLiveRecs] = useState<LiveRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [activePlayTypeTab, setActivePlayTypeTab] = useState('all');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      api.tickets({ limit: 100 }),
      api.liveRecommendations({ limit: 20, min_ev: 0.01 }),
    ])
      .then(([ticketRes, recRes]) => {
        if (!cancelled) {
          setTickets(ticketRes.tickets);
          setLiveRecs(recRes.recommendations || []);
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

  // ---- Play type tabs for live recommendations ----
  const PLAY_TYPE_TABS = [
    { key: 'all',       label: '全部',              playTypes: ['spf', 'rqspf', 'bf', 'zjq', 'bqc'] },
    { key: 'spf_rqspf', label: '胜平负/让球',        playTypes: ['spf', 'rqspf'] },
    { key: 'bf',        label: '比分',               playTypes: ['bf'] },
    { key: 'zjq',       label: '总进球数',            playTypes: ['zjq'] },
    { key: 'bqc',       label: '半全场',              playTypes: ['bqc'] },
  ];
  const filteredLiveRecs = activePlayTypeTab === 'all'
    ? liveRecs
    : liveRecs.filter((r) => {
        const tab = PLAY_TYPE_TABS.find((t) => t.key === activePlayTypeTab);
        return tab ? tab.playTypes.includes(r.play_type) : true;
      });

  const riskBadge = (level: string) => {
    const map: Record<string, 'ok' | 'warning' | 'error'> = {
      low: 'ok',
      medium: 'warning',
      high: 'error',
    };
    return <StatusBadge status={map[level] || 'info'} label={riskLabel(level)} />;
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
      render: (v) => <StatusBadge status={statusBadge(String(v))} label={statusLabel(String(v))} />,
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

  // ---- Charts ----

  const riskDonutOption = (() => {
    if (tickets.length === 0) return null;
    const riskCount: Record<string, number> = {};
    for (const t of tickets) {
      riskCount[t.risk_level] = (riskCount[t.risk_level] || 0) + 1;
    }
    const colorMap: Record<string, string> = { low: '#22c55e', medium: '#f59e0b', high: '#ef4444' };
    const labelMap: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' };

    return {
      tooltip: {
        trigger: 'item' as const,
        formatter: '{b}: {c} 张 ({d}%)',
      },
      series: [
        {
          type: 'pie',
          radius: ['50%', '75%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          label: {
            show: true,
            position: 'outside',
            formatter: '{b}\n{c} 张',
            fontSize: 12,
            lineHeight: 17,
            color: '#F4F5F7',
            fontWeight: 600,
          },
          labelLine: {
            length: 20,
            length2: 32,
            lineStyle: { color: 'rgba(255,255,255,0.12)' },
          },
          data: Object.entries(riskCount).map(([level, count]) => ({
            value: count,
            name: labelMap[level] || level,
            itemStyle: { color: colorMap[level] || '#6b7280' },
          })),
        },
      ],
    };
  })();

  const strategyBarOption = (() => {
    if (tickets.length === 0) return null;
    // Aggregate by strategy_pool
    const pools: Record<string, { count: number; totalEv: number }> = {};
    for (const t of tickets) {
      const p = t.strategy_pool || '未分类';
      if (!pools[p]) pools[p] = { count: 0, totalEv: 0 };
      pools[p].count++;
      pools[p].totalEv += (t.expected_value ?? 0);
    }
    const entries = Object.entries(pools).sort((a, b) => b[1].count - a[1].count);
    const names = entries.map(([k]) => k);
    const counts = entries.map(([, v]) => v.count);
    const avgEvs = entries.map(([, v]) => v.count > 0 ? +(v.totalEv / v.count).toFixed(4) : 0);

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
      },
      legend: {
        data: ['票单数', '平均EV'],
        top: 0,
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '10%',
        top: '40px',
        containLabel: true,
      },
      xAxis: {
        type: 'category' as const,
        data: names,
        axisLabel: { rotate: 30, fontSize: 12 },
      },
      yAxis: [
        {
          type: 'value' as const,
          name: '数量',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        },
        {
          type: 'value' as const,
          name: 'EV',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '票单数',
          type: 'bar',
          data: counts,
          itemStyle: { color: '#3b82f6', borderRadius: [4, 4, 0, 0] },
          barWidth: '50%',
        },
        {
          name: '平均EV',
          type: 'line',
          yAxisIndex: 1,
          data: avgEvs,
          lineStyle: { color: '#f59e0b', width: 2 },
          itemStyle: { color: '#f59e0b' },
          symbol: 'circle',
          symbolSize: 8,
        },
      ],
    };
  })();

  if (error) {
    return (
      <div>
        <PageHeader title="推荐票单" />
      <DisclaimerBanner text={PAGE_DEFAULTS.recommendations} type="page" />
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

      <DisclaimerBanner text={PAGE_DEFAULTS.recommendations} type="page" />

      {/* Live recommendations panel */}
      {!loading && liveRecs.length > 0 && (
        <Card style={{ marginBottom: 20, borderColor: 'rgba(34,197,94,0.30)', animation: 'fqpSlideUpBounce 0.4s ease both' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <span style={{ fontSize: 18, animation: 'fqpNotificationDot 2s infinite', display: 'inline-block' }}>🎯</span>
            <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--fqp-text)' }}>
              实时推荐（基于最新模型预测）
            </span>
            <span style={{ fontSize: 11, color: 'var(--fqp-text-muted)', marginLeft: 4 }}>
              EV &gt; 0.01 · 共 {liveRecs.length} 条
            </span>
          </div>

          {/* 玩法导航标签 */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
            {PLAY_TYPE_TABS.map((tab) => {
              const count = tab.key === 'all'
                ? liveRecs.length
                : liveRecs.filter((r) => tab.playTypes.includes(r.play_type)).length;
              return (
                <button
                  key={tab.key}
                  className={activePlayTypeTab === tab.key ? 'fqp-btn fqp-btn-sm fqp-btn-primary' : 'fqp-btn fqp-btn-sm'}
                  style={{ padding: '4px 14px', fontSize: 12 }}
                  onClick={() => setActivePlayTypeTab(tab.key)}
                >
                  {tab.label}（{count}）
                </button>
              );
            })}
          </div>

          <div className="fqp-table-wrapper">
            <table className="fqp-table" style={{ fontSize: 13 }}>
              <thead>
                <tr>
                  <th>比赛</th>
                  <th>联赛</th>
                  <th>玩法</th>
                  <th>推荐</th>
                  <th>模型概率</th>
                  <th>市场概率</th>
                  <th>Edge</th>
                  <th>EV</th>
                  <th>置信度</th>
                  <th>模型</th>
                </tr>
              </thead>
              <tbody>
                {filteredLiveRecs.map((rec) => (
                  <tr key={rec.prediction_id} className="clickable">
                    <td style={{ fontWeight: 600 }}>
                      {rec.home_team} vs {rec.away_team}
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--fqp-text-muted)' }}>{rec.league}</td>
                    <td>
                      <span
                        style={{
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontSize: 11,
                          fontWeight: 600,
                          background: 'rgba(59,130,246,0.12)',
                          color: 'var(--fqp-info)',
                        }}
                      >
                        {rec.play_type_name}
                      </span>
                    </td>
                    <td>
                      <span
                        style={{
                          fontWeight: 700,
                          fontSize: 14,
                          color: rec.option_code === '3' ? 'var(--fqp-success)'
                            : rec.option_code === '0' ? 'var(--fqp-red-neon)'
                            : 'var(--fqp-warning)',
                        }}
                      >
                        {rec.option_name}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--fqp-text-muted)', marginLeft: 4 }}>
                        @{rec.fair_odds}
                      </span>
                    </td>
                    <td className="fqp-mono" style={{ color: 'var(--fqp-success)' }}>
                      {(rec.model_probability * 100).toFixed(1)}%
                    </td>
                    <td className="fqp-mono" style={{ color: 'var(--fqp-text-muted)' }}>
                      {(rec.market_probability * 100).toFixed(1)}%
                    </td>
                    <td className="fqp-mono">
                      <span style={{ color: rec.edge > 0 ? 'var(--fqp-success)' : 'var(--fqp-red-neon)' }}>
                        {rec.edge >= 0 ? '+' : ''}{(rec.edge * 100).toFixed(1)}%
                      </span>
                    </td>
                    <td className="fqp-mono">
                      <span
                        style={{
                          fontWeight: 700,
                          color: rec.ev > 0.05 ? 'var(--fqp-success)'
                            : rec.ev > 0.02 ? 'var(--fqp-warning)'
                            : 'var(--fqp-text-muted)',
                        }}
                      >
                        +{rec.ev.toFixed(3)}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div
                          style={{
                            width: 40,
                            height: 4,
                            borderRadius: 2,
                            background: 'var(--fqp-panel)',
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              height: '100%',
                              width: `${Math.round(rec.confidence * 100)}%`,
                              background:
                                rec.confidence > 0.6 ? 'var(--fqp-success)'
                                : rec.confidence > 0.4 ? 'var(--fqp-warning)'
                                : 'var(--fqp-red-neon)',
                              borderRadius: 2,
                            }}
                          />
                        </div>
                        <span style={{ fontSize: 11, color: 'var(--fqp-text-muted)' }}>
                          {(rec.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--fqp-text-muted)', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {rec.model_name}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Charts */}
      {!loading && tickets.length > 0 && (
        <div className="fqp-grid-2" style={{ marginBottom: '16px' }}>
          {riskDonutOption ? (
            <ChartCard title="风险等级分布" option={riskDonutOption} height={280} />
          ) : (
            <Card title="风险等级分布">
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            </Card>
          )}
          {strategyBarOption ? (
            <ChartCard title="策略池对比" option={strategyBarOption} height={300} />
          ) : (
            <Card title="策略池对比">
              <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)' }}>暂无数据</div>
            </Card>
          )}
        </div>
      )}

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
