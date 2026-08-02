import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError, type OfficialCollectionStatus } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import Skeleton from '../shared/components/Skeleton';
import ErrorState from '../shared/components/ErrorState';
import useBackgroundRefresh from '../shared/hooks/useBackgroundRefresh';
import { buildDataHealthRows, formatPipelineTime, type PipelineStatus } from './dataHealthPresentation';

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
  snapshot_time: string | null;
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
  const [opsStatus, setOpsStatus] = useState<string | null>(null);
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);
  const [officialCollection, setOfficialCollection] = useState<OfficialCollectionStatus[] | null>(null);
  const [officialCollectionError, setOfficialCollectionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoading(true);
      setError(null);
    }
    try {
      const [basic, ops, pipe, collection] = await Promise.all([
        api.health().catch(() => null),
        api.ops.health().catch(() => null),
        api.ops.pipeline().catch(() => null),
        api.official.collectionStatus({ limit: 8 }).catch((collectionError) => {
          setOfficialCollectionError(
            collectionError instanceof ApiError ? collectionError.message : '官方采集记录暂时无法读取',
          );
          return null;
        }),
      ]);
      if (basic) {
        setHealth({
          service: basic.service || 'fqp',
          status: basic.status === 'ok' ? 'ok' : 'error',
          detail: basic.status === 'ok' ? '后端服务正常响应' : `状态: ${basic.status}`,
          lastCheck: new Date().toLocaleString('zh-CN', { hour12: false }),
        });
      }
      const opsData = ops as Record<string, unknown> | null;
      if (opsData) {
        setOpsStatus(String(opsData.status || 'no_data'));
        if (opsData.status !== 'no_data') {
          setOpsHealth(opsData as unknown as OpsHealth);
        }
      }
      const pipeData = pipe as Record<string, unknown> | null;
      if (pipeData) {
        setPipeline(pipeData as unknown as PipelineStatus);
      }
      if (collection) {
        setOfficialCollection(collection.items);
        setOfficialCollectionError(null);
      }
      setError(null);
    } catch (e) {
      if (showLoading) setError(e instanceof ApiError ? e.message : '检测失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchHealth(); }, [fetchHealth]);
  useBackgroundRefresh(() => fetchHealth(false));

  if (loading) return (
    <div>
      <PageHeader title="数据源与系统监控" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <Skeleton variant="card" height={56} />
        <Skeleton variant="card" height={200} />
        <Skeleton variant="card" height={160} />
        <Skeleton variant="table-row" count={12} />
      </div>
    </div>
  );

  const sources = buildDataHealthRows(pipeline);

  const stage8Passes = opsHealth?.metrics
    ? Object.entries(STAGE8_TARGETS).filter(([key, cfg]) => {
        const val = opsHealth.metrics[key as keyof Stage8Metrics];
        return cfg.pass(val);
      }).length
    : 0;
  const stage8Total = Object.keys(STAGE8_TARGETS).length;
  const stage8AllPass = stage8Passes === stage8Total;
  const latestOfficialCollection = officialCollection?.[0] ?? null;
  const overallHealth = (() => {
    if (opsStatus === 'critical') {
      return { status: 'error' as const, label: '系统运行异常', detail: opsHealth?.notes || '关键运行指标异常' };
    }
    if (opsStatus === 'degraded') {
      return { status: 'warning' as const, label: '系统运行降级', detail: opsHealth?.notes || '部分运行指标未达标' };
    }
    if (opsStatus === 'no_data') {
      return { status: 'warning' as const, label: '监控数据不足', detail: '后端可响应，但缺少运维健康快照' };
    }
    if (health?.status === 'ok') {
      return { status: 'ok' as const, label: '系统运行正常', detail: health.detail };
    }
    return { status: 'error' as const, label: '后端服务异常', detail: health?.detail || '后端服务未响应' };
  })();
  const officialCollectionBadge = latestOfficialCollection?.status === 'ok'
    ? { status: 'ok' as const, label: '已导入' }
    : latestOfficialCollection?.status === 'partial'
    ? { status: 'warning' as const, label: '部分待匹配' }
    : latestOfficialCollection?.status === 'blocked'
    ? { status: 'warning' as const, label: '需本地导入' }
    : latestOfficialCollection
    ? { status: 'error' as const, label: '需处理' }
    : { status: 'info' as const, label: '暂无记录' };

  return (
    <div>
      <PageHeader title="数据源与系统监控" />

      {/* Overall health */}
      <Card style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
        <StatusBadge
          status={overallHealth.status}
          label={overallHealth.label}
          dot
        />
        <span style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
          {overallHealth.detail}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
          最后检测: {health?.lastCheck}
        </span>
      </Card>

      {/* Stage 8: Operational Health KPIs */}
      {opsHealth && (
        <Card
          title={`第 8 阶段运行指标 (${stage8Passes}/${stage8Total})`}
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
            {opsHealth.snapshot_time && (
              <span style={{ float: 'right', fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                快照: {formatPipelineTime(opsHealth.snapshot_time)}
              </span>
            )}
          </div>

          {/* KPI grid — staggered entrance */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '12px' }}>
            {Object.entries(STAGE8_TARGETS).map(([key, cfg], i) => {
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
                    background: 'var(--fqp-panel-overlay)',
                    borderRadius: 'var(--fqp-radius-sm)',
                    border: `1px solid ${passing ? 'rgba(0,255,136,0.2)' : 'rgba(255,42,61,0.2)'}`,
                    animation: 'fqpPopIn 0.35s ease both',
                    animationDelay: `${i * 60}ms`,
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
            <div className="fqp-label">Service Name</div>
            <div>{health?.service || '—'}</div>
          </div>
          <div>
            <div className="fqp-label">Frontend Version</div>
            <div>Phase 8 — Red-Black Tech</div>
          </div>
          <div>
            <div className="fqp-label">Configuration Mode</div>
            <div>Local Service Stack — PostgreSQL</div>
          </div>
          <div>
            <div className="fqp-label">调度任务</div>
            <div>{pipeline?.jobs.length ?? 0} 个已记录任务</div>
          </div>
        </div>
      </Card>

      <Card
        title="官方历史数据采集"
        action={<StatusBadge status={officialCollectionBadge.status} label={officialCollectionBadge.label} dot />}
        style={{ marginBottom: '20px' }}
      >
        {officialCollectionError ? (
          <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
            采集状态暂时不可读取：{officialCollectionError}
          </div>
        ) : latestOfficialCollection?.status === 'blocked' ? (
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              体彩官方结果暂不可自动读取
            </div>
            <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)', lineHeight: 1.6 }}>
              系统不会使用第三方赛果替代体彩官方结果；可稍后重试自动采集，或在浏览器保存体彩官网 HTML 或 HAR 文件后再本地导入。
            </div>
          </div>
        ) : latestOfficialCollection ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
            <span>日期：{latestOfficialCollection.business_date}</span>
            <span>类型：{latestOfficialCollection.crawl_type}</span>
            <span>发现：{latestOfficialCollection.records_found}</span>
            <span>写入：{latestOfficialCollection.records_inserted + latestOfficialCollection.records_updated}</span>
            {latestOfficialCollection.source_artifact_path && <span>来源：本地导入文件</span>}
          </div>
        ) : (
          <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
            暂无官方历史数据采集记录；首次采集或导入后会在这里留下可追溯状态。
          </div>
        )}
      </Card>

      {/* Data source grid */}
      <Card title="数据源与任务状态">
        {error && (
          <div style={{ marginBottom: '16px', padding: '10px 14px', background: 'rgba(255,42,61,0.1)', borderRadius: 'var(--fqp-radius-sm)', color: 'var(--fqp-red-neon)', fontSize: '13px' }}>
            {error}
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {sources.map((src, i) => (
            <div
              key={src.key}
              className="fqp-anim-listItemEnter"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 0',
                borderBottom: '1px solid var(--fqp-border-light)',
                animationDelay: `${i * 30}ms`,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span className={`fqp-status-dot fqp-status-dot-${src.status}`} />
                <span style={{ fontSize: '13px' }}>{src.name}</span>
                <StatusBadge
                  status="info"
                  label={src.type === 'official' ? '官方' : src.type === 'supplemental' ? '补充' : src.type === 'model' ? '模型' : '复盘'}
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
