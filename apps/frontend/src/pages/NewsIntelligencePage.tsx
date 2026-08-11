import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type {
  NewsArticleItem,
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

export default function NewsIntelligencePage() {
  const [overview, setOverview] = useState<NewsIntelligenceOverview | null>(null);
  const [articles, setArticles] = useState<NewsArticleItem[]>([]);
  const [sources, setSources] = useState<NewsSourceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.newsIntelligence.overview(),
      api.newsIntelligence.events({ limit: 20 }),
      api.newsIntelligence.sources(),
      api.newsIntelligence.experiments(),
    ])
      .then(([overviewResponse, eventResponse, sourceResponse]) => {
        if (cancelled) return;
        setOverview(overviewResponse.overview);
        setArticles(eventResponse.items);
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

      <Card title="比赛情报">
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
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
