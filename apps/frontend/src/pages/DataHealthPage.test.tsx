import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DataHealthPage from './DataHealthPage';

const { mockHealth, mockOpsHealth, mockPipeline, mockCollectionStatus } = vi.hoisted(() => ({
  mockHealth: vi.fn(),
  mockOpsHealth: vi.fn(),
  mockPipeline: vi.fn(),
  mockCollectionStatus: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    health: mockHealth,
    ops: {
      health: mockOpsHealth,
      pipeline: mockPipeline,
    },
    official: {
      collectionStatus: mockCollectionStatus,
    },
  },
}));

describe('DataHealthPage', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockHealth.mockResolvedValue({ status: 'ok', service: 'fqp' });
    mockOpsHealth.mockResolvedValue({ status: 'no_data' });
    mockPipeline.mockResolvedValue({
      sources: [{
        name: 'sporttery', source_type: 'results', status: 'ok',
        last_success: '2026-07-15T03:00:06Z', last_failure: null, failures: 0, latency_ms: 4033,
      }],
      jobs: [],
    });
    mockCollectionStatus.mockResolvedValue({
      total: 1,
      items: [
        {
          id: 3,
          business_date: '2026-07-01',
          crawl_type: 'results',
          source_name: 'sporttery',
          status: 'blocked',
          source_url: 'https://webapi.sporttery.cn/gateway/jc/football/getMatchResultV1.qry',
          source_artifact_path: null,
          source_artifact_hash: null,
          records_found: 0,
          records_inserted: 0,
          records_updated: 0,
          error_message: '567 Restricted Access',
          updated_at: '2026-07-11T12:00:00',
        },
      ],
    });
  });

  it('shows blocked official result collection as an actionable local import notice', async () => {
    render(<DataHealthPage />);

    expect(await screen.findByText('官方历史数据采集')).toBeInTheDocument();
    expect(screen.getByText('体彩官方结果暂不可自动读取')).toBeInTheDocument();
    expect(screen.getByText(/不会使用第三方赛果替代体彩官方结果/)).toBeInTheDocument();
    expect(screen.getByText(/保存体彩官网 HTML 或 HAR 文件/)).toBeInTheDocument();
    expect(screen.queryByText('500.com 赛果补充源')).not.toBeInTheDocument();
    expect(mockCollectionStatus).toHaveBeenCalledWith({ limit: 8 });
  });

  it('uses degraded operational health for the overall system badge', async () => {
    mockOpsHealth.mockResolvedValue({
      status: 'degraded',
      snapshot_date: '2026-07-13',
      metrics: {
        uptime_days: 1,
        official_collection_rate: 1,
        odds_missing_rate: 1,
        review_generation_rate: 0.5,
        backup_success: true,
        evidence_chain_completeness: null,
        data_contamination_count: null,
      },
      services: { scheduler: false, worker: true, api: true, db: true },
      disk_usage_pct: 20,
      notes: '部分指标未达标',
    });

    render(<DataHealthPage />);

    expect(await screen.findByText('系统运行降级')).toBeInTheDocument();
    expect(screen.queryByText('系统运行正常')).not.toBeInTheDocument();
  });

  it('shows distinct source roles and current normalized task status', async () => {
    mockPipeline.mockResolvedValue({
      sources: [
        {
          name: 'sporttery', source_type: 'results', status: 'error',
          last_success: null, last_failure: '2026-07-15T03:00:02Z', failures: 192, latency_ms: 0,
        },
        {
          name: 'sporttery_v2', source_type: 'schedule', status: 'ok',
          last_success: '2026-07-15T02:40:00Z', last_failure: null, failures: 0, latency_ms: 381,
        },
        {
          name: 'sporttery', source_type: 'odds', status: 'ok',
          last_success: '2026-07-15T03:08:19Z', last_failure: null, failures: 0, latency_ms: 250,
        },
      ],
      jobs: [
        {
          code: 'official_odds_snapshot', name: '赔率快照采集', status: 'success',
          finished_at: '2026-07-15T03:08:19Z', error: null,
          schedule: '按开盘/每30分钟/开赛时', category: 'official',
        },
      ],
    });

    render(<DataHealthPage />);

    expect(await screen.findByText('官方竞彩赛果 (sporttery.cn)')).toBeInTheDocument();
    expect(screen.getByText('官方竞彩赛程 (sporttery.cn)')).toBeInTheDocument();
    expect(screen.getByText('官方竞彩赔率 (sporttery.cn)')).toBeInTheDocument();
    expect(screen.queryByText('500.com 赛果补充源')).not.toBeInTheDocument();
    expect(screen.getByText('1 个已记录任务')).toBeInTheDocument();
    expect(screen.getByText(/最近成功: .*按开盘\/每30分钟\/开赛时/)).toBeInTheDocument();
  });

  it('shows stale sources and never-run jobs without claiming success', async () => {
    mockPipeline.mockResolvedValue({
      sources: [{
        name: 'sporttery_v2', source_type: 'schedule', status: 'stale',
        last_success: '2026-07-14T02:40:00Z', last_failure: null, failures: 0, latency_ms: 381,
      }],
      jobs: [{
        code: 'generate_monthly_review', name: '月报生成', status: 'pending',
        finished_at: null, error: null, schedule: '每月1日 10:00', category: 'review',
      }],
    });

    render(<DataHealthPage />);

    expect(await screen.findByText(/状态已过期/)).toBeInTheDocument();
    expect(screen.getByText(/尚未运行: 尚无记录/)).toBeInTheDocument();
  });

  it('页面保持打开时自动刷新监控状态', async () => {
    vi.useFakeTimers();

    render(<DataHealthPage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockPipeline).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(30_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockPipeline).toHaveBeenCalledTimes(2);
    expect(mockCollectionStatus).toHaveBeenCalledTimes(2);
  });
});
