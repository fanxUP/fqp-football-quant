import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import type { DailyReview, DashboardRoiDailyItem, DashboardTodayKpi, DashboardModelPerfItem } from '../core/types';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import StatusBadge from '../shared/components/StatusBadge';
import Skeleton from '../shared/components/Skeleton';
import PageHeader from '../shared/components/PageHeader';
import DisclaimerBanner, { PAGE_DEFAULTS } from '../shared/components/DisclaimerBanner';
import { RoiLineChart, EmptyChartState, AiPoolDashboard } from '../visualization';

// ---- CountUp: animates a number from 0 to target ----
function CountUp({ value, duration = 600 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    if (value <= 0) { setDisplay(0); return; }
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
  }, [value, duration]);
  return <span>{display.toLocaleString()}</span>;
}

interface HealthInfo {
  status: string;
  service?: string;
}

interface DashboardData {
  health: HealthInfo | null;
  healthError: string | null;
  teamCount: number;
  predictionCount: number;
  activeTicketCount: number;
  realTicketCount: number;
  latestReview: string | null;
  loading: boolean;
  errors: Record<string, string>;
}

function fmtTime(): string {
  return new Date().toLocaleString('zh-CN', { hour12: false });
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData>({
    health: null,
    healthError: null,
    teamCount: 0,
    predictionCount: 0,
    activeTicketCount: 0,
    realTicketCount: 0,
    latestReview: null,
    loading: true,
    errors: {},
  });

  // Daily reviews for trend chart
  const [dailyReviews, setDailyReviews] = useState<DailyReview[]>([]);

  // Dashboard API data
  const [todayKpis, setTodayKpis] = useState<DashboardTodayKpi[]>([]);
  const [roiDaily, setRoiDaily] = useState<DashboardRoiDailyItem[]>([]);
  const [dashLoading, setDashLoading] = useState(false);
  const [dashError, setDashError] = useState<string | null>(null);
  const [modelPerf, setModelPerf] = useState<DashboardModelPerfItem[]>([]);
  const [todayExtras, setTodayExtras] = useState<{ current_round_label: string | null; business_date: string }>({
    current_round_label: null,
    business_date: '',
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const results: Partial<DashboardData> = { errors: {} };

      const settle = <T,>(
        key: string,
        promise: Promise<T>,
        onOk: (val: T) => void,
      ) =>
        promise
          .then((val) => {
            if (!cancelled) onOk(val);
          })
          .catch((e) => {
            if (!cancelled) {
              results.errors = {
                ...results.errors,
                [key]: e instanceof ApiError ? e.message : '请求失败',
              };
            }
          });

      await Promise.all([
        settle('health', api.health(), (h) => (results.health = h)),
        settle('teams', api.teams(), (t) => (results.teamCount = t.total)),
        settle('predictions', api.predictions({ limit: 200 }), (p) => (results.predictionCount = p.total)),
        settle('tickets', api.tickets({ status: 'generated', limit: 50 }), (t) => (results.activeTicketCount = t.total)),
        settle('realTickets', api.realTickets.list({ limit: 50 }), (t) => (results.realTicketCount = t.total)),
        settle('reviews', api.reviews.daily(30), (r) => {
          if (r.reviews.length > 0) {
            results.latestReview = r.reviews[0].review_date;
          }
          if (!cancelled) setDailyReviews(r.reviews);
        }),
      ]);

      // Dashboard API — independent from existing loads
      if (!cancelled) {
        setDashLoading(true);
        try {
          const [todayRes, roiRes, modelRes] = await Promise.all([
            api.dashboard.today().catch(() => null),
            api.dashboard.roiDaily({ days: 30 }).catch(() => null),
            api.dashboard.modelPerformance().catch(() => null),
          ]);
          if (!cancelled) {
            if (todayRes?.data?.kpis) setTodayKpis(todayRes.data.kpis);
            if (todayRes?.data?.extras) setTodayExtras({
              current_round_label: todayRes.data.extras.current_round_label,
              business_date: todayRes.data.extras.business_date,
            });
            if (roiRes?.data?.series) setRoiDaily(roiRes.data.series as DashboardRoiDailyItem[]);
            if (modelRes?.data?.series) setModelPerf(modelRes.data.series as DashboardModelPerfItem[]);
          }
        } catch {
          if (!cancelled) setDashError('Dashboard API 异常');
        } finally {
          if (!cancelled) setDashLoading(false);
        }
      }

      if (!cancelled) {
        setData((prev) => ({
          ...prev,
          ...results,
          loading: false,
          errors: results.errors || {},
        }));
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

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
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
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

  const healthOk = data.health?.status === 'ok';
  const healthStatus: 'ok' | 'error' = healthOk ? 'ok' : 'error';
  const healthLabel = healthOk
    ? `后端正常 — ${data.health?.service || 'fqp'}`
    : data.healthError
      ? '后端异常'
      : '检测中...';

  return (
    <div>
      <PageHeader title="今日驾驶舱" lastUpdated={fmtTime()} />
      <DisclaimerBanner text={PAGE_DEFAULTS.dashboard} type="page" />

      {/* System status bar */}
      <Card style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
        <StatusBadge status={healthStatus} label={healthLabel} dot />
        {healthOk && (
          <span className="fqp-notification-dot" style={{ background: 'var(--fqp-success)' }} />
        )}
        {data.healthError && (
          <span style={{ color: 'var(--fqp-red-neon)', fontSize: '12px' }}>{data.healthError}</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
          {data.teamCount > 0 ? `${data.teamCount} 支球队已映射` : '等待数据采集'}
        </span>
      </Card>

      {/* Stat cards — staggered entrance */}
      <div className="fqp-grid-4" style={{ marginBottom: '24px' }}>
        <Card title="可分析比赛" entranceDelay={0}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">
              <CountUp value={todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? 0} />
            </div>
            <div className="fqp-stat-sub">
              {todayKpis.length > 0 ? '场体彩在售 · 模型已预测' : '加载中...'}
            </div>
          </div>
        </Card>

        <Card title="模型预测" entranceDelay={80}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value"><CountUp value={data.predictionCount} /></div>
            <div className="fqp-stat-sub">
              {data.predictionCount > 0 ? '条预测结果' : '等待模型计算'}
            </div>
          </div>
        </Card>

        <Card title="活跃推荐" entranceDelay={160}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value"><CountUp value={data.activeTicketCount} /></div>
            <div className="fqp-stat-sub">
              {data.activeTicketCount > 0 ? '张推荐票单待确认' : '暂无活跃推荐'}
            </div>
          </div>
        </Card>

        <Card title="实票记录" entranceDelay={240}>
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value"><CountUp value={data.realTicketCount} /></div>
            <div className="fqp-stat-sub">
              {data.realTicketCount > 0 ? '张实票已录入' : '暂无实票记录'}
            </div>
          </div>
        </Card>
      </div>

      {/* AI资金池 + 盈亏趋势 */}
      <div className="fqp-grid-2" style={{ marginBottom: '24px' }}>
        {/* AI 虚拟资金池仪表盘 — 取代数据完整度环状图 */}
        <Card title="AI 虚拟资金池">
          <div style={{ padding: '8px 0' }}>
            {/* 大数字：已用 / 总额 */}
            <div style={{ textAlign: 'center', marginBottom: '16px' }}>
              <div style={{ fontSize: '36px', fontWeight: 700, color: 'var(--fqp-text)', fontFamily: "'JetBrains Mono', monospace" }}>
                <CountUp value={data.activeTicketCount * 2} /> / 500
              </div>
              <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)', marginTop: '4px' }}>
                已使用 ¥{data.activeTicketCount * 2} / ¥500 （每日预算）
              </div>
            </div>

            {/* 进度条 */}
            <div style={{
              width: '100%', height: '10px',
              background: 'rgba(255,255,255,0.06)', borderRadius: '6px',
              overflow: 'hidden', marginBottom: '16px',
            }}>
              <div style={{
                width: `${Math.min((data.activeTicketCount * 2 / 500) * 100, 100)}%`,
                height: '100%',
                background: 'linear-gradient(90deg, #3B82F6, #FF2A3D)',
                borderRadius: '6px',
                transition: 'width 0.8s cubic-bezier(0.34,1.56,0.64,1)',
              }} />
            </div>

            {/* 关键指标三列 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
              <div style={{ textAlign: 'center', padding: '8px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: '#3B82F6' }}>
                  {data.activeTicketCount}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>票单数</div>
              </div>
              <div style={{ textAlign: 'center', padding: '8px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: '#F5A524' }}>
                  <CountUp value={data.predictionCount} />
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>待开奖</div>
              </div>
              <div style={{ textAlign: 'center', padding: '8px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                <div className="fqp-mono" style={{ fontSize: '18px', fontWeight: 700, color: '#22C55E' }}>
                  <CountUp value={todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? 0} />
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
              status={data.activeTicketCount > 0 ? 'warning' : 'ok'}
              label={data.activeTicketCount > 0 ? 'R3 中风险' : 'R1 低风险'}
              dot
            />
            <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
              {data.activeTicketCount > 0
                ? '存在活跃推荐，建议核实赔率有效性'
                : '系统空闲，无活跃风险敞口'}
            </span>
          </div>
          <div style={{ marginTop: '12px', padding: '10px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
              <span style={{ color: 'var(--fqp-text-muted)' }}>每日预算使用</span>
              <span className="fqp-mono" style={{ color: 'var(--fqp-text)' }}>¥0 / ¥500</span>
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
                  width: '0%',
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

      {/* Dashboard API Charts — AI vs ROI comparison + pool usage */}
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

        {/* AI 虚拟池综合看板 — 多维度数据 */}
        <Card title="AI 虚拟池概览" subtitle="当日模拟统计">
          <AiPoolDashboard
            kpis={todayKpis}
            models={modelPerf}
            extras={todayExtras}
            pageStats={{
              matchCount: todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? data.matchCount,
              predictionCount: data.predictionCount,
              activeTicketCount: data.activeTicketCount,
              realTicketCount: data.realTicketCount,
            }}
            loading={dashLoading}
            error={dashError}
          />
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
                detail: healthOk ? '正常响应' : data.healthError || '未检测',
              },
              {
                label: '球队映射',
                ok: data.teamCount > 0,
                detail: data.teamCount > 0 ? `${data.teamCount} 支` : '等待数据采集',
              },
              {
                label: '体彩在售',
                ok: (todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? 0) > 0,
                detail: todayKpis.length > 0
                  ? `${todayKpis.find(k => k.key === 'predicted_match_count')?.value ?? 0} 场 · 模型已预测`
                  : '等待体彩数据',
              },
              {
                label: '模型预测',
                ok: data.predictionCount > 0,
                detail: data.predictionCount > 0 ? `${data.predictionCount} 条` : '等待模型计算',
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
                  borderBottom: '1px solid rgba(39,39,42,0.3)',
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
