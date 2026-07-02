import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import ErrorState from '../shared/components/ErrorState';

interface HealthStatus {
  service: string;
  status: 'ok' | 'warning' | 'error';
  detail: string;
  lastCheck: string;
}

interface Stage8Metrics {
  uptime_days: number | null;
  official_collection_rate: number | null;
  odds_missing_rate: number | null;
  review_generation_rate: number | null;
  backup_success: boolean | null;
  evidence_chain_completeness: number | null;
  data_contamination_count: number | null;
}

interface OpsHealth {
  status: string;
  snapshot_date: string | null;
  metrics: Stage8Metrics;
  services: {
    scheduler: boolean | null;
    worker: boolean | null;
    api: boolean | null;
    db: boolean | null;
  } | null;
  disk_usage_pct: number | null;
  notes: string | null;
}

const STAGE8_TARGETS: Record<string, { label: string; target: string; pass: (v: number | boolean | null) => boolean }> = {
  official_collection_rate: { label: '官方采集成功率', target: '≥ 98%', pass: (v) => typeof v === 'number' && v >= 0.98 },
  odds_missing_rate: { label: '赔率快照缺失率', target: '≤ 2%', pass: (v) => typeof v === 'number' && v <= 0.02 },
  review_generation_rate: { label: '日报生成成功率', target: '≥ 99%', pass: (v) => typeof v === 'number' && v >= 0.99 },
  backup_success: { label: '备份成功率', target: '= 100%', pass: (v) => v === true },
  evidence_chain_completeness: { label: '证据链完整率', target: '= 100%', pass: (v) => typeof v === 'number' && v >= 1.0 },
  data_contamination_count: { label: '数据污染', target: '= 0', pass: (v) => typeof v === 'number' && v === 0 },
};

