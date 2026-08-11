import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import NewsIntelligencePage from './NewsIntelligencePage';

const { overview, articles, events, sources, experiments, verifyEvent, setSourceEnabled } = vi.hoisted(() => ({
  overview: vi.fn(),
  articles: vi.fn(),
  events: vi.fn(),
  sources: vi.fn(),
  experiments: vi.fn(),
  verifyEvent: vi.fn(),
  setSourceEnabled: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: { newsIntelligence: {
    overview, articles, events, sources, experiments, verifyEvent, setSourceEnabled,
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
    experiments.mockResolvedValue({ experiments: [], productionFeatureEnabled: false });
    verifyEvent.mockResolvedValue({ event: { id: 9, verificationStatus: 'verified', reviewNote: null } });
    setSourceEnabled.mockResolvedValue({ source: { id: 2, enabled: false } });
  });

  it('展示情报概览、来源等级和正式预测安全边界', async () => {
    render(<NewsIntelligencePage />);

    expect(await screen.findByText('新闻情报')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('球队公告')).toBeInTheDocument();
    expect(screen.getByText('主力前锋伤缺')).toBeInTheDocument();
    expect(screen.getByText('待核验')).toBeInTheDocument();
    expect(screen.getAllByText('S级')).toHaveLength(2);
    expect(screen.getByText('正式预测未启用新闻特征')).toBeInTheDocument();
  });

  it('可人工确认结构化事件并停用信源', async () => {
    const user = userEvent.setup();
    render(<NewsIntelligencePage />);

    await user.click(await screen.findByRole('button', { name: '确认可靠' }));
    expect(verifyEvent).toHaveBeenCalledWith(9, 'verified');
    expect(await screen.findByText('已核验')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '停用' }));
    expect(setSourceEnabled).toHaveBeenCalledWith(2, false);
    expect(await screen.findByRole('button', { name: '启用' })).toBeInTheDocument();
  });
});
