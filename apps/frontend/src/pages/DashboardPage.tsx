import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import type { DailyReview, DashboardRoiDailyItem, DashboardModelPerfItem } from '../core/types';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import StatusBadge from '../shared/components/StatusBadge';
import Skeleton from '../shared/components/Skeleton';
import PageHeader from '../shared/components/PageHeader';
import useBackgroundRefresh from '../shared/hooks/useBackgroundRefresh';
import { RoiLineChart, EmptyChartState, AiPoolDashboard } from '../visualization';
import CommandWorkspace from '../features/command-center/CommandWorkspace';
import { useLiveStatus } from '../features/command-center/LiveStatus';
import useReducedMotion from '../features/command-center/useReducedMotion';

// ---- CountUp: animates a number from 0 to target ----
function CountUp({ value, duration = 600 }: { value: number | null; duration?: number }) {
  const reducedMotion = useReducedMotion();
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (value === null) return;
    if (value <= 0 || reducedMotion) { setDisplay(value); return; }
    const start = performance.now();
    let raf: number;
    const animate = (now: number) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      setDisplay(Math.round(value * eased));
      if (p < 1) raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [value, duration, reducedMotion]);
  return <span>{value === null ? '—' : display.toLocaleString()}</span>;
}

interface DashboardData {
  teamCount: number | null;
  predictionCount: number | null;
  activeTicketCount: number | null;
  ticketLedgerCount: number | null;
  latestReview: string | null;
  loading: boolean;
  errors: Record<string, string>;
}

