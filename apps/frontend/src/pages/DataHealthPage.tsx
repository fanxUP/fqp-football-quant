import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import { ApiError, type OfficialCollectionStatus } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import Skeleton from '../shared/components/Skeleton';
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

interface PipelineStatus {
  sources: Array<{
    name: string;
    status: string;
    last_success: string | null;
    last_failure: string | null;
    failures: number;
    latency_ms: number;
  }>;
  jobs: Array<{
    name: string;
    status: string;
    finished_at: string | null;
  }>;
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
  const [opsStatus, setOpsStatus] = useState<string | null>(null);
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);
  const [officialCollection, setOfficialCollection] = useState<OfficialCollectionStatus[] | null>(null);
  const [officialCollectionError, setOfficialCollectionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.health().catch(() => null),
      api.ops.health().catch(() => null),
      api.ops.pipeline().catch(() => null),
      api.official.collectionStatus({ limit: 8 }).catch((collectionError) => {
        setOfficialCollectionError(
          collectionError instanceof ApiError ? collectionError.message : '官方采集记录暂时无法读取',
        );
        return null;
      }),
    ]).then(([basic, ops, pipe, collection]) => {
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
      }
      setLoading(false);
    }).catch((e) => {
      setError(e instanceof ApiError ? e.message : '检测失败');
      setLoading(false);
    });
  }, []);

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

  // Build data source + task list from real pipeline data
  const jobStatusMap = new Map<string, string>();
  const jobTimeMap = new Map<string, string>();
  if (pipeline?.jobs) {
    for (const j of pipeline.jobs) {
      jobStatusMap.set(j.name, j.status === 'success' ? 'ok' : 'error');
      jobTimeMap.set(j.name, j.finished_at ? new Date(j.finished_at).toLocaleString('zh-CN', { hour12: false }) : '');
    }
  }
  const srcStatus = pipeline?.sources?.find(s => s.name === 'sporttery');
  const src500Status = pipeline?.sources?.find(s => s.name === '500.com');

  // Job name → detail label mapping
  const jobDetailMap: Record<string, string> = {
    '赔率快照采集': '每30分钟', '赛果结算': '每30分钟', '联赛积分榜采集': '每日 03:07',
    '伤停数据采集': '每日 08:07', '首发阵容采集': '每日 10:07/14:07', '天气数据采集': '每日 09:07/15:07',
    '模型预测执行': '每6小时', '推荐候选生成': '每日 16:00', '日报生成': '每日 23:30',
    '错因分析': '每日 23:45', 'Elo评分更新': '每日 01:00', '健康指标采集': '每日 23:55',
    '模型评估指标计算': '每日 23:40', '数据污染审计': '每日 23:45', '证据链校验': '每日 23:30',
    '备份验证': '每日 23:00', '票单结算': '每15分钟', '特征快照构建': '每日 00:00',
    '官方赛程采集': '每10分钟', '球队联赛映射': '每日 02:00',
  };
  const jobTypeMap: Record<string, 'official' | 'model' | 'review'> = {
    '赔率快照采集': 'official', '赛果结算': 'official', '联赛积分榜采集': 'official',
    '伤停数据采集': 'official', '首发阵容采集': 'official', '天气数据采集': 'official',
    '官方赛程采集': 'official', '球队联赛映射': 'official', '票单结算': 'official',
    '模型预测执行': 'model', '推荐候选生成': 'model', 'Elo评分更新': 'model',
    '模型评估指标计算': 'model', '特征快照构建': 'model',
    '日报生成': 'review', '错因分析': 'review', '健康指标采集': 'review',
    '数据污染审计': 'review', '证据链校验': 'review', '备份验证': 'review',
  };

  const sources: Array<{name: string; type: string; status: 'ok' | 'warning' | 'error' | 'info'; detail: string}> = [
    {
      name: '官方竞彩 (sporttery.cn)',
      type: 'official',
      status: srcStatus?.status === 'ok' ? 'ok' : 'error',
      detail: srcStatus?.status === 'ok' ? `延迟 ${srcStatus.latency_ms}ms` : `失败 ${srcStatus?.failures ?? '?'} 次`,
    },
    {
      name: '500.com 补充源',
      type: 'supplemental',
      status: src500Status?.status === 'ok' ? 'ok' : 'warning',
      detail: src500Status?.status === 'ok' ? `补充数据正常，延迟 ${src500Status.latency_ms}ms` : '未启用',
    },
  ];

  // Add task statuses from real job data
  const taskNames = [
    '赔率快照采集', '赛果结算', '联赛积分榜采集', '伤停数据采集', '首发阵容采集',
    '天气数据采集', '模型预测执行', '推荐候选生成', '日报生成', '错因分析',
    'Elo评分更新', '模型评估指标计算', '数据污染审计', '证据链校验',
  ];
  for (const name of taskNames) {
    const jobStatus = jobStatusMap.get(name);
    const lastTime = jobTimeMap.get(name);
    const type = jobTypeMap[name] || 'official';
    const defaultDetail = jobDetailMap[name] || '';
    const detail = jobStatus === 'ok' && lastTime ? `最近: ${lastTime}` : defaultDetail;
    sources.push({
      name,
      type,
      status: jobStatus === 'ok' ? 'ok' : (jobStatus === 'error' ? 'error' : 'warning'),
      detail,
    });
  }

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
            <div className="fqp-label">服务名称</div>
            <div>{health?.service || '—'}</div>
          </div>
          <div>
            <div className="fqp-label">前端版本</div>
            <div>Stage 8 — Red-Black Tech</div>
          </div>
          <div>
            <div className="fqp-label">部署模式</div>
            <div>本机进程 — PostgreSQL 本地版</div>
          </div>
          <div>
            <div className="fqp-label">调度任务</div>
            <div>21 个定时任务</div>
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
              已由 500.com 为体彩已收录的比赛补充赛果，并明确保留“补充”来源标记；如需体彩原始证据，可在浏览器保存官网 HTML 或 HAR 文件后再本地导入。
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
              key={src.name}
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
