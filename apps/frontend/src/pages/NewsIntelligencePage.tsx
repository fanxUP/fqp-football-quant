import { useRef, useState, type ReactNode } from 'react';
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
import NewsScreeningStatus from '../features/news-intelligence/NewsScreeningStatus';
import Card from '../shared/components/Card';
import PageHeader from '../shared/components/PageHeader';
import StatusBadge from '../shared/components/StatusBadge';
import useManualEvidence from './useManualEvidence';
import ReadEvidenceStatus from './ReadEvidenceStatus';
import './BusinessEvidence.css';
import './NewsIntelligencePage.css';

function formatTime(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' });
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
  return value == null ? '样本不足' : !Number.isFinite(value) ? '—' : value.toFixed(4);
}

function finiteFields(value: object) {
  return Object.values(value).every(item => typeof item !== 'number' || Number.isFinite(item));
}
function checkedRows<T extends object>(items: T[], key: (item: T) => string | number, limit: number, message: string) {
  if (!Array.isArray(items) || items.length > limit || items.some(item => !item || !finiteFields(item) || key(item) == null) || new Set(items.map(key)).size !== items.length) throw new Error(message);
  return items;
}
function checkedPage<T extends object>(response: { items: T[]; total: number; limit: number; offset: number }, key: (item: T)=>string|number, limit: number, message: string) {
  checkedRows(response.items, key, limit, message);
  if (!Number.isSafeInteger(response.total) || response.total < response.items.length || response.limit !== limit || response.offset !== 0) throw new Error(message);
  return response;
}
function checkedRelease(value: NewsReleaseState) {
  if (!value || !['production','shadow'].includes(value.mode) || !value.promotion || typeof value.promotion.eligible!=='boolean' || typeof value.promotion.reason!=='string' || !value.metrics || !finiteFields(value.metrics) || !Number.isSafeInteger(value.metrics.sampleSize) || value.metrics.sampleSize<0) throw new Error('新闻发布状态格式不正确');
  return value;
}
function webUrl(value: string) {
  try { return ['http:', 'https:'].includes(new URL(value).protocol); } catch { return false; }
}

function NewsSubset<T>({ items, total, limit, size, name, searchLabel, filterLabel, options, text, value, emptyFiltered, children }: {
  items: T[]; total: number | undefined; limit: number; size: number; name: string; searchLabel?: string;
  filterLabel?: string; options?: { value: string; label: string }[]; text?: (item:T)=>string; value?: (item:T)=>string;
  emptyFiltered: string; children: (items:T[])=>ReactNode;
}) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(1);
  const query = search.trim().toLocaleLowerCase();
  const filtered = items.filter(item => (!query || (text?.(item) ?? '').toLocaleLowerCase().includes(query)) && (!filter || value?.(item) === filter));
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  const current = Math.min(page, pages);
  return <>
    {searchLabel && <div className="be-toolbar news-intelligence-filters">
      <label>{searchLabel}<input value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}} /></label>
      {filterLabel && <label>{filterLabel}<select value={filter} onChange={e=>{setFilter(e.target.value);setPage(1);}}><option value="">全部</option>{options?.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}
      <button type="button" onClick={()=>{setSearch('');setFilter('');setPage(1);}}>清空{name}筛选</button>
    </div>}
    <p className="be-note">已获取 {items.length} / 最多 {limit} · API 共 {total ?? '—'} · 筛选 {filtered.length}，仅筛选当前已获取记录</p>
    {filtered.length === 0 && items.length > 0 ? <div className="fqp-empty-state">{emptyFiltered}</div> : children(filtered.slice((current-1)*size,current*size))}
    <div className="be-pagination" aria-label={`${name}分页`}>
      <button type="button" disabled={current===1} onClick={()=>setPage(current-1)} aria-label={`${name}上一页`}>上一页</button>
      <span>{current} / {pages} 页</span>
      <button type="button" disabled={current===pages} onClick={()=>setPage(current+1)} aria-label={`${name}下一页`}>下一页</button>
    </div>
  </>;
}

