import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type {
  NewsArticleItem,
  NewsEventItem,
  NewsIntelligenceOverview,
  NewsSourceItem,
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

export default function NewsIntelligencePage() {
  const [overview, setOverview] = useState<NewsIntelligenceOverview | null>(null);
  const [articles, setArticles] = useState<NewsArticleItem[]>([]);
  const [events, setEvents] = useState<NewsEventItem[]>([]);
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
      api.newsIntelligence.experiments(),
    ])
      .then(([overviewResponse, articleResponse, eventResponse, sourceResponse]) => {
        if (cancelled) return;
        setOverview(overviewResponse.overview);
        setArticles(articleResponse.items);
        setEvents(eventResponse.items);
        setSources(sourceResponse.sources);
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
        <StatusBadge status="ok" label="安全隔离" dot />
        <strong>正式预测未启用新闻特征</strong>
        <span style={{ color: 'var(--fqp-text-muted)', fontSize: 13 }}>
          当前仅归档与展示，影子评估和人工晋升完成前不会影响推荐、投注或风控。
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
