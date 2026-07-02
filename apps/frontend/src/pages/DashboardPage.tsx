import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import ErrorState from '../shared/components/ErrorState';
import PageHeader from '../shared/components/PageHeader';

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

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const results: Partial<DashboardData> = { errors: {} };

      // Fire all requests in parallel
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
        }),
        settle('predictions', api.predictions({ limit: 200 }), (p) => (results.predictionCount = p.total)),
        settle('tickets', api.tickets({ status: 'generated', limit: 50 }), (t) => (results.activeTicketCount = t.total)),
        settle('realTickets', api.realTickets.list({ limit: 50 }), (t) => (results.realTicketCount = t.total)),
        settle('reviews', api.reviews.daily(1), (r) => {
          if (r.reviews.length > 0) {
            results.latestReview = r.reviews[0].review_date;
          }
        }),
      ]);

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
        {/* Today's matches */}
        <Card title="可分析比赛">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.matchCount}</div>
            <div className="fqp-stat-sub">
              {data.matchCount > 0 ? '场已生成特征快照' : '暂无比赛数据'}
            </div>
          </div>
        </Card>

        {/* Predictions */}
        <Card title="模型预测">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.predictionCount}</div>
            <div className="fqp-stat-sub">
              {data.predictionCount > 0 ? '条预测结果' : '等待模型计算'}
            </div>
          </div>
        </Card>

        {/* Active recommendations */}
        <Card title="活跃推荐">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.activeTicketCount}</div>
            <div className="fqp-stat-sub">
              {data.activeTicketCount > 0 ? '张推荐票单待确认' : '暂无活跃推荐'}
            </div>
          </div>
        </Card>

        {/* Real tickets */}
        <Card title="实票记录">
          <div className="fqp-stat-card" style={{ padding: 0 }}>
            <div className="fqp-stat-value">{data.realTicketCount}</div>
            <div className="fqp-stat-sub">
              {data.realTicketCount > 0 ? '张实票已录入' : '暂无实票记录'}
            </div>
          </div>
        </Card>
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