export default function DashboardPage() {
  const live = useLiveStatus();
  const hasLoadedInitialData = useRef(false);
  const isMounted = useRef(false);
  const [data, setData] = useState<DashboardData>({
    teamCount: null,
    predictionCount: null,
    activeTicketCount: null,
    ticketLedgerCount: null,
    latestReview: null,
    loading: true,
    errors: {},
  });

  // Daily reviews for trend chart
  const [dailyReviews, setDailyReviews] = useState<DailyReview[]>([]);

  // Dashboard API data
  const todayKpis = live.today.data?.kpis ?? [];
  const [roiDaily, setRoiDaily] = useState<DashboardRoiDailyItem[]>([]);
  const [dashLoading, setDashLoading] = useState(false);
  const dashError = live.today.error;
  const [modelPerf, setModelPerf] = useState<DashboardModelPerfItem[]>([]);
  const todayExtras = { current_round_label: live.today.data?.roundLabel ?? null, business_date: live.today.data?.businessDate ?? '' };

  const load = useCallback(async (showLoading = true) => {
    const results: Partial<DashboardData> = { errors: {} };

    const settle = <T,>(
      key: string,
      promise: Promise<T>,
      onOk: (val: T) => void,
    ) =>
      promise
        .then((val) => {
          if (isMounted.current) onOk(val);
        })
        .catch((e) => {
          if (isMounted.current) {
            results.errors = {
              ...results.errors,
              [key]: e instanceof ApiError ? e.message : '请求失败',
            };
          }
        });

    await Promise.all([
      settle('teams', api.teams(), (t) => (results.teamCount = t.total)),
      settle('predictions', api.predictions({ limit: 200 }), (p) => (results.predictionCount = p.total)),
      settle('tickets', api.tickets({ status: 'generated', limit: 50 }), (t) => (results.activeTicketCount = t.total)),
      settle('bettingTickets', api.betting.tickets({ limit: 1 }), (t) => (results.ticketLedgerCount = t.total)),
      settle('reviews', api.reviews.daily(30), (r) => {
        if (r.reviews.length > 0) {
          results.latestReview = r.reviews[0].review_date;
        }
        if (isMounted.current) setDailyReviews(r.reviews);
      }),
    ]);

    // Dashboard API — independent from existing loads
    if (isMounted.current) {
      if (showLoading) setDashLoading(true);
      try {
        const [roiRes, modelRes] = await Promise.all([
          api.dashboard.roiDaily({ days: 30 }).catch(() => null),
          api.dashboard.modelPerformance().catch(() => null),
        ]);
        if (isMounted.current) {
          if (roiRes?.data?.series) setRoiDaily(roiRes.data.series as DashboardRoiDailyItem[]);
          if (modelRes?.data?.series) setModelPerf(modelRes.data.series as DashboardModelPerfItem[]);
        }
      } finally {
        if (isMounted.current && showLoading) setDashLoading(false);
      }
    }

    if (isMounted.current) {
      setData((prev) => ({
        ...prev,
        ...results,
        loading: showLoading ? false : prev.loading,
        errors: results.errors || {},
      }));
    }
  }, []);

  const refreshLive = useCallback(async () => {
    const [ledger, roi, reviews] = await Promise.all([
      api.betting.tickets({ limit: 1 }).catch(() => null),
      api.dashboard.roiDaily({ days: 30 }).catch(() => null),
      api.reviews.daily(30).catch(() => null),
    ]);
    if (!isMounted.current) return;

    setData((prev) => ({
      ...prev,
      ticketLedgerCount: ledger?.total ?? prev.ticketLedgerCount,
      latestReview: reviews?.reviews[0]?.review_date ?? prev.latestReview,
    }));
    if (roi?.data?.series) setRoiDaily(roi.data.series as DashboardRoiDailyItem[]);
    if (reviews?.reviews) setDailyReviews(reviews.reviews);
  }, []);

  useEffect(() => {
    isMounted.current = true;
    if (!hasLoadedInitialData.current) {
      hasLoadedInitialData.current = true;
      void load();
    }
    return () => {
      isMounted.current = false;
    };
  }, [load]);
  useBackgroundRefresh(refreshLive);

  // ---- Chart options ----

  const dailyTrendOption = (() => {
    if (dailyReviews.length === 0) return null;
    // Sort by date ascending
    const sorted = [...dailyReviews].sort((a, b) => a.review_date.localeCompare(b.review_date));
    const dates = sorted.map((r) => r.review_date.slice(5)); // MM-DD
    const profits = sorted.map((r) => r.real_profit_loss);
    // Cumulative profit
    let cum = 0;
    const cumulative = sorted.map((r) => {
      cum += r.real_profit_loss;
      return cum;
    });

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
      },
      legend: {
        data: ['日盈亏', '累计盈亏'],
        top: 0,
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '12%',
        top: '40px',
        containLabel: true,
      },
      xAxis: {
        type: 'category' as const,
        data: dates,
        axisLabel: {
          rotate: 45,
          fontSize: 11,
        },
      },
      yAxis: [
        {
          type: 'value' as const,
          name: '日盈亏 (¥)',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { lineStyle: { color: 'var(--fqp-border-subtle)' } },
        },
        {
          type: 'value' as const,
          name: '累计 (¥)',
          nameTextStyle: { fontSize: 11 },
          axisLabel: { fontSize: 11 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '日盈亏',
          type: 'bar',
          data: profits,
          itemStyle: {
            color: (params: { value: number }) =>
              (params.value >= 0 ? '#22c55e' : '#ef4444'),
          },
        },
        {
          name: '累计盈亏',
          type: 'line',
          yAxisIndex: 1,
          data: cumulative,
          lineStyle: { color: '#3b82f6', width: 2 },
          itemStyle: { color: '#3b82f6' },
          symbol: 'none',
          smooth: true,
        },
      ],
    };
  })();

  // ---- Render helpers ----

  const healthOk = live.health.data?.status === 'ok' && !live.health.error;
  const healthStatus: 'ok' | 'error' | 'info' = healthOk ? 'ok' : live.health.error ? 'error' : 'info';
  const healthLabel = healthOk
    ? `后端正常 — ${live.health.data?.service || 'fqp'}`
    : live.health.error
      ? '后端异常'
      : live.health.loading ? '检测中...' : '后端状态待确认';
  const kpiValue = (key: string) => todayKpis.find((kpi) => kpi.key === key)?.value ?? null;
  const agentStakeToday = kpiValue('ai_stake_today');
  const agentTicketCount = kpiValue('ai_ticket_count');
  const agentPendingCount = kpiValue('pending_settlement_count');
  const budgetUsagePercent = Math.min(((agentStakeToday ?? 0) / 500) * 100, 100);

  return (
    <div>
      <PageHeader title="今日驾驶舱" subtitle="赤焰量化指挥中心 · 真实赛事与决策证据" lastUpdated={live.today.receivedAt ? new Date(live.today.receivedAt).toLocaleString('zh-CN', { hour12: false }) : undefined} />

      {/* System status bar */}
      <Card style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
        <StatusBadge status={healthStatus} label={healthLabel} dot />
        {healthOk && (
          <span className="fqp-notification-dot" style={{ background: 'var(--fqp-success)' }} />
        )}
        {live.health.error && (
          <span style={{ color: 'var(--fqp-red-neon)', fontSize: '12px' }}>{live.health.error}</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
          {(data.teamCount ?? 0) > 0 ? `${data.teamCount} 支球队已映射` : '等待数据采集'}
        </span>
      </Card>

      {/* Stat cards — staggered entrance */}
      <div className="fqp-grid-4" style={{ marginBottom: '24px' }}>
        <Card title="可分析比赛" entranceDelay={0}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">
              <CountUp value={todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? null} />
            </div>
            <div className="fqp-stat-sub">
              {todayKpis.length > 0 ? '场体彩在售 · 模型已预测' : live.today.loading ? '加载中...' : '数据未获取'}
            </div>
          </div>
        </Card>

        <Card title="模型预测" entranceDelay={80}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value"><CountUp value={data.predictionCount} /></div>
            <div className="fqp-stat-sub">
              {data.predictionCount === null ? '数据未获取' : data.predictionCount > 0 ? '条预测结果' : '等待模型计算'}
            </div>
          </div>
        </Card>

        <Card title="活跃推荐" entranceDelay={160}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value"><CountUp value={data.activeTicketCount} /></div>
            <div className="fqp-stat-sub">
              {data.activeTicketCount === null ? '数据未获取' : data.activeTicketCount > 0 ? '张推荐票单待确认' : '暂无活跃推荐'}
            </div>
          </div>
        </Card>

        <Card title="彩票记录" entranceDelay={240}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value"><CountUp value={data.ticketLedgerCount} /></div>
            <div className="fqp-stat-sub">
              {data.ticketLedgerCount === null ? '数据未获取' : data.ticketLedgerCount > 0 ? '张彩票已归档' : '暂无彩票记录'}
            </div>
          </div>
        </Card>
      </div>

      <CommandWorkspace />

      {/* AI资金池 + 盈亏趋势 */}
      <div className="fqp-grid-2" style={{ marginBottom: '24px' }}>
        {/* 智能代理资金池仪表盘 — 取代数据完整度环状图 */}
        <Card title="智能代理资金池">
          <div style={{ padding: '8px 0' }}>
            {/* 大数字：已用 / 总额 */}
            <div style={{ textAlign: 'center', marginBottom: '16px' }}>
              <div style={{ fontSize: '36px', fontWeight: 700, color: 'var(--fqp-text)', fontFamily: "'JetBrains Mono', monospace" }}>
                <CountUp value={agentStakeToday} /> / 500
              </div>
              <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)', marginTop: '4px' }}>
                已使用 ¥{agentStakeToday ?? '—'} / ¥500 （每日预算）
              </div>
            </div>

            {/* 进度条 */}
            <div style={{
              width: '100%', height: '10px',
              background: 'var(--fqp-hover-bg)', borderRadius: '6px',
              overflow: 'hidden', marginBottom: '16px',
            }}>
              <div style={{
                width: `${budgetUsagePercent}%`,
                height: '100%',
                background: 'linear-gradient(90deg, #3B82F6, #FF2A3D)',
                borderRadius: '6px',
                transition: 'width 0.8s cubic-bezier(0.34,1.56,0.64,1)',
              }} />
            </div>

            {/* 关键指标三列 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
              <div style={{ textAlign: 'center', padding: '8px', background: 'var(--fqp-hover-subtle)', borderRadius: '6px' }}>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: '#3B82F6' }}>
                  {agentTicketCount ?? '—'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>票单数</div>
              </div>
              <div style={{ textAlign: 'center', padding: '8px', background: 'var(--fqp-hover-subtle)', borderRadius: '6px' }}>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: '#F5A524' }}>
                  <CountUp value={agentPendingCount} />
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>待开奖</div>
              </div>
              <div style={{ textAlign: 'center', padding: '8px', background: 'var(--fqp-hover-subtle)', borderRadius: '6px' }}>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: '#22C55E' }}>
                  <CountUp value={todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? null} />
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>可分析比赛</div>
              </div>
            </div>
          </div>
        </Card>

        {dailyTrendOption ? (
          <ChartCard title="近期实盘盈亏趋势" option={dailyTrendOption} height={300} />
        ) : (
          <Card title="近期实盘盈亏趋势">
            <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)', fontSize: '13px' }}>
              等待复盘数据...
            </div>
          </Card>
        )}
      </div>

      {/* Risk & Review row */}
      <div className="fqp-grid-2" style={{ marginBottom: '24px' }}>
        <Card title="风控状态">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '8px 0' }}>
            <StatusBadge
              status={agentPendingCount === null ? 'info' : agentPendingCount > 0 ? 'warning' : 'ok'}
              label={agentPendingCount === null ? '风险数据未获取' : agentPendingCount > 0 ? 'R3 中风险' : 'R1 低风险'}
              dot
            />
            <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
              {agentPendingCount === null ? '等待总览数据' : agentPendingCount > 0
                ? `存在 ${agentPendingCount} 张待开奖智能代理票，请关注风险敞口`
                : '系统空闲，无活跃风险敞口'}
            </span>
          </div>
          <div style={{ marginTop: '12px', padding: '10px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
              <span style={{ color: 'var(--fqp-text-muted)' }}>每日预算使用</span>
              <span className="fqp-mono" style={{ color: 'var(--fqp-text)' }}>¥{agentStakeToday ?? '—'} / ¥500</span>
            </div>
            <div
              style={{
                height: '4px',
                background: 'var(--fqp-panel)',
                borderRadius: '2px',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${budgetUsagePercent}%`,
                  background: 'var(--fqp-success)',
                  borderRadius: '2px',
                  transition: 'width 0.5s ease',
                }}
              />
            </div>
          </div>
        </Card>

        <Card title="最新复盘">
          {data.latestReview ? (
            <div style={{ padding: '8px 0' }}>
              <div style={{ fontSize: '14px', fontWeight: 600 }}>📅 {data.latestReview}</div>
              <div style={{ fontSize: '12px', color: 'var(--fqp-text-muted)', marginTop: '4px' }}>
                日报已生成，点击"复盘"查看详情
              </div>
            </div>
          ) : (
            <div style={{ padding: '8px 0', fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
              暂无复盘报告，每日 23:30 自动生成
            </div>
          )}
        </Card>
      </div>

        {/* 驾驶舱图表 — 人工智能与 ROI 对比及资金池使用情况 */}
      <div className="fqp-grid-2" style={{ marginBottom: '24px' }}>
        {roiDaily.length > 0 ? (
          <RoiLineChart
            data={roiDaily.map((d) => ({
              date: d.snapshot_date.slice(5),
              agentRoi: d.agent_cumulative_roi,
              userRoi: d.user_cumulative_roi,
            }))}
            title="累计 ROI 对比"
            height={280}
          />
        ) : (
          <Card title="累计 ROI 对比">
            <EmptyChartState
              icon="📈"
              title={dashLoading ? '加载中...' : '暂无数据'}
              description={dashLoading ? '正在获取 Dashboard 数据' : (dashError || '等待 ROI 数据')}
              height={260}
            />
          </Card>
        )}

        {/* 智能代理资金池综合看板 — 多维度数据 */}
        <Card title="智能代理资金池概览" subtitle="当日策略统计">
          {todayKpis.length > 0 && data.predictionCount !== null && data.activeTicketCount !== null && data.ticketLedgerCount !== null ? <AiPoolDashboard
            kpis={todayKpis}
            models={modelPerf}
            extras={todayExtras}
            pageStats={{
              matchCount: todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? 0,
              predictionCount: data.predictionCount,
              activeTicketCount: data.activeTicketCount,
              ticketLedgerCount: data.ticketLedgerCount,
            }}
            loading={dashLoading}
            error={dashError}
          /> : <p className="cc-muted">{dashError || '总览数据尚未完整获取'}</p>}
        </Card>
      </div>

      {/* System status summary */}
      <Card title="系统状态总览">
        {data.loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <Skeleton variant="card" height={80} count={4} />
              <Skeleton variant="card" height={200} count={2} />
            </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {[
              {
                label: '后端服务',
                ok: healthOk,
                detail: healthOk ? '正常响应' : live.health.error || '未检测',
              },
              {
                label: '球队映射',
                ok: (data.teamCount ?? 0) > 0,
                detail: (data.teamCount ?? 0) > 0 ? `${data.teamCount} 支` : '等待数据采集',
              },
              {
                label: '体彩在售',
                ok: (todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? 0) > 0,
                detail: todayKpis.length > 0
                  ? `${todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? null} 场 · 模型已预测`
                  : '等待体彩数据',
              },
              {
                label: '模型预测',
                ok: (data.predictionCount ?? 0) > 0,
                detail: (data.predictionCount ?? 0) > 0 ? `${data.predictionCount} 条` : '等待模型计算',
              },
              {
                label: '推荐引擎',
                ok: true,
                detail: '就绪',
              },
              {
                label: '复盘生成',
                ok: true,
                detail: data.latestReview ? `最近: ${data.latestReview}` : '就绪，等待首份日报',
              },
            ].map((item, i) => (
              <div
                key={item.label}
                className="fqp-anim-listItemEnter"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: '1px solid var(--fqp-border-light)',
                  animationDelay: `${i * 50}ms`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span
                    className={`fqp-status-dot fqp-status-dot-${item.ok ? 'ok' : 'warning'}`}
                  />
                  <span style={{ fontSize: '13px' }}>{item.label}</span>
                </div>
                <span
                  style={{
                    fontSize: '12px',
                    color: item.ok ? 'var(--fqp-success)' : 'var(--fqp-warning)',
                  }}
                >
                  {item.detail}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
