import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import NewsIntelligencePage from './NewsIntelligencePage';

const { overview, events, sources, experiments } = vi.hoisted(() => ({
  overview: vi.fn(),
  events: vi.fn(),
  sources: vi.fn(),
  experiments: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: { newsIntelligence: { overview, events, sources, experiments } },
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
    events.mockResolvedValue({ items: [{
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
  });

  it('展示情报概览、来源等级和正式预测安全边界', async () => {
    render(<NewsIntelligencePage />);

    expect(await screen.findByText('新闻情报')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('球队公告')).toBeInTheDocument();
    expect(screen.getAllByText('S级')).toHaveLength(2);
    expect(screen.getByText('正式预测未启用新闻特征')).toBeInTheDocument();
  });
});
