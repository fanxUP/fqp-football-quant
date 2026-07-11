import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
  beforeEach(() => {
    vi.clearAllMocks();
    mockHealth.mockResolvedValue({ status: 'ok', service: 'fqp' });
    mockOpsHealth.mockResolvedValue({ status: 'no_data' });
    mockPipeline.mockResolvedValue({ sources: [], jobs: [] });
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
    expect(screen.getByText(/已由 500.com 为体彩已收录的比赛补充赛果/)).toBeInTheDocument();
    expect(screen.getByText(/如需体彩原始证据/)).toBeInTheDocument();
    expect(screen.getByText('500.com 补充源')).toBeInTheDocument();
    expect(screen.getByText('补充')).toBeInTheDocument();
    expect(mockCollectionStatus).toHaveBeenCalledWith({ limit: 8 });
  });
});