export default function DataHealthPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [opsHealth, setOpsHealth] = useState<OpsHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.health().catch(() => null),
      api.ops.health().catch(() => null),
    ]).then(([basic, ops]) => {
      if (basic) {
        setHealth({
          service: basic.service || 'fqp',
          status: basic.status === 'ok' ? 'ok' : 'error',
          detail: basic.status === 'ok' ? '后端服务正常响应' : `状态: ${basic.status}`,
          lastCheck: new Date().toLocaleString('zh-CN', { hour12: false }),
        });
      }
      const opsData = ops as Record<string, unknown> | null;
      if (opsData && opsData.status !== 'no_data') {
        setOpsHealth(opsData as unknown as OpsHealth);
      }
      setLoading(false);
    }).catch((e) => {
      setError(e instanceof ApiError ? e.message : '检测失败');
      setLoading(false);
    });
  }, []);

  if (loading) return <LoadingSpinner text="正在检测系统状态..." size="lg" />;

  // Data sources — static list
  const sources = [
    { name: '官方竞彩 (sporttery.cn)', type: 'official', status: health?.status === 'ok' ? 'ok' as const : 'error' as const, detail: health?.status === 'ok' ? '后端连接正常' : '后端不可达' },
    { name: '赔率快照采集', type: 'official', status: 'warning' as const, detail: '状态由后端 scheduler 管理' },
    { name: '赛果结算', type: 'official', status: 'warning' as const, detail: '状态由后端 scheduler 管理' },
    { name: '联赛积分榜采集', type: 'official', status: 'info' as const, detail: '每日 03:07' },
    { name: '伤停数据采集', type: 'official', status: 'info' as const, detail: '每日 08:07' },
    { name: '首发阵容采集', type: 'official', status: 'info' as const, detail: '每日 10:07 / 14:07' },
    { name: '天气数据采集', type: 'official', status: 'info' as const, detail: '每日 09:07 / 15:07' },
    { name: '模型预测引擎', type: 'model', status: 'info' as const, detail: '每6小时执行一次' },
    { name: '推荐引擎', type: 'model', status: 'info' as const, detail: '每日16:00执行' },
    { name: '日报生成', type: 'review', status: 'info' as const, detail: '每日23:30执行' },
    { name: '错因分析', type: 'review', status: 'info' as const, detail: '每日23:45执行' },
  ];

  const stage8Passes = opsHealth?.metrics
    ? Object.entries(STAGE8_TARGETS).filter(([key, cfg]) => {
        const val = opsHealth.metrics[key as keyof Stage8Metrics];
        return cfg.pass(val);
      }).length
    : 0;
  const stage8Total = Object.keys(STAGE8_TARGETS).length;
  const stage8AllPass = stage8Passes === stage8Total;

  return (
    <div>
      <PageHeader title="数据源与系统监控" />

      {/* Overall health */}
      <Card style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
        <StatusBadge
          status={health?.status || 'error'}
          label={health?.status === 'ok' ? '系统运行正常' : '后端服务异常'}
          dot
        />
        <span style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
          {health?.detail}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
          最后检测: {health?.lastCheck}
        </span>
      </Card>

      {/* Stage 8: Operational Health KPIs */}
      {opsHealth && (
        <Card
          title={`Stage 8 运行指标 (${stage8Passes}/${stage8Total})`}
          style={{ marginBottom: '20px' }}
        >
          {/* Overall status banner */}
          <div
            style={{
              marginBottom: '16px',
              padding: '10px 14px',
              borderRadius: 'var(--fqp-radius-sm)',
              background:
                opsHealth.status === 'healthy'
                  ? 'rgba(0,255,136,0.08)'
                  : opsHealth.status === 'critical'
                  ? 'rgba(255,42,61,0.1)'
                  : 'rgba(255,193,7,0.08)',
              borderLeft: `3px solid ${
                opsHealth.status === 'healthy'
                  ? 'var(--fqp-green-neon)'
                  : opsHealth.status === 'critical'
                  ? 'var(--fqp-red-neon)'
                  : 'var(--fqp-yellow)'
              }`,
              fontSize: '13px',
            }}
          >
            <strong>
              {opsHealth.status === 'healthy'
                ? '✅ 所有指标达标'
                : opsHealth.status === 'critical'
                ? '🚨 关键指标异常'
                : '⚠️ 部分指标未达标'}
            </strong>
            {opsHealth.notes && (
              <span style={{ marginLeft: '12px', color: 'var(--fqp-text-muted)' }}>
                {opsHealth.notes}
              </span>
            )}
            {opsHealth.snapshot_date && (
              <span style={{ float: 'right', fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                快照日期: {opsHealth.snapshot_date}
              </span>
            )}
          </div>

          {/* KPI grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '12px' }}>
            {Object.entries(STAGE8_TARGETS).map(([key, cfg]) => {
              const val = opsHealth.metrics[key as keyof Stage8Metrics];
              const passing = cfg.pass(val);
              let displayVal = '—';
              if (typeof val === 'number') {
                if (key === 'data_contamination_count') {
                  displayVal = String(val);
                } else {
                  displayVal = (val * 100).toFixed(1) + '%';
                }
              } else if (typeof val === 'boolean') {
                displayVal = val ? '100%' : '失败';
              }
              return (
                <div
                  key={key}
                  style={{
                    padding: '12px',
                    background: 'rgba(24,24,27,0.5)',
                    borderRadius: 'var(--fqp-radius-sm)',
                    border: `1px solid ${passing ? 'rgba(0,255,136,0.2)' : 'rgba(255,42,61,0.2)'}`,
                  }}
                >
                  <div style={{ fontSize: '12px', color: 'var(--fqp-text-muted)', marginBottom: '4px' }}>
                    {cfg.label}
                    <span style={{ marginLeft: '6px', fontSize: '10px', opacity: 0.6 }}>{cfg.target}</span>
                  </div>
                  <div
                    style={{
                      fontSize: '20px',
                      fontWeight: 600,
                      color: passing ? 'var(--fqp-green-neon)' : 'var(--fqp-red-neon)',
                    }}
                  >
                    {displayVal}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Service status + disk */}
          {opsHealth.services && (
            <div style={{ marginTop: '16px', display: 'flex', gap: '24px', flexWrap: 'wrap', fontSize: '12px' }}>
              {Object.entries(opsHealth.services).map(([svc, ok]) => (
                <span key={svc}>
                  <span
                    className={`fqp-status-dot fqp-status-dot-${ok ? 'ok' : 'error'}`}
                    style={{ display: 'inline-block', marginRight: '4px' }}
                  />
                  {svc}
                </span>
              ))}
              {opsHealth.disk_usage_pct != null && (
                <span style={{ color: 'var(--fqp-text-muted)', marginLeft: 'auto' }}>
                  磁盘: {opsHealth.disk_usage_pct}%
                </span>
              )}
              {opsHealth.metrics.uptime_days != null && (
                <span style={{ color: 'var(--fqp-text-muted)' }}>
                  连续运行: {opsHealth.metrics.uptime_days} 天
                </span>
              )}
            </div>
          )}
        </Card>
      )}

      {/* Info card */}
      <Card title="服务信息" style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
          <div>
            <div className="fqp-label">服务名称</div>
            <div>{health?.service || '—'}</div>
          </div>
          <div>
            <div className="fqp-label">前端版本</div>
            <div>Stage 8 — Red-Black Tech</div>
          </div>
          <div>
            <div className="fqp-label">部署模式</div>
            <div>Docker Compose — 本地个人版</div>
          </div>
          <div>
            <div className="fqp-label">调度任务</div>
            <div>21 个定时任务</div>
          </div>
        </div>
      </Card>

      {/* Data source grid */}
      <Card title="数据源与任务状态">
        {error && (
          <div style={{ marginBottom: '16px', padding: '10px 14px', background: 'rgba(255,42,61,0.1)', borderRadius: 'var(--fqp-radius-sm)', color: 'var(--fqp-red-neon)', fontSize: '13px' }}>
            {error}
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {sources.map((src) => (
            <div
              key={src.name}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 0',
                borderBottom: '1px solid rgba(39,39,42,0.3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span className={`fqp-status-dot fqp-status-dot-${src.status}`} />
                <span style={{ fontSize: '13px' }}>{src.name}</span>
                <StatusBadge
                  status="info"
                  label={src.type === 'official' ? '官方' : src.type === 'model' ? '模型' : '复盘'}
                />
              </div>
              <span style={{ fontSize: '12px', color: 'var(--fqp-text-muted)' }}>{src.detail}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