export default function NewsIntelligencePage() {
  const overviewResource = useManualEvidence(async () => {
    const response = await api.newsIntelligence.overview();
    const value: NewsIntelligenceOverview = response.overview;
    const counts = ['articleCount','linkedMatchCount','sourceCount','healthySourceCount','screeningCount','aiScreeningCount','modelFailureCount','pendingReviewCount'] as const;
    if (!value || counts.some(key=>!Number.isSafeInteger(value[key]) || value[key]<0) || typeof value.newsAgentReady !== 'boolean') throw new Error('新闻概览格式不正确');
    return value;
  });
  const articleResource = useManualEvidence(async () => {
    const response = checkedPage(await api.newsIntelligence.articles({limit:20}), item=>`${item.id}:${item.matchId}`, 20, '新闻证据格式不正确');
    if (response.items.some(item=>!Number.isSafeInteger(item.id) || item.id<=0 || !webUrl(item.canonicalUrl) || typeof item.title!=='string' || !['S','A','B','C','D'].includes(item.sourceLevel))) throw new Error('新闻证据格式不正确');
    return response;
  });
  const eventResource = useManualEvidence(async () => {
    const response = checkedPage(await api.newsIntelligence.events({limit:20}), item=>`${item.id}:${item.matchId}`, 20, '情报事件格式不正确');
    if (response.items.some(item=>!Number.isSafeInteger(item.id) || item.id<=0 || !(item.verificationStatus in VERIFICATION_LABELS) || typeof item.title!=='string' || !Number.isSafeInteger(item.sourceCount) || item.sourceCount<0)) throw new Error('情报事件格式不正确');
    return response;
  });
  const sourceResource = useManualEvidence(async () => {
    const response = await api.newsIntelligence.sources();
    checkedRows(response.sources, item=>item.id, 500, '新闻信源格式不正确');
    if (response.sources.some(item=>!Number.isSafeInteger(item.id) || item.id<=0 || typeof item.enabled!=='boolean')) throw new Error('新闻信源格式不正确');
    return response;
  });
  const featureResource = useManualEvidence(async () => {
    const response = checkedPage(await api.newsIntelligence.features({limit:12}), item=>item.snapshotId, 12, '特征快照格式不正确');
    if (response.items.some(item=>!Number.isSafeInteger(item.snapshotId) || item.snapshotId<=0 || !Number.isSafeInteger(item.matchId) || item.matchId<=0 || !Number.isFinite(item.homeNetImpact) || !Number.isFinite(item.awayNetImpact))) throw new Error('特征快照格式不正确');
    return response;
  });
  const experimentResource = useManualEvidence(async () => {
    const response = await api.newsIntelligence.experiments();
    const value: NewsShadowExperiment = response.experiment;
    if (!value || !finiteFields(value) || !Array.isArray(value.models) || value.models.some(model=>!finiteFields(model))) throw new Error('影子评估格式不正确');
    return value;
  });
  const releaseResource = useManualEvidence(async () => checkedRelease((await api.newsIntelligence.release()).release));
  const overview = overviewResource.data;
  const articles: NewsArticleItem[] = articleResource.data?.items ?? [];
  const events: NewsEventItem[] = eventResource.data?.items ?? [];
  const features: NewsFeatureSnapshotItem[] = featureResource.data?.items ?? [];
  const sources: NewsSourceItem[] = sourceResource.data?.sources ?? [];
  const experiment = experimentResource.data;
  const release = releaseResource.data;
  const [releaseNote, setReleaseNote] = useState('');
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const writing = useRef(false);
  const busy = actionPending !== null;

  async function verifyEvent(eventId: number, status: 'verified' | 'rejected') {
    if (writing.current || eventResource.isReading() || eventResource.error) return;
    writing.current = true;
    const actionKey = `event-${eventId}`;
    setActionPending(actionKey);
    setActionError(null);
    try {
      const response = await api.newsIntelligence.verifyEvent(eventId, status);
      if (response.event.id !== eventId || response.event.verificationStatus !== status) throw new Error('核验响应与事件不一致');
      eventResource.update((current) => ({ ...current, items: current.items.map((event) => (
        event.id === eventId
          ? { ...event, verificationStatus: response.event.verificationStatus as NewsEventItem['verificationStatus'] }
          : event
      )) }));
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : '新闻事件核验失败');
    } finally {
      writing.current = false;
      setActionPending(null);
    }
  }

  async function toggleSource(source: NewsSourceItem) {
    if (writing.current || sourceResource.isReading() || sourceResource.error) return;
    writing.current = true;
    const actionKey = `source-${source.id}`;
    setActionPending(actionKey);
    setActionError(null);
    try {
      const response = await api.newsIntelligence.setSourceEnabled(source.id, !source.enabled);
      if (response.source.id !== source.id || response.source.enabled !== !source.enabled) throw new Error('信源响应与所选状态不一致');
      sourceResource.update((current) => ({ ...current, sources: current.sources.map((item) => (
        item.id === source.id ? { ...item, enabled: response.source.enabled } : item
      )) }));
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : '信源状态修改失败');
    } finally {
      writing.current = false;
      setActionPending(null);
    }
  }

  async function changeReleaseMode(target: 'production' | 'shadow') {
    if (writing.current || releaseResource.isReading() || releaseResource.error || !release) return;
    const note = releaseNote.trim();
    if (!note) {
      setActionError('请先填写人工审核或回滚说明');
      return;
    }
    writing.current = true;
    setActionPending('release');
    setActionError(null);
    try {
      const response = target === 'production'
        ? await api.newsIntelligence.promote(note)
        : await api.newsIntelligence.rollback(note);
      checkedRelease(response.release);
      if (response.release.mode !== target) throw new Error('发布响应与目标模式不一致');
      releaseResource.update(() => response.release);
      setReleaseNote('');
    } catch (requestError) {
      setActionError(requestError instanceof Error ? requestError.message : '发布状态修改失败');
    } finally {
      writing.current = false;
      setActionPending(null);
    }
  }

  const metrics = [
    ['已归档文章', overview?.articleCount ?? '—'],
    ['关联比赛', overview?.linkedMatchCount ?? '—'],
    ['信源', overview?.sourceCount ?? '—'],
    ['健康信源', overview?.healthySourceCount ?? '—'],
  ] as const;

  return (
    <div className="news-intelligence-page be-page">
      <PageHeader
        title="新闻情报"
        subtitle="新闻发现、可信度与比赛证据；正式预测保持独立"
        lastUpdated={formatTime(overview?.lastCapturedAt ?? null)}
      />

      <Card className="news-intelligence-boundary">
        <StatusBadge status={!release ? 'warning' : release.mode === 'production' ? 'warning' : 'ok'} label={!release ? '发布状态未知' : release.mode === 'production' ? '生产已晋升' : '安全隔离'} dot />
        {releaseResource.error && release && <span role="note">发布状态刷新失败，以下为上次成功读取结果</span>}
        <strong>{!release ? '尚无成功发布状态，请先读取核验' : release.mode === 'production' ? '正式推荐已启用锁定新闻版本' : '正式预测未启用新闻特征'}</strong>
        <span style={{ color: 'var(--fqp-text-muted)', fontSize: 13 }}>
          {!release ? '无法确认当前正式推荐是否启用新闻覆盖。' : release.mode === 'production'
            ? '仅对锁定的 SPF 基线概率应用受限新闻覆盖；风控和正式预测事实表仍保持不变。'
            : '当前仅归档与展示，影子评估和人工晋升完成前不会影响推荐、投注或风控。'}
        </span>
      </Card>

      <ReadEvidenceStatus resource={overviewResource} label="刷新新闻概览" note="统计与筛选链路；时间为本次接口接收时间" />
      <div className="news-intelligence-metrics">
        {metrics.map(([label, value]) => (
          <Card key={label} className="fqp-stat-card">
            <div className="fqp-stat-value">{value}</div>
            <div className="fqp-stat-sub">{label}</div>
          </Card>
        ))}
      </div>

      {actionError && <div role="alert" id="news-action-error" className="news-intelligence-action-error">{actionError}</div>}

      <NewsScreeningStatus overview={overview} formatTime={formatTime} />

      <Card title="结构化情报事件">
        <ReadEvidenceStatus resource={{ ...eventResource, loading: eventResource.loading || busy }} label="刷新情报事件" />
        {eventResource.data && <NewsSubset items={events} total={eventResource.data.total} name="事件" size={10} limit={20} searchLabel="搜索情报事件" filterLabel="事件核验状态" options={Object.entries(VERIFICATION_LABELS).map(([value,label])=>({value,label}))} text={event=>`${event.title} ${event.summary} ${event.officialMatchCode ?? ""} ${event.homeTeamName ?? ""} ${event.awayTeamName ?? ""}`} value={event=>event.verificationStatus} emptyFiltered="当前筛选无情报事件">
          {visibleEvents => <>
        {visibleEvents.length === 0 ? (
          <div className="fqp-empty-state">暂无可核验的结构化事件</div>
        ) : (
          <div className="news-intelligence-list">
            {visibleEvents.map((event) => (
              <article key={`${event.id}:${event.matchId}`} className="news-intelligence-event">
                <div className="news-intelligence-event-heading">
                  <StatusBadge
                    status={verificationBadge(event.verificationStatus)}
                    label={VERIFICATION_LABELS[event.verificationStatus]}
                    dot
                  />
                  <strong>{EVENT_LABELS[event.eventType] ?? event.eventType}</strong>
                  <span className={`news-intelligence-direction news-intelligence-direction-${event.direction}`}>
                    {event.direction === 'positive' ? '正向' : event.direction === 'negative' ? '负向' : event.direction === 'mixed' ? '混合' : '中性'}
                  </span>
                </div>
                <div>
                  <strong>{event.title}</strong>
                  <p className="news-intelligence-summary">{event.summary}</p>
                  <div className="news-intelligence-meta">
                    {event.officialMatchCode ?? '未关联比赛'}
                    {event.homeTeamName && event.awayTeamName ? ` · ${event.homeTeamName} VS ${event.awayTeamName}` : ''}
                    {` · ${event.sourceCount} 条证据 · 可用于 ${formatTime(event.firstAvailableAt)}`}
                    {event.matchId && <a className="news-intelligence-match-link" href={`#/matches/${event.matchId}`}>查看比赛 #{event.matchId}</a>}
                  </div>
                </div>
                {(event.verificationStatus === 'pending' || event.verificationStatus === 'conflicting') && (
                  <div className="news-intelligence-actions">
                    <button
                      type="button"
                      className="fqp-btn fqp-btn-primary"
                      disabled={busy || eventResource.loading || !!eventResource.error}
                      onClick={() => verifyEvent(event.id, 'verified')}
                    >
                      确认可靠
                    </button>
                    <button
                      type="button"
                      className="fqp-btn fqp-btn-secondary"
                      disabled={busy || eventResource.loading || !!eventResource.error}
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

          </>}
        </NewsSubset>}
      </Card>

      <Card title="时点特征快照">
        <ReadEvidenceStatus resource={{ ...featureResource, loading: featureResource.loading || busy }} label="刷新特征快照" />
        {featureResource.data && <NewsSubset items={features} total={featureResource.data.total} name="快照" size={6} limit={12} emptyFiltered="当前筛选无特征快照">
          {visibleFeatures => <>
        {visibleFeatures.length === 0 ? (
          <div className="fqp-empty-state">暂无已到时点的特征快照</div>
        ) : (
          <div className="news-intelligence-feature-grid">
            {visibleFeatures.map((feature) => (
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
                  {feature.snapshotLabel === "POST120" && <span> · 赛后快照，不用于赛前决策</span>}
                  <a className="news-intelligence-match-link" href={`#/matches/${feature.matchId}`}>查看比赛 #{feature.matchId}</a>
                </div>
              </article>
            ))}
          </div>
        )}

          </>}
        </NewsSubset>}
      </Card>

      <Card title="影子模型对比">
        <ReadEvidenceStatus resource={experimentResource} label="刷新影子评估" />
        <div className="news-intelligence-shadow-summary">
          <div><span>已结算样本</span><strong>{experiment?.sampleSize ?? '—'}</strong></div>
          <div><span>基线 Brier</span><strong>{experiment ? formatMetric(experiment.baselineBrier) : '—'}</strong></div>
          <div><span>新闻影子 Brier</span><strong>{experiment ? formatMetric(experiment.shadowBrier) : '—'}</strong></div>
          <div><span>Brier 变化</span><strong>{experiment ? formatMetric(experiment.brierDelta) : '—'}</strong></div>
        </div>
        <div className="news-intelligence-meta">
          数值越低越好。该面板只展示评估指标；新闻是否启用以发布状态为准。
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
        <ReadEvidenceStatus resource={{ ...releaseResource, loading: releaseResource.loading || busy }} label="刷新发布状态" />
        <div className="news-intelligence-release">
          <div>
            <StatusBadge
              status={release?.mode === 'production' ? 'warning' : 'info'}
              label={!release ? '模式未知' : release.mode === 'production' ? '生产模式' : '影子模式'}
              dot
            />
            <strong>{release?.promotion.reason ?? '正在读取晋升门槛'}</strong>
            <span className="news-intelligence-meta">
              候选版本 {release?.candidateShadowVersion ?? '—'} · 门槛样本 {release?.metrics.sampleSize ?? '—'}
            </span>
          </div>
          <label className="news-intelligence-release-note">人工审核或回滚说明<textarea
            aria-describedby={actionError ? "news-action-error" : undefined}
            value={releaseNote}
            maxLength={2000}
            placeholder="填写人工审核或回滚说明"
            onChange={(event) => setReleaseNote(event.target.value)}
          /></label>
          <div className="news-intelligence-actions">
            {release?.mode === 'production' ? (
              <button
                type="button"
                className="fqp-btn fqp-btn-secondary"
                disabled={busy || releaseResource.loading || !!releaseResource.error}
                onClick={() => changeReleaseMode('shadow')}
              >
                立即回滚到影子模式
              </button>
            ) : (
              <button
                type="button"
                className="fqp-btn fqp-btn-primary"
                disabled={!release?.promotion.eligible || busy || releaseResource.loading || !!releaseResource.error}
                onClick={() => changeReleaseMode('production')}
              >
                人工晋升并锁定版本
              </button>
            )}
          </div>
        </div>
      </Card>

      <Card title="原始新闻证据">
        <ReadEvidenceStatus resource={{ ...articleResource, loading: articleResource.loading || busy }} label="刷新新闻证据" />
        {articleResource.data && <NewsSubset items={articles} total={articleResource.data.total} name="文章" size={10} limit={20} searchLabel="搜索新闻证据" filterLabel="新闻信源等级" options={["S","A","B","C","D"].map(value=>({value,label:`${value}级`}))} text={article=>`${article.title} ${article.sourceName} ${article.officialMatchCode ?? ""}`} value={article=>article.sourceLevel} emptyFiltered="当前筛选无新闻证据">
          {visibleArticles => <>
        {visibleArticles.length === 0 ? (
          <div className="fqp-empty-state">暂无已关联的可靠新闻</div>
        ) : (
          <div className="news-intelligence-list">
            {visibleArticles.map((article) => (
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
                <div className="news-intelligence-meta">发布 <time>{formatTime(article.publishedAt)}</time><br />可用 <time>{formatTime(article.availableAt)}</time>{article.matchId && <a className="news-intelligence-match-link" href={`#/matches/${article.matchId}`}>查看比赛 #{article.matchId}</a>}</div>
              </article>
            ))}
          </div>
        )}

          </>}
        </NewsSubset>}
      </Card>

      <Card title="信源健康">
        <ReadEvidenceStatus resource={{ ...sourceResource, loading: sourceResource.loading || busy }} label="刷新信源健康" />
        {sourceResource.data && (sources.length === 0 ? (
          <div className="fqp-empty-state">尚未配置新闻信源</div>
        ) : (
          <div className="news-intelligence-list">
            {sources.map((source) => (
              <div key={source.id} className="news-intelligence-article">
                <StatusBadge status={source.enabled && source.lastSuccessAt && !source.lastError ? 'ok' : 'warning'} label={`${source.sourceLevel}级`} dot />
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
                  disabled={busy || sourceResource.loading || !!sourceResource.error}
                  onClick={() => toggleSource(source)}
                >
                  {source.enabled ? '停用' : '启用'}
                </button>
              </div>
            ))}
          </div>
        ))}
      </Card>
    </div>
  );
}
