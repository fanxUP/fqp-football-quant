import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import type { DailyReview } from '../core/types';
import Card from '../shared/components/Card';
import ChartCard from '../shared/components/ChartCard';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import ErrorState from '../shared/components/ErrorState';
import PageHeader from '../shared/components/PageHeader';
import DisclaimerBanner, { PAGE_DEFAULTS } from '../shared/components/DisclaimerBanner';

interface HealthInfo {
  status: string;
  service?: string;
}

interface DashboardData {
  health: HealthInfo | null;
  healthError: string | null;
  teamCount: number;
  matchCount: number;
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
    matchCount: 0,
    predictionCount: 0,
    activeTicketCount: 0,
    realTicketCount: 0,
    latestReview: null,
    loading: true,
    errors: {},
  });

  // Completeness buckets from features
  const [completenessBuckets, setCompletenessBuckets] = useState<{ low: number; mid: number; high: number }>({ low: 0, mid: 0, high: 0 });

  // Daily reviews for trend chart
  const [dailyReviews, setDailyReviews] = useState<DailyReview[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const results: Partial<DashboardData> = { errors: {} };

      // Collect snapshots for completeness chart
      let snapshots: { data_completeness_score: number | null }[] = [];

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
        settle('features', api.features({ limit: 200 }), (f) => {
          const ids = new Set(f.snapshots.map((s) => s.match_id));
          results.matchCount = ids.size;
          snapshots = f.snapshots;
        }),
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

      // Compute completeness buckets
      if (!cancelled) {
        let low = 0, mid = 0, high = 0;
        for (const s of snapshots) {
          const score = s.data_completeness_score;
          if (score === null) continue;
          if (score < 0.5) low++;
          else if (score < 0.8) mid++;
          else high++;
        }
        setCompletenessBuckets({ low, mid, high });

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

  const completenessDonutOption = (() => {
    const { low, mid, high } = completenessBuckets;
    const total = low + mid + high;
    if (total === 0) return null;

    return {
      tooltip: {
        trigger: 'item' as const,
        formatter: '{b}: {c} 场 ({d}%)',
      },
      series: [
        {
          type: 'pie',
          radius: ['55%', '78%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 4,
            borderColor: 'transparent',
            borderWidth: 3,
          },
          label: {
            show: true,
            position: 'outside' as const,
            formatter: '{b}\n{d}%',
            fontSize: 12,
          },
          labelLine: {
            length: 16,
            length2: 24,
            lineStyle: { color: 'rgba(255,255,255,0.2)' },
          },
          data: [
            { value: low, name: '<50%', itemStyle: { color: '#ef4444' } },
            { value: mid, name: '50-80%', itemStyle: { color: '#f59e0b' } },
            { value: high, name: '≥80%', itemStyle: { color: '#22c55e' } },
          ],
        },
      ],
    };
  })();

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
        {data.healthError && (
          <span style={{ color: 'var(--fqp-red-neon)', fontSize: '12px' }}>{data.healthError}</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
          {data.teamCount > 0 ? `${data.teamCount} 支球队已映射` : '等待数据采集'}
        </span>
      </Card>

      {/* Stat cards */}
      <div className="fqp-grid-4" style={{ marginBottom: '24px' }}>
        <Card title="可分析比赛">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.matchCount}</div>
            <div className="fqp-stat-sub">
              {data.matchCount > 0 ? '场已生成特征快照' : '暂无比赛数据'}
            </div>
          </div>
        </Card>

        <Card title="模型预测">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.predictionCount}</div>
            <div className="fqp-stat-sub">
              {data.predictionCount > 0 ? '条预测结果' : '等待模型计算'}
            </div>
          </div>
        </Card>

        <Card title="活跃推荐">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.activeTicketCount}</div>
            <div className="fqp-stat-sub">
              {data.activeTicketCount > 0 ? '张推荐票单待确认' : '暂无活跃推荐'}
            </div>
          </div>
        </Card>

        <Card title="实票记录">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.realTicketCount}</div>
            <div className="fqp-stat-sub">
              {data.realTicketCount > 0 ? '张实票已录入' : '暂无实票记录'}
            </div>
          </div>
        </Card>
      </div>

      {/* Charts row */}
      <div className="fqp-grid-2" style={{ marginBottom: '24px' }}>
        {completenessDonutOption ? (
          <ChartCard title="数据完整度分布" option={completenessDonutOption} height={280} />
        ) : (
          <Card title="数据完整度分布">
            <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--fqp-text-muted)', fontSize: '13px' }}>
              等待特征快照数据...
            </div>
          </Card>
        )}
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

      {/* System status summary */}
      <Card title="系统状态总览">
        {data.loading ? (
          <LoadingSpinner text="正在检测各模块状态..." />
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
                label: '特征快照',
                ok: data.matchCount > 0,
                detail: data.matchCount > 0 ? `${data.matchCount} 场` : '等待比赛数据',
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
            ].map((item) => (
              <div
                key={item.label}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: '1px solid rgba(39,39,42,0.3)',
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
