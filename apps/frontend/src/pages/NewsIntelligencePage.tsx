import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type {
  NewsArticleItem,
  NewsEventItem,
  NewsFeatureSnapshotItem,
  NewsIntelligenceOverview,
  NewsSourceItem,
  NewsShadowExperiment,
  NewsReleaseState,
} from '../features/news-intelligence/types';
import Card from '../shared/components/Card';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import PageHeader from '../shared/components/PageHeader';
import StatusBadge from '../shared/components/StatusBadge';
import './NewsIntelligencePage.css';

function formatTime(value: string | null): string {
  if (!value) return '暂无';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

const EVENT_LABELS: Record<string, string> = {
  injury: '伤病',
  suspension: '停赛',
  return: '复出',
  lineup: '阵容',
  rotation: '轮换',
  manager_change: '主教练变动',
  schedule_pressure: '赛程压力',
  internal_issue: '队内问题',
  morale: '士气',
};

const VERIFICATION_LABELS = {
  pending: '待核验',
  verified: '已核验',
  rejected: '已拒绝',
  conflicting: '证据冲突',
} as const;

function verificationBadge(status: NewsEventItem['verificationStatus']) {
  if (status === 'verified') return 'ok' as const;
  if (status === 'rejected') return 'error' as const;
  return 'warning' as const;
}

function formatMetric(value: number | null): string {
  return value === null ? '样本不足' : value.toFixed(4);
}

export default function NewsIntelligencePage() {
  const [overview, setOverview] = useState<NewsIntelligenceOverview | null>(null);
  const [articles, setArticles] = useState<NewsArticleItem[]>([]);
  const [events, setEvents] = useState<NewsEventItem[]>([]);
  const [features, setFeatures] = useState<NewsFeatureSnapshotItem[]>([]);
  const [experiment, setExperiment] = useState<NewsShadowExperiment | null>(null);
  const [release, setRelease] = useState<NewsReleaseState | null>(null);
  const [releaseNote, setReleaseNote] = useState('');
  const [sources, setSources] = useState<NewsSourceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.newsIntelligence.overview(),
      api.newsIntelligence.articles({ limit: 20 }),
      api.newsIntelligence.events({ limit: 20 }),
      api.newsIntelligence.sources(),
      api.newsIntelligence.features({ limit: 12 }),
      api.newsIntelligence.experiments(),
      api.newsIntelligence.release(),
    ])
      .then(([
        overviewResponse,
        articleResponse,
        eventResponse,
        sourceResponse,
        featureResponse,
        experimentResponse,
        releaseResponse,
      ]) => {
        if (cancelled) return;
        setOverview(overviewResponse.overview);
        setArticles(articleResponse.items);
        setEvents(eventResponse.items);
        setSources(sourceResponse.sources);
        setFeatures(featureResponse.items);
        setExperiment(experimentResponse.experiment);
        setRelease(releaseResponse.release);
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError instanceof Error ? requestError.message : '新闻情报加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function verifyEvent(eventId: number, status: 'verified' | 'rejected') {
    const actionKey = `event-${eventId}`;
    setActionPending(actionKey);
    setActionError(null);
    try {
      const response = await api.newsIntelligence.verifyEvent(eventId, status);
      setEvents((current) => current.map((event) => (
        event.id === eventId
          ? { ...event, verificationStatus: response.event.verificationStatus as NewsEventItem['verificationStatus'] }
          : event
      )));
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : '新闻事件核验失败');
    } finally {
      setActionPending(null);
    }
  }

  async function toggleSource(source: NewsSourceItem) {
    const actionKey = `source-${source.id}`;
    setActionPending(actionKey);
    setActionError(null);
    try {
      const response = await api.newsIntelligence.setSourceEnabled(source.id, !source.enabled);
      setSources((current) => current.map((item) => (
        item.id === source.id ? { ...item, enabled: response.source.enabled } : item
      )));
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : '信源状态修改失败');
    } finally {
      setActionPending(null);
    }
  }

  async function changeReleaseMode(target: 'production' | 'shadow') {
    const note = releaseNote.trim();
    if (!note) {
      setActionError('请先填写人工审核或回滚说明');
      return;
    }
    setActionPending('release');
    setActionError(null);
    try {
      const response = target === 'production'
        ? await api.newsIntelligence.promote(note)
        : await api.newsIntelligence.rollback(note);
      setRelease(response.release);
      setReleaseNote('');
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : '发布状态修改失败');
    } finally {
      setActionPending(null);
    }
  }

  if (loading) return <LoadingSpinner text="加载新闻情报..." size="lg" />;
  if (error) return <ErrorState message={error} />;

  const metrics = [
    ['已归档文章', overview?.articleCount ?? 0],
    ['关联比赛', overview?.linkedMatchCount ?? 0],
    ['信源', overview?.sourceCount ?? 0],
    ['健康信源', overview?.healthySourceCount ?? 0],
  ] as const;

  return (
    <div className="news-intelligence-page">
      <PageHeader
        title="新闻情报"
        subtitle="新闻发现、可信度与比赛证据；正式预测保持独立"
        lastUpdated={formatTime(overview?.lastCapturedAt ?? null)}
      />

      <Card className="news-intelligence-boundary">
        <StatusBadge status={release?.mode === 'production' ? 'warning' : 'ok'} label={release?.mode === 'production' ? '生产已晋升' : '安全隔离'} dot />
        <strong>{release?.mode === 'production' ? '正式推荐已启用锁定新闻版本' : '正式预测未启用新闻特征'}</strong>
        <span style={{ color: 'var(--fqp-text-muted)', fontSize: 13 }}>
          {release?.mode === 'production'
            ? '仅对锁定的 SPF 基线概率应用受限新闻覆盖；风控和正式预测事实表仍保持不变。'
            : '当前仅归档与展示，影子评估和人工晋升完成前不会影响推荐、投注或风控。'}
        </span>
      </Card>

      <div className="news-intelligence-metrics">
        {metrics.map(([label, value]) => (
          <Card key={label} className="fqp-stat-card">
            <div className="fqp-stat-value">{value}</div>
            <div className="fqp-stat-sub">{label}</div>
          </Card>
        ))}
      </div>

      {actionError && <div className="news-intelligence-action-error">{actionError}</div>}

      <Card title="结构化情报事件">
        {events.length === 0 ? (
          <div className="fqp-empty-state">暂无可核验的结构化事件</div>
        ) : (
          <div className="news-intelligence-list">
            {events.map((event) => (
              <article key={event.id} className="news-intelligence-event">
                <div className="news-intelligence-event-heading">
                  <StatusBadge
                    status={verificationBadge(event.verificationStatus)}
                    label={VERIFICATION_LABELS[event.verificationStatus]}
                    dot
                  />
                  <strong>{EVENT_LABELS[event.eventType] ?? event.eventType}</strong>
                  <span className={`news-intelligence-direction news-intelligence-direction-${event.direction}`}>
                    {event.direction === 'positive' ? '正向' : event.direction === 'negative' ? '负向' : '中性'}
                  </span>
                </div>
                <div>
                  <strong>{event.title}</strong>
                  <p className="news-intelligence-summary">{event.summary}</p>
                  <div className="news-intelligence-meta">
                    {event.officialMatchCode ?? '未关联比赛'}
                    {event.homeTeamName && event.awayTeamName ? ` · ${event.homeTeamName} VS ${event.awayTeamName}` : ''}
                    {` · ${event.sourceCount} 条证据 · 可用于 ${formatTime(event.firstAvailableAt)}`}
                  </div>
                </div>
                {(event.verificationStatus === 'pending' || event.verificationStatus === 'conflicting') && (
                  <div className="news-intelligence-actions">
                    <button
                      type="button"
                      className="fqp-btn fqp-btn-primary"
                      disabled={actionPending === `event-${event.id}`}
                      onClick={() => verifyEvent(event.id, 'verified')}
                    >
                      确认可靠
                    </button>
                    <button
                      type="button"
                      className="fqp-btn fqp-btn-secondary"
                      disabled={actionPending === `event-${event.id}`}
                      onClick={() => verifyEvent(event.id, 'rejected')}
                    >
                      标记拒绝
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </Card>

      <Card title="时点特征快照">
        {features.length === 0 ? (
          <div className="fqp-empty-state">暂无已到时点的特征快照</div>
        ) : (
          <div className="news-intelligence-feature-grid">
            {features.map((feature) => (
              <article key={feature.snapshotId} className="news-intelligence-feature-card">
                <div className="news-intelligence-event-heading">
                  <StatusBadge status="info" label={feature.snapshotLabel} />
                  <strong>{feature.officialMatchCode}</strong>
                </div>
                <div className="news-intelligence-feature-match">
                  {feature.homeTeamName} VS {feature.awayTeamName}
                </div>
                <div className="news-intelligence-feature-values">
                  <span>主队影响 <strong>{feature.homeNetImpact.toFixed(2)}</strong></span>
                  <span>客队影响 <strong>{feature.awayNetImpact.toFixed(2)}</strong></span>
                  <span>核验事件 <strong>{feature.verifiedEventCount}</strong></span>
                  <span>证据 <strong>{feature.evidenceCount}</strong></span>
                </div>
                <div className="news-intelligence-meta">
                  截止 {formatTime(feature.snapshotCutoff)} · {feature.featureVersion}
                </div>
              </article>
            ))}
          </div>
        )}
      </Card>

      <Card title="影子模型对比">
        <div className="news-intelligence-shadow-summary">
          <div><span>已结算样本</span><strong>{experiment?.sampleSize ?? 0}</strong></div>
          <div><span>基线 Brier</span><strong>{formatMetric(experiment?.baselineBrier ?? null)}</strong></div>
          <div><span>新闻影子 Brier</span><strong>{formatMetric(experiment?.shadowBrier ?? null)}</strong></div>
          <div><span>Brier 变化</span><strong>{formatMetric(experiment?.brierDelta ?? null)}</strong></div>
        </div>
        <div className="news-intelligence-meta">
          数值越低越好。当前只做影子对比，不会改变正式预测、推荐、投注或风控。
        </div>
        {experiment && experiment.models.length > 0 && (
          <div className="news-intelligence-model-list">
            {experiment.models.map((model) => (
              <div key={`${model.modelName}-${model.modelVersion}`}>
                <strong>{model.modelName}</strong>
                <span>{model.sampleSize} 场 · Brier {formatMetric(model.baselineBrier)} → {formatMetric(model.shadowBrier)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="发布与回滚">
        <div className="news-intelligence-release">
          <div>
            <StatusBadge
              status={release?.mode === 'production' ? 'warning' : 'info'}
              label={release?.mode === 'production' ? '生产模式' : '影子模式'}
              dot
            />
            <strong>{release?.promotion.reason ?? '正在读取晋升门槛'}</strong>
            <span className="news-intelligence-meta">
              候选版本 {release?.candidateShadowVersion ?? 'news-shadow-v1'} · 门槛样本 {release?.metrics.sampleSize ?? 0}
            </span>
          </div>
          <textarea
            value={releaseNote}
            maxLength={2000}
            placeholder="填写人工审核或回滚说明"
            onChange={(event) => setReleaseNote(event.target.value)}
          />
          <div className="news-intelligence-actions">
            {release?.mode === 'production' ? (
              <button
                type="button"
                className="fqp-btn fqp-btn-secondary"
                disabled={actionPending === 'release'}
                onClick={() => changeReleaseMode('shadow')}
              >
                立即回滚到影子模式
              </button>
            ) : (
              <button
                type="button"
                className="fqp-btn fqp-btn-primary"
                disabled={!release?.promotion.eligible || actionPending === 'release'}
                onClick={() => changeReleaseMode('production')}
              >
                人工晋升并锁定版本
              </button>
            )}
          </div>
        </div>
      </Card>

      <Card title="原始新闻证据">
        {articles.length === 0 ? (
          <div className="fqp-empty-state">暂无已关联的可靠新闻</div>
        ) : (
          <div className="news-intelligence-list">
            {articles.map((article) => (
              <article key={`${article.id}-${article.matchId ?? 'unlinked'}`} className="news-intelligence-article">
                <StatusBadge status={article.sourceLevel === 'D' ? 'warning' : 'info'} label={`${article.sourceLevel}级`} />
                <div>
                  <a href={article.canonicalUrl} target="_blank" rel="noreferrer">
                    {article.title}
                  </a>
                  <div className="news-intelligence-meta">
                    {article.sourceName}
                    {article.officialMatchCode ? ` · ${article.officialMatchCode}` : ' · 尚未关联比赛'}
                  </div>
                </div>
                <time className="news-intelligence-meta">{formatTime(article.publishedAt)}</time>
              </article>
            ))}
          </div>
        )}
      </Card>

      <Card title="信源健康">
        {sources.length === 0 ? (
          <div className="fqp-empty-state">尚未配置新闻信源</div>
        ) : (
          <div className="news-intelligence-list">
            {sources.map((source) => (
              <div key={source.id} className="news-intelligence-article">
                <StatusBadge status={source.enabled && !source.lastError ? 'ok' : 'warning'} label={`${source.sourceLevel}级`} dot />
                <div>
                  <strong>{source.sourceName}</strong>
                  <div className="news-intelligence-meta">
                    {source.enabled ? '已启用' : '已停用'} · 最近成功 {formatTime(source.lastSuccessAt)}
                  </div>
                </div>
                {source.lastError && <span className="news-intelligence-meta">{source.lastError}</span>}
                <button
                  type="button"
                  className="fqp-btn fqp-btn-secondary"
                  disabled={actionPending === `source-${source.id}`}
                  onClick={() => toggleSource(source)}
                >
                  {source.enabled ? '停用' : '启用'}
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
