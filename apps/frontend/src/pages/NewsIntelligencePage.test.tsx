import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import NewsIntelligencePage from './NewsIntelligencePage';

const { overview, articles, events, sources, features, experiments, release, promote, rollback, verifyEvent, setSourceEnabled } = vi.hoisted(() => ({
  overview: vi.fn(),
  articles: vi.fn(),
  events: vi.fn(),
  sources: vi.fn(),
  features: vi.fn(),
  experiments: vi.fn(),
  release: vi.fn(),
  promote: vi.fn(),
  rollback: vi.fn(),
  verifyEvent: vi.fn(),
  setSourceEnabled: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: { newsIntelligence: {
    overview, articles, events, sources, features, experiments, release, promote, rollback, verifyEvent, setSourceEnabled,
  } },
}));

describe('NewsIntelligencePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    overview.mockResolvedValue({ overview: {
      articleCount: 12,
      linkedMatchCount: 4,
      sourceCount: 3,
      healthySourceCount: 2,
      lastCapturedAt: '2026-08-11T01:00:00+00:00',
      productionFeatureEnabled: false,
      screeningCount: 10,
      aiScreeningCount: 7,
      modelFailureCount: 1,
      pendingReviewCount: 2,
      lastModelInvocationAt: '2026-08-11T01:05:00+00:00',
      newsAgentReady: true,
    } });
    articles.mockResolvedValue({ items: [{
      id: 7,
      matchId: 31,
      officialMatchCode: '周一101',
      sourceName: '测试俱乐部官网',
      sourceLevel: 'S',
      title: '球队公告',
      canonicalUrl: 'https://club.example/news/7',
      publishedAt: '2026-08-10T08:00:00+00:00',
      availableAt: '2026-08-10T08:05:00+00:00',
    }], total: 1, limit: 20, offset: 0 });
    events.mockResolvedValue({ items: [{
      id: 9,
      eventType: 'injury',
      direction: 'negative',
      title: '主力前锋伤缺',
      summary: '俱乐部确认该球员无法出场。',
      severityScore: 0.8,
      confidenceScore: 0.95,
      matchRelevanceScore: 1,
      verificationStatus: 'pending',
      occurredAt: null,
      firstAvailableAt: '2026-08-10T08:05:00+00:00',
      extractionMethod: 'rule',
      extractionVersion: 'news-rule-v1',
      matchId: 31,
      officialMatchCode: '周一101',
      leagueName: '测试联赛',
      homeTeamName: '主队',
      awayTeamName: '客队',
      sourceCount: 1,
    }], total: 1, limit: 20, offset: 0 });
    sources.mockResolvedValue({ sources: [{
      id: 2,
      sourceCode: 'club-official',
      sourceName: '俱乐部官网',
      sourceLevel: 'S',
      enabled: true,
      lastSuccessAt: null,
      lastError: null,
    }], total: 1 });
    features.mockResolvedValue({ items: [{
      snapshotId: 12,
      matchId: 31,
      officialMatchCode: '周一101',
      leagueName: '测试联赛',
      homeTeamName: '主队',
      awayTeamName: '客队',
      snapshotLabel: 'T45M',
      snapshotCutoff: '2026-08-11T10:15:00+00:00',
      homeNetImpact: -0.72,
      awayNetImpact: 0.4,
      verifiedEventCount: 2,
      pendingEventCount: 0,
      evidenceCount: 3,
      coverageScore: 1,
      confidenceScore: 0.9,
      featureVersion: 'news-features-v1',
    }], total: 1, limit: 12, offset: 0 });
    experiments.mockResolvedValue({ experiment: {
      sampleSize: 120,
      baselineBrier: 0.61,
      shadowBrier: 0.59,
      brierDelta: -0.02,
      baselineLogLoss: 1.02,
      shadowLogLoss: 0.99,
      logLossDelta: -0.03,
      productionFeatureEnabled: false,
      models: [{
        modelName: 'dixon_coles',
        modelVersion: 'v1',
        shadowVersion: 'news-shadow-v1',
        sampleSize: 120,
        baselineBrier: 0.61,
        shadowBrier: 0.59,
        brierDelta: -0.02,
        baselineLogLoss: 1.02,
        shadowLogLoss: 0.99,
      }],
    } });
    release.mockResolvedValue({ release: {
      mode: 'shadow',
      approvedShadowVersion: null,
      approvedFeatureVersion: null,
      approvalNote: null,
      approvedBy: null,
      approvedAt: null,
      updatedAt: '2026-08-11T10:00:00+00:00',
      candidateShadowVersion: 'news-shadow-v1',
      candidateFeatureVersion: 'news-features-v1',
      metrics: { sampleSize: 120, brierDelta: -0.02, logLossDelta: -0.03 },
      promotion: { eligible: false, reason: '已结算样本少于 1000 场' },
    } });
    verifyEvent.mockResolvedValue({ event: { id: 9, verificationStatus: 'verified', reviewNote: null } });
    setSourceEnabled.mockResolvedValue({ source: { id: 2, enabled: false } });
  });

  it('展示情报概览、来源等级和正式预测安全边界', async () => {
    render(<NewsIntelligencePage />);

    expect(await screen.findByText('球队公告')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('球队公告')).toBeInTheDocument();
    expect(screen.getByText('主力前锋伤缺')).toBeInTheDocument();
    expect(screen.getByText('T45M')).toBeInTheDocument();
    expect(screen.getByText('主队 VS 客队')).toBeInTheDocument();
    expect(screen.getByText('影子模型对比')).toBeInTheDocument();
    expect(screen.getByText('0.6100')).toBeInTheDocument();
    expect(screen.getByText('dixon_coles')).toBeInTheDocument();
    expect(screen.getByText('影子模式')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '人工晋升并锁定版本' })).toBeDisabled();
    expect(screen.getByText('待核验', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getAllByText('S级', { selector: 'span' })).toHaveLength(2);
    expect(screen.getByText('正式预测未启用新闻特征')).toBeInTheDocument();
    expect(screen.getByText('AI 筛选 Agent 已就绪')).toBeInTheDocument();
    expect(screen.getByText(/模型筛选 7/)).toBeInTheDocument();
    expect(screen.getByText(/回退 1 次/)).toBeInTheDocument();
  });

  it('可人工确认结构化事件并停用信源', async () => {
    const user = userEvent.setup();
    render(<NewsIntelligencePage />);

    await user.click(await screen.findByRole('button', { name: '确认可靠' }));
    expect(verifyEvent).toHaveBeenCalledWith(9, 'verified');
    expect(await screen.findByText('已核验', { selector: 'span' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '停用' }));
    expect(setSourceEnabled).toHaveBeenCalledWith(2, false);
    expect(await screen.findByRole('button', { name: '启用' })).toBeInTheDocument();
  });
  it('one failing resource leaves other news evidence usable and retries only itself', async () => {
    sources.mockRejectedValueOnce(new Error('信源读取失败'));
    render(<NewsIntelligencePage />);
    expect(await screen.findByText('球队公告')).toBeInTheDocument();
    expect(screen.getByText(/信源读取失败/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '刷新信源健康' }));
    expect(await screen.findByRole('button', { name: '停用' })).toBeInTheDocument();
    expect(sources).toHaveBeenCalledTimes(2); expect(articles).toHaveBeenCalledTimes(1);
  });
  it('unknown overview and release never claim zero, safety or screening readiness', async () => {
    overview.mockRejectedValueOnce(new Error('概览失败')); release.mockRejectedValueOnce(new Error('发布失败'));
    render(<NewsIntelligencePage />);
    await screen.findByText('球队公告');
    expect(screen.getByText('发布状态未知')).toBeInTheDocument();
    expect(screen.queryByText('安全隔离')).not.toBeInTheDocument();
    expect(screen.queryByText('正式预测未启用新闻特征')).not.toBeInTheDocument();
    expect(screen.queryByText('当前使用确定性规则筛选')).not.toBeInTheDocument();
    expect(screen.getByText('AI 筛选状态未知')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '人工晋升并锁定版本' })).toBeDisabled();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4);
  });
  it('same-resource refresh failure retains articles; successful empty clears them', async () => {
    render(<NewsIntelligencePage />); await screen.findByText('球队公告');
    articles.mockRejectedValueOnce(new Error('文章暂不可读'));
    await userEvent.click(screen.getByRole('button', { name: '刷新新闻证据' }));
    expect(await screen.findByText(/文章暂不可读/)).toBeInTheDocument(); expect(screen.getByText('球队公告')).toBeInTheDocument();
    articles.mockResolvedValueOnce({ items: [], total: 0, limit: 20, offset: 0 });
    await userEvent.click(screen.getByRole('button', { name: '刷新新闻证据' }));
    expect(await screen.findByText('暂无已关联的可靠新闻')).toBeInTheDocument();
    expect(screen.queryByText('球队公告')).not.toBeInTheDocument();
  });
  it('filters and pages only the fetched event subset with match deep links', async () => {
    const response = await events(); events.mockClear();
    events.mockResolvedValue({ ...response, total: 55, items: Array.from({length:20}, (_, i) => ({...response.items[0], id:i+1, title:`事件-${i+1}`, verificationStatus:i===19?'verified':'pending'})) });
    render(<NewsIntelligencePage />); await screen.findByText('事件-1');
    expect(screen.queryByText('事件-11')).not.toBeInTheDocument();
    expect(screen.getByText(/已获取 20.*API 共 55/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '事件下一页' }));
    expect(screen.getByText('事件-11')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('事件核验状态'), 'verified');
    expect(screen.getByText('事件-20')).toBeInTheDocument(); expect(screen.queryByText('事件-11')).not.toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: '查看比赛 #31' })[0]).toHaveAttribute('href', '#/matches/31');
  });
  it('article search and source-level filter reset pagination', async () => {
    const response = await articles(); articles.mockClear();
    articles.mockResolvedValue({ ...response, total: 80, items: Array.from({length:20}, (_, i) => ({...response.items[0], id:i+1, title:`新闻-${i+1}`, sourceLevel:i===19?'D':'S'})) });
    render(<NewsIntelligencePage />); await screen.findByText('新闻-1');
    await userEvent.click(screen.getByRole('button', {name:'文章下一页'}));
    expect(screen.getByText('新闻-11')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('新闻信源等级'), 'D');
    expect(screen.getByText('新闻-20')).toBeInTheDocument(); expect(screen.queryByText('新闻-11')).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('搜索新闻证据'), '不存在');
    expect(screen.getByText('当前筛选无新闻证据')).toBeInTheDocument();
  });
  it('rejects malformed snapshot numbers without hiding healthy articles', async () => {
    const response = await features(); features.mockClear();
    features.mockResolvedValue({...response, items:[{...response.items[0], homeNetImpact:NaN}]});
    render(<NewsIntelligencePage />); await screen.findByText('球队公告');
    expect(screen.getByText(/特征快照格式不正确/)).toBeInTheDocument(); expect(screen.queryByText('NaN')).not.toBeInTheDocument();
  });
  it('rejects a non-web news URL and wrong verification identity', async () => {
    const response=await articles(); articles.mockClear();
    articles.mockResolvedValue({...response,items:[{...response.items[0],canonicalUrl:'javascript:alert(1)'}]});
    verifyEvent.mockResolvedValueOnce({event:{id:88,verificationStatus:'verified'}});
    render(<NewsIntelligencePage />); await screen.findByText('主力前锋伤缺');
    expect(screen.getByText(/新闻证据格式不正确/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'确认可靠'}));
    expect(await screen.findByText(/核验响应与事件不一致/)).toBeInTheDocument();
    expect(screen.getByText('待核验', { selector: 'span' })).toBeInTheDocument();
  });
  it('serializes writes and keeps the previous source state on save failure', async () => {
    let reject!: (e: Error)=>void;
    setSourceEnabled.mockReturnValueOnce(new Promise((_,r)=>{reject=r;}));
    render(<NewsIntelligencePage />); const button=await screen.findByRole('button',{name:'停用'});
    fireEvent.click(button); fireEvent.click(button);
    expect(setSourceEnabled).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button',{name:'确认可靠'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'刷新信源健康'})).toBeDisabled();
    reject(new Error('保存信源失败'));
    expect(await screen.findByRole('alert')).toHaveTextContent('保存信源失败');
    expect(screen.getByRole('button',{name:'停用'})).toBeEnabled();
  });

  it('initial article failure is distinct from a valid empty list', async () => {
    articles.mockRejectedValueOnce(new Error('文章失败'));
    render(<NewsIntelligencePage />); await screen.findByText(/文章失败/);
    expect(screen.queryByText('暂无已关联的可靠新闻')).not.toBeInTheDocument();
    expect(screen.getByText('主力前锋伤缺')).toBeInTheDocument();
  });
  it('pages twelve source snapshots six at a time without fetching more', async () => {
    const response=await features(); features.mockClear();
    features.mockResolvedValue({...response,total:100,items:Array.from({length:12},(_,i)=>({...response.items[0],snapshotId:i+1,officialMatchCode:`快照-${i+1}`}))});
    render(<NewsIntelligencePage />); await screen.findByText('快照-1');
    expect(screen.queryByText('快照-7')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'快照下一页'}));
    expect(screen.getByText('快照-7')).toBeInTheDocument(); expect(features).toHaveBeenCalledTimes(1);
  });
  it('deduplicates repeated manual reads and disables writes during related read', async () => {
    render(<NewsIntelligencePage />); await screen.findByText('主力前锋伤缺');
    let resolve!: (v:unknown)=>void; const response=await events(); events.mockClear();
    events.mockReturnValueOnce(new Promise(r=>{resolve=r;}));
    const button=screen.getByRole('button',{name:'刷新情报事件'});
    fireEvent.click(button); fireEvent.click(button);
    expect(events).toHaveBeenCalledTimes(1); expect(screen.getByRole('button',{name:'确认可靠'})).toBeDisabled();
    resolve(response); await waitFor(()=>expect(screen.getByRole('button',{name:'确认可靠'})).toBeEnabled());
  });
  it('production release displays its actual boundary and requires a rollback note', async () => {
    const response=await release(); release.mockClear();
    release.mockResolvedValue({...response,release:{...response.release,mode:'production'}});
    rollback.mockResolvedValue(response);
    render(<NewsIntelligencePage />); await screen.findByText('生产模式');
    expect(screen.getByText('正式推荐已启用锁定新闻版本')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'立即回滚到影子模式'}));
    expect(rollback).not.toHaveBeenCalled(); expect(await screen.findByRole('alert')).toHaveTextContent('请先填写');
    await userEvent.type(screen.getByLabelText('人工审核或回滚说明'),'人工确认回滚');
    await userEvent.click(screen.getByRole('button',{name:'立即回滚到影子模式'}));
    expect(rollback).toHaveBeenCalledWith('人工确认回滚'); await screen.findByText('影子模式');
  });
  it('no settled sample count or insufficient-sample claim is invented when experiment fails', async () => {
    experiments.mockRejectedValueOnce(new Error('评估不可读'));
    render(<NewsIntelligencePage />); await screen.findByText('球队公告');
    expect(screen.getByText('已结算样本').nextElementSibling).toHaveTextContent('—');
    expect(screen.queryByText('样本不足')).not.toBeInTheDocument();
  });

});
